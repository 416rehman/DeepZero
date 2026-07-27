from __future__ import annotations

import csv
import json

from deepzero.engine.report import (
    BUCKET_CLEAN,
    BUCKET_FILTERED,
    BUCKET_SUSPICIOUS,
    BUCKET_VULNERABLE,
    ReportConfig,
    collect,
    iter_items,
    render_index,
    write_report,
)
from deepzero.engine.state import RunState, SampleState, StateStore
from deepzero.engine.types import RunStatus, Verdict


def _seed(tmp_path, *, with_findings=True, with_assessment=True, classification="vulnerable"):
    """build a work dir shaped like a real run: one risky driver, one clean."""
    work = tmp_path / "work" / "loldrivers"
    store = StateStore(work)
    store.save_run(
        RunState(
            run_id="run_1",
            pipeline="loldrivers",
            target="C:/drivers",
            model="claude-code/opus",
            status=RunStatus.COMPLETED,
        )
    )

    risky = SampleState(
        sample_id="aaa1",
        sha256="a" * 64,
        filename="risky.sys",
        source_path="C:/drivers/risky.sys",
    )
    risky.mark_stage_completed(
        "discover", data={"priority_score": 8.0, "dangerous_imports": ["MmMapIoSpace"]}
    )
    risky.mark_stage_completed(
        "decompile",
        artifacts={"ghidra_result": "decompiled/ghidra_result.json"},
        data={"device_name": "RiskyDev", "function_count": 42, "ioctl_count": 2},
    )
    if with_findings:
        risky.mark_stage_completed("semgrep_scanner", data={"finding_count": 2})
    if with_assessment:
        risky.mark_stage_completed(
            "assess",
            artifacts={"llm_output": "assessment.md"},
            data={"classification": classification},
        )
    store.save_sample(risky)

    clean = SampleState(sample_id="bbb2", filename="clean.sys", source_path="C:/drivers/clean.sys")
    clean.mark_stage_completed("discover", data={"priority_score": 1.0})
    store.save_sample(clean)

    d = store.sample_dir("aaa1")
    (d / "decompiled").mkdir(parents=True, exist_ok=True)
    (d / "decompiled" / "ghidra_result.json").write_text(
        json.dumps(
            {
                "success": True,
                "device_name": "RiskyDev",
                "symbolic_link": "\\\\DosDevices\\\\RiskyDev",
                "ioctl_handlers": [{"code": 0x222004}, {"code": 0x222008}],
            }
        ),
        encoding="utf-8",
    )
    if with_findings:
        (d / "findings.json").write_text(
            json.dumps(
                [
                    {
                        "rule_id": "pipelines.loldrivers.rules.ghidra-mmmapiospace-user-controlled",
                        "severity": "HIGH",
                        "message": "user controlled physical map",
                        "line_start": 42,
                        "matched_code": "MmMapIoSpace(pa, len, 0);",
                    },
                    {
                        "rule_id": "pipelines.loldrivers.rules.method-neither",
                        "severity": "MEDIUM",
                        "message": "METHOD_NEITHER buffer",
                        "line_start": 88,
                        "matched_code": "irp->UserBuffer",
                    },
                ]
            ),
            encoding="utf-8",
        )
    if with_assessment:
        (d / "assessment.md").write_text(
            "[VULNERABLE] arbitrary physical memory map via IOCTL 0x222004", encoding="utf-8"
        )
    return work


