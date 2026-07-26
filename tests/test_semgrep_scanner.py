import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from deepzero.engine.stage import ProcessorContext, ProcessorEntry, ProcessorResult, StageSpec
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

    def test_validate_and_process_resolve_the_same_path(self, tmp_path, monkeypatch):
        # the check that approves a run and the run itself must agree on where
        # the rules live, otherwise a scan can start with no rules loaded.
        # pin cwd so the cwd-relative "rules" resolves deterministically.
        monkeypatch.chdir(tmp_path)
        rules = tmp_path / "rules"
        rules.mkdir()
        (rules / "r.yaml").write_text("rules: []")
        scanner = self._scanner("rules")
        ctx = _ctx(tmp_path)

        validation = scanner.validate(ctx)
        # [] when semgrep is installed, else only the "semgrep CLI not found" note
        assert validation == [] or "semgrep CLI" in validation[0]
        assert scanner._resolve_rules_path(ctx) == rules.resolve()
        assert scanner._resolve_rules_path(ctx).exists()

    def test_missing_rules_dir_flagged(self, tmp_path):
        scanner = self._scanner("does_not_exist_anywhere")
        ctx = _ctx(tmp_path)
        errs = [e for e in scanner.validate(ctx) if "rules_dir" in e]
        assert errs

    def test_process_fails_fast_when_rules_unresolvable(self, tmp_path):
        # must not fall back to scanning with an unintended config path
        scanner = self._scanner("nope_missing_rules")
        ctx = _ctx(tmp_path)
        results = scanner.process(ctx, [_entry(tmp_path)])
        assert len(results) == 1
        assert results[0].status == "failed"
        assert "rules_dir not found" in results[0].error


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


def _distribute(tmp_path, proc, file_to_sample=None):
    scanner = _scanner(tmp_path)
    entry = _entry(tmp_path)
    uncached = [(0, entry)]
    results = [None]
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        # the scan records each sample's outcome in `results` rather than
        # returning them, so a batch that fails only marks its own samples
        asyncio.run(
            scanner._run_and_distribute(
                Path("rules"),
                tmp_path / "bulk",
                300,
                uncached,
                file_to_sample if file_to_sample is not None else {"s1_dispatch.c": 0},
                results,
                0,
            )
        )
    return results


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


class TestAScanThatNeverLookedIsNotACleanResult:
    """zero findings because the files were read, and zero findings because they
    were never opened, reach the report identically unless they are separated
    here - and the second sends an unexamined corpus on to assessment."""

    def test_reading_none_of_the_submitted_files_fails(self, tmp_path):
        out = json.dumps({"results": [], "paths": {"scanned": []}}).encode()
        res = _distribute(tmp_path, _FakeProc(0, stdout=out))
        assert res[0].status == "failed"
        assert "read none of the 1 files submitted" in res[0].error

    def test_reading_the_files_and_finding_nothing_is_a_clean_result(self, tmp_path):
        out = json.dumps({"results": [], "paths": {"scanned": ["b/s1_dispatch.c"]}}).encode()
        res = _distribute(tmp_path, _FakeProc(0, stdout=out))
        assert res[0].status == "completed"
        assert res[0].data["finding_count"] == 0
        assert res[0].data["files_scanned"] == 1
        assert res[0].data["files_submitted"] == 1

    def test_a_sample_whose_files_went_unread_is_visible(self, tmp_path):
        # semgrep read something, just not this sample's file: not a batch
        # failure, but the count has to show why it reported nothing
        out = json.dumps({"results": [], "paths": {"scanned": ["b/other_x.c"]}}).encode()
        res = _distribute(tmp_path, _FakeProc(0, stdout=out))
        assert res[0].status == "completed"
        assert res[0].data["files_submitted"] == 1
        assert res[0].data["files_scanned"] == 0

    def test_semgrep_not_reporting_scanned_paths_stays_a_clean_result(self, tmp_path):
        # older semgrep versions omit paths entirely; absence is not evidence
        out = json.dumps({"results": [], "version": "1.0"}).encode()
        res = _distribute(tmp_path, _FakeProc(0, stdout=out))
        assert res[0].status == "completed"
        assert "files_scanned" not in res[0].data


class TestOneBadBatchDoesNotDiscardTheRest:
    def _entries(self, tmp_path, n):
        out = []
        for i in range(n):
            d = tmp_path / "work" / "samples" / f"s{i}"
            (d / "decompiled").mkdir(parents=True, exist_ok=True)
            (d / "decompiled" / "dispatch.c").write_text("int main(){}", encoding="utf-8")
            out.append(
                ProcessorEntry(
                    sample_id=f"s{i}",
                    source_path=tmp_path / f"s{i}.sys",
                    filename=f"s{i}.sys",
                    sample_dir=d,
                )
            )
        return out

    def test_samples_are_scanned_in_batches(self, tmp_path):
        rules = tmp_path / "rules"
        rules.mkdir()
        scanner = SemgrepScanner(
            StageSpec(
                name="scan",
                processor="semgrep",
                config={"rules_dir": str(rules), "batch_size": 2},
            )
        )
        entries = self._entries(tmp_path, 5)
        seen: list[int] = []

        async def fake_run(rules_path, bulk_dir, timeout, batch, f2s, results, min_findings):
            seen.append(len(batch))
            for idx, _ in batch:
                results[idx] = scanner._make_result([], 0, cached=False, submitted=1, scanned=1)

        with patch.object(scanner, "_run_and_distribute", side_effect=fake_run):
            res = scanner.process(_ctx(tmp_path), entries)

        # five samples at two per batch, and every one still accounted for
        assert seen == [2, 2, 1]
        assert len(res) == 5
        assert all(r.status == "completed" for r in res)

    def test_a_failing_batch_costs_only_its_own_samples(self, tmp_path):
        rules = tmp_path / "rules"
        rules.mkdir()
        scanner = SemgrepScanner(
            StageSpec(
                name="scan",
                processor="semgrep",
                config={"rules_dir": str(rules), "batch_size": 2},
            )
        )
        entries = self._entries(tmp_path, 4)
        calls = {"n": 0}

        async def fake_run(rules_path, bulk_dir, timeout, batch, f2s, results, min_findings):
            calls["n"] += 1
            failed = calls["n"] == 1
            for idx, _ in batch:
                results[idx] = (
                    ProcessorResult.fail("semgrep batch timed out after 300s")
                    if failed
                    else scanner._make_result([], 0, cached=False, submitted=1, scanned=1)
                )

        with patch.object(scanner, "_run_and_distribute", side_effect=fake_run):
            res = scanner.process(_ctx(tmp_path), entries)

        statuses = [r.status for r in res]
        assert statuses.count("failed") == 2
        assert statuses.count("completed") == 2
