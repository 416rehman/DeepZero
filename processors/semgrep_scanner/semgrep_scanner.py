from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from deepzero.engine.stage import (
    Sample,
    BulkMapProcessor,
    ProcessorResult,
    ProcessorContext,
)


class SemgrepScanner(BulkMapProcessor):
    description = (
        "runs semgrep batch scan against decompiled source across all active samples"
    )

    def validate(self, ctx: ProcessorContext) -> list[str]:
        errors = []
        if not shutil.which("semgrep"):
            errors.append(
                "semgrep CLI not found in PATH - install with: pip install semgrep"
            )

        rules_dir = self.config.get("rules_dir")
        if not rules_dir:
            errors.append("semgrep_scanner requires 'rules_dir' in config")
        else:
            rules_path = (Path.cwd() / rules_dir).resolve()
            if not rules_path.exists():
                rules_path = (ctx.pipeline_dir / rules_dir).resolve()
            if not rules_path.exists():
                errors.append(f"rules_dir does not exist: {rules_dir}")

        return errors

    def process(
        self, ctx: ProcessorContext, entries: list[Sample]
    ) -> list[ProcessorResult]:
        rules_dir = self.config.get("rules_dir", "")
        rules_path = (ctx.pipeline_dir / rules_dir).resolve()

        target_subdir = self.config.get("target_dir", "decompiled")
        timeout = self.config.get("timeout", 300)
        min_findings = self.config.get("min_findings", 0)

        results: list[ProcessorResult | None] = [None] * len(entries)
        uncached_entries: list[tuple[int, Sample]] = []

        for i, entry in enumerate(entries):
            findings_path = entry.sample_dir / "findings.json"
            if findings_path.exists():
                try:
                    findings = json.loads(findings_path.read_text(encoding="utf-8"))
                    results[i] = self._make_result(findings, min_findings, cached=True)
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    self.log.debug(
                        "cache read failed for %s, rescanning: %s", entry.sample_id, exc
                    )

            scan_dir = entry.sample_dir / target_subdir
            if not scan_dir.exists():
                results[i] = ProcessorResult.fail(
                    f"scan target '{target_subdir}' missing - does a decompile processor run before this?"
                )
                continue

            uncached_entries.append((i, entry))

        if not uncached_entries:
            return [r for r in results if r is not None]

        bulk_dir = entries[0].sample_dir.parent.parent / ".bulk_temp" / "semgrep"
        file_to_sample = self._build_bulk_dir(uncached_entries, bulk_dir, target_subdir)

        if not file_to_sample:
            for idx, _entry in uncached_entries:
                results[idx] = ProcessorResult.ok(
                    data={"finding_count": 0, "findings_cached": False},
                )
            self._cleanup_bulk_dir(bulk_dir)
            return [r for r in results if r is not None]

        try:
            return asyncio.run(
                self._run_and_distribute(
                    rules_path,
                    bulk_dir,
                    timeout,
                    uncached_entries,
                    file_to_sample,
                    results,
                    min_findings,
                )
            )
        finally:
            self._cleanup_bulk_dir(bulk_dir)

    def _build_bulk_dir(
        self,
        uncached_entries: list[tuple[int, Sample]],
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
        uncached_entries: list[tuple[int, Sample]],
        file_to_sample: dict[str, int],
        results: list[ProcessorResult | None],
        min_findings: int,
    ) -> list[ProcessorResult]:
        cmd = [
            "semgrep",
            "scan",
            "--config",
            str(rules_path),
            "--json",
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
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except OSError:
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail(
                    "semgrep not installed - pip install semgrep"
                )
            return [r for r in results if r is not None]
        except asyncio.TimeoutError:
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail(
                    f"semgrep batch timed out after {timeout}s"
                )
            return [r for r in results if r is not None]

        if proc.returncode not in (0, 1):
            err = stderr_bytes.decode("utf-8", errors="replace")[:500]
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail(f"semgrep error: {err}")
            return [r for r in results if r is not None]

        try:
            out_str = stdout_bytes.decode("utf-8", errors="replace")
            output = json.loads(out_str) if out_str.strip() else {}
        except json.JSONDecodeError:
            for idx, _ in uncached_entries:
                results[idx] = ProcessorResult.fail(
                    "failed to parse semgrep json output"
                )
            return [r for r in results if r is not None]

        self._distribute_findings(
            output, file_to_sample, uncached_entries, results, min_findings
        )
        return [r for r in results if r is not None]

    def _distribute_findings(
        self,
        output: dict[str, Any],
        file_to_sample: dict[str, int],
        uncached_entries: list[tuple[int, Sample]],
        results: list[ProcessorResult | None],
        min_findings: int,
    ) -> None:
        sev_map = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}
        per_sample_findings: dict[int, list[dict]] = {
            idx: [] for idx, _ in uncached_entries
        }

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
                self.log.debug(
                    "failed to write findings for %s: %s", entry.sample_id, exc
                )
            results[idx] = self._make_result(findings, min_findings, cached=False)

    def _make_result(
        self, findings: list[dict], min_findings: int, cached: bool
    ) -> ProcessorResult:
        data: dict[str, Any] = {
            "finding_count": len(findings),
            "findings_cached": cached,
        }

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
