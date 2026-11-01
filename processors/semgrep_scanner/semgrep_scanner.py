from __future__ import annotations

import asyncio
import itertools
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from deepzero.engine.stage import (
    BulkMapProcessor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
)


class SemgrepScanner(BulkMapProcessor):
    cache_global_keys = ()
    description = "runs semgrep batch scan across all active samples"

    # what a sample's scannable files are called on disk. The default suits a
    # pipeline that decompiles first and writes C beside each sample; a pipeline
    # whose samples are already source (a repository checkout, say) sets
    # target_dir to "" so the sample's own path is scanned, and widens
    # extensions to whatever it actually ingests.
    DEFAULT_TARGET_DIR = "decompiled"
    DEFAULT_EXTENSIONS = (".c", ".h", ".cpp", ".py")

    # Unauthenticated scans may withhold snippets. Read the reported source span
    # instead of sending "requires login" to the assessment model.
    _LINES_WITHHELD = "requires login"
    _MAX_SNIPPET_LINES = 40

    # findings_json is the parsed report a prompt reads: findings.json is written
    # into the sample's own directory, and an artifact is named after its path.
    #
    # files_submitted and files_scanned come from the semgrep run itself, so a
    # result adopted from a findings.json already on disk does not carry them.
    provides = (
        "finding_count",
        "findings_cached",
        "files_submitted",
        "files_scanned",
        "findings_json",
    )

    def _resolve_rules_path(self, ctx: ProcessorContext) -> Path | None:
        # resolve rules_dir consistently for validate() and process(): try
        # cwd-relative first (how the shipped pipelines reference their rules),
        # then relative to the pipeline directory. resolving these differently
        # let validation pass while the scan silently ran with no rules loaded.
        rules_dir = self.config.get("rules_dir", "")
        if not rules_dir:
            return None
        cwd_path = (Path.cwd() / rules_dir).resolve()
        if cwd_path.exists():
            return cwd_path
        return (ctx.pipeline_dir / rules_dir).resolve()

    def validate(self, ctx: ProcessorContext) -> list[str]:
        errors = []
        if not shutil.which("semgrep"):
            errors.append("semgrep CLI not found in PATH - install with: pip install semgrep")

        if not self.config.get("rules_dir"):
            errors.append("semgrep_scanner requires 'rules_dir' in config")
        else:
            rules_path = self._resolve_rules_path(ctx)
            if rules_path is None or not rules_path.exists():
                errors.append(f"rules_dir does not exist: {self.config.get('rules_dir')}")

        return errors

    def process(
        self, ctx: ProcessorContext, entries: list[ProcessorEntry]
    ) -> list[ProcessorResult]:
        rules_path = self._resolve_rules_path(ctx)
        if rules_path is None or not rules_path.exists():
            # fail fast rather than pointing semgrep at a fallback path and
            # scanning with no rules loaded (the silent-empty-results class)
            reason = f"semgrep rules_dir not found: {self.config.get('rules_dir') or '(unset)'}"
            return [ProcessorResult.fail(reason) for _ in entries]

        target_subdir = self.config.get("target_dir", self.DEFAULT_TARGET_DIR)
        timeout = self.config.get("timeout", 300)
        min_findings = self.config.get("min_findings", 0)

        results: list[ProcessorResult | None] = [None] * len(entries)
        uncached_entries: list[tuple[int, ProcessorEntry]] = []

        for i, entry in enumerate(entries):
            # Record cached findings as artifacts so --redo can discard them.
            findings_path = entry.sample_dir / "findings.json"
            if findings_path.exists() and entry.cache_is_valid:
                try:
                    findings = json.loads(findings_path.read_text(encoding="utf-8"))
                    results[i] = self._make_result(findings, min_findings, cached=True)
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    self.log.debug("cache read failed for %s, rescanning: %s", entry.sample_id, exc)

            scan_dir = self._scan_dir(entry, target_subdir)
            if not scan_dir.exists():
                results[i] = ProcessorResult.fail(
                    f"scan target '{scan_dir}' missing - does the stage that produces it run before this?"
                )
                continue

            uncached_entries.append((i, entry))

        if not uncached_entries:
            return [r for r in results if r is not None]

        # one semgrep run per batch of samples, so a batch that times out or
        # comes back unreadable costs only its own samples. A whole corpus in a
        # single run means six minutes of work discarded by one failure.
        batch_size = int(self.config.get("batch_size", 200) or 0)
        if batch_size > 0:
            batches = [
                uncached_entries[i : i + batch_size]
                for i in range(0, len(uncached_entries), batch_size)
            ]
        else:
            batches = [uncached_entries]

        base_dir = entries[0].sample_dir.parent.parent / ".bulk_temp"
        for n, batch in enumerate(batches):
            bulk_dir = base_dir / f"semgrep_{n}"
            file_to_sample = self._build_bulk_dir(batch, bulk_dir, target_subdir)
            try:
                if not file_to_sample:
                    for idx, _entry in batch:
                        results[idx] = self._make_result(
                            [], min_findings, cached=False, submitted=0, scanned=0
                        )
                    continue
                if len(batches) > 1:
                    self.log.info("batch %d/%d", n + 1, len(batches))
                asyncio.run(
                    self._run_and_distribute(
                        rules_path,
                        bulk_dir,
                        timeout,
                        batch,
                        file_to_sample,
                        results,
                        min_findings,
                    )
                )
            finally:
                self._cleanup_bulk_dir(bulk_dir)

        return [r for r in results if r is not None]

    def _scan_dir(self, entry: ProcessorEntry, target_subdir: str) -> Path:
        # an empty target_dir means the sample IS the tree to scan, which is the
        # case when ingest produced a checkout rather than a file to decompile
        if not target_subdir:
            return Path(entry.source_path)
        return entry.sample_dir / target_subdir

    def _scan_extensions(self) -> tuple[str, ...]:
        raw = self.config.get("extensions") or self.DEFAULT_EXTENSIONS
        if isinstance(raw, str):
            raw = [raw]
        return tuple(e if e.startswith(".") else f".{e}" for e in raw)

    def _build_bulk_dir(
        self,
        uncached_entries: list[tuple[int, ProcessorEntry]],
        bulk_dir: Path,
        target_subdir: str,
    ) -> dict[str, int]:
        if bulk_dir.exists():
            shutil.rmtree(bulk_dir, ignore_errors=True)
        bulk_dir.mkdir(parents=True, exist_ok=True)

        extensions = self._scan_extensions()
        file_to_sample: dict[str, int] = {}
        for idx, entry in uncached_entries:
            scan_dir = self._scan_dir(entry, target_subdir)
            for src_file in scan_dir.rglob("*"):
                if not src_file.is_file():
                    continue
                if src_file.suffix not in extensions:
                    continue
                # a checkout has many files sharing a basename, so key on the
                # path within the sample to keep them apart in one flat bulk dir
                rel = src_file.relative_to(scan_dir).as_posix().replace("/", "__")
                dest_name = f"{entry.sample_id}_{rel}"
                dest = bulk_dir / dest_name
                try:
                    os.link(src_file, dest)
                except OSError:
                    shutil.copy2(src_file, dest)
                file_to_sample[dest_name] = idx
        return file_to_sample

    async def _run_and_distribute(
        self,
        rules_path: Path,
        bulk_dir: Path,
        timeout: int,
        uncached_entries: list[tuple[int, ProcessorEntry]],
        file_to_sample: dict[str, int],
        results: list[ProcessorResult | None],
        min_findings: int,
    ) -> None:
        # scanning thousands of files produces a results document far too large to
        # read back through a pipe, so semgrep writes it to a file and we read that
        report_path = bulk_dir.parent / f"{bulk_dir.name}_output.json"
        report_path.unlink(missing_ok=True)
        cmd = [
            "semgrep",
            "scan",
            "--config",
            str(rules_path),
            "--json",
            "--output",
            str(report_path),
            "--no-git-ignore",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
            str(bulk_dir),
        ]

        self.log.info(
            "bulk scanning %d files from %d samples",
            len(file_to_sample),
            len(uncached_entries),
        )

        # Windows' default codec can fail while Semgrep writes quoted source bytes.
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"

        try:
            proc = await asyncio.create_subprocess_exec(
                cmd[0],
                *cmd[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except FileNotFoundError:
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail("semgrep not installed - pip install semgrep")
            return
        except OSError as exc:
            # report what actually went wrong rather than guessing at the cause
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail(f"could not run semgrep: {exc}")
            return
        except asyncio.TimeoutError:
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail(f"semgrep batch timed out after {timeout}s")
            return

        err_str = stderr_bytes.decode("utf-8", errors="replace")
        try:
            out_str = report_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out_str = stdout_bytes.decode("utf-8", errors="replace")
        finally:
            report_path.unlink(missing_ok=True)

        # semgrep emits a complete results document on stdout even when it exits
        # with an unexpected code (observed on windows), so a parseable scan
        # result is authoritative over the exit code. only treat the run as
        # failed when no usable output came back - and always report the exit
        # code, never an empty "semgrep error:".
        output: dict[str, Any] | None = None
        if out_str.strip():
            try:
                parsed = json.loads(out_str)
                if isinstance(parsed, dict) and "results" in parsed:
                    output = parsed
            except json.JSONDecodeError:
                output = None

        if output is None:
            detail = (err_str.strip() or "no readable results document")[:500]
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail(
                    f"semgrep failed (exit {proc.returncode}): {detail}"
                )
            return

        # semgrep reports rule/config load failures in an "errors" array while
        # still exiting 0 with empty results - which would otherwise look like
        # "no vulnerabilities found". fail loudly when nothing scanned.
        scan_errors = output.get("errors") or []
        if scan_errors and not output.get("results"):
            detail = "; ".join(
                str(e.get("message") or e.get("type") or e) for e in scan_errors[:3]
            )[:500]
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail(f"semgrep produced no results: {detail}")
            return

        if scan_errors:
            self.log.warning("semgrep reported %d non-fatal error(s) during scan", len(scan_errors))

        # semgrep lists the files it actually read. Reading none of them is not
        # the same result as reading them and finding nothing: the first means
        # the scan never looked, and recording it as zero findings would send
        # every sample on to assessment described as clean.
        scanned_paths = (output.get("paths") or {}).get("scanned")
        if isinstance(scanned_paths, list) and not scanned_paths:
            detail = (err_str.strip() or "semgrep listed no scanned files")[:500]
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail(
                    f"semgrep read none of the {len(file_to_sample)} files submitted, "
                    f"so this is not a clean result: {detail}"
                )
            return

        self._distribute_findings(
            output,
            file_to_sample,
            uncached_entries,
            results,
            min_findings,
            scanned_paths,
            bulk_dir,
        )

    def _matched_code(self, result_entry: dict[str, Any], bulk_dir: Path | None) -> str:
        lines = result_entry.get("extra", {}).get("lines", "")
        if lines and lines.strip() != self._LINES_WITHHELD:
            return lines

        start = result_entry.get("start", {}).get("line", 0)
        end = result_entry.get("end", {}).get("line", 0)
        reported = result_entry.get("path", "")
        if not reported or start < 1 or end < start:
            return ""

        candidate = Path(reported)
        if not candidate.is_absolute() and bulk_dir is not None:
            # semgrep may report the path relative to where it was invoked
            candidate = bulk_dir / candidate.name

        try:
            with candidate.open("r", encoding="utf-8", errors="replace") as fh:
                span = list(
                    itertools.islice(fh, start - 1, min(end, start + self._MAX_SNIPPET_LINES - 1))
                )
        except OSError as exc:
            self.log.debug("could not read source for %s: %s", reported, exc)
            return ""

        snippet = "".join(span).rstrip()
        if end - start + 1 > self._MAX_SNIPPET_LINES:
            snippet += f"\n... ({end - start + 1 - self._MAX_SNIPPET_LINES} more lines)"
        return snippet

    def _distribute_findings(
        self,
        output: dict[str, Any],
        file_to_sample: dict[str, int],
        uncached_entries: list[tuple[int, ProcessorEntry]],
        results: list[ProcessorResult | None],
        min_findings: int,
        scanned_paths: list | None = None,
        bulk_dir: Path | None = None,
    ) -> None:
        sev_map = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}
        per_sample_findings: dict[int, list[dict]] = {idx: [] for idx, _ in uncached_entries}

        # how many of each sample's files semgrep actually read, so a sample
        # reported as having nothing can be told apart from one whose files were
        # never opened - the report shows both as zero findings otherwise
        submitted: dict[int, int] = dict.fromkeys((idx for idx, _ in uncached_entries), 0)
        for name, idx in file_to_sample.items():
            submitted[idx] = submitted.get(idx, 0) + 1
        scanned: dict[int, int] = dict.fromkeys((idx for idx, _ in uncached_entries), 0)
        for path in scanned_paths or []:
            idx = file_to_sample.get(Path(str(path)).name)
            if idx is not None:
                scanned[idx] = scanned.get(idx, 0) + 1

        for result_entry in output.get("results", []):
            file_path = result_entry.get("path", "")
            filename = Path(file_path).name

            sample_idx = file_to_sample.get(filename)
            if sample_idx is None:
                continue

            raw_sev = result_entry.get("extra", {}).get("severity", "WARNING")
            finding: dict[str, Any] = {
                "rule_id": result_entry.get("check_id", ""),
                "severity": sev_map.get(raw_sev, "MEDIUM"),
                "message": result_entry.get("extra", {}).get("message", ""),
                "file": result_entry.get("path", ""),
                "line_start": result_entry.get("start", {}).get("line", 0),
                "line_end": result_entry.get("end", {}).get("line", 0),
                "matched_code": self._matched_code(result_entry, bulk_dir),
            }
            per_sample_findings[sample_idx].append(finding)

        for idx, entry in uncached_entries:
            findings = per_sample_findings.get(idx, [])
            findings_path = entry.sample_dir / "findings.json"
            fd, tmp = tempfile.mkstemp(dir=str(entry.sample_dir), suffix=".json")
            try:
                os.write(fd, json.dumps(findings, indent=2).encode("utf-8"))
                os.close(fd)
                os.replace(tmp, str(findings_path))
            except OSError as exc:
                try:
                    os.close(fd)
                except OSError:
                    self.log.debug("cleanup of failed temp json ignored")
                self.log.debug("failed to write findings for %s: %s", entry.sample_id, exc)
            results[idx] = self._make_result(
                findings,
                min_findings,
                cached=False,
                submitted=submitted.get(idx, 0),
                scanned=scanned.get(idx) if scanned_paths is not None else None,
            )

    def _make_result(
        self,
        findings: list[dict],
        min_findings: int,
        cached: bool,
        submitted: int | None = None,
        scanned: int | None = None,
    ) -> ProcessorResult:
        data: dict[str, Any] = {
            "finding_count": len(findings),
            "findings_cached": cached,
        }
        if submitted is not None:
            data["files_submitted"] = submitted
        if scanned is not None:
            data["files_scanned"] = scanned

        artifacts = {"findings": "findings.json"}

        if min_findings > 0 and len(findings) < min_findings:
            # built here rather than via ProcessorResult.filter() so the artifact
            # travels with the filtered sample too: the file is on disk either
            # way, and a run that does not record it cannot discard it on --redo
            filtered = ProcessorResult.filter(
                f"{len(findings)} findings < min {min_findings}", data
            )
            filtered.artifacts = artifacts
            return filtered

        return ProcessorResult.ok(artifacts=artifacts, data=data)

    def _cleanup_bulk_dir(self, bulk_dir: Path) -> None:
        try:
            shutil.rmtree(bulk_dir, ignore_errors=True)
        except OSError:
            self.log.debug("batch dir cleanup failed: %s", bulk_dir)
