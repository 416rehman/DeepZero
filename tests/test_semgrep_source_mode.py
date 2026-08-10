from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from deepzero.engine.stage import ProcessorContext, ProcessorEntry, StageSpec
from processors.semgrep_scanner.semgrep_scanner import SemgrepScanner

needs_semgrep = pytest.mark.skipif(
    shutil.which("semgrep") is None, reason="semgrep CLI not installed"
)


def _scanner(**config) -> SemgrepScanner:
    return SemgrepScanner(StageSpec(name="scan", processor="semgrep", config=config))


def _entry(tmp_path, sample_id="s1", source_path=None) -> ProcessorEntry:
    """a sample as the engine hands it over: a working dir, plus wherever the
    thing being analysed actually lives."""
    sample_dir = tmp_path / "work" / "samples" / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    return ProcessorEntry(
        sample_id=sample_id,
        source_path=source_path if source_path is not None else tmp_path / f"{sample_id}.sys",
        filename=sample_id,
        sample_dir=sample_dir,
    )


def _checkout(root, files: dict[str, str]):
    """a source tree keyed by path within it, the shape a repository ingest hands on."""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _ctx(pipeline_dir):
    return ProcessorContext(pipeline_dir=pipeline_dir, global_config={}, llm=None)


def _rules_dir(root, body: str = "") -> Path:
    """process() refuses to run without rules on disk, so every scan needs one."""
    rules = root / "rules"
    rules.mkdir(exist_ok=True)
    if body:
        (rules / "rules.yaml").write_text(body, encoding="utf-8")
    return rules


class TestTheScanTreeFollowsWhatIngestProduced:
    """a driver pipeline decompiles into the sample's working directory, while a
    source pipeline ingests a checkout that was never copied there. Pointing the
    scan at the wrong one of those two finds nothing and reports it as clean."""

    def test_an_empty_target_dir_scans_the_checkout_itself(self, tmp_path):
        # the checkout holds nothing this scan looks at, so it completes without
        # semgrep. What it proves is which tree was read: a scan still pointed
        # at a decompiled subdirectory would have failed on the missing path.
        checkout = _checkout(tmp_path / "repo", {"notes.md": "# readme"})
        scanner = _scanner(rules_dir=str(_rules_dir(tmp_path)), target_dir="")
        results = scanner.process(_ctx(tmp_path), [_entry(tmp_path, source_path=checkout)])
        assert results[0].status == "completed"
        assert results[0].data["files_submitted"] == 0

    def test_an_unset_target_dir_still_scans_the_decompiled_subdirectory(self, tmp_path):
        # the driver pipeline never set this, so leaving it out has to keep
        # meaning exactly what it meant before source mode existed
        scanner = _scanner(rules_dir=str(_rules_dir(tmp_path)))
        entry = _entry(tmp_path)
        results = scanner.process(_ctx(tmp_path), [entry])
        assert results[0].status == "failed"
        assert str(entry.sample_dir / "decompiled") in results[0].error

    def test_a_named_target_dir_stays_relative_to_the_sample_dir(self, tmp_path):
        scanner = _scanner(rules_dir=str(_rules_dir(tmp_path)), target_dir="sources")
        entry = _entry(tmp_path)
        results = scanner.process(_ctx(tmp_path), [entry])
        assert str(entry.sample_dir / "sources") in results[0].error

    def test_a_checkout_that_is_not_there_is_named_in_the_failure(self, tmp_path):
        # the reader has to be able to tell "the clone never landed" from
        # "the decompile stage did not run", and only the path says which
        scanner = _scanner(rules_dir=str(_rules_dir(tmp_path)), target_dir="")
        entry = _entry(tmp_path, source_path=tmp_path / "repo_never_cloned")
        results = scanner.process(_ctx(tmp_path), [entry])
        assert results[0].status == "failed"
        assert "repo_never_cloned" in results[0].error


