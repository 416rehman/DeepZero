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
    BUCKET_SUSPICIOUS: "Needs review",
    BUCKET_FAILED: "Errored",
    BUCKET_UNASSESSED: "Not assessed",
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

# keys worth promoting into the summary table when a pipeline declares no columns
_INTERESTING_HINTS = ("count", "score", "severity", "total", "hits", "size", "stars", "rank")


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
            "status": str(getattr(getattr(run, "status", ""), "value", getattr(run, "status", ""))),
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


_CSS = """
/* Cold paper, hairline rules, and wide-tracked monospace micro-labels set
   against a tight heavy headline. A single colour marks a positive result. */
:root{
  --paper:#F7F8FA; --plate:#FFFFFF; --ink:#0E1216; --body:#3A424C;
  --faint:#5E6672; --rule:#DCE1E7; --rule-hard:#A6AFBA;
  --positive:#9B1C31; --positive-wash:#9B1C310F;
  --review:#5B3FBF;  --review-wash:#5B3FBF0F;
  --ok:#1F7A5C; --inert:#C3CAD2;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"Cascadia Mono","SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root{
    --paper:#0E1116; --plate:#141920; --ink:#F1F4F7; --body:#A9B2BD;
    --faint:#8B95A2; --rule:#222932; --rule-hard:#3E4854;
    --positive:#FF6A75; --positive-wash:#FF6A7514;
    --review:#A78BFA; --review-wash:#A78BFA14;
    --ok:#4ADE80; --inert:#39424E;
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--paper);color:var(--body);
  font:400 13px/1.6 var(--sans);padding:0 32px 120px;
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
.mast{padding:58px 0 0}
.kicker{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}
.kicker .mark{font:700 10.5px/1 var(--mono);letter-spacing:.24em;color:var(--ink)}
h1{
  margin:20px 0 0;color:var(--ink);
  font:700 clamp(30px,4.6vw,52px)/0.98 var(--sans);letter-spacing:-.035em;
}
h1 .qty{color:var(--faint);font-weight:400;letter-spacing:-.02em}
.plate{
  margin:32px 0 0;border-top:1px solid var(--rule-hard);border-bottom:1px solid var(--rule);
  display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
}
.plate > div{padding:15px 20px 16px 0;border-right:1px solid var(--rule)}
.plate > div:last-child{border-right:0}
.plate dd{margin:8px 0 0;font:400 12.5px/1.45 var(--mono);color:var(--ink);word-break:break-word}

.dist{margin:38px 0 0;padding-top:22px;border-top:1px solid var(--rule)}
.ticks{display:flex;flex-wrap:wrap;gap:0 48px}
.tick b{letter-spacing:-.03em}
.tick b{display:block;color:var(--ink);font:600 27px/1 var(--mono)}
.tick .lbl{display:block;margin-top:7px}
.tick.pos b{color:var(--positive)}
.tick.rev b{color:var(--review)}

/* statements -------------------------------------------------------------- */
.finding-note{
  margin:30px 0 0;padding:15px 18px;background:var(--positive-wash);
  border-left:2px solid var(--positive);color:var(--ink);font-size:13px
}
.finding-note b{font-weight:600}
.aside{
  margin:20px 0 0;padding:13px 0 0;border-top:1px solid var(--rule);
  color:var(--faint);font-size:12px
}
.files{margin:26px 0 0;display:flex;gap:22px;flex-wrap:wrap}
.files a{font:400 11.5px/1 var(--mono);color:var(--body)}

/* sections ---------------------------------------------------------------- */
section{margin-top:62px}
.shead{display:flex;align-items:baseline;gap:16px;padding-bottom:12px;border-bottom:1px solid var(--rule-hard)}
.shead h2{margin:0;color:var(--ink);font:600 13px/1 var(--mono);letter-spacing:.16em;text-transform:uppercase}
.shead .n{font:600 13px/1 var(--mono);color:var(--positive)}
.shead.q h2{color:var(--body)}
.shead.q .n{color:var(--faint)}
.shead .of{margin-left:auto;color:var(--faint);font-size:11.5px;text-align:right;max-width:44ch}

/* result table ------------------------------------------------------------ */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse}
thead th{
  position:sticky;top:0;z-index:2;background:var(--paper);
  font:500 9.5px/1 var(--mono);letter-spacing:.17em;text-transform:uppercase;color:var(--faint);
  text-align:left;padding:15px 14px 10px 0;white-space:nowrap;border-bottom:1px solid var(--rule);
  cursor:pointer;user-select:none
}
thead th::after{
  content:"95";margin-left:7px;opacity:.4;font-size:10px;letter-spacing:0
}
thead th:hover{color:var(--ink)}
thead th:hover::after{opacity:1}
thead th[data-dir="asc"], thead th[data-dir="desc"]{color:var(--ink)}
thead th[data-dir="asc"]::after{content:"91";opacity:1}
thead th[data-dir="desc"]::after{content:"93";opacity:1}
thead th.r{text-align:right}
tbody tr{cursor:pointer}
tbody td{padding:14px 14px 14px 0;border-bottom:1px solid var(--rule);vertical-align:baseline}
tbody tr:hover td{background:var(--plate)}
tbody tr:hover td.spec a{border-bottom-color:var(--ink)}
tbody tr:focus-within td{background:var(--plate)}
td.open{width:1%;text-align:right;font:400 14px/1 var(--mono);color:var(--faint);opacity:0}
tbody tr:hover td.open{opacity:1;color:var(--ink)}
td.r{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--ink)}
td.idx{font:400 11px/1.5 var(--mono);color:var(--faint);white-space:nowrap;padding-right:20px}
td.spec a{font:500 13.5px/1.35 var(--sans);color:var(--ink);letter-spacing:-.01em;
  border-bottom:1px solid var(--rule-hard)}
td.spec a:hover{border-bottom-color:var(--ink)}
td.muted{color:var(--faint)}
.res{font:600 9.5px/1 var(--mono);letter-spacing:.15em;text-transform:uppercase}
.res.pos{color:var(--positive)}
.res.rev{color:var(--review)}
.res.non{color:var(--faint)}
.grade{font-family:var(--mono);white-space:nowrap;color:var(--faint)}
.grade b{color:var(--positive);font-weight:600}
.grade i{color:var(--body);font-style:normal}

/* specimen fingerprint ---------------------------------------------------- */
.strip{display:flex;gap:14px;flex-wrap:wrap;margin-top:7px}
.chip{font:400 11px/1.4 var(--mono);color:var(--body);white-space:nowrap}
.chip em{color:var(--faint);font-style:normal;margin-right:5px;letter-spacing:.06em}
.chip.on{color:var(--positive)}

/* filter ------------------------------------------------------------------ */
.filter{margin:38px 0 0;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.field{
  display:flex;align-items:center;gap:9px;background:var(--plate);
  border:1px solid var(--rule-hard);padding:0 12px;min-width:300px
}
.field:focus-within{border-color:var(--review);box-shadow:0 0 0 3px var(--review-wash)}
.field .glyph{color:var(--faint);font:400 14px/1 var(--mono)}
input[type=search]{
  flex:1;background:transparent;color:var(--ink);border:0;outline:0;
  padding:11px 0;font:400 13px/1 var(--mono)
}
input[type=search]::placeholder{color:var(--faint)}
.hint{color:var(--faint);font-size:11.5px}
.files a{
  border:1px solid var(--rule-hard);padding:6px 11px;color:var(--body);
  font:400 11px/1 var(--mono);letter-spacing:.04em
}
.files a:hover{border-color:var(--ink);color:var(--ink)}

/* specimen page ----------------------------------------------------------- */
.back{display:inline-block;margin:44px 0 0;font:400 11px/1 var(--mono);letter-spacing:.1em;
  text-transform:uppercase;color:var(--faint);border:0}
.back:hover{color:var(--ink)}
.verdict{display:block;margin-top:18px}
.verdict .res{font-size:11px;letter-spacing:.2em}
.verdict hr{margin:10px 0 0;border:0;border-top:2px solid var(--positive);width:44px}
.verdict.rev hr{border-top-color:var(--review)}
.verdict.non hr{border-top-color:var(--rule-hard)}
.evidence{list-style:none;padding:0;margin:0}
.evidence li{padding:22px 0;border-bottom:1px solid var(--rule)}
.ehead{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}
.ehead .sev{font:600 9.5px/1 var(--mono);letter-spacing:.15em;text-transform:uppercase;color:var(--positive)}
.ehead .rule{font:500 12.5px/1 var(--mono);color:var(--ink)}
.ehead .at{margin-left:auto;font:400 11px/1 var(--mono);color:var(--faint)}
.emsg{margin:9px 0 0;color:var(--body);font-size:13px;max-width:76ch}
pre{
  margin:13px 0 0;padding:16px 18px;background:var(--plate);
  border:1px solid var(--rule);border-left:2px solid var(--rule-hard);
  overflow-x:auto;font:400 12px/1.7 var(--mono);color:var(--ink);
  white-space:pre-wrap;word-break:break-word
}
.prose pre{border-left-color:var(--positive)}
.kv{width:100%;border-collapse:collapse;margin-top:6px}
.kv td{padding:10px 16px 10px 0;border-bottom:1px solid var(--rule);
  font:400 12px/1.5 var(--mono);vertical-align:baseline;color:var(--ink)}
.kv td:first-child{color:var(--faint);white-space:nowrap;width:1%;letter-spacing:.04em}
.empty{color:var(--faint);font-size:12.5px;padding:22px 0}
@media (max-width:640px){
  body{padding:0 18px 72px}
  .mast{padding-top:36px}
  .plate > div{border-right:0;border-bottom:1px solid var(--rule)}
  .shead .of{display:none}
}
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
  if(q)q.addEventListener('input',function(){
    var v=q.value.toLowerCase();
    document.querySelectorAll('tbody tr').forEach(function(r){
      if(!r.dataset.k)return;
      r.style.display=r.dataset.k.indexOf(v)>-1?'':'none';
    });
    report();
  });
  report();

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


def _page(title: str, body: str, *, refresh: str = "") -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"{refresh}<title>{_esc(title)}</title><style>{_CSS}</style></head>"
        f'<body><div class="shell">{body}</div><script>{_JS}</script></body></html>'
    )


def _sev_cell(item: ItemReport) -> str:
    sev = item.severity_counts
    high = sev.get("CRITICAL", 0) + sev.get("HIGH", 0) + sev.get("ERROR", 0)
    med = sev.get("MEDIUM", 0) + sev.get("WARNING", 0)
    low = sev.get("LOW", 0) + sev.get("INFO", 0)
    parts = []
    if high:
        parts.append(f"<span class='h'>{high}H</span>")
    if med:
        parts.append(f"<span class='m'>{med}M</span>")
    if low:
        parts.append(f"<span class='l'>{low}L</span>")
    return f"<span class='sev'>{' '.join(parts) or '<span class=l>-</span>'}</span>"


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


def _grade(item: ItemReport) -> str:
    """the severity mix of an item, most serious first."""
    sev = item.severity_counts
    high = sev.get("CRITICAL", 0) + sev.get("HIGH", 0) + sev.get("ERROR", 0)
    med = sev.get("MEDIUM", 0) + sev.get("WARNING", 0)
    low = sev.get("LOW", 0) + sev.get("INFO", 0)
    parts = []
    if high:
        parts.append(f"<b>{high}&thinsp;high</b>")
    if med:
        parts.append(f"<i>{med}&thinsp;med</i>")
    if low:
        parts.append(f"{low}&thinsp;low")
    return f"<span class='grade'>{' '.join(parts) or '&mdash;'}</span>"


def render_item_page(item: ItemReport, out_dir: Path, cfg: ReportConfig, pipeline: str = "") -> str:
    res = _RES_CLASS.get(item.bucket, "non")
    evidence = []
    for f in sorted(item.findings, key=lambda x: _SEVERITY_ORDER.get(x["severity"], 9)):
        at = " ".join(x for x in (f["location"], f"line {f['line']}" if f["line"] else "") if x)
        code = f"<pre>{_esc(f['code'][:1400])}</pre>" if f["code"] else ""
        evidence.append(
            "<li><div class='ehead'>"
            f"<span class='sev'>{_esc(f['severity'])}</span>"
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
    body = f"""<a class="back" href="../index.html">&larr; all results</a>
