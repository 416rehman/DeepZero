import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from deepzero.engine.stage import ProcessorContext, ProcessorEntry, StageSpec
from processors.semgrep_scanner.semgrep_scanner import SemgrepScanner


def test_semgrep_scanner_init():
    spec = StageSpec(name="test_scanner", processor="semgrep", config={"rules": []})
    scanner = SemgrepScanner(spec)
    assert scanner.description != ""


def _ctx(pipeline_dir):
    return ProcessorContext(pipeline_dir=pipeline_dir, global_config={}, llm=None)


class TestRulesPathResolution:
    def _scanner(self, rules_dir):
        return SemgrepScanner(
            StageSpec(name="scan", processor="semgrep", config={"rules_dir": rules_dir})
        )

    def test_validate_and_process_resolve_the_same_path(self, tmp_path):
        # regression: validate() approved a cwd-relative path while process()
        # used a pipeline_dir-relative one, so the scan ran with no rules.
        rules = tmp_path / "rules"
        rules.mkdir()
        (rules / "r.yaml").write_text("rules: []")
        scanner = self._scanner("rules")
        ctx = _ctx(tmp_path)

        assert scanner.validate(ctx) == [] or "semgrep CLI" in scanner.validate(ctx)[0]
        assert scanner._resolve_rules_path(ctx) == rules.resolve()
        assert scanner._resolve_rules_path(ctx).exists()

    def test_missing_rules_dir_flagged(self, tmp_path):
        scanner = self._scanner("does_not_exist_anywhere")
        ctx = _ctx(tmp_path)
        errs = [e for e in scanner.validate(ctx) if "rules_dir" in e]
        assert errs


class _FakeProc:
    def __init__(self, returncode, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


def _scanner(tmp_path):
    return SemgrepScanner(StageSpec(name="scan", processor="semgrep", config={}))


def _entry(tmp_path, sample_id="s1"):
    d = tmp_path / "samples" / sample_id
    d.mkdir(parents=True, exist_ok=True)
    return ProcessorEntry(
        sample_id=sample_id,
        source_path=tmp_path / f"{sample_id}.sys",
        filename=f"{sample_id}.sys",
        sample_dir=d,
    )


def _distribute(tmp_path, proc):
    scanner = _scanner(tmp_path)
    entry = _entry(tmp_path)
    uncached = [(0, entry)]
    file_to_sample = {"s1_dispatch.c": 0}
    results = [None]
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        return asyncio.run(
            scanner._run_and_distribute(
                Path("rules"), tmp_path / "bulk", 300, uncached, file_to_sample, results, 0
            )
        )


def test_valid_json_with_findings_exit_1(tmp_path):
    out = json.dumps(
        {
            "results": [
                {
                    "check_id": "r1",
                    "path": "x/s1_dispatch.c",
                    "start": {"line": 5},
                    "end": {"line": 5},
                    "extra": {"severity": "ERROR", "message": "bad"},
                }
            ]
        }
    ).encode()
    res = _distribute(tmp_path, _FakeProc(1, stdout=out))
    assert res[0].status == "completed"
    assert res[0].data["finding_count"] == 1


def test_valid_json_survives_unexpected_exit_code(tmp_path):
    # semgrep can emit a full results doc yet exit non-0/1 (observed on windows)
    out = json.dumps({"results": [], "version": "1.0"}).encode()
    res = _distribute(tmp_path, _FakeProc(2, stdout=out))
    assert res[0].status == "completed"
    assert res[0].data["finding_count"] == 0


def test_no_output_fails_with_exit_code(tmp_path):
    res = _distribute(tmp_path, _FakeProc(2, stdout=b"", stderr=b"boom"))
    assert res[0].status == "failed"
    # the opaque "semgrep error:" is gone - exit code and stderr are surfaced
    assert "exit 2" in res[0].error
    assert "boom" in res[0].error


def test_unparseable_output_fails_with_exit_code(tmp_path):
    res = _distribute(tmp_path, _FakeProc(0, stdout=b"not json"))
    assert res[0].status == "failed"
    assert "exit 0" in res[0].error


def test_scan_errors_with_no_results_fail_loudly(tmp_path):
    # a bad --config makes semgrep exit 0 with errors but no results; that must
    # not look like "no vulnerabilities found"
    out = json.dumps(
        {"results": [], "errors": [{"message": "config error: rules not found"}]}
    ).encode()
    res = _distribute(tmp_path, _FakeProc(0, stdout=out))
    assert res[0].status == "failed"
    assert "no results" in res[0].error
    assert "config error" in res[0].error


def test_findings_present_tolerate_nonfatal_errors(tmp_path):
    # per-file parse warnings alongside real results should not fail the scan
    out = json.dumps(
        {
            "results": [
                {
                    "check_id": "r1",
                    "path": "x/s1_dispatch.c",
                    "start": {"line": 1},
                    "end": {"line": 1},
                    "extra": {"severity": "ERROR", "message": "m"},
                }
            ],
            "errors": [{"message": "could not parse one file"}],
        }
    ).encode()
    res = _distribute(tmp_path, _FakeProc(0, stdout=out))
    assert res[0].status == "completed"
    assert res[0].data["finding_count"] == 1
