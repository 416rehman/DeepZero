"""turn a run's scattered output into something a human can triage.

This is pipeline-agnostic on purpose. The engine's contract is already generic -
every stage records `data` (an arbitrary namespaced dict), `artifacts` (label ->
relative path) and a status - so the report is built from whatever the pipeline
actually produced rather than from any domain's field names. A kernel-driver
pipeline, a source-code bug hunt over GitHub repositories and anything else all
render without changing this module.

What a pipeline can optionally declare in its yaml to shape the output:

    report:
      title: GitHub source bug hunt
      entity: repository          # what one sample is called in the ui
      classification_key: verdict # stage data key holding the conclusion
      vulnerable_when: [vulnerable, exploitable]
      safe_when: [safe, clean]
      columns: [scan.finding_count, discover.stars]
      findings_files: [findings.json, sast.json]

Everything has a default, so a pipeline that declares nothing still gets a
useful report.

Output is layered, because rendering every sample into one html file does not
survive a corpus of 100k artifacts:

    index.html          verdict-first summary, bounded size
    items/<id>.html     one page per sample worth reading, links to artifacts
    inventory.csv       every sample, one row - opens in a spreadsheet
    findings.jsonl      every finding, one json object per line
    report.json         summary totals only

Nothing is dropped silently: when a listing is capped the page says so and
points at the csv holding the rest.
"""

from __future__ import annotations

import csv
import html
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from deepzero.engine import liveness
from deepzero.engine.state import StateStore

log = logging.getLogger("deepzero.report")

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "ERROR": 1, "MEDIUM": 2, "WARNING": 2, "LOW": 3}

BUCKET_VULNERABLE = "vulnerable"
BUCKET_SUSPICIOUS = "suspicious"
BUCKET_CLEAN = "clean"
BUCKET_FILTERED = "filtered"
BUCKET_FAILED = "failed"
BUCKET_UNASSESSED = "unassessed"

_BUCKET_LABELS = {
    BUCKET_VULNERABLE: "Vulnerable",
    BUCKET_SUSPICIOUS: "Needs assessment",
    BUCKET_FAILED: "Errored",
    # these were assessed - what is missing is a verdict the pipeline recognises
    BUCKET_UNASSESSED: "Unclear verdict",
    BUCKET_FILTERED: "Filtered out",
    BUCKET_CLEAN: "Clear",
}
_BUCKET_HELP = {
    BUCKET_VULNERABLE: "an assessment stage concluded these are vulnerable",
    BUCKET_SUSPICIOUS: "findings exist but no assessment confirmed them",
    BUCKET_FAILED: "a stage errored, so these were never fully analysed",
    BUCKET_UNASSESSED: "assessed but the verdict could not be classified",
    BUCKET_FILTERED: "a stage excluded these, so the later stages never saw them",
    BUCKET_CLEAN: "analysed all the way through and nothing was flagged",
}

# how each outcome is decided, shown when the label is hovered
_BUCKET_RULE = {
    BUCKET_VULNERABLE: (
        "An assessment stage recorded a verdict matching one of this pipeline's "
        "vulnerable_when values. Work through these first."
    ),
    BUCKET_SUSPICIOUS: (
        "A scan produced findings, but no assessment stage has confirmed or "
        "dismissed them yet. Either assessment has not reached these, or the "
        "pipeline has no assessment stage."
    ),
    BUCKET_FAILED: (
        "A stage recorded an error for these, so they never finished the "
        "pipeline. Their result says nothing about whether they are safe."
    ),
    BUCKET_UNASSESSED: (
        "An assessment ran and produced text, but its verdict did not match "
        "either the vulnerable_when or safe_when values this pipeline declares."
    ),
    BUCKET_FILTERED: (
        "A stage excluded these before the analysis finished, so the later "
        "stages never saw them. This is not a judgement about the item."
    ),
    BUCKET_CLEAN: (
        "These went through every stage, produced no findings, and were not "
        "flagged by an assessment."
    ),
}

# keys worth promoting into the summary table when a pipeline declares no columns
_INTERESTING_HINTS = ("count", "score", "severity", "total", "hits", "size", "stars", "rank")

# What a pipeline concludes and what a person has checked are different claims.
# A stage records the first; only the reader can record the second, so the report
# carries marks they make while reading it. Deliberately generic: whether the
# outstanding work is reproducing a crash, proving a precondition or reading a
# diff is the pipeline's business, and this only needs somewhere to put it.
MARK_CONFIRMED = "confirmed"
MARK_OUTSTANDING = "outstanding"
_MARK_LABELS = {MARK_CONFIRMED: "Confirmed", MARK_OUTSTANDING: "Outstanding"}
_MARKS_FILE = "marks.json"


def _load_marks(out_dir: Path) -> dict[str, dict[str, str]]:
    """review marks saved back into the report directory, if there are any.

    The report is a file, so marking happens in the browser and lives there.
    Saving the export next to the report makes the marks durable: they then
    render for anyone who opens it and appear in the csv alongside everything
    else, rather than being stranded in one person's browser.
    """
    raw = _read_json(out_dir / _MARKS_FILE)
    if not isinstance(raw, dict):
        return {}
    marks: dict[str, dict[str, str]] = {}
    for sample_id, mark in raw.items():
        if not isinstance(mark, dict):
            continue
        state = str(mark.get("state", ""))
        if state in _MARK_LABELS:
            marks[str(sample_id)] = {"state": state, "note": str(mark.get("note", ""))[:300]}
    return marks


@dataclass
class ReportConfig:
    """optional per-pipeline presentation, all defaulted."""

    title: str = ""
    entity: str = "sample"
    classification_key: str = "classification"
    vulnerable_when: tuple[str, ...] = ("vulnerab", "exploitab", "confirmed")
    safe_when: tuple[str, ...] = ("safe", "not vulnerab", "benign", "clean")
    columns: tuple[str, ...] = ()
    findings_files: tuple[str, ...] = ("findings.json",)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ReportConfig:
        raw = raw or {}

        def tup(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
            val = raw.get(key)
            if val is None:
                return default
            if isinstance(val, str):
                return (val,)
            return tuple(str(v) for v in val)

        return cls(
            title=str(raw.get("title", "") or ""),
            entity=str(raw.get("entity", "sample") or "sample"),
            classification_key=str(raw.get("classification_key", "classification")),
            vulnerable_when=tuple(s.lower() for s in tup("vulnerable_when", cls.vulnerable_when)),
            safe_when=tuple(s.lower() for s in tup("safe_when", cls.safe_when)),
            columns=tup("columns", ()),
            findings_files=tup("findings_files", cls.findings_files),
        )


@dataclass
class ItemReport:
    """one sample, described only in terms the engine guarantees."""

    sample_id: str
    name: str = ""
    source_path: str = ""
    sha256: str = ""
    status: str = ""
    classification: str = ""
    data: dict[str, Any] = field(default_factory=dict)  # "stage.key" -> value
    stages: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    skips: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)  # label -> relative path
    texts: dict[str, str] = field(default_factory=dict)  # label -> inline text
    findings: list[dict[str, Any]] = field(default_factory=list)
    severity_counts: dict[str, int] = field(default_factory=dict)
    rule_hits: dict[str, int] = field(default_factory=dict)
    sample_dir: str = ""
    filtered_at: str = ""
    _bucket: str = ""

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def risk(self) -> int:
        sev = self.severity_counts
        bonus = 1_000_000 if self._bucket == BUCKET_VULNERABLE else 0
        return (
            bonus
            + sev.get("CRITICAL", 0) * 100_000
            + (sev.get("HIGH", 0) + sev.get("ERROR", 0)) * 10_000
            + (sev.get("MEDIUM", 0) + sev.get("WARNING", 0)) * 100
            + sev.get("LOW", 0) * 10
            + self.finding_count
        )

    @property
    def interesting(self) -> bool:
        return bool(self.findings or self.texts or self.errors or self.classification)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _normalize_finding(raw: Any) -> dict[str, Any] | None:
    """accept whatever shape a processor emits and pull out the common fields."""
    if not isinstance(raw, dict):
        return None
    sev = str(raw.get("severity") or raw.get("level") or raw.get("impact") or "MEDIUM").upper()
    rule = str(raw.get("rule_id") or raw.get("rule") or raw.get("check_id") or raw.get("id") or "")
    return {
        "severity": sev,
        "rule_id": rule,
        "message": str(raw.get("message") or raw.get("title") or raw.get("description") or ""),
        "location": str(
            raw.get("file") or raw.get("path") or raw.get("location") or raw.get("url") or ""
        ),
        "line": raw.get("line_start") or raw.get("line") or raw.get("start_line") or "",
        "code": str(raw.get("matched_code") or raw.get("snippet") or raw.get("code") or ""),
    }