<header class="mast" style="padding-top:26px">
  <div class="kicker"><span class="mark">{_esc(pipeline or "DEEPZERO")}</span>
    <span class="lbl">{_esc(cfg.entity)}</span></div>
  <h1>{_esc(item.name)}</h1>
  <div class="verdict {res}">
    <span class="res {res}">{_esc(_BUCKET_LABELS.get(item.bucket, item.bucket))}</span>
    <hr>
  </div>
  <div class="files">{"".join(files)}</div>
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
    return _page(f"{item.name} - DeepZero", body)


def render_index(payload: dict[str, Any], out_dir: Path, *, table_limit: int = 500) -> str:
    cfg: ReportConfig = payload["config"]
    run = payload.get("run") or {}
    t = payload["totals"]
    buckets = payload["buckets"]
    items: list[ItemReport] = payload["items"]
    columns: list[str] = payload["columns"]
    running = str(run.get("status", "")).lower() == "running"
    entity = cfg.entity

    total = t["samples"]
    n_pos = buckets.get(BUCKET_VULNERABLE, 0)
    n_rev = buckets.get(BUCKET_SUSPICIOUS, 0)
    n_err = buckets.get(BUCKET_FAILED, 0)
    n_set = buckets.get(BUCKET_FILTERED, 0)
    n_ok = max(total - n_pos - n_rev - n_err - n_set, 0)

    ticks = "".join(
        f"<div class='tick {cls}'><b>{n:,}</b><span class='lbl'>{label}</span></div>"
        for cls, n, label in (
            ("pos", n_pos, "vulnerable"),
            ("rev", n_rev, "needs review"),
            ("err", n_err, "errored"),
            ("ok", n_ok, "clear"),
            ("set", n_set, "filtered out"),
        )
    )

    def section(bucket: str, *, quiet: bool = False) -> str:
        rows = [i for i in items if i.bucket == bucket]
        if not rows:
            return ""
        shown = rows[:table_limit]
        capped = (
            f"<p class='aside'>Showing the {len(shown):,} highest-risk of {len(rows):,}. "
            f"Every {entity} is in <a href='inventory.csv'>inventory.csv</a>.</p>"
            if len(rows) > len(shown)
            else ""
        )
        res = _RES_CLASS.get(bucket, "non")
        body_rows = "".join(
            "<tr data-k='{k}'><td class='idx'>{idx}</td>"
            "<td class='spec'><a href='items/{sid}.html'>{name}</a>{strip}</td>"
            "<td class='r{muted}' data-v='{fc}'>{fc}</td>"
            "<td class='r' data-v='{risk}'>{grade}</td>"
            "<td class='r'><span class='res {res}'>{verdict}</span></td>"
            "<td class='open' aria-hidden='true'>&rarr;</td></tr>".format(
                k=_esc(i.name.lower()),
                idx=f"{n:03d}",
                sid=_esc(i.sample_id),
                name=_esc(i.name),
                strip=_strip(i, columns),
                fc=i.finding_count,
                muted="" if i.finding_count else " muted",
                risk=i.risk,
                grade=_grade(i),
                res=res,
                verdict=_esc(i.classification or "&mdash;"),
            )
            for n, i in enumerate(shown, start=1)
        )
        return f"""<section>
  <div class="shead{" q" if quiet else ""}">
    <h2>{_esc(_BUCKET_LABELS.get(bucket, bucket))}</h2><span class="n">{len(rows):,}</span>
    <span class="of">{_esc(_BUCKET_HELP.get(bucket, ""))}</span>
  </div>
  {capped}
  <div class="scroll"><table data-sortable><thead><tr>
    <th>&numero;</th><th>{_esc(entity)}</th><th class="r">findings</th>
    <th class="r">severity</th><th class="r">result</th><th aria-label="open"></th>
  </tr></thead><tbody>{body_rows}</tbody></table></div>
</section>"""

    sections = (
        section(BUCKET_VULNERABLE)
        + section(BUCKET_SUSPICIOUS, quiet=True)
        + section(BUCKET_FAILED, quiet=True)
        + section(BUCKET_UNASSESSED, quiet=True)
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
            f"<section><div class='shead q'><h2>Filtered out</h2>"
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

    note = (
        f"<p class='finding-note'><b>{n_pos:,} {_esc(entity)}"
        f"{'s' if n_pos != 1 else ''} assessed as vulnerable.</b> "
        f"Listed first, ordered by severity.</p>"
        if n_pos
        else ""
    )
    trunc = (
        f"<p class='aside'>Detail pages are capped at {len(items):,}. The remaining "
        f"{payload['detail_truncated']:,} appear in <a href='inventory.csv'>inventory.csv</a>.</p>"
        if payload["detail_truncated"]
        else ""
    )

    title = cfg.title or f"{run.get('pipeline', 'DeepZero')} results"
    status = _esc(run.get("status", "")) or "unknown"
    plate = "".join(
        f"<div><div class='lbl'>{lbl}</div><dd>{_esc(val)}</dd></div>"
        for lbl, val in (
            ("corpus", run.get("target", "-")),
            ("assessed by", run.get("model", "-")),
            ("run", run.get("run_id", "-")),
            ("status", f"{status}{' - updating' if running else ''}"),
        )
    )
    refresh = '<meta http-equiv="refresh" content="20">' if running else ""

    body = f"""<header class="mast">
  <div class="kicker"><span class="mark">DEEPZERO</span>
    <span class="lbl">vulnerability research</span></div>
  <h1>{_esc(title)} <span class="qty">{t["samples"]:,} {_esc(entity)}s</span></h1>
  <dl class="plate">{plate}</dl>
  <div class="dist"><div class="ticks">{ticks}</div></div>
  {note}{trunc}
  <div class="files">
    <a href="inventory.csv">inventory.csv</a>
    <a href="findings.jsonl">findings.jsonl</a>
    <a href="report.json">report.json</a>
  </div>
  <div class="filter">
    <span class="field"><span class="glyph">&#9906;</span>
      <input type="search" id="q" placeholder="Filter by name"></span>
    <span class="hint" id="hint"></span>
    <span class="hint">Click a column to sort. Click a row to open its evidence.</span>
  </div>
</header>
{sections}{rules_section}"""
    return _page(title, body, refresh=refresh)


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

    pipeline = (payload.get("run") or {}).get("pipeline", "")
    for it in items:
        (target / "items" / f"{it.sample_id}.html").write_text(
            render_item_page(it, target / "items", cfg, pipeline), encoding="utf-8"
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