class TestWhatCountsAsSourceIsDeclaredByThePipeline:
    """the shipped default matches decompiler output. A repository pipeline that
    could only ever scan .c files would silently ignore most of its corpus."""

    def test_the_default_set_covers_decompiler_output(self, tmp_path):
        # a pipeline that configures nothing gets what the decompiler writes,
        # which is the behaviour the driver pipeline has always relied on
        checkout = _checkout(
            tmp_path / "repo",
            {"a.c": "", "b.h": "", "c.cpp": "", "d.py": "", "e.go": "", "f.md": ""},
        )
        staged = _scanner()._build_bulk_dir(
            [(0, _entry(tmp_path, source_path=checkout))], tmp_path / "bulk", ""
        )
        assert set(staged) == {"s1_a.c", "s1_b.h", "s1_c.cpp", "s1_d.py"}

    def test_a_configured_set_replaces_the_default(self):
        exts = _scanner(extensions=[".go", ".ts"])._scan_extensions()
        assert exts == (".go", ".ts")
        assert ".c" not in exts

    def test_extensions_may_be_written_without_the_dot(self):
        # yaml authors write `extensions: [go, rs]`; both spellings mean the same
        assert _scanner(extensions=["go", ".rs"])._scan_extensions() == (".go", ".rs")

    def test_a_single_extension_need_not_be_a_list(self):
        assert _scanner(extensions=".java")._scan_extensions() == (".java",)

    def test_only_the_configured_extensions_are_collected(self, tmp_path):
        checkout = _checkout(
            tmp_path / "repo",
            {
                "server.go": "package main",
                "notes.md": "# readme",
                "main.c": "int main(){}",
            },
        )
        scanner = _scanner(target_dir="", extensions=["go"])
        staged = scanner._build_bulk_dir(
            [(0, _entry(tmp_path, source_path=checkout))], tmp_path / "bulk", ""
        )
        assert list(staged) == ["s1_server.go"]

    def test_widening_the_set_reaches_files_the_default_would_skip(self, tmp_path):
        checkout = _checkout(
            tmp_path / "repo", {"server.go": "package main", "main.c": "int main(){}"}
        )
        entries = [(0, _entry(tmp_path, source_path=checkout))]
        default_staged = _scanner()._build_bulk_dir(entries, tmp_path / "bulk_default", "")
        widened = _scanner(extensions=[".c", ".go"])._build_bulk_dir(
            entries, tmp_path / "bulk_wide", ""
        )
        assert set(default_staged) == {"s1_main.c"}
        assert set(widened) == {"s1_main.c", "s1_server.go"}


class TestOneCheckoutsFilesDoNotOverwriteEachOther:
    """every sample's files are staged flat into a single directory for one
    semgrep invocation. A repository holds dozens of files called main.c or
    __init__.py, so naming by basename alone would drop all but the last of
    them and report the rest of the checkout as unscanned."""

    def test_a_repeated_basename_survives_staging(self, tmp_path):
        checkout = _checkout(
            tmp_path / "repo",
            {
                "cmd/api/main.go": "package main // api",
                "cmd/worker/main.go": "package main // worker",
            },
        )
        staged = _scanner(extensions=["go"])._build_bulk_dir(
            [(0, _entry(tmp_path, source_path=checkout))], tmp_path / "bulk", ""
        )
        assert len(staged) == 2
        contents = {(tmp_path / "bulk" / name).read_text(encoding="utf-8") for name in staged}
        assert contents == {"package main // api", "package main // worker"}

    def test_the_staged_name_carries_the_path_within_the_checkout(self, tmp_path):
        checkout = _checkout(tmp_path / "repo", {"cmd/api/main.c": "int main(){}"})
        staged = _scanner()._build_bulk_dir(
            [(0, _entry(tmp_path, source_path=checkout))], tmp_path / "bulk", ""
        )
        assert "s1_cmd__api__main.c" in staged

    def test_the_same_layout_in_two_repositories_stays_apart(self, tmp_path):
        # findings are routed back by staged filename, so a collision here would
        # attribute one repository's vulnerability to another
        first = _checkout(tmp_path / "one", {"src/main.c": "int a(){}"})
        second = _checkout(tmp_path / "two", {"src/main.c": "int b(){}"})
        staged = _scanner()._build_bulk_dir(
            [
                (0, _entry(tmp_path, sample_id="repo_one", source_path=first)),
                (1, _entry(tmp_path, sample_id="repo_two", source_path=second)),
            ],
            tmp_path / "bulk",
            "",
        )
        assert staged == {"repo_one_src__main.c": 0, "repo_two_src__main.c": 1}

    def test_decompiled_output_is_staged_the_same_way(self, tmp_path):
        # the naming change must not disturb the driver pipeline's routing
        entry = _entry(tmp_path)
        decompiled = entry.sample_dir / "decompiled"
        decompiled.mkdir(parents=True)
        (decompiled / "dispatch.c").write_text("int main(){}", encoding="utf-8")
        staged = _scanner()._build_bulk_dir([(0, entry)], tmp_path / "bulk", "decompiled")
        assert staged == {"s1_dispatch.c": 0}


