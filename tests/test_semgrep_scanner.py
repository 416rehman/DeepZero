from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from deepzero.engine.stage import BatchEntry, StageSpec
from deepzero.stages.semgrep_scanner import SemgrepScannerTool


def _make_tool():
    spec = StageSpec(name="semgrep", tool="semgrep_scanner")
    return SemgrepScannerTool(spec)


def _make_entry(tmp_path, sample_id, decompiled_content=None):
    sample_dir = tmp_path / "samples" / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    source_path = sample_dir / f"{sample_id}.sys"
    source_path.write_bytes(b"MZ")

    if decompiled_content is not None:
        decompiled = sample_dir / "decompiled"
        decompiled.mkdir(parents=True, exist_ok=True)
        (decompiled / "dispatch_ioctl.c").write_text(decompiled_content)

    return BatchEntry(
        sample_id=sample_id,
        sample_dir=sample_dir,
        source_path=source_path,
        history={},
    )


class TestSemgrepNoRulesDir:
    def test_fails_without_rules_dir(self, tmp_path):
        tool = _make_tool()
        entry = _make_entry(tmp_path, "s1", "int x;")
        results = tool.execute_batch([entry], {})
        assert len(results) == 1
        assert results[0].status == "failed"
        assert "rules_dir" in results[0].error

    def test_fails_with_missing_rules_dir(self, tmp_path):
        tool = _make_tool()
        entry = _make_entry(tmp_path, "s1", "int x;")
        results = tool.execute_batch([entry], {"rules_dir": "/nonexistent/rules"})
        assert len(results) == 1
        assert results[0].status == "failed"
        assert "not found" in results[0].error


class TestSemgrepMissingTarget:
    def test_missing_decompiled_dir(self, tmp_path):
        tool = _make_tool()
        # entry without decompiled/ subdir
        entry = _make_entry(tmp_path, "s1")

        rules = tmp_path / "rules"
        rules.mkdir()
        (rules / "test.yaml").write_text("rules: []")

        results = tool.execute_batch([entry], {"rules_dir": str(rules)})
        assert len(results) == 1
        assert results[0].status == "failed"
        assert "missing" in results[0].error.lower()


class TestSemgrepCached:
    def test_uses_cached_findings(self, tmp_path):
        tool = _make_tool()
        entry = _make_entry(tmp_path, "s1", "int x;")

        # pre-write findings cache
        findings = [{"rule_id": "test.rule", "severity": "HIGH"}]
        (entry.sample_dir / "findings.json").write_text(json.dumps(findings))

        rules = tmp_path / "rules"
        rules.mkdir()

        results = tool.execute_batch([entry], {"rules_dir": str(rules)})
        assert len(results) == 1
        assert results[0].status == "completed"
        assert results[0].data["findings_cached"] is True


class TestSemgrepBatchExecution:
    @patch("deepzero.stages.semgrep_scanner.subprocess.run")
    def test_successful_batch(self, mock_run, tmp_path):
        tool = _make_tool()
        entry = _make_entry(tmp_path, "s1", "void vulnerable() { memcpy(buf, src, n); }")

        rules = tmp_path / "rules"
        rules.mkdir()
        (rules / "c_rules.yaml").write_text("rules: []")

        # mock semgrep returning findings
        finding = {
            "results": [{
                "check_id": "rules.buffer-overflow",
                "path": f"{entry.sample_dir.parent.parent / '.batch_temp' / 'semgrep' / 's1_dispatch_ioctl.c'}",
                "extra": {"severity": "ERROR", "message": "buffer overflow", "lines": "memcpy(buf, src, n);"},
                "start": {"line": 1},
                "end": {"line": 1},
            }]
        }
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = json.dumps(finding).encode()
        mock_proc.stderr = b""
        mock_run.return_value = mock_proc

        results = tool.execute_batch([entry], {"rules_dir": str(rules)})
        assert len(results) == 1
        assert results[0].status == "completed"
        mock_run.assert_called_once()

    @patch("deepzero.stages.semgrep_scanner.subprocess.run")
    def test_semgrep_not_installed(self, mock_run, tmp_path):
        tool = _make_tool()
        entry = _make_entry(tmp_path, "s1", "int x;")

        rules = tmp_path / "rules"
        rules.mkdir()

        mock_run.side_effect = FileNotFoundError("semgrep not found")

        results = tool.execute_batch([entry], {"rules_dir": str(rules)})
        assert len(results) == 1
        assert results[0].status == "failed"
        assert "not installed" in results[0].error

    @patch("deepzero.stages.semgrep_scanner.subprocess.run")
    def test_semgrep_timeout(self, mock_run, tmp_path):
        import subprocess

        tool = _make_tool()
        entry = _make_entry(tmp_path, "s1", "int x;")

        rules = tmp_path / "rules"
        rules.mkdir()

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="semgrep", timeout=300)

        results = tool.execute_batch([entry], {"rules_dir": str(rules), "timeout": 300})
        assert len(results) == 1
        assert results[0].status == "failed"
        assert "timed out" in results[0].error

    @patch("deepzero.stages.semgrep_scanner.subprocess.run")
    def test_semgrep_error_returncode(self, mock_run, tmp_path):
        tool = _make_tool()
        entry = _make_entry(tmp_path, "s1", "int x;")

        rules = tmp_path / "rules"
        rules.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 2
        mock_proc.stderr = b"fatal error"
        mock_run.return_value = mock_proc

        results = tool.execute_batch([entry], {"rules_dir": str(rules)})
        assert len(results) == 1
        assert results[0].status == "failed"
        assert "fatal error" in results[0].error

    @patch("deepzero.stages.semgrep_scanner.subprocess.run")
    def test_no_scannable_files(self, mock_run, tmp_path):
        tool = _make_tool()

        # create entry with non-scannable file extensions only
        sample_dir = tmp_path / "samples" / "s1"
        decompiled = sample_dir / "decompiled"
        decompiled.mkdir(parents=True, exist_ok=True)
        (decompiled / "readme.pdf").write_bytes(b"binary")

        source_path = sample_dir / "s1.sys"
        source_path.write_bytes(b"MZ")

        entry = BatchEntry(sample_id="s1", sample_dir=sample_dir, source_path=source_path, history={})

        rules = tmp_path / "rules"
        rules.mkdir()

        results = tool.execute_batch([entry], {"rules_dir": str(rules)})
        assert len(results) == 1
        assert results[0].status == "completed"
        assert results[0].data["finding_count"] == 0
        mock_run.assert_not_called()


class TestSemgrepMakeResult:
    def test_skip_below_min_findings(self):
        tool = _make_tool()
        result = tool._make_result([], min_findings=3, cached=False)
        assert result.verdict == "skip"
        assert "reject_reason" in result.data

    def test_continue_above_min_findings(self):
        tool = _make_tool()
        findings = [{"rule_id": "r1"}, {"rule_id": "r2"}, {"rule_id": "r3"}]
        result = tool._make_result(findings, min_findings=2, cached=False)
        assert result.verdict == "continue"
        assert result.data["finding_count"] == 3