_FINDING_FIELDS = frozenset(
    {
        "severity",
        "level",
        "impact",
        "message",
        "title",
        "description",
        "rule_id",
        "rule",
        "check_id",
    }
)


def _looks_like_findings(rows: list[Any]) -> bool:
    """a findings list is records carrying a severity or a description."""
    for raw in rows[:5]:
        if isinstance(raw, dict) and _FINDING_FIELDS & set(raw):
            return True
    return False


def _classify(value: str, cfg: ReportConfig) -> str:
    v = (value or "").lower()
    if not v:
        return ""
    if any(k in v for k in cfg.vulnerable_when):
        return BUCKET_VULNERABLE
    if any(k in v for k in cfg.safe_when):
        return BUCKET_CLEAN
    return ""


def iter_items(work_dir: Path, cfg: ReportConfig) -> Iterator[ItemReport]:
    store = StateStore(work_dir)
    for state in store.list_samples():
        sample_dir = store.sample_dir(state.sample_id)
        item = ItemReport(
            sample_id=state.sample_id,
            name=state.filename or state.sample_id,
            source_path=state.source_path,
            sha256=state.sha256,
            status=str(getattr(state.verdict, "value", state.verdict)),
            sample_dir=str(sample_dir),
        )

        for stage_name, output in (state.history or {}).items():
            status = str(getattr(output.status, "value", output.status))
            verdict = str(getattr(output.verdict, "value", output.verdict or ""))
            item.stages[stage_name] = status
            # a filter records a completed stage with a filter verdict, so this
            # is where the sample left the pipeline
            if not item.filtered_at and (status == "filtered" or verdict == "filter"):
                item.filtered_at = stage_name
            # a skip reason is not a failure; older runs stored it in `error`
            if getattr(output, "skip_reason", ""):
                item.skips[stage_name] = output.skip_reason
            if output.error:
                if status == "failed":
                    item.errors[stage_name] = output.error
                else:
                    item.skips.setdefault(stage_name, output.error)

            for key, val in (getattr(output, "data", None) or {}).items():
                if key.startswith("__"):
                    continue
                item.data[f"{stage_name}.{key}"] = val
                if key == cfg.classification_key and val:
                    item.classification = str(val)

            for label, rel in (getattr(output, "artifacts", None) or {}).items():
                item.artifacts[label] = rel

        # findings come from the declared filenames plus any json artifact whose
        # contents look like a findings list, so a pipeline that names its output
        # something else still gets picked up without extra configuration
        candidates: list[Path] = [sample_dir / name for name in cfg.findings_files]
        for rel in item.artifacts.values():
            if str(rel).lower().endswith(".json"):
                candidates.append(sample_dir / rel)
        seen: set[Path] = set()
        for cand in candidates:
            if cand in seen or not cand.exists():
                continue
            seen.add(cand)
            payload = _read_json(cand)
            rows = payload if isinstance(payload, list) else (payload or {}).get("results")
            if not isinstance(rows, list) or not _looks_like_findings(rows):
                continue
            for raw in rows:
                f = _normalize_finding(raw)
                if not f:
                    continue
                item.findings.append(f)
                item.severity_counts[f["severity"]] = item.severity_counts.get(f["severity"], 0) + 1
                short = f["rule_id"].split(".")[-1]
                if short:
                    item.rule_hits[short] = item.rule_hits.get(short, 0) + 1

        # inline any small text artifact (assessments, reports, notes)
        for label, rel in item.artifacts.items():
            p = sample_dir / rel
            if p.suffix.lower() in (".md", ".txt", ".log") and p.exists():
                try:
                    item.texts[label] = p.read_text(encoding="utf-8", errors="replace")[:40000]
                except OSError:
                    pass

        bucket = _classify(item.classification, cfg)
        if not bucket:
            if item.errors:
                bucket = BUCKET_FAILED
            elif item.findings:
                bucket = BUCKET_SUSPICIOUS
            elif item.classification or item.texts:
                bucket = BUCKET_UNASSESSED
            elif item.filtered_at:
                # never reached the later stages, so it was not judged clean
                bucket = BUCKET_FILTERED
            else:
                bucket = BUCKET_CLEAN
        item._bucket = bucket

        yield item


def _auto_columns(items: list[ItemReport], all_keys: dict[str, int], limit: int = 6) -> list[str]:
    """pick informative numeric-ish data keys when the pipeline declares none."""
    scored: list[tuple[int, int, str]] = []
    for key, freq in all_keys.items():
        hint = any(h in key.lower() for h in _INTERESTING_HINTS)
        numeric = 0
        for it in items[:200]:
            v = it.data.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric += 1
        if not hint and not numeric:
            continue
        scored.append((-(2 if hint else 0) - (1 if numeric else 0), -freq, key))
    scored.sort()
    return [k for _, _, k in scored[:limit]]


def collect(
    work_dir: Path, *, config: ReportConfig | None = None, detail_limit: int = 2000
) -> dict[str, Any]:
    cfg = config or ReportConfig()
    interesting: list[ItemReport] = []
    rows: list[dict[str, Any]] = []
    totals = {
        "samples": 0,
        "with_findings": 0,
        "total_findings": 0,
        "assessed": 0,
        "errored": 0,
    }
    buckets: dict[str, int] = {}
    rule_totals: dict[str, int] = {}
    severity_totals: dict[str, int] = {}
    key_freq: dict[str, int] = {}

    for item in iter_items(work_dir, cfg):
        totals["samples"] += 1
        totals["total_findings"] += item.finding_count
        if item.findings:
            totals["with_findings"] += 1
        if item.classification or item.texts:
            totals["assessed"] += 1
        if item.errors:
            totals["errored"] += 1
        buckets[item.bucket] = buckets.get(item.bucket, 0) + 1
        for r, n in item.rule_hits.items():
            rule_totals[r] = rule_totals.get(r, 0) + n
        for s, n in item.severity_counts.items():
            severity_totals[s] = severity_totals.get(s, 0) + n
        for k in item.data:
            key_freq[k] = key_freq.get(k, 0) + 1

        rows.append(
            {
                "sample_id": item.sample_id,
                "name": item.name,
                "bucket": item.bucket,
                "classification": item.classification,
                "findings": item.finding_count,
                **{f"sev_{k.lower()}": v for k, v in item.severity_counts.items()},
                "rules": ";".join(sorted(item.rule_hits)),
                "stage_errors": ";".join(f"{k}:{v[:80]}" for k, v in item.errors.items()),
                "source_path": item.source_path,
                "sample_dir": item.sample_dir,
                "sha256": item.sha256,
                **{k: v for k, v in item.data.items() if not isinstance(v, (list, dict))},
            }
        )
        if item.interesting:
            interesting.append(item)

    interesting.sort(key=lambda x: (-x.risk, x.name.lower()))
    truncated = max(0, len(interesting) - detail_limit)
    kept = interesting[:detail_limit]

    columns = list(cfg.columns) or _auto_columns(kept, key_freq)

    store = StateStore(work_dir)
    run = store.load_run()
    recorded = str(getattr(getattr(run, "status", ""), "value", getattr(run, "status", "")))
    live = liveness.resolve(
        recorded,
        pid=int(getattr(run, "pid", 0) or 0),
        host=str(getattr(run, "host", "") or ""),
        token=str(getattr(run, "pid_token", "") or ""),
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "work_dir": str(work_dir),
        "config": cfg,
        "columns": columns,
        "run": {
            "run_id": getattr(run, "run_id", ""),
            "pipeline": getattr(run, "pipeline", ""),
            "target": getattr(run, "target", ""),
            "model": getattr(run, "model", ""),
            # what the pipeline last wrote down, and what checking its process
            # says about whether that is still true.
            "status": recorded,
            "state": live.state,
            "state_detail": live.detail,
            "pid": int(getattr(run, "pid", 0) or 0),
            "host": str(getattr(run, "host", "") or ""),
            "started_at": str(getattr(run, "started_at", "") or ""),
            "heartbeat_at": str(getattr(run, "heartbeat_at", "") or ""),
            "stages": list(getattr(run, "stages", []) or []),
        }
        if run
        else {},
        "totals": totals,
        "buckets": buckets,
        "severity_totals": dict(sorted(severity_totals.items(), key=lambda kv: -kv[1])),
        "rule_totals": dict(sorted(rule_totals.items(), key=lambda kv: -kv[1])),
        "detail_truncated": truncated,
        "items": kept,
        "rows": rows,
    }


def _esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def _short(key: str) -> str:
    return key.split(".", 1)[1] if "." in key else key


def _artifact_uri(sample_dir: str, rel: str, out_dir: Path) -> str:
    target = Path(sample_dir) / rel
    try:
        return _esc(os.path.relpath(target, out_dir).replace("\\", "/"))
    except ValueError:
        return _esc(target.resolve().as_uri())