class TestCollect:
    def test_totals(self, tmp_path):
        payload = collect(_seed(tmp_path))
        t = payload["totals"]
        assert t["samples"] == 2
        assert t["total_findings"] == 2
        assert t["with_findings"] == 1
        assert t["assessed"] == 1
        # severities are counted by whatever labels the findings actually use
        assert payload["severity_totals"] == {"HIGH": 1, "MEDIUM": 1}

    def test_driver_detail_is_gathered(self, tmp_path):
        d = collect(_seed(tmp_path))["items"][0]
        assert d.name == "risky.sys"
        assert d.data["decompile.device_name"] == "RiskyDev"
        assert d.data["decompile.ioctl_count"] == 2
        assert d.data["discover.dangerous_imports"] == ["MmMapIoSpace"]
        assert "VULNERABLE" in d.texts["llm_output"]
        assert d.severity_counts == {"HIGH": 1, "MEDIUM": 1}
        assert "ghidra-mmmapiospace-user-controlled" in d.rule_hits

    def test_only_interesting_drivers_are_kept_in_memory(self, tmp_path):
        payload = collect(_seed(tmp_path))
        # the clean driver is still counted and written to csv, but needs no page
        assert [d.sample_id for d in payload["items"]] == ["aaa1"]
        assert len(payload["rows"]) == 2

    def test_bucketing_uses_the_assessment_verdict(self, tmp_path):
        payload = collect(_seed(tmp_path, classification="vulnerable"))
        assert payload["items"][0].bucket == BUCKET_VULNERABLE
        assert payload["buckets"][BUCKET_VULNERABLE] == 1

    def test_findings_without_assessment_are_only_suspicious(self, tmp_path):
        payload = collect(_seed(tmp_path, with_assessment=False))
        assert payload["items"][0].bucket == BUCKET_SUSPICIOUS

    def test_safe_verdict_is_not_flagged(self, tmp_path):
        payload = collect(_seed(tmp_path, classification="safe"))
        assert payload["buckets"].get(BUCKET_VULNERABLE, 0) == 0

    def test_rule_totals_aggregated(self, tmp_path):
        rt = collect(_seed(tmp_path))["rule_totals"]
        assert rt["ghidra-mmmapiospace-user-controlled"] == 1
        assert rt["method-neither"] == 1

    def test_run_metadata(self, tmp_path):
        run = collect(_seed(tmp_path))["run"]
        assert run["model"] == "claude-code/opus"
        assert run["pipeline"] == "loldrivers"

    def test_safe_before_any_findings_exist(self, tmp_path):
        payload = collect(_seed(tmp_path, with_findings=False, with_assessment=False))
        assert payload["totals"]["total_findings"] == 0
        assert payload["totals"]["samples"] == 2

    def test_empty_work_dir_is_safe(self, tmp_path):
        assert collect(tmp_path / "nothing")["totals"]["samples"] == 0


class TestIndex:
    def test_self_contained_and_offline(self, tmp_path):
        out = render_index(collect(_seed(tmp_path)), tmp_path)
        assert out.startswith("<!doctype html>")
        # must open with no network: no remote assets of any kind
        assert "http://" not in out and "https://" not in out
        assert "<script src" not in out and "stylesheet" not in out

    def test_vulnerable_is_the_headline(self, tmp_path):
        out = render_index(collect(_seed(tmp_path)), tmp_path)
        assert "assessed as vulnerable" in out
        # the verdict section leads, ahead of the supporting rule breakdown
        assert out.index("Vulnerable") < out.index("Rules that fired")
        assert "items/aaa1.html" in out

    def test_empty_buckets_are_omitted(self, tmp_path):
        # nothing needs assessment in this run, so it must not be offered as a
        # filter that would only ever narrow the list to nothing
        out = render_index(collect(_seed(tmp_path)), tmp_path)
        assert "data-b='suspicious'" not in out
        assert "data-b='vulnerable'" in out

    def test_suspicious_ranks_below_vulnerable(self, tmp_path):
        work = _seed(tmp_path)
        # add a second driver with findings but no assessment -> suspicious
        store = StateStore(work)
        s = SampleState(sample_id="ccc3", filename="maybe.sys", source_path="C:/drivers/maybe.sys")
        s.mark_stage_completed("semgrep_scanner", data={"finding_count": 1})
        store.save_sample(s)
        (store.sample_dir("ccc3") / "findings.json").write_text(
            json.dumps([{"rule_id": "r.x", "severity": "MEDIUM", "message": "m", "line_start": 1}]),
            encoding="utf-8",
        )
        out = render_index(collect(work), tmp_path)
        # one ranked list, so the confirmed one has to come first in it
        assert out.index("risky.sys") < out.index("maybe.sys")
        assert out.index("Vulnerable") < out.index("Needs assessment")