@needs_semgrep
class TestAWholeCheckoutScansEndToEnd:
    """the pieces above are only worth having if a real semgrep run over a real
    checkout attributes its findings back to the right sample and file."""

    def _rules(self, tmp_path):
        return _rules_dir(
            tmp_path,
            "rules:\n"
            "  - id: python-eval\n"
            "    languages: [python]\n"
            "    severity: ERROR\n"
            "    message: eval on caller-supplied text\n"
            "    pattern: eval(...)\n",
        )

    def test_findings_land_on_the_repository_that_owns_them(self, tmp_path):
        risky = _checkout(
            tmp_path / "risky",
            {"web/views.py": "def run(req):\n    return eval(req.body)\n"},
        )
        clean = _checkout(
            tmp_path / "clean",
            {"web/views.py": "def run(req):\n    return int(req.body)\n"},
        )
        scanner = _scanner(rules_dir=str(self._rules(tmp_path)), target_dir="", extensions=[".py"])
        entries = [
            _entry(tmp_path, sample_id="risky", source_path=risky),
            _entry(tmp_path, sample_id="clean", source_path=clean),
        ]
        results = scanner.process(_ctx(tmp_path), entries)

        assert [r.status for r in results] == ["completed", "completed"]
        assert results[0].data["finding_count"] == 1
        assert results[1].data["finding_count"] == 0
        # both were read, so the clean one is a real answer and not an untouched tree
        assert results[1].data["files_submitted"] == 1
        assert results[1].data["files_scanned"] == 1

        findings = json.loads((entries[0].sample_dir / "findings.json").read_text(encoding="utf-8"))
        assert findings[0]["severity"] == "HIGH"
        # the path reaches the report as the scanner saw it, and the assessment
        # prompt tells the model to read that name back to a path in the repository
        assert Path(findings[0]["file"]).name == "risky_web__views.py"

    def test_the_finding_quotes_the_code_and_not_semgreps_login_notice(self, tmp_path):
        """an unauthenticated semgrep returns "requires login" in place of the
        matched source. That field is what the assessment prompt quotes to the
        model and what the report renders, so a finding carrying the notice
        instead of the code asks for a verdict on something nobody was shown."""
        risky = _checkout(
            tmp_path / "risky",
            {"web/views.py": "def run(req):\n    return eval(req.body)\n"},
        )
        scanner = _scanner(rules_dir=str(self._rules(tmp_path)), target_dir="", extensions=[".py"])
        entries = [_entry(tmp_path, sample_id="risky", source_path=risky)]
        scanner.process(_ctx(tmp_path), entries)

        findings = json.loads((entries[0].sample_dir / "findings.json").read_text(encoding="utf-8"))
        code = findings[0]["matched_code"]
        assert "requires login" not in code
        assert "eval(req.body)" in code
