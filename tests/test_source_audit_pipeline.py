"""the source_audit pipeline is configuration, and its failure mode is silence.

Most of what follows is an agreement between two files that nothing enforces at run
time: a scan whose extensions miss a rule's language, or a prompt whose verdict words
the report does not recognise, both produce a run that finishes cleanly and reports
nothing. These are the assertions that would have to break before that could happen
again.

The last class is the exception: it runs semgrep over a defect per language, because
a rule that parses is not the same as a rule that matches, and a rule that matches
nothing is invisible in every other check here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PIPELINE_DIR = Path(__file__).resolve().parent.parent / "pipelines" / "source_audit"

pytestmark = pytest.mark.skipif(
    not (PIPELINE_DIR / "pipeline.yaml").exists(),
    reason="source_audit pipeline not present in this checkout",
)

# what a semgrep rule's `languages:` entry means on disk. Only the languages this
# pipeline's rules actually declare need an entry; an unmapped one fails loudly
# in the coverage test rather than being quietly treated as covered.
LANGUAGE_EXTENSIONS = {
    "python": {".py"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs"},
    "js": {".js", ".jsx", ".mjs", ".cjs"},
    "typescript": {".ts", ".tsx"},
    "ts": {".ts", ".tsx"},
    "go": {".go"},
    "java": {".java"},
    "ruby": {".rb"},
    "rb": {".rb"},
    "php": {".php"},
    "csharp": {".cs"},
    "c": {".c", ".h"},
    "cpp": {".cc", ".cpp", ".cxx", ".hh", ".hpp"},
    "rust": {".rs"},
    "kotlin": {".kt", ".kts"},
    "scala": {".scala"},
    "swift": {".swift"},
    "bash": {".sh", ".bash"},
    "generic": set(),
    "regex": set(),
}


def _pipeline() -> dict:
    return yaml.safe_load((PIPELINE_DIR / "pipeline.yaml").read_text(encoding="utf-8"))


def _stage(name: str) -> dict:
    for stage in _pipeline()["stages"]:
        if stage["name"] == name:
            return stage
    raise AssertionError(f"pipeline has no stage named {name}")


def _rule_languages() -> set[str]:
    languages: set[str] = set()
    for rule in _rules():
        languages.update(str(lang).lower() for lang in rule.get("languages") or [])
    return languages


def _rules() -> list[dict]:
    rules: list[dict] = []
    for path in sorted(PIPELINE_DIR.glob("rules/*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules.extend(doc.get("rules") or [])
    return rules


class TestTheScanReachesEveryLanguageTheRulesTarget:
    """a rule for a language whose extension nobody listed never fires, and the
    repository is reported as having nothing wrong with it. Neither stage can
    notice: ingest counts zero files of a language it was not told about, and
    semgrep is handed a directory that simply has no java in it."""

    def test_rules_are_present_to_check(self):
        # an empty rules directory passes the scanner's own validate(), so the
        # rest of this file would assert nothing at all
        assert _rule_languages(), "pipelines/source_audit/rules holds no semgrep rules"

    def test_every_rule_language_is_mapped_to_extensions(self):
        unmapped = sorted(_rule_languages() - set(LANGUAGE_EXTENSIONS))
        assert not unmapped, (
            f"rules target {', '.join(unmapped)}, which this test cannot check. "
            f"add the extensions to LANGUAGE_EXTENSIONS before trusting the rest"
        )

    @pytest.mark.parametrize("stage_name", ["discover", "scan"])
    def test_the_stage_lists_an_extension_for_every_rule_language(self, stage_name):
        listed = set(_stage(stage_name)["config"]["extensions"])
        for language in sorted(_rule_languages()):
            wanted = LANGUAGE_EXTENSIONS[language]
            if not wanted:
                continue
            assert wanted & listed, (
                f"rules/ has {language} rules but the {stage_name} stage lists none of "
                f"{sorted(wanted)}, so those files are never read"
            )

    def test_no_extension_is_listed_that_no_rule_can_match(self):
        # the other direction: staging files for rules that do not exist costs a
        # walk, a hard link and a semgrep parse per file, and buys nothing
        covered: set[str] = set()
        for language in _rule_languages():
            covered |= LANGUAGE_EXTENSIONS[language]
        listed = set(_stage("scan")["config"]["extensions"])
        assert not listed - covered, (
            f"the scan stage lists {sorted(listed - covered)}, which no rule in rules/ can match"
        )

    def test_discover_and_scan_agree(self):
        # discover's count is what size_filter thresholds on, so a set that is
        # wider or narrower than the scan's makes those thresholds describe a
        # different corpus from the one that gets scanned
        assert _stage("discover")["config"]["extensions"] == _stage("scan")["config"]["extensions"]


class TestTheVerdictWordsSurviveTheReport:
    """the prompt's two markers, the stage's classify_by regex and the report's
    vulnerable_when/safe_when lists are three separate spellings of the same two
    outcomes. A mismatch buckets every finished repository as an unclear verdict."""

    def _classification(self, response: str) -> str:
        import re

        classify_by = _stage("assess")["config"]["classify_by"]
        match = re.search(classify_by, response[:200], re.IGNORECASE)
        return match.group(0).strip("[]").lower() if match else ""

    def _bucket(self, response: str) -> str:
        from deepzero.engine.report import ReportConfig, _classify

        cfg = ReportConfig.from_dict(_pipeline()["report"])
        return _classify(self._classification(response), cfg)

    def test_a_vulnerable_verdict_reaches_the_vulnerable_bucket(self):
        from deepzero.engine.report import BUCKET_VULNERABLE

        assert self._bucket("[VULNERABLE]\nsql injection in views.py") == BUCKET_VULNERABLE

    def test_a_cleared_verdict_reaches_the_clean_bucket(self):
        from deepzero.engine.report import BUCKET_CLEAN

        assert self._bucket("[NOT EXPLOITABLE]\nevery hit is under tests/") == BUCKET_CLEAN

    def test_the_two_markers_are_not_substrings_of_each_other(self):
        # _classify checks vulnerable_when first, so a negative marker containing
        # a positive word ("[NOT VULNERABLE]") would be filed as a vulnerability
        cfg_raw = _pipeline()["report"]
        for negative in cfg_raw["safe_when"]:
            for positive in cfg_raw["vulnerable_when"]:
                assert positive.lower() not in negative.lower()

    def test_an_unreadable_scan_claims_neither_verdict(self):
        # the prompt asks for this wording when the findings could not be read,
        # and it has to fall through to no classification rather than to clean
        assert self._bucket("findings unavailable\nthe scan output could not be read") == ""


class TestThePromptOnlyNamesValuesTheStagesRecord:
    """`deepzero validate` makes this check, but only when git and semgrep are
    installed - the processors' own validate() runs first and fails without them.
    This is the same check with nothing on PATH."""

    def test_every_variable_comes_from_an_earlier_stage(self):
        import jinja2
        from jinja2 import meta

        import deepzero.stages  # noqa: F401
        from deepzero.engine.stage import ALWAYS_PROVIDED, resolve_processor_class

        available = set(ALWAYS_PROVIDED)
        for stage in _pipeline()["stages"]:
            available |= set(getattr(resolve_processor_class(stage["processor"]), "provides", ()))

        template = (PIPELINE_DIR / "assessment.j2").read_text(encoding="utf-8")
        used = meta.find_undeclared_variables(jinja2.Environment(autoescape=False).parse(template))
        assert sorted(used - available) == []


class TestThePromptQuotesCodeAsItIsWritten:
    """the prompt is plain text and the values in it are source. Anything that
    escapes them for html sends the model `hdr-&gt;len` and invites a verdict on
    code the repository does not contain."""

    def _render(self, **template_vars) -> str:
        from deepzero.engine.stage import ProcessorContext, ProcessorEntry, StageSpec
        from deepzero.stages.llm import GenericLLM

        stage = GenericLLM(
            StageSpec(
                name="assess",
                processor="generic_llm",
                config=_stage("assess")["config"],
            )
        )
        sample_dir = Path(template_vars.pop("_sample_dir"))
        entry = ProcessorEntry(
            sample_id="s1",
            source_path=Path("/srv/widget"),
            filename="acme/widget",
            sample_dir=sample_dir,
        )
        entry._history = {"discover": _Output(template_vars)}
        ctx = ProcessorContext(pipeline_dir=PIPELINE_DIR, global_config={}, llm=None)
        return stage._render_prompt(str(PIPELINE_DIR / "assessment.j2"), ctx, entry)

    def test_code_reaches_the_model_unescaped(self, tmp_path):
        out = self._render(
            _sample_dir=tmp_path,
            finding_count=1,
            findings_json=[
                {
                    "rule_id": "source-audit.sqli",
                    "severity": "HIGH",
                    "message": "tainted sql",
                    "file": "s1_web__views.py",
                    "line_start": 12,
                    "matched_code": 'cur.execute("a=" + req.args["a"])  # hdr->len & x<y',
                }
            ],
        )
        assert 'cur.execute("a=" + req.args["a"])  # hdr->len & x<y' in out
        for escaped in ("&gt;", "&lt;", "&amp;", "&#34;", "&#39;"):
            assert escaped not in out

    def test_the_first_line_is_the_instruction_the_model_reads(self, tmp_path):
        # classify_by only searches the first 200 characters of the response, so
        # a prompt that opens with a stray blank line or a jinja tag's leftover
        # whitespace is worth catching here
        out = self._render(_sample_dir=tmp_path, finding_count=0)
        assert out.splitlines()[0].startswith("You are an expert vulnerability researcher")

    @pytest.mark.parametrize(
        "reported",
        [
            # semgrep reports the absolute path of the staged copy, which on
            # windows arrives with backslashes and may sit under a directory
            # whose own name has spaces in it
            r"C:\Users\a\AppData\Local\Temp\dz audit\.bulk_temp\semgrep_0\s1_web__views.py",
            "/tmp/dz audit/work/.bulk_temp/semgrep_0/s1_web__views.py",
            "s1_web__views.py",
        ],
    )
    def test_a_finding_is_quoted_at_its_path_inside_the_repository(self, tmp_path, reported):
        # the scanner stages every file flat, so what lands in findings.json is
        # a name like `s1_web__views.py` under a temp directory that is deleted
        # as soon as the scan ends. Asking the model for "the path inside the
        # repository" while showing it that is how a report comes back pointing
        # at a file the repository does not have.
        out = self._render(
            _sample_dir=tmp_path,
            finding_count=1,
            findings_json=[
                {
                    "rule_id": "source-audit.sqli",
                    "severity": "HIGH",
                    "message": "tainted sql",
                    "file": reported,
                    "line_start": 12,
                    "matched_code": "eval(x)",
                }
            ],
        )
        assert "web/views.py:12" in out
        assert "s1_web__views.py" not in out
        assert ".bulk_temp" not in out

    def test_the_severe_findings_survive_the_cap(self, tmp_path):
        # a repository produces hundreds of findings where a driver produced a
        # handful. Capping in scan order would show thirty LOW hits and drop the
        # one the assessment exists to judge.
        noise = [
            {
                "rule_id": f"source-audit.noise{i}",
                "severity": "LOW",
                "message": "style",
                "file": f"s1_pkg{i}__a.py",
                "line_start": i,
                "matched_code": "pass",
            }
            for i in range(40)
        ]
        hot = {
            "rule_id": "source-audit.rce",
            "severity": "HIGH",
            "message": "command injection",
            "file": "s1_web__admin.py",
            "line_start": 7,
            "matched_code": "os.system(cmd)",
        }
        out = self._render(_sample_dir=tmp_path, finding_count=41, findings_json=noise + [hot])
        assert "source-audit.rce" in out
        assert "the 30 most severe shown" in out

    def test_findings_that_could_not_be_read_are_not_reported_as_a_clean_tree(self, tmp_path):
        # min_findings keeps repositories with nothing flagged out of this stage,
        # so an empty findings list here means the artifact was lost, truncated
        # or unparseable. Telling the model there is nothing to judge would turn
        # a broken run into a confident all-clear.
        out = self._render(_sample_dir=tmp_path, finding_count=9)
        assert "could not be read back" in out
        assert "nothing to judge" not in out


class TestTheRulesKeepTheirTriageContract:
    """what a reviewer has in hand when a finding lands in front of them. The
    scanner records the rule id and the severity against every hit, so an id that
    lies about its language and a severity that does not mean what the other 135
    rules mean by it are both read as fact by whoever triages the result."""

    def test_every_rule_id_is_unique(self):
        # findings.json carries the id and nothing else that identifies the rule,
        # so two rules sharing one cannot be told apart in a report
        ids = [rule["id"] for rule in _rules()]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        assert not duplicated, f"these ids are used by more than one rule: {duplicated}"

    def test_the_id_names_a_language_the_rule_declares(self):
        # the id prefix is what tells a triager which language a hit is in, and
        # a rule copied to a new language keeps the old prefix unless someone looks
        wrong = [
            (rule["id"], rule["languages"])
            for rule in _rules()
            if rule["id"].split("-")[0] not in {str(x).lower() for x in rule["languages"]}
        ]
        assert not wrong, f"the id prefix does not name a declared language: {wrong}"

    def test_every_rule_says_what_class_it_is_and_how_far_to_trust_it(self):
        missing = [
            (rule["id"], key)
            for rule in _rules()
            for key in ("vuln_class", "cwe", "confidence")
            if not (rule.get("metadata") or {}).get(key)
        ]
        assert not missing, f"metadata missing: {missing}"

    def test_only_the_rules_marked_error_claim_exploitability(self):
        # ERROR here means a primitive an attacker can use, WARNING means a
        # heuristic that needs corroborating. Exploitability on a heuristic
        # promises a confidence the rule does not have.
        wrong = [
            (rule["id"], rule["severity"])
            for rule in _rules()
            if bool((rule.get("metadata") or {}).get("exploitability"))
            != (rule["severity"] == "ERROR")
        ]
        assert not wrong, f"severity and exploitability disagree: {wrong}"


# one defect per language, each the kind the rules exist to find. The value is
# not the coverage - it is that semgrep is made to load the directory and report
# something, which nothing else in this file does.
SMOKE_FIXTURES = {
    "smoke.py": (
        "python-sql-injection",
        "import flask\n"
        "def view():\n"
        "    name = flask.request.args['name']\n"
        "    cursor.execute('SELECT * FROM users WHERE name = ' + name)\n",
    ),
    "smoke.js": (
        "javascript-command-injection",
        "const cp = require('child_process');\n"
        "app.get('/x', (req, res) => {\n"
        "  cp.exec('ping ' + req.query.host);\n"
        "});\n",
    ),
    "smoke.ts": (
        "typescript-smoke",
        "const cp = require('child_process');\n"
        "app.get('/x', (req: any, res: any) => {\n"
        "  cp.exec('ping ' + req.query.host);\n"
        "});\n",
    ),
    "smoke.go": (
        "go-ssrf",
        "package main\n"
        'import "net/http"\n'
        "func handler(w http.ResponseWriter, r *http.Request) {\n"
        '\thttp.Get(r.FormValue("u"))\n'
        "}\n",
    ),
    "Smoke.java": (
        "java-sql-injection",
        "public class Smoke {\n"
        "  void run(javax.servlet.http.HttpServletRequest req, java.sql.Statement st)\n"
        "      throws Exception {\n"
        '    st.executeQuery("SELECT * FROM users WHERE name = " + req.getParameter("n"));\n'
        "  }\n"
        "}\n",
    ),
    "smoke.rb": (
        "ruby-command-injection",
        "def run\n  system('ping ' + params[:host])\nend\n",
    ),
    # a traversal rather than the shorter eval($_GET[...]): written on its own
    # into a temp directory that is a webshell by every signature there is, and
    # an endpoint scanner takes the file away between the write and the scan
    "smoke.php": (
        "php-path-traversal",
        "<?php\nfunction run() {\n    readfile('/srv/' . $_GET['p']);\n}\n",
    ),
    # imported and called short, the way the rules expect and the way C# is
    # written: semgrep does not resolve System.IO.File.ReadAllText against a
    # pattern naming File.ReadAllText
    "Smoke.cs": (
        "csharp-path-traversal",
        "using System.IO;\n"
        "public class Smoke {\n"
        "  public void Run(HttpRequest req) {\n"
        '    File.ReadAllText("/srv/" + req.Query["p"]);\n'
        "  }\n"
        "}\n",
    ),
}


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep is not installed")
class TestTheRulesMatchSomethingWhenSemgrepRunsThem:
    """a rule that parses is not a rule that matches. Semgrep drops a rule whose
    pattern fails to parse in any one of the languages it lists, reports no error
    for it, and scans on - so the repository comes back clean and the run looks
    like a result. Every other check in this file passes while that is happening."""

    @pytest.fixture(scope="class")
    def scan(self, tmp_path_factory):
        tree = tmp_path_factory.mktemp("smoke")
        for name, (_, source) in SMOKE_FIXTURES.items():
            (tree / name).write_text(source, encoding="utf-8")
        proc = subprocess.run(
            [
                "semgrep",
                "scan",
                "--config",
                str(PIPELINE_DIR / "rules"),
                "--json",
                "--no-git-ignore",
                "--quiet",
                "--metrics=off",
                "--disable-version-check",
                str(tree),
            ],
            capture_output=True,
            text=True,
            # semgrep writes progress characters the windows locale codec cannot
            # decode, and the default decoding drops the whole stream when it
            # hits one - which arrives here as a scan that produced nothing
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout.strip(), (
            f"semgrep exited {proc.returncode} with no results document: {proc.stderr[:400]}"
        )
        return json.loads(proc.stdout)

    def test_the_rules_directory_loads_without_error(self, scan):
        # semgrep reports a config it could not load in this array and still
        # exits zero with no results, which reads exactly like a clean repository
        assert scan.get("errors") == [], scan.get("errors")

    def test_every_language_the_rules_target_produces_a_finding(self, scan):
        # a whole language going quiet is the shape the silent-parse-failure
        # takes, and it is indistinguishable from a tree with nothing wrong in it
        by_file = {Path(r["path"]).name for r in scan["results"]}
        assert by_file == set(SMOKE_FIXTURES), (
            f"no rule matched in {sorted(set(SMOKE_FIXTURES) - by_file)}"
        )

    @pytest.mark.parametrize(
        "filename,expected",
        [(name, rule) for name, (rule, _) in SMOKE_FIXTURES.items() if rule != "typescript-smoke"],
    )
    def test_the_rule_that_should_match_is_the_one_that_does(self, scan, filename, expected):
        fired = {
            r["check_id"].rsplit(".", 1)[-1]
            for r in scan["results"]
            if Path(r["path"]).name == filename
        }
        assert expected in fired, f"{filename} produced {sorted(fired) or 'nothing'}"


class _Output:
    """the shape ProcessorEntry.history yields: a stage's recorded data."""

    def __init__(self, data: dict):
        self.data = data
        self.artifacts: dict[str, str] = {}