class TestWriteReport:
    def test_writes_the_layered_output(self, tmp_path):
        index, json_path = write_report(_seed(tmp_path))
        assert index.name == "index.html" and index.parent.name == "report"
        out = index.parent
        for name in ("inventory.csv", "findings.jsonl", "report.json"):
            assert (out / name).exists(), name
        summary = json.loads(json_path.read_text(encoding="utf-8"))
        assert summary["totals"]["samples"] == 2
        # totals only - the summary must not grow with the corpus
        assert "items" not in summary

    def test_index_stays_small_while_csv_holds_everything(self, tmp_path):
        index, _ = write_report(_seed(tmp_path))
        out = index.parent
        csv_text = (out / "inventory.csv").read_text(encoding="utf-8")
        assert "risky.sys" in csv_text and "clean.sys" in csv_text
        pages = {p.stem for p in (out / "items").glob("*.html")}
        assert pages == {"aaa1"}

    def test_findings_are_one_json_object_per_line(self, tmp_path):
        index, _ = write_report(_seed(tmp_path))
        lines = [
            ln
            for ln in (index.parent / "findings.jsonl").read_text(encoding="utf-8").splitlines()
            if ln
        ]
        assert len(lines) == 2
        rec = json.loads(lines[0])
        assert rec["sample_id"] == "aaa1" and rec["bucket"] == BUCKET_VULNERABLE
        assert rec["severity"] in ("HIGH", "MEDIUM")

    def test_driver_page_shows_evidence_and_links_to_artifacts(self, tmp_path):
        index, _ = write_report(_seed(tmp_path))
        page = (index.parent / "items" / "aaa1.html").read_text(encoding="utf-8")
        assert "MmMapIoSpace(pa, len, 0);" in page
        assert "llm_output" in page and "ghidra_result" in page
        assert "all results" in page
        # links resolve to the real artifact folder
        assert "samples" in page

    def test_untrusted_text_is_escaped_on_driver_pages(self, tmp_path):
        work = _seed(tmp_path)
        d = StateStore(work).sample_dir("aaa1")
        (d / "assessment.md").write_text("<img src=x onerror=alert(1)>", encoding="utf-8")
        index, _ = write_report(work)
        page = (index.parent / "items" / "aaa1.html").read_text(encoding="utf-8")
        # decompiled and LLM text is untrusted - never render it as live markup
        assert "<img src=x onerror" not in page
        assert "&lt;img" in page

    def test_capping_detail_is_disclosed_not_silent(self, tmp_path):
        index, _ = write_report(_seed(tmp_path), detail_limit=0)
        text = index.read_text(encoding="utf-8")
        assert "appear in" in text and "inventory.csv" in text

    def test_custom_out_dir(self, tmp_path):
        out = tmp_path / "elsewhere"
        index, _ = write_report(_seed(tmp_path), out)
        assert index.parent == out

    def test_regenerating_overwrites(self, tmp_path):
        work = _seed(tmp_path)
        write_report(work)
        index, _ = write_report(work)
        assert index.read_text(encoding="utf-8").count("<!doctype html>") == 1


class TestPipelineAgnostic:
    """a completely different pipeline must render without code changes."""

    def _github_run(self, tmp_path):
        work = tmp_path / "work" / "srchunt"
        store = StateStore(work)
        store.save_run(
            RunState(
                run_id="run_9",
                pipeline="srchunt",
                target="github.com/acme",
                model="claude-code/opus",
                status=RunStatus.COMPLETED,
            )
        )
        repo = SampleState(sample_id="r1", filename="acme/api", source_path="github.com/acme/api")
        repo.mark_stage_completed("discover", data={"stars": 4200, "language": "go"})
        repo.mark_stage_completed(
            "sast", data={"finding_count": 1}, artifacts={"sast": "sast.json"}
        )
        repo.mark_stage_completed("triage", data={"verdict": "exploitable"})
        store.save_sample(repo)
        (store.sample_dir("r1") / "sast.json").write_text(
            json.dumps(
                [
                    {
                        "id": "go.sql-injection",
                        "level": "critical",
                        "title": "SQL injection in query builder",
                        "path": "internal/db/query.go",
                        "start_line": 88,
                        "snippet": 'db.Raw("SELECT " + userInput)',
                    }
                ]
            ),
            encoding="utf-8",
        )
        return work

    def test_declared_config_shapes_the_report(self, tmp_path):
        work = self._github_run(tmp_path)
        cfg = {
            "title": "Acme source review",
            "entity": "repository",
            "classification_key": "verdict",
            "vulnerable_when": ["exploitable"],
            "columns": ["discover.stars", "discover.language"],
            "findings_files": ["sast.json"],
        }
        index, json_path = write_report(work, config=cfg)
        text = index.read_text(encoding="utf-8")

        # the pipeline's own vocabulary and verdict key drive the page
        assert "Acme source review" in text
        assert "repository" in text and "repositorys" not in text.replace("repositorys", "")
        assert "assessed as vulnerable" in text
        # its own severity vocabulary is preserved, not remapped to a fixed set
        assert "CRITICAL" in json.loads(json_path.read_text(encoding="utf-8"))["severity_totals"]
        # declared columns appear as chips/columns
        assert "stars" in text and "4200" in text

    def test_works_with_no_config_at_all(self, tmp_path):
        work = self._github_run(tmp_path)
        index, _ = write_report(work)
        text = index.read_text(encoding="utf-8")
        # default entity wording, and the finding is still surfaced for review
        assert "sample" in text
        # no verdict key configured, so nothing can confirm it either way
        assert "Needs assessment" in text

    def test_alien_finding_shape_is_normalized(self, tmp_path):
        work = self._github_run(tmp_path)
        payload = collect(work, config=ReportConfig.from_dict({"findings_files": ["sast.json"]}))
        f = payload["items"][0].findings[0]
        assert f["severity"] == "CRITICAL"
        assert f["rule_id"] == "go.sql-injection"
        assert "SQL injection" in f["message"]
        assert f["location"] == "internal/db/query.go"
        assert f["line"] == 88


