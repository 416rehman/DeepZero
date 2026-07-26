from __future__ import annotations

import asyncio
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
    description = "runs semgrep batch scan against decompiled source across all active samples"

    # findings_json is the parsed report; `findings` holds its filename, which is
    # why a prompt wanting the findings themselves has to name findings_json
    provides = (
        "finding_count",
        "findings_cached",
        "files_submitted",
        "files_scanned",
        "findings",
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

        target_subdir = self.config.get("target_dir", "decompiled")
        timeout = self.config.get("timeout", 300)
        min_findings = self.config.get("min_findings", 0)

        results: list[ProcessorResult | None] = [None] * len(entries)
        uncached_entries: list[tuple[int, ProcessorEntry]] = []

        for i, entry in enumerate(entries):
            findings_path = entry.sample_dir / "findings.json"
            if findings_path.exists():
                try:
                    findings = json.loads(findings_path.read_text(encoding="utf-8"))
                    results[i] = self._make_result(findings, min_findings, cached=True)
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    self.log.debug("cache read failed for %s, rescanning: %s", entry.sample_id, exc)

            scan_dir = entry.sample_dir / target_subdir
            if not scan_dir.exists():
                results[i] = ProcessorResult.fail(
                    f"scan target '{target_subdir}' missing - does a decompile processor run before this?"
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

    def _build_bulk_dir(
        self,
        uncached_entries: list[tuple[int, ProcessorEntry]],
        bulk_dir: Path,
        target_subdir: str,
    ) -> dict[str, int]:
        if bulk_dir.exists():
            shutil.rmtree(bulk_dir, ignore_errors=True)
        bulk_dir.mkdir(parents=True, exist_ok=True)

        file_to_sample: dict[str, int] = {}
        for idx, entry in uncached_entries:
            scan_dir = entry.sample_dir / target_subdir
            for src_file in scan_dir.rglob("*"):
                if not src_file.is_file():
                    continue
                if src_file.suffix not in (".c", ".h", ".cpp", ".py"):
                    continue
                dest_name = f"{entry.sample_id}_{src_file.name}"
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

        try:
            proc = await asyncio.create_subprocess_exec(
                cmd[0],
                *cmd[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
            output, file_to_sample, uncached_entries, results, min_findings, scanned_paths
        )

    def _distribute_findings(
        self,
        output: dict[str, Any],
        file_to_sample: dict[str, int],
        uncached_entries: list[tuple[int, ProcessorEntry]],
        results: list[ProcessorResult | None],
        min_findings: int,
        scanned_paths: list | None = None,
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
                "matched_code": result_entry.get("extra", {}).get("lines", ""),
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

        if min_findings > 0 and len(findings) < min_findings:
            return ProcessorResult.filter(
                f"{len(findings)} findings < min {min_findings}",
                data={**data, "findings": "findings.json"},
            )

        return ProcessorResult.ok(
            artifacts={"findings": "findings.json"},
            data=data,
        )

    def _cleanup_bulk_dir(self, bulk_dir: Path) -> None:
        try:
            shutil.rmtree(bulk_dir, ignore_errors=True)
        except OSError:
            self.log.debug("batch dir cleanup failed: %s", bulk_dir)