_CSS = r"""
/* Cold paper, hairline rules, and wide-tracked monospace micro-labels set
   against a tight heavy headline. Colour is spent only on outcomes, so
   anything on this page carrying colour is saying something. */
:root{
  /* one spacing scale, each step ~1.6x the last, so a wide gap and a tight gap
     never look accidentally alike. The margin goes on the larger element. */
  --s1:4px; --s2:7px; --s3:11px; --s4:18px; --s5:29px; --s6:47px; --s7:76px;
  --bar:52px;  /* height of the sticky filter; the table head parks under it */
  /* Deep and muted in both modes. The dark set is a counterpart to the light
     one - same hues walked down in saturation - not a second palette. */
  --paper:#F5F7F8; --plate:#FFFFFF; --ink:#0D1114; --body:#39424B;
  --faint:#5C6570; --rule:#DDE2E6; --rule-hard:#A8B1B9;
  --positive:#9B1C31; --positive-wash:#9B1C310F;
  --review:#4B3A9E;  --review-wash:#4B3A9E0F;
  --warn:#8A5209; --ok:#1D6E54; --inert:#C3CAD2;
  --lift:0 10px 24px -18px rgba(13,17,20,.55);
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"Cascadia Mono","SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root{
    --paper:#0F1215; --plate:#171C21; --ink:#E7EBEE; --body:#A3ACB6;
    --faint:#7E8892; --rule:#222930; --rule-hard:#3B4550;
    --positive:#E8555F; --positive-wash:#E8555F16;
    --review:#8C7BE0;  --review-wash:#8C7BE016;
    --warn:#DFA05C; --ok:#45C98A; --inert:#39424E;
    --lift:0 10px 24px -18px rgba(0,0,0,.8);
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--paper);color:var(--body);
  font:400 13px/1.6 var(--sans);padding:0 var(--s5) var(--s7);
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
}
.shell{max-width:1180px;margin:0 auto}
a{color:inherit;text-decoration:none;border-bottom:1px solid var(--rule-hard)}
a:hover{border-bottom-color:currentColor}
:focus-visible{outline:2px solid var(--review);outline-offset:2px}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}

/* micro-label: the connective tissue of a form */
.lbl{font:500 9.5px/1 var(--mono);letter-spacing:.19em;text-transform:uppercase;color:var(--faint)}

/* requisition plate ------------------------------------------------------- */
.mast{padding:var(--s5) 0 0}
.kicker{display:flex;gap:var(--s3);align-items:baseline;flex-wrap:wrap}
.kicker .mark{font:700 10.5px/1 var(--mono);letter-spacing:.24em;color:var(--ink)}
.kicker .id{margin-left:auto;font:400 10.5px/1 var(--mono);color:var(--faint)}
h1{
  margin:var(--s4) 0 0;color:var(--ink);
  font:700 clamp(30px,4.6vw,52px)/0.98 var(--sans);letter-spacing:-.035em;
}
h1 .qty{color:var(--faint);font-weight:400;letter-spacing:-.02em}
.plate{
  margin:var(--s5) 0 0;border-top:1px solid var(--rule-hard);border-bottom:1px solid var(--rule);
  display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
}
.plate > div{padding:var(--s3) var(--s4) var(--s3) 0;border-right:1px solid var(--rule)}
.plate > div:last-child{border-right:0}
.plate dd{margin:var(--s2) 0 0;font:400 12.5px/1.45 var(--mono);color:var(--ink);word-break:break-word}
.plate .why{margin:var(--s1) 0 0;font:400 11.5px/1.5 var(--sans);color:var(--faint)}

/* the run state carries a dot because it is the one value on the plate that
   can change while somebody is looking at the page. */
.run{display:flex;align-items:center;gap:var(--s2)}
.run i{width:7px;height:7px;border-radius:50%;background:var(--inert);flex:none}
.run.running i{background:var(--ok);animation:beat 2s ease-in-out infinite}
.run.stopped i{background:var(--positive)}
.run.finished i{background:var(--rule-hard)}
.run .age{color:var(--faint);font-size:11.5px}
@keyframes beat{50%{opacity:.2}}

/* readout: the two outcomes worth acting on at full size, then the shape of
   the whole corpus, then the ones that only need acknowledging. */
.readout{margin:var(--s5) 0 0;padding-top:var(--s5);border-top:1px solid var(--rule)}
.ticks{display:flex;flex-wrap:wrap;gap:var(--s4) var(--s7)}
.tick{cursor:help}
.tick b{display:block;color:var(--ink);letter-spacing:-.04em;
  font:600 clamp(30px,3.6vw,38px)/1 var(--mono)}
.tick .lbl{display:block;margin-top:var(--s2)}
.tick.pos b{color:var(--positive)}
.tick.rev b{color:var(--review)}
.tick.zero b{color:var(--inert)}

/* the shape of the whole corpus in one line. It dims to whatever the outcome
   filter is showing, so it always reads as the view currently on screen. */
.spread{display:flex;gap:1px;height:7px;margin:var(--s5) 0 0;background:var(--rule)}
.spread i{display:block;background:var(--inert);min-width:3px;
  transition:opacity .15s,transform .15s}
.spread i.pos{background:var(--positive)}
.spread i.rev{background:var(--review)}
.spread i.err{background:var(--warn)}
.spread i.una{background:var(--rule-hard)}
.spread i.ok{background:var(--ok)}
.spread i:hover{transform:scaleY(1.7)}
.spread.narrowed i{opacity:.22}
.spread.narrowed i.on{opacity:1}
.rest{display:flex;flex-wrap:wrap;gap:var(--s2) var(--s5);margin:var(--s3) 0 0;
  font:400 11.5px/1.4 var(--mono);color:var(--faint)}
.rest span{display:flex;align-items:center;cursor:help}
.rest i{width:6px;height:6px;border-radius:50%;background:var(--inert);flex:none;
  margin-right:var(--s2)}
.rest .err i{background:var(--warn)}
.rest .una i{background:var(--rule-hard)}
.rest .ok i{background:var(--ok)}
.rest b{color:var(--body);font-weight:600;margin-right:.38em}

/* statements -------------------------------------------------------------- */
.finding-note{
  margin:var(--s5) 0 0;padding:var(--s3) var(--s4);background:var(--positive-wash);
  border-left:2px solid var(--positive);color:var(--ink);font-size:13px
}
.finding-note.rev{background:var(--review-wash);border-left-color:var(--review)}
.finding-note b{font-weight:600}
.aside{
  margin:var(--s4) 0 0;padding:var(--s3) 0 0;border-top:1px solid var(--rule);
  color:var(--faint);font-size:12px
}
.files{margin:var(--s5) 0 0;display:flex;gap:var(--s3);flex-wrap:wrap}
.files a{
  border:1px solid var(--rule-hard);padding:var(--s2) var(--s3);color:var(--body);
  font:400 11px/1 var(--mono);letter-spacing:.04em;transition:border-color .12s,color .12s
}
.files a:hover{border-color:var(--ink);color:var(--ink)}

/* filter ------------------------------------------------------------------ */
/* a corpus list is longer than a screen, so the way to narrow it travels. its
   measured height becomes --bar, which is where the table head parks. */
.filter{
  position:sticky;top:0;z-index:6;margin:var(--s5) 0 0;padding:var(--s3) 0;
  display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap;background:var(--paper);
  border-bottom:1px solid var(--rule);transition:box-shadow .15s
}
/* once it is actually pinned it should read as floating over the list */
.filter.stuck{box-shadow:var(--lift)}
.field{
  display:flex;align-items:center;gap:var(--s2);background:var(--plate);
  border:1px solid var(--rule-hard);padding:0 var(--s3);min-width:250px;
  transition:border-color .12s,box-shadow .12s
}
.field:focus-within{border-color:var(--review);box-shadow:0 0 0 3px var(--review-wash)}
.field .glyph{color:var(--faint);font:400 14px/1 var(--mono)}
input[type=search]{
  flex:1;background:transparent;color:var(--ink);border:0;outline:0;
  padding:var(--s3) 0;font:400 13px/1 var(--mono)
}
input[type=search]::placeholder{color:var(--faint)}
.hint{color:var(--faint);font-size:11.5px;margin-left:auto}

/* outcome toggles: narrowing to a single outcome is the move a triage pass
   makes over and over, so it travels with the search rather than sitting in
   the header where the list would scroll away from it */
.chipf{
  display:inline-flex;align-items:center;gap:var(--s2);background:transparent;
  border:1px solid var(--rule);color:var(--faint);padding:var(--s2) var(--s3);
  font:500 9.5px/1 var(--mono);letter-spacing:.13em;text-transform:uppercase;
  cursor:pointer;transition:border-color .12s,color .12s,background .12s
}
.chipf b{font:600 11px/1 var(--mono);letter-spacing:0}
.chipf:hover{border-color:var(--rule-hard);color:var(--body)}
.chipf[aria-pressed="true"]{border-color:currentColor;color:var(--ink)}
.chipf.pos[aria-pressed="true"]{color:var(--positive);background:var(--positive-wash)}
.chipf.rev[aria-pressed="true"]{color:var(--review);background:var(--review-wash)}

/* sections ---------------------------------------------------------------- */
section{margin-top:var(--s6)}
.shead{display:flex;align-items:baseline;gap:var(--s4);
  padding-bottom:var(--s3);border-bottom:1px solid var(--rule-hard)}
.shead h2{margin:0;color:var(--ink);font:600 13px/1 var(--mono);letter-spacing:.16em;text-transform:uppercase}
.shead .n{font:600 13px/1 var(--mono);color:var(--positive)}
.shead.q h2{color:var(--body)}
.shead.q .n{color:var(--faint)}
.shead .of{margin-left:auto;color:var(--faint);font-size:11.5px;text-align:right;max-width:44ch}
.shead[title]{cursor:help}

/* result table ------------------------------------------------------------ */
/* no scroll container at desktop width: an overflow ancestor becomes the
   scrollport, which is what stops a sticky table head from ever sticking. */
.scroll{overflow:visible}
table{width:100%;border-collapse:collapse}
thead th{
  position:sticky;top:var(--bar);z-index:2;background:var(--paper);
  font:500 9.5px/1 var(--mono);letter-spacing:.17em;text-transform:uppercase;color:var(--faint);
  text-align:left;padding:var(--s4) var(--s3) var(--s3) 0;white-space:nowrap;
  border-bottom:1px solid var(--rule);cursor:pointer;user-select:none
}
thead th::after{content:"\2195";margin-left:var(--s2);opacity:.35;font-size:10px;letter-spacing:0}
thead th:hover{color:var(--ink)}
thead th:hover::after{opacity:1}
thead th[data-dir]{color:var(--ink)}
thead th[data-dir="asc"]::after{content:"\2191";opacity:1}
thead th[data-dir="desc"]::after{content:"\2193";opacity:1}
thead th.r{text-align:right}
tbody tr{cursor:pointer}
tbody td{padding:var(--s3) var(--s3) var(--s3) 0;border-bottom:1px solid var(--rule);
  vertical-align:baseline}
/* hovering tints the row in its own outcome colour, so the palette is teaching
   what the colours mean every time somebody runs down the list */
tbody tr:hover td,tbody tr:focus-within td{background:var(--plate)}
tbody tr.pos:hover td,tbody tr.pos:focus-within td{background:var(--positive-wash)}
tbody tr.rev:hover td,tbody tr.rev:focus-within td{background:var(--review-wash)}
tbody tr:hover td.spec a{border-bottom-color:var(--ink)}
td.r{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--ink)}
td.spec{word-break:break-word}
td.spec a{font:500 13.5px/1.35 var(--sans);color:var(--ink);letter-spacing:-.01em;
  border-bottom:1px solid var(--rule-hard)}
td.spec a:hover{border-bottom-color:var(--ink)}
td.muted{color:var(--faint)}
.res{font:600 9.5px/1 var(--mono);letter-spacing:.15em;text-transform:uppercase}
.res.pos{color:var(--positive)}
.res.rev{color:var(--review)}
.res.non{color:var(--faint)}
td.out{width:1%;white-space:nowrap}
td.out .res{cursor:help}

/* severity: the counts themselves, coloured by tier. Counts rather than a
   proportional bar, because a bar shows the mix within a row and says nothing
   about how much there is - one high and nine high would fill it alike. */
td.sev{text-align:right;white-space:nowrap;color:var(--faint);
  font:400 11.5px/1.5 var(--mono);font-variant-numeric:tabular-nums}
td.sev span{margin-left:var(--s2)}
td.sev .c{color:var(--positive);font-weight:700}
td.sev .h{color:var(--positive)}
td.sev .m{color:var(--warn)}

/* review marks ------------------------------------------------------------ */
/* what a stage concluded and what a person has checked are different claims,
   so a mark never reuses an outcome colour: green is checked by a human. */
td.rev{width:1%;white-space:nowrap;text-align:right}
.mark{font:600 9.5px/1 var(--mono);letter-spacing:.13em;text-transform:uppercase;
  color:var(--faint);white-space:nowrap}
.mark.confirmed{color:var(--ok)}
.mark.outstanding{color:var(--warn)}
.mark .note{display:block;margin-top:var(--s1);font:400 11px/1.4 var(--mono);
  letter-spacing:0;text-transform:none;color:var(--faint);max-width:34ch;
  white-space:normal;text-align:right}

/* the control on a result's own page, where the reader decides */
.review{margin:var(--s5) 0 0;padding:var(--s4) 0 0;border-top:1px solid var(--rule)}
.review .lbl{display:block;margin-bottom:var(--s3)}
.review .opts{display:flex;gap:var(--s2);flex-wrap:wrap}
.review button{
  background:transparent;border:1px solid var(--rule);color:var(--faint);
  padding:var(--s2) var(--s3);font:500 9.5px/1 var(--mono);letter-spacing:.13em;
  text-transform:uppercase;cursor:pointer;transition:border-color .12s,color .12s
}
.review button:hover{border-color:var(--rule-hard);color:var(--body)}
.review button[aria-pressed="true"]{border-color:currentColor;color:var(--ink)}
.review button.confirmed[aria-pressed="true"]{color:var(--ok)}
.review button.outstanding[aria-pressed="true"]{color:var(--warn)}
.review textarea{
  display:none;width:100%;margin-top:var(--s3);background:var(--plate);
  border:1px solid var(--rule-hard);color:var(--ink);padding:var(--s3);
  font:400 12.5px/1.5 var(--mono);resize:vertical;min-height:62px
}
.review textarea:focus{outline:0;border-color:var(--review);box-shadow:0 0 0 3px var(--review-wash)}
.review.outstanding textarea{display:block}
.review .saved{margin:var(--s3) 0 0;font:400 11.5px/1 var(--mono);color:var(--faint)}

/* specimen fingerprint ---------------------------------------------------- */
.strip{display:flex;gap:var(--s3);flex-wrap:wrap;margin-top:var(--s2)}
.chip{font:400 11px/1.4 var(--mono);color:var(--body);white-space:nowrap}
.chip em{color:var(--faint);font-style:normal;margin-right:var(--s1);letter-spacing:.06em}
.chip.on{color:var(--positive)}

/* specimen page ----------------------------------------------------------- */
.back{display:inline-block;margin:var(--s6) 0 0;font:400 11px/1 var(--mono);letter-spacing:.1em;
  text-transform:uppercase;color:var(--faint);border:0}
.back:hover{color:var(--ink)}
.verdict{display:block;margin-top:var(--s4)}
.verdict .res{font-size:11px;letter-spacing:.2em}
.verdict .tally{margin-left:var(--s3);font:400 11.5px/1 var(--mono);color:var(--faint)}
.verdict hr{margin:var(--s2) 0 0;border:0;border-top:2px solid var(--positive);width:44px}
.verdict.rev hr{border-top-color:var(--review)}
.verdict.non hr{border-top-color:var(--rule-hard)}
.evidence{list-style:none;padding:0;margin:0}
.evidence li{padding:var(--s5) 0;border-bottom:1px solid var(--rule)}
.ehead{display:flex;gap:var(--s3);align-items:baseline;flex-wrap:wrap}
.ehead .sev{font:600 9.5px/1 var(--mono);letter-spacing:.15em;text-transform:uppercase;color:var(--faint)}
.ehead .sev.c,.ehead .sev.h{color:var(--positive)}
.ehead .sev.m{color:var(--warn)}
.ehead .rule{font:500 12.5px/1 var(--mono);color:var(--ink)}
.ehead .at{margin-left:auto;font:400 11px/1 var(--mono);color:var(--faint)}
.emsg{margin:var(--s2) 0 0;color:var(--body);font-size:13px;max-width:76ch}
pre{
  margin:var(--s3) 0 0;padding:var(--s4);background:var(--plate);
  border:1px solid var(--rule);border-left:2px solid var(--rule-hard);
  overflow-x:auto;font:400 12px/1.7 var(--mono);color:var(--ink);
  white-space:pre-wrap;word-break:break-word
}
.evidence li.c pre,.evidence li.h pre{border-left-color:var(--positive)}
.evidence li.m pre{border-left-color:var(--warn)}
.prose pre{border-left-color:var(--review)}
.kv{width:100%;border-collapse:collapse;margin-top:var(--s1)}
.kv td{padding:var(--s3) var(--s4) var(--s3) 0;border-bottom:1px solid var(--rule);
  font:400 12px/1.5 var(--mono);vertical-align:baseline;color:var(--ink)}
.kv td:first-child{color:var(--faint);white-space:nowrap;width:1%;letter-spacing:.04em}
.empty{color:var(--faint);font-size:12.5px;padding:var(--s5) 0}
@media (max-width:640px){
  body{padding:0 var(--s4) var(--s6)}
  .mast{padding-top:var(--s5)}
  .kicker .id{margin-left:0}
  .plate > div{border-right:0;border-bottom:1px solid var(--rule)}
  .ticks{gap:var(--s4) var(--s6)}
  /* the help text is what makes a label readable, so it stacks under the
     heading rather than disappearing where hover does not exist */
  .shead{flex-wrap:wrap}
  .shead .of{margin-left:0;text-align:left;flex-basis:100%;max-width:none}
  .filter{position:static}
  .hint{margin-left:0}
  thead th{top:0}
}
@media (max-width:900px){
  /* narrow enough that the table cannot fit: it scrolls in its own box, and
     the head stops sticking because that box is now the scrollport */
  .scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
  thead th{position:static}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

_JS = """
(function(){
  /* filter: hide rows that do not match, and say how many are showing */
  var q=document.getElementById('q'),hint=document.getElementById('hint');
  function report(){
    var shown=0,total=0;
    document.querySelectorAll('tbody tr').forEach(function(r){
      if(!r.dataset.k)return; total++; if(r.style.display!=='none')shown++;
    });
    if(hint)hint.textContent=shown===total?total+' shown':shown+' of '+total+' shown';
  }

  /* text and outcome narrow the same list: no chip pressed means show all */
  var chips=[].slice.call(document.querySelectorAll('.chipf'));
  var spread=document.querySelector('.spread');
  function apply(){
    var v=q?q.value.toLowerCase():'';
    var pressed=chips.filter(function(c){return c.getAttribute('aria-pressed')==='true'});
    var on=pressed.filter(function(c){return c.dataset.b}).map(function(c){return c.dataset.b});
    var wantMark=pressed.filter(function(c){return c.dataset.mark})
                        .map(function(c){return c.dataset.mark});
    document.querySelectorAll('tbody tr').forEach(function(r){
      if(!r.dataset.k)return;
      var hit=r.dataset.k.indexOf(v)>-1
        &&(!on.length||on.indexOf(r.dataset.b)>-1)
        &&(!wantMark.length||wantMark.indexOf(r.dataset.mark||'unmarked')>-1);
      r.style.display=hit?'':'none';
    });
    /* the corpus bar shows which slice of the run is on screen right now */
    if(spread){
      spread.classList.toggle('narrowed',on.length>0);
      [].forEach.call(spread.children,function(seg){
        seg.classList.toggle('on',on.indexOf(seg.dataset.b)>-1);
      });
    }
    report();
  }
  if(q)q.addEventListener('input',apply);
  chips.forEach(function(c){
    c.addEventListener('click',function(){
      c.setAttribute('aria-pressed',c.getAttribute('aria-pressed')==='true'?'false':'true');
      apply();
    });
  });
  report();

  /* the head parks under the filter, so it has to know how tall that is */
  var barEl=document.querySelector('.filter');
  function fit(){
    document.documentElement.style.setProperty('--bar',barEl.offsetHeight+'px');
  }
  function stick(){barEl.classList.toggle('stuck',barEl.getBoundingClientRect().top<=0)}
  if(barEl){
    fit();stick();
    window.addEventListener('resize',fit);
    window.addEventListener('scroll',stick,{passive:true});
  }

  /* a live run rewrites this file every few seconds. reload to pick that up,
     but put the reader back where they were rather than at the top, and stop
     once the page has gone long enough without being rewritten to be stale. */
  var live=document.body.dataset.live,store=null,key='dz:'+location.pathname;
  try{store=window.sessionStorage}catch(e){}
  if(live&&store){
    try{
      var was=JSON.parse(store.getItem(key)||'{}');
      if(was.q&&q){q.value=was.q;apply()}
      if(was.y)window.scrollTo(0,was.y);
    }catch(e){}
    window.addEventListener('beforeunload',function(){
      try{store.setItem(key,JSON.stringify({q:q?q.value:'',y:window.scrollY}))}catch(e){}
    });
    var beat=document.querySelector('.run[data-beat]');
    var age=beat?(Date.now()-Date.parse(beat.getAttribute('data-beat')))/1000:0;
    if(!(age>300))setTimeout(function(){location.reload()},20000);
  }

  /* review marks: what the reader has checked, which no stage can know.
     Held in the browser because the report is a file, and exportable so they
     can be saved next to it and stop being one person's private notes. */
  var MK = 'dz:marks:' + (document.body.dataset.corpus || location.pathname);
  function loadMarks(){
    var baked = {};
    try{ baked = JSON.parse(document.getElementById('baked-marks').textContent) }catch(e){}
    try{
      var mine = JSON.parse(window.localStorage.getItem(MK) || '{}');
      for(var k in mine){ baked[k] = mine[k] }
    }catch(e){}
    return baked;
  }
  function saveMark(sid, mark){
    try{
      var all = JSON.parse(window.localStorage.getItem(MK) || '{}');
      if(mark){ all[sid] = mark } else { delete all[sid] }
      window.localStorage.setItem(MK, JSON.stringify(all));
    }catch(e){}
  }

  var marks = loadMarks();

  /* index: show each mark against its row, and let the list be narrowed to
     whatever still needs looking at */
  document.querySelectorAll('tr[data-sid]').forEach(function(row){
    var m = marks[row.dataset.sid];
    row.dataset.mark = m ? m.state : 'unmarked';
    var cell = row.querySelector('.rev');
    if(!cell || !m) return;
    var note = m.note ? "<span class='note'>" + m.note.replace(/[<&]/g, function(c){
      return c === '<' ? '&lt;' : '&amp;';
    }) + "</span>" : '';
    cell.innerHTML = "<span class='mark " + m.state + "'>" + m.state + note + "</span>";
  });
  // painted before any filter runs, so narrowing by mark sees them
  apply();

  /* the control on a result's own page */
  var panel = document.querySelector('.review[data-sid]');
  if(panel){
    var sid = panel.dataset.sid;
    var box = panel.querySelector('textarea');
    var saved = panel.querySelector('.saved');
    var current = marks[sid] || null;
    function paint(){
      panel.classList.toggle('outstanding', !!current && current.state === 'outstanding');
      panel.querySelectorAll('button').forEach(function(b){
        b.setAttribute('aria-pressed', String(!!current && current.state === b.dataset.state));
      });
      if(box && current) box.value = current.note || '';
      saved.textContent = current
        ? 'marked ' + current.state + (current.note ? ', with a note' : '')
        : 'not reviewed yet';
    }
    panel.querySelectorAll('button').forEach(function(b){
      b.addEventListener('click', function(){
        var want = b.dataset.state;
        current = (current && current.state === want)
          ? null
          : {state: want, note: (box && box.value) || ''};
        saveMark(sid, current); paint();
      });
    });
    if(box) box.addEventListener('input', function(){
      if(!current) return;
      current.note = box.value; saveMark(sid, current); paint();
    });
    paint();
  }

  /* marks are only durable once they leave the browser */
  var dump = document.getElementById('export-marks');
  if(dump) dump.addEventListener('click', function(e){
    e.preventDefault();
    var blob = new Blob([JSON.stringify(loadMarks(), null, 2)], {type:'application/json'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'marks.json';
    a.click();
    URL.revokeObjectURL(a.href);
  });

  /* a row opens its own page; the link inside keeps it keyboard reachable */
  document.querySelectorAll('tbody').forEach(function(body){
    body.addEventListener('click',function(e){
      if(e.target.closest('a'))return;
      if(window.getSelection&&String(window.getSelection())) return;
      var row=e.target.closest('tr'),link=row&&row.querySelector('a[href]');
      if(link)window.location.href=link.getAttribute('href');
    });
  });

  /* sortable columns, with the active column and direction shown */
  document.querySelectorAll('table[data-sortable]').forEach(function(tb){
    var head=tb.tHead.rows[0];
    [].forEach.call(head.cells,function(th,i){
      th.tabIndex=0;
      th.setAttribute('title','Sort by '+th.textContent.trim());
      th.setAttribute('aria-sort','none');
      function sort(){
        var body=tb.tBodies[0],rows=[].slice.call(body.rows);
        var desc=th.dataset.dir!=='desc';
        [].forEach.call(head.cells,function(c){
          if(c!==th){delete c.dataset.dir;c.setAttribute('aria-sort','none')}
        });
        th.dataset.dir=desc?'desc':'asc';
        th.setAttribute('aria-sort',desc?'descending':'ascending');
        rows.sort(function(a,b){
          var x=(a.cells[i].dataset.v||a.cells[i].innerText).trim();
          var y=(b.cells[i].dataset.v||b.cells[i].innerText).trim();
          var nx=parseFloat(x),ny=parseFloat(y),r;
          r=(!isNaN(nx)&&!isNaN(ny)&&x!==''&&y!=='')?nx-ny:x.localeCompare(y);
          return desc?-r:r;
        });
        rows.forEach(function(r){body.appendChild(r)});
      }
      th.addEventListener('click',sort);
      th.addEventListener('keydown',function(e){
        if(e.key==='Enter'||e.key===' '){e.preventDefault();sort()}
      });
    });
  });
})();
"""


def _page(
    title: str,
    body: str,
    *,
    live: bool = False,
    corpus: str = "",
    marks: dict[str, dict[str, str]] | None = None,
) -> str:
    # a live page reloads itself from script rather than a meta refresh, so it
    # can put the reader back where they were instead of at the top
    attrs = ' data-live="1"' if live else ""
    # marks are keyed on the corpus rather than the page, so they survive a run
    # rewriting the report and are still there when it is regenerated
    if corpus:
        attrs += f' data-corpus="{_esc(corpus)}"'
    # script content is raw text: the parser does not decode entities there, so
    # html-escaping this would hand the page a document json cannot read. Only
    # "<" needs neutralising, which is what stops a note closing the tag early.
    baked = json.dumps(marks or {}).replace("<", "\\u003c")
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head>"
        f'<body{attrs}><div class="shell">{body}</div>'
        f'<script type="application/json" id="baked-marks">{baked}</script>'
        f"<script>{_JS}{_LIVENESS_JS}</script></body></html>"
    )


# already shown in their own column, so repeating them in the strip is noise
_STRIP_SUPPRESS = frozenset({"finding_count", "classification", "verdict"})


def _strip(item: ItemReport, columns: list[str], limit: int = 3) -> str:
    """a terse fingerprint of the item: the few values that tell you what it is."""
    chips: list[str] = []
    for key in columns:
        if _short(key) in _STRIP_SUPPRESS:
            continue
        val = item.data.get(key)
        if val in (None, "", [], {}, 0, 0.0):
            continue
        if isinstance(val, list):
            shown = ", ".join(str(v) for v in val[:3])
            if len(val) > 3:
                shown += f" +{len(val) - 3}"
        else:
            shown = str(val)
        chips.append(f"<span class='chip'><em>{_esc(_short(key))}</em> {_esc(shown)}</span>")
        if len(chips) >= limit:
            break
    for rule in sorted(item.rule_hits)[:2]:
        chips.append(f"<span class='chip on'>{_esc(rule)}</span>")
    if len(item.rule_hits) > 2:
        chips.append(f"<span class='chip'>+{len(item.rule_hits) - 2}</span>")
    return f"<div class='strip'>{''.join(chips)}</div>" if chips else ""


_RES_CLASS = {
    BUCKET_VULNERABLE: "pos",
    BUCKET_SUSPICIOUS: "rev",
    BUCKET_FAILED: "non",
    BUCKET_UNASSESSED: "non",
    BUCKET_CLEAN: "non",
}

# the order a triage pass works in, and the only outcomes with rows to work on
_LIST_ORDER = {
    BUCKET_VULNERABLE: 0,
    BUCKET_SUSPICIOUS: 1,
    BUCKET_FAILED: 2,
    BUCKET_UNASSESSED: 3,
}

# a pipeline names its own severities, so they are folded onto the four tiers
# the risk score actually weighs. Critical stays separate from high: it is worth
# ten times as much in the ranking, so collapsing them would leave the severity
# column unable to explain the order it is sorted in.
_SEV_TIER = {"CRITICAL": "c", "HIGH": "h", "ERROR": "h", "MEDIUM": "m", "WARNING": "m"}
_TIER_LABEL = (("c", "crit"), ("h", "high"), ("m", "med"), ("l", "low"))
_DASH = "—"


def _tiers(counts: dict[str, int]) -> dict[str, int]:
    tally = {"c": 0, "h": 0, "m": 0, "l": 0}
    for sev, n in counts.items():
        tally[_SEV_TIER.get(sev, "l")] += n
    return tally


def _severity(item: ItemReport) -> str:
    """the severity mix as counts, most serious first."""
    tally = _tiers(item.severity_counts)
    parts = [
        f"<span class='{tier}'>{tally[tier]}</span>&thinsp;{label}"
        for tier, label in _TIER_LABEL
        if tally[tier]
    ]
    return " ".join(parts) or _DASH


def _review_panel(item: ItemReport, entity: str) -> str:
    """where the reader records what they have actually checked.

    The pipeline's verdict and a person's verification are separate claims, and
    only one of them can be made here. What counts as outstanding is left open
    on purpose: reproducing a crash, proving a precondition or reading a diff
    are all the same shape of unfinished work from the report's point of view.
    """
    return f"""<div class="review" data-sid="{_esc(item.sample_id)}">
  <span class="lbl">your review</span>
  <div class="opts">
    <button type="button" class="confirmed" data-state="confirmed" aria-pressed="false">
      confirmed</button>
    <button type="button" class="outstanding" data-state="outstanding" aria-pressed="false">
      something outstanding</button>
  </div>
  <textarea placeholder="what is still unproven about this {_esc(entity)}?"
    aria-label="what is still outstanding"></textarea>
  <p class="saved"></p>
</div>"""


def render_item_page(
    item: ItemReport,
    out_dir: Path,
    cfg: ReportConfig,
    pipeline: str = "",
    corpus: str = "",
    marks: dict[str, dict[str, str]] | None = None,
) -> str:
    res = _RES_CLASS.get(item.bucket, "non")
    evidence = []
    for f in sorted(item.findings, key=lambda x: _SEVERITY_ORDER.get(x["severity"], 9)):
        at = " ".join(x for x in (f["location"], f"line {f['line']}" if f["line"] else "") if x)
        code = f"<pre>{_esc(f['code'][:1400])}</pre>" if f["code"] else ""
        tier = _SEV_TIER.get(f["severity"], "l")
        evidence.append(
            f"<li class='{tier}'><div class='ehead'>"
            f"<span class='sev {tier}'>{_esc(f['severity'])}</span>"
            f"<span class='rule'>{_esc(f['rule_id'].split('.')[-1] or 'finding')}</span>"
            f"<span class='at'>{_esc(at)}</span></div>"
            f"<p class='emsg'>{_esc(f['message'])}</p>{code}</li>"
        )

    files = [f"<a href='{_artifact_uri(item.sample_dir, '.', out_dir)}'>artifact folder</a>"]
    for label, rel in sorted(item.artifacts.items()):
        files.append(f"<a href='{_artifact_uri(item.sample_dir, rel, out_dir)}'>{_esc(label)}</a>")

    facts = [("findings", str(item.finding_count)), (f"{cfg.entity} id", item.sample_id)]
    if item.sha256:
        facts.append(("sha256", item.sha256[:32] + "&hellip;"))
    if item.source_path:
        facts.append(("source", item.source_path))
    plate = "".join(
        f"<div><div class='lbl'>{_esc(k)}</div><dd>{v if k == 'sha256' else _esc(v)}</dd></div>"
        for k, v in facts
    )

    scalar = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_esc(v)[:400]}</td></tr>"
        for k, v in sorted(item.data.items())
        if not isinstance(v, (list, dict))
    )
    listy = "".join(
        "<tr><td>{k}</td><td>{v}</td></tr>".format(
            k=_esc(k), v=_esc(", ".join(map(str, v))[:900] if isinstance(v, list) else v)
        )
        for k, v in sorted(item.data.items())
        if isinstance(v, (list, dict))
    )

    narrative = "".join(
        f"<section><div class='shead'><h2>{_esc(label.replace('_', ' '))}</h2></div>"
        f"<div class='prose'><pre>{_esc(body)}</pre></div></section>"
        for label, body in sorted(item.texts.items())
    )
    problems = ""
    if item.errors:
        problems += (
            "<section><div class='shead q'><h2>Errors</h2></div>"
            f"<pre>{_esc(chr(10).join(f'{k}: {v}' for k, v in item.errors.items()))}</pre></section>"
        )
    if item.skips:
        problems += (
            "<section><div class='shead q'><h2>Skipped</h2></div>"
            f"<pre>{_esc(chr(10).join(f'{k}: {v}' for k, v in item.skips.items()))}</pre></section>"
        )

    stages = ", ".join(f"{k} {v}" for k, v in item.stages.items())
    # the verdict word alone does not say how much is behind it
    counts = _tiers(item.severity_counts)
    tally = (
        ", ".join(f"{counts[t]} {label}" for t, label in _TIER_LABEL if counts[t])
        or "nothing flagged"
    )
    body = f"""<a class="back" href="../index.html">&larr; all results</a>
<header class="mast" style="padding-top:26px">
  <div class="kicker"><span class="mark">{_esc(pipeline or "DEEPZERO")}</span>
    <span class="lbl">{_esc(cfg.entity)}</span></div>
  <h1>{_esc(item.name)}</h1>
  <div class="verdict {res}">
    <span class="res {res}">{_esc(_BUCKET_LABELS.get(item.bucket, item.bucket))}</span>
    <span class="tally">{_esc(tally)}</span>
    <hr>
  </div>
  <div class="files">{"".join(files)}</div>
  {_review_panel(item, cfg.entity)}
</header>
<dl class="plate">{plate}</dl>
<p class="aside">{_esc(stages)}</p>
{narrative}{problems}
<section>
  <div class="shead"><h2>Evidence</h2><span class="n">{item.finding_count}</span>
    <span class="of">every finding, with the code it matched</span></div>
  {"<ul class='evidence'>" + "".join(evidence) + "</ul>" if evidence else "<p class='empty'>No findings were recorded for this " + _esc(cfg.entity) + ".</p>"}
</section>
<section>
  <div class="shead q"><h2>Recorded data</h2><span class="of">every value the pipeline stored</span></div>
  {"<table class='kv'><tbody>" + scalar + listy + "</tbody></table>" if (scalar or listy) else "<p class='empty'>Nothing recorded.</p>"}
</section>"""
    return _page(f"{item.name} - DeepZero", body, corpus=corpus, marks=marks)


_STATE_WORDING = {
    "running": "running",
    "stopped": "stopped before finishing",
    "finished": "finished",
    "unknown": "unknown",
}

_STATE_WHY = {
    "stopped": "The process that was writing this run is gone and it never "
    "recorded an outcome, so the counts below are wherever it got to.",
    "unknown": "This run last recorded that it was in progress, but whether "
    "that is still true could not be established.",
}


def _run_state_cell(run: dict[str, Any], generated_at: str = "") -> str:
    """The status entry on the plate.

    This is the only value on the page that can stop being true while somebody
    is reading it, so it carries the time the page was written. A live run
    rewrites the page every few seconds; once that stops, the gap between the
    stamp and the reader's clock is what gives the run away.
    """
    state = str(run.get("state", "") or "unknown").lower()
    detail = str(run.get("state_detail", "") or "")
    if state == "finished" and detail:
        wording = detail  # finished, failed, interrupted - say which
    else:
        wording = _STATE_WORDING.get(state, state)

    attrs = f" data-beat='{_esc(generated_at)}'" if generated_at else ""
    why = _STATE_WHY.get(state, "")
    if state == "unknown" and detail:
        why = f"{why} {detail.capitalize()}."

    return (
        "<div><div class='lbl'>status</div>"
        f"<dd><span class='run {_esc(state)}'{attrs}>"
        f"<i></i><span>{_esc(wording)}</span>"
        "<span class='age'></span></span></dd>"
        + (f"<p class='why'>{_esc(why)}</p>" if why else "")
        + "</div>"
    )


# the page is a file. once written it learns nothing further, so if the run dies
# the browser keeps reloading a snapshot that still claims to be running. the
# reader's own clock is the only thing left that can tell them otherwise.
_LIVENESS_JS = """
(function(){
  var el=document.querySelector('.run[data-beat]');
  if(!el) return;
  var beat=Date.parse(el.getAttribute('data-beat'));
  if(isNaN(beat)) return;
  var live=el.classList.contains('running'), age=el.querySelector('.age');
  var label=el.querySelector('span');
  function ago(s){
    if(s<60) return Math.max(0,Math.round(s))+'s ago';
    if(s<3600) return Math.round(s/60)+' min ago';
    if(s<86400) return Math.round(s/3600)+' hr ago';
    return Math.round(s/86400)+' d ago';
  }
  function tick(){
    var s=(Date.now()-beat)/1000;
    if(!live){ age.textContent='written '+ago(s); return; }
    // a run rewrites this page every few seconds. a gap far wider than that
    // means the page is a leftover, whatever it says about itself.
    if(s>180){
      el.classList.remove('running'); el.classList.add('stopped');
      label.textContent='no longer updating';
      age.textContent='last written '+ago(s);
      live=false;
      return;
    }
    age.textContent='updated '+ago(s);
  }
  tick(); setInterval(tick,1000);
})();
"""


def render_index(payload: dict[str, Any], out_dir: Path, *, table_limit: int = 500) -> str:
    cfg: ReportConfig = payload["config"]
    run = payload.get("run") or {}
    # marks belong to the corpus, not to one run over it, so a rerun keeps them
    corpus = f"{run.get('pipeline', '')}:{run.get('target', '')}"
    marks = _load_marks(out_dir)
    t = payload["totals"]
    buckets = payload["buckets"]
    items: list[ItemReport] = payload["items"]
    columns: list[str] = payload["columns"]
    running = str(run.get("state", "")).lower() == "running"
    entity = cfg.entity

    total = t["samples"]
    n_pos = buckets.get(BUCKET_VULNERABLE, 0)
    n_rev = buckets.get(BUCKET_SUSPICIOUS, 0)
    n_err = buckets.get(BUCKET_FAILED, 0)
    n_una = buckets.get(BUCKET_UNASSESSED, 0)
    n_set = buckets.get(BUCKET_FILTERED, 0)
    n_ok = max(total - n_pos - n_rev - n_err - n_una - n_set, 0)

    # the two outcomes somebody has to act on carry the headline; the rest are
    # acknowledged on one line, so the eye is not asked to triage five equals.
    lead = (
        ("pos", n_pos, "vulnerable", BUCKET_VULNERABLE),
        ("rev", n_rev, "needs assessment", BUCKET_SUSPICIOUS),
    )
    rest = (
        ("err", n_err, "errored", BUCKET_FAILED),
        ("una", n_una, "unclear verdict", BUCKET_UNASSESSED),
        ("ok", n_ok, "clear", BUCKET_CLEAN),
        ("set", n_set, "filtered out", BUCKET_FILTERED),
    )
    ticks = "".join(
        f"<div class='tick {cls}{'' if n else ' zero'}' title=\"{_esc(_BUCKET_RULE[bucket])}\">"
        f"<b>{n:,}</b><span class='lbl'>{label}</span></div>"
        for cls, n, label, bucket in lead
    )
    trailing = "".join(
        f"<span class='{cls}' title=\"{_esc(_BUCKET_RULE[bucket])}\"><i></i>"
        f"<b>{n:,}</b>{label}</span>"
        for cls, n, label, bucket in rest
        if n
    )
    # the whole corpus as one line, keyed by outcome so the filter can dim it
    # down to the slice on screen. It describes the list being looked at, which
    # during a live run is also the clearest sign the corpus is still growing.
    spread = "".join(
        f"<i class='{cls}' data-b='{bucket}' style='flex:{n}' title='{n:,} {label}'></i>"
        for cls, n, label, bucket in lead + rest
        if n
    )
    readout = (
        f"<div class='readout'><div class='ticks'>{ticks}</div>"
        + (
            f"<div class='spread' role='img' aria-label='{total:,} {_esc(entity)}s by "
            f"outcome'>{spread}</div>"
            if total
            else ""
        )
        + (f"<p class='rest'>{trailing}</p>" if trailing else "")
        + "</div>"
    )

    # one list, ranked across every outcome, because risk ranks across the whole
    # corpus rather than restarting per outcome. The outcome is a filter over
    # that list, so a sort applies to everything the reader can currently see.
    listed = sorted(
        (i for i in items if i.bucket in _LIST_ORDER),
        key=lambda x: (_LIST_ORDER[x.bucket], -x.risk, x.name.lower()),
    )
    shown = listed[:table_limit]
    capped = (
        f"<p class='aside'>Showing the {len(shown):,} highest-risk of {len(listed):,}. "
        f"Every {entity} is in <a href='inventory.csv'>inventory.csv</a>.</p>"
        if len(listed) > len(shown)
        else ""
    )
    present: dict[str, int] = {}
    for i in listed:
        present[i.bucket] = present.get(i.bucket, 0) + 1
    # a control gets the short gloss; the full rule belongs on the result it
    # was applied to, which is where somebody stops to question a label
    chips = "".join(
        f"<button type='button' class='chipf {_RES_CLASS.get(b, 'non')}' data-b='{b}' "
        f"aria-pressed='false' title=\"{_esc(_BUCKET_HELP[b])}\">"
        f"{_esc(_BUCKET_LABELS[b])}<b>{n:,}</b></button>"
        for b, n in sorted(present.items(), key=lambda kv: _LIST_ORDER[kv[0]])
    )
    review_chips = "".join(
        f"<button type='button' class='chipf' data-mark='{state}' aria-pressed='false' "
        f'title="{_esc(help_text)}">{label}</button>'
        for state, label, help_text in (
            (
                MARK_CONFIRMED,
                "Confirmed",
                "you marked these as checked while reading the report",
            ),
            (
                MARK_OUTSTANDING,
                "Outstanding",
                "you marked these as resting on something still unproven",
            ),
            (
                "unmarked",
                "Unreviewed",
                "nobody has recorded a review of these yet",
            ),
        )
    )
    body_rows = "".join(
        "<tr class='{res}' data-k='{k}' data-b='{b}' data-sid='{sid}'>"
        "<td class='spec'><a href='items/{sid}.html'>{name}</a>{strip}</td>"
        "<td class='r{muted}' data-v='{fc}'>{fc}</td>"
        "<td class='sev' data-v='{risk}'>{sev}</td>"
        # sorts in triage order, not alphabetically: vulnerable before errored
        "<td class='out' data-v='{ord}'><span class='res {res}' title=\"{rule}\">{label}</span></td>"
        "<td class='rev'></td>"
        "</tr>".format(
            k=_esc(i.name.lower()),
            b=_esc(i.bucket),
            ord=_LIST_ORDER[i.bucket],
            sid=_esc(i.sample_id),
            name=_esc(i.name),
            strip=_strip(i, columns),
            fc=i.finding_count,
            muted="" if i.finding_count else " muted",
            risk=i.risk,
            sev=_severity(i),
            res=_RES_CLASS.get(i.bucket, "non"),
            rule=_esc(_BUCKET_RULE[i.bucket]),
            label=_esc(_BUCKET_LABELS[i.bucket]),
        )
        for i in shown
    )
    sections = (
        f"""<section>
  {capped}
  <div class="scroll"><table data-sortable><thead><tr>
    <th>{_esc(entity)}</th><th class="r">findings</th>
    <th class="r">severity</th><th>outcome</th><th class="r">review</th>
  </tr></thead><tbody>{body_rows}</tbody></table></div>
</section>"""
        if shown
        else ""
    )
    if n_set:
        by_stage: dict[str, int] = {}
        for i in items:
            if i.bucket == BUCKET_FILTERED:
                by_stage[i.filtered_at or "an earlier stage"] = (
                    by_stage.get(i.filtered_at or "an earlier stage", 0) + 1
                )
        where = ", ".join(
            f"{n:,} at {_esc(k)}" for k, n in sorted(by_stage.items(), key=lambda kv: -kv[1])
        )
        sections += (
            f"<section><div class='shead q' title=\"{_esc(_BUCKET_RULE[BUCKET_FILTERED])}\">"
            f"<h2>Filtered out</h2>"
            f"<span class='n'>{n_set:,}</span>"
            f"<span class='of'>{_esc(_BUCKET_HELP[BUCKET_FILTERED])}</span></div>"
            f"<p class='aside'>These were excluded before the analysis finished, so they are "
            f"not a judgement about the {_esc(entity)}"
            + (f": {where}." if where else ".")
            + " Every one is listed in <a href='inventory.csv'>inventory.csv</a>.</p></section>"
        )
    if not sections:
        sections = "<section><p class='aside'>No findings or assessments have landed yet." + (
            " This page updates itself as results arrive.</p></section>"
            if running
            else " The run recorded no results to review.</p></section>"
        )

    rules = "".join(
        f"<tr><td class='spec mono' style='color:var(--ink)'>{_esc(k)}</td>"
        f"<td class='r' data-v='{v}'>{v:,}</td></tr>"
        for k, v in payload["rule_totals"].items()
    )
    rules_section = (
        f"""<section>
  <div class="shead q"><h2>Rules that fired</h2>
    <span class="n">{len(payload["rule_totals"]):,}</span>
    <span class="of">across every {_esc(entity)} scanned</span></div>
  <div class="scroll"><table data-sortable><thead><tr><th>rule</th>
  <th class="r">hits</th></tr></thead><tbody>{rules}</tbody></table></div>
</section>"""
        if rules
        else ""
    )

    # say what to do next, not only what happened
    if n_pos:
        note = (
            f"<p class='finding-note'><b>{n_pos:,} {_esc(entity)}"
            f"{'s' if n_pos != 1 else ''} assessed as vulnerable.</b> "
            f"They lead the list below, ordered by the severity of what was "
            f"found {_DASH} start at the top.</p>"
        )
    elif n_rev:
        note = (
            f"<p class='finding-note rev'><b>Nothing was confirmed vulnerable.</b> "
            f"{n_rev:,} {_esc(entity)}{'s' if n_rev != 1 else ''} produced findings "
            f"that no assessment has confirmed or dismissed {_DASH} those are the "
            f"ones worth reading.</p>"
        )
    else:
        note = ""
    trunc = (
        f"<p class='aside'>Detail pages are capped at {len(items):,}. The remaining "
        f"{payload['detail_truncated']:,} appear in <a href='inventory.csv'>inventory.csv</a>.</p>"
        if payload["detail_truncated"]
        else ""
    )

    title = cfg.title or f"{run.get('pipeline', 'DeepZero')} results"
    # the run id is an identifier you copy, not one you scan, so it sits in the
    # kicker and the plate keeps the three values that describe the work
    plate = "".join(
        f"<div><div class='lbl'>{lbl}</div><dd>{_esc(val)}</dd></div>"
        for lbl, val in (
            ("corpus", run.get("target", "-")),
            ("assessed by", run.get("model", "-")),
        )
    ) + _run_state_cell(run, str(payload.get("generated_at", "")))

    body = f"""<header class="mast">
  <div class="kicker"><span class="mark">DEEPZERO</span>
    <span class="lbl">vulnerability research</span>
    <span class="id">{_esc(run.get("run_id", "") or "")}</span></div>
  <h1>{_esc(title)} <span class="qty">{t["samples"]:,} {_esc(entity)}s</span></h1>
  <dl class="plate">{plate}</dl>
  {readout}
  {note}{trunc}
  <div class="files">
    <a href="inventory.csv">inventory.csv</a>
    <a href="findings.jsonl">findings.jsonl</a>
    <a href="report.json">report.json</a>
    <a href="#" id="export-marks" title="save your review marks next to the report as marks.json, so they render for anyone who opens it">export marks</a>
  </div>
</header>
<div class="filter">
  <span class="field"><span class="glyph">&#9906;</span>
    <input type="search" id="q" placeholder="Filter by name" aria-label="Filter by name"></span>
  {chips}{review_chips}
  <span class="hint" id="hint"></span>
</div>
{sections}{rules_section}"""
    return _page(title, body, live=running, corpus=corpus, marks=marks)


def write_report(
    work_dir: Path,
    out_dir: Path | None = None,
    *,
    config: ReportConfig | dict[str, Any] | None = None,
    detail_limit: int = 2000,
    table_limit: int = 500,
) -> tuple[Path, Path]:
    """write the layered report. returns (index.html, report.json)."""
    cfg = config if isinstance(config, ReportConfig) else ReportConfig.from_dict(config)
    payload = collect(work_dir, config=cfg, detail_limit=detail_limit)
    target = out_dir or (work_dir / "report")
    (target / "items").mkdir(parents=True, exist_ok=True)

    rows = payload.pop("rows")
    # a mark saved back into the report belongs in the spreadsheet too, so it
    # can be sorted and counted with everything else rather than only viewed
    saved_marks = _load_marks(target)
    if saved_marks:
        for r in rows:
            mark = saved_marks.get(str(r.get("sample_id", "")))
            r["review"] = mark["state"] if mark else ""
            r["review_note"] = mark["note"] if mark else ""
    fieldnames: list[str] = []
    for r in rows:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with (target / "inventory.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames or ["sample_id"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    items: list[ItemReport] = payload["items"]
    with (target / "findings.jsonl").open("w", encoding="utf-8") as fh:
        for it in items:
            for f in it.findings:
                fh.write(
                    json.dumps(
                        {
                            "sample_id": it.sample_id,
                            "name": it.name,
                            "bucket": it.bucket,
                            "source_path": it.source_path,
                            **f,
                        },
                        default=str,
                    )
                    + "\n"
                )

    run_info = payload.get("run") or {}
    pipeline = run_info.get("pipeline", "")
    corpus = f"{pipeline}:{run_info.get('target', '')}"
    marks = _load_marks(target)
    for it in items:
        (target / "items" / f"{it.sample_id}.html").write_text(
            render_item_page(it, target / "items", cfg, pipeline, corpus, marks),
            encoding="utf-8",
        )

    index = target / "index.html"
    index.write_text(render_index(payload, target, table_limit=table_limit), encoding="utf-8")

    summary = {k: v for k, v in payload.items() if k not in ("items", "config")}
    summary["item_pages"] = len(items)
    summary["entity"] = cfg.entity
    json_path = target / "report.json"
    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    log.debug(
        "report: %d samples, %d findings, %d vulnerable -> %s",
        payload["totals"]["samples"],
        payload["totals"]["total_findings"],
        payload["buckets"].get(BUCKET_VULNERABLE, 0),
        index,
    )
    return index, json_path