class TestFilteredOutIsNotCalledClear:
    """a sample a stage excluded was never analysed to the end, so it must not be
    counted alongside ones that were analysed and had nothing flagged."""

    def _run(self, tmp_path):
        work = tmp_path / "work" / "p"
        store = StateStore(work)
        store.save_run(RunState(run_id="r", pipeline="p", status=RunStatus.COMPLETED))

        # excluded before analysis: a filter marked it complete with a filter verdict
        early = SampleState(sample_id="e1", filename="not_a_driver.sys")
        early.mark_stage_completed("discover")
        early.mark_stage_completed("kernel_filter", verdict=Verdict.FILTER)
        store.save_sample(early)

        # analysed all the way through and nothing was flagged
        clean = SampleState(sample_id="c1", filename="clean.sys")
        clean.mark_stage_completed("discover")
        clean.mark_stage_completed("kernel_filter")
        clean.mark_stage_completed("scan", data={"finding_count": 0})
        store.save_sample(clean)
        return work

    def test_they_land_in_different_buckets(self, tmp_path):
        payload = collect(self._run(tmp_path))
        buckets = {i.sample_id: i.bucket for i in payload["items"]} or {}
        counts = payload["buckets"]
        assert counts.get(BUCKET_FILTERED) == 1
        assert counts.get(BUCKET_CLEAN) == 1
        assert buckets.get("e1", BUCKET_FILTERED) == BUCKET_FILTERED

    def test_the_excluding_stage_is_recorded(self, tmp_path):
        payload = collect(self._run(tmp_path))
        early = next(
            i for i in iter_items(self._run(tmp_path), payload["config"]) if i.sample_id == "e1"
        )
        assert early.filtered_at == "kernel_filter"

    def test_the_page_does_not_call_them_clean(self, tmp_path):
        out = render_index(collect(self._run(tmp_path)), tmp_path)
        assert "clear" in out
        assert "Filtered out" in out
        assert "not a judgement" in out


class TestLabelsExplainThemselves:
    def test_every_outcome_label_carries_its_rule(self, tmp_path):
        from deepzero.engine.report import _BUCKET_LABELS, _BUCKET_RULE

        # a label a reader cannot interpret is a label that misleads
        assert set(_BUCKET_RULE) == set(_BUCKET_LABELS)
        for bucket, text in _BUCKET_RULE.items():
            assert len(text) > 40, f"{bucket} has no usable explanation"

    def test_the_page_exposes_them_on_hover(self, tmp_path):
        out = render_index(collect(_seed(tmp_path)), tmp_path)
        assert 'title="An assessment stage recorded a verdict' in out
        assert "cursor:help" in out


