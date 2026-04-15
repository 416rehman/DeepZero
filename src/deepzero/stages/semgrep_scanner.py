from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from deepzero.engine.stage import BatchEntry, BatchTool, StageResult


class SemgrepScannerTool(BatchTool):
    # runs one semgrep process against all active samples using a temp-copy pattern

    def execute_batch(self, entries: list[BatchEntry], config: dict[str, Any]) -> list[StageResult]:
        rules_dir = config.get("rules_dir")
        if not rules_dir:
            return [StageResult(status="failed", error="semgrep_scanner requires 'rules_dir' in config")] * len(entries)

        rules_path = (Path.cwd() / rules_dir).resolve()
        if not rules_path.exists():
            return [StageResult(status="failed", error=f"semgrep rules dir not found: {rules_path}")] * len(entries)

        target_subdir = config.get("target_dir", "decompiled")
        timeout = config.get("timeout", 300)
        min_findings = config.get("min_findings", 0)

        # check for cached results first
        results: list[StageResult | None] = [None] * len(entries)
        uncached_entries: list[tuple[int, BatchEntry]] = []

        for i, entry in enumerate(entries):
            findings_path = entry.sample_dir / "findings.json"
            if findings_path.exists():
                try:
                    findings = json.loads(findings_path.read_text(encoding="utf-8"))
                    results[i] = self._make_result(findings, min_findings, cached=True)
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    self.log.debug("cache read failed for %s, rescanning: %s", entry.sample_id, exc)

            # verify scan target exists
            scan_dir = entry.sample_dir / target_subdir
            if not scan_dir.exists():
                results[i] = StageResult(
                    status="failed",
                    error=f"scan target '{target_subdir}' missing - does a decompile tool run before this?",
                )
                continue

            uncached_entries.append((i, entry))

        if not uncached_entries:
            return [r for r in results if r is not None]

        # temp-copy pattern: hardlink (or copy) all .c files into a batch dir
        # lives inside work dir to guarantee same-volume for hardlinks
        batch_dir = entries[0].sample_dir.parent.parent / ".batch_temp" / "semgrep"
        if batch_dir.exists():
            shutil.rmtree(batch_dir, ignore_errors=True)
        batch_dir.mkdir(parents=True, exist_ok=True)

        # track which files belong to which sample
        file_to_sample: dict[str, int] = {}

        for idx, entry in uncached_entries:
            scan_dir = entry.sample_dir / target_subdir
            for src_file in scan_dir.rglob("*"):
                if not src_file.is_file():
                    continue
                if src_file.suffix not in (".c", ".h", ".cpp", ".py"):
                    continue
                # unique name: {sample_id}_{filename}
                dest_name = f"{entry.sample_id}_{src_file.name}"
                dest = batch_dir / dest_name
                try:
                    os.link(src_file, dest)
                except OSError:
                    shutil.copy2(src_file, dest)
                file_to_sample[dest_name] = idx

        if not file_to_sample:
            # nothing to scan - all entries had no scannable files
            for idx, _entry in uncached_entries:
                results[idx] = StageResult(
                    status="completed", verdict="continue",
                    data={"finding_count": 0, "findings_cached": False},
                )
            self._cleanup_batch_dir(batch_dir)
            return [r for r in results if r is not None]

        # one semgrep invocation for the entire batch
        cmd = [
            "semgrep", "scan",
            "--config", str(rules_path),
            "--json",
            "--no-git-ignore",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
            str(batch_dir),
        ]

        self.log.info("batch scanning %d files from %d samples", len(file_to_sample), len(uncached_entries))

        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            self._cleanup_batch_dir(batch_dir)
            for idx, _ in uncached_entries:
                results[idx] = StageResult(status="failed", error="semgrep not installed - pip install semgrep")
            return [r for r in results if r is not None]
        except subprocess.TimeoutExpired:
            self._cleanup_batch_dir(batch_dir)
            for idx, _ in uncached_entries:
                results[idx] = StageResult(status="failed", error=f"semgrep batch timed out after {timeout}s")
            return [r for r in results if r is not None]

        if proc.returncode not in (0, 1):
            err = proc.stderr.decode("utf-8", errors="replace")[:500]
            self._cleanup_batch_dir(batch_dir)
            for idx, _ in uncached_entries:
                results[idx] = StageResult(status="failed", error=f"semgrep error: {err}")
            return [r for r in results if r is not None]

        try:
            out_str = proc.stdout.decode("utf-8", errors="replace")
            output = json.loads(out_str) if out_str.strip() else {}
        except json.JSONDecodeError:
            self._cleanup_batch_dir(batch_dir)
            for idx, _ in uncached_entries:
                results[idx] = StageResult(status="failed", error="failed to parse semgrep json output")
            return [r for r in results if r is not None]

        # map findings back to samples
        sev_map = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}
        per_sample_findings: dict[int, list[dict]] = {idx: [] for idx, _ in uncached_entries}

        for result_entry in output.get("results", []):
            file_path = result_entry.get("path", "")
            filename = Path(file_path).name

            # find which sample this file belongs to
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

        # write findings and build results
        for idx, entry in uncached_entries:
            findings = per_sample_findings.get(idx, [])
            findings_path = entry.sample_dir / "findings.json"
            fd, tmp = tempfile.mkstemp(dir=str(entry.sample_dir), suffix=".json")
            try:
                os.write(fd, json.dumps(findings, indent=2).encode("utf-8"))
                os.close(fd)
                os.replace(tmp, str(findings_path))
            except OSError:
                try:
                    os.close(fd)
                except OSError:
                    pass
                self.log.debug("failed to write findings for %s", entry.sample_id)
            results[idx] = self._make_result(findings, min_findings, cached=False)

        self._cleanup_batch_dir(batch_dir)
        return [r for r in results if r is not None]

    def _make_result(self, findings: list[dict], min_findings: int, cached: bool) -> StageResult:
        data: dict[str, Any] = {"finding_count": len(findings), "findings_cached": cached}

        if min_findings > 0 and len(findings) < min_findings:
            data["reject_reason"] = f"{len(findings)} findings < min {min_findings}"
            return StageResult(
                status="completed", verdict="skip",
                artifacts={"findings": "findings.json"}, data=data,
            )

        return StageResult(
            status="completed", verdict="continue",
            artifacts={"findings": "findings.json"}, data=data,
        )

    def _cleanup_batch_dir(self, batch_dir: Path) -> None:
        try:
            shutil.rmtree(batch_dir, ignore_errors=True)
        except OSError:
            # rmtree with ignore_errors already handles most failures
            self.log.debug("batch dir cleanup failed: %s", batch_dir)