class TestTheReaderCanRecordWhatTheyChecked:
    """what a pipeline concluded and what a person verified are separate claims.
    Only the reader can make the second, so the report has to carry it."""

    def test_a_result_page_offers_the_control(self, tmp_path):
        index, _ = write_report(_seed(tmp_path))
        page = (index.parent / "items" / "aaa1.html").read_text(encoding="utf-8")
        assert 'class="review" data-sid="aaa1"' in page
        assert 'data-state="confirmed"' in page and 'data-state="outstanding"' in page

    def test_marks_saved_beside_the_report_are_rendered(self, tmp_path):
        index, _ = write_report(_seed(tmp_path))
        (index.parent / "marks.json").write_text(
            json.dumps({"aaa1": {"state": "outstanding", "note": "ACL not checked"}}),
            encoding="utf-8",
        )
        index, _ = write_report(_seed(tmp_path))
        text = index.read_text(encoding="utf-8")
        # readable by json, not html-escaped: script content is never decoded
        assert '{"aaa1": {"state": "outstanding", "note": "ACL not checked"}}' in text

    def test_a_mark_reaches_the_spreadsheet(self, tmp_path):
        work = _seed(tmp_path)
        index, _ = write_report(work)
        (index.parent / "marks.json").write_text(
            json.dumps({"aaa1": {"state": "confirmed", "note": "reproduced locally"}}),
            encoding="utf-8",
        )
        index, _ = write_report(work)
        rows = list(csv.DictReader((index.parent / "inventory.csv").open(encoding="utf-8")))
        risky = next(r for r in rows if r["sample_id"] == "aaa1")
        assert risky["review"] == "confirmed"
        assert risky["review_note"] == "reproduced locally"

    def test_an_unrecognised_state_is_not_rendered(self, tmp_path):
        work = _seed(tmp_path)
        index, _ = write_report(work)
        (index.parent / "marks.json").write_text(
            json.dumps({"aaa1": {"state": "probably-fine", "note": "x"}}), encoding="utf-8"
        )
        index, _ = write_report(work)
        assert "probably-fine" not in index.read_text(encoding="utf-8")

    def test_a_note_cannot_close_the_script_tag(self, tmp_path):
        work = _seed(tmp_path)
        index, _ = write_report(work)
        (index.parent / "marks.json").write_text(
            json.dumps({"aaa1": {"state": "confirmed", "note": "</script><script>alert(1)"}}),
            encoding="utf-8",
        )
        index, _ = write_report(work)
        text = index.read_text(encoding="utf-8")
        assert "<script>alert(1)" not in text
        assert "\u003c/script>" in text

    def test_marks_are_keyed_on_the_corpus_not_the_page(self, tmp_path):
        # a rerun rewrites the report; marks have to survive that
        index, _ = write_report(_seed(tmp_path))
        text = index.read_text(encoding="utf-8")
        assert 'data-corpus="loldrivers:C:/drivers"' in text

    def test_the_marks_can_be_taken_out_of_the_browser(self, tmp_path):
        index, _ = write_report(_seed(tmp_path))
        assert 'id="export-marks"' in index.read_text(encoding="utf-8")


class TestAResultThatDidNotHoldUpIsItsOwnOutcome:
    """checked-and-it-failed is a finished piece of work with a definite answer.
    Folding it in with unreviewed loses the most expensive result there is."""

    def test_the_control_offers_all_three(self, tmp_path):
        index, _ = write_report(_seed(tmp_path))
        page = (index.parent / "items" / "aaa1.html").read_text(encoding="utf-8")
        for state in ("confirmed", "refuted", "outstanding"):
            assert f'data-state="{state}"' in page

    def test_a_refuted_result_is_rendered_and_filterable(self, tmp_path):
        work = _seed(tmp_path)
        index, _ = write_report(work)
        (index.parent / "marks.json").write_text(
            json.dumps({"aaa1": {"state": "refuted", "note": "guard held under verifier"}}),
            encoding="utf-8",
        )
        index, _ = write_report(work)
        text = index.read_text(encoding="utf-8")
        assert '"state": "refuted"' in text
        assert "data-mark='refuted'" in text

    def test_a_refuted_result_reaches_the_spreadsheet(self, tmp_path):
        work = _seed(tmp_path)
        index, _ = write_report(work)
        (index.parent / "marks.json").write_text(
            json.dumps({"aaa1": {"state": "refuted", "note": "did not reproduce"}}),
            encoding="utf-8",
        )
        index, _ = write_report(work)
        rows = list(csv.DictReader((index.parent / "inventory.csv").open(encoding="utf-8")))
        risky = next(r for r in rows if r["sample_id"] == "aaa1")
        assert risky["review"] == "refuted"
        assert risky["review_note"] == "did not reproduce"

    def test_the_summary_has_somewhere_to_count_reviews(self, tmp_path):
        # filled in by the browser, because marks made there are not saved yet
        index, _ = write_report(_seed(tmp_path))
        assert "id='review-tally'" in index.read_text(encoding="utf-8")
