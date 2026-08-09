"""Regenerate the report screenshot used in the README and the docs site.

The data is invented. Screenshots of a real run would publish findings before
the people who own the code have seen them, and would also go stale the moment
that run was rerun. This builds a fixed, fictional corpus instead, so the image
can be regenerated at any time and always looks the same.

    python .github/assets/make_demo_report.py
    chrome --headless=new --window-size=1400,760 \
        --screenshot=.github/assets/report-source-audit.png \
        file:///<abs path>/.demo/work/source_audit/report/index.html
"""

from __future__ import annotations

import json
import pathlib
import shutil

from deepzero.engine.report import ReportConfig, write_report
from deepzero.engine.state import RunState, SampleState, StateStore
from deepzero.engine.types import RunStatus

# a spread wide enough to show every outcome the report distinguishes: confirmed,
# found but unjudged, and analysed with nothing to say
REPOS = [
    (
        "example-org/checkout-api",
        "go",
        41200,
        "vulnerable",
        [
            (
                "dz.injection.go-sql-concat",
                "ERROR",
                "user input concatenated into a SQL query, so an attacker controls the statement",
                "internal/orders/store.go",
                148,
            ),
            (
                "dz.ssrf.go-user-url",
                "ERROR",
                "an attacker-supplied url is fetched by the server, reaching internal addresses",
                "internal/webhook/send.go",
                62,
            ),
            (
                "dz.authnz.go-missing-check",
                "WARNING",
                "handler mutates an order without checking the caller owns it",
                "internal/orders/http.go",
                210,
            ),
        ],
    ),
    (
        "example-org/billing-worker",
        "python",
        18900,
        "vulnerable",
        [
            (
                "dz.deserialization.py-pickle-untrusted",
                "ERROR",
                "pickle.loads on queue data gives an attacker code execution",
                "worker/tasks.py",
                77,
            )
        ],
    ),
    (
        "example-org/admin-console",
        "typescript",
        66400,
        "suspicious",
        [
            (
                "dz.injection.js-command-concat",
                "ERROR",
                "request data reaches child_process.exec unquoted",
                "src/server/tools.ts",
                33,
            ),
            (
                "dz.crypto.js-weak-hash",
                "WARNING",
                "password hashed with md5",
                "src/server/auth.ts",
                19,
            ),
        ],
    ),
    ("example-org/design-tokens", "typescript", 2100, "safe", []),
    ("example-org/docs-site", "javascript", 9800, "safe", []),
    (
        "example-org/legacy-reports",
        "java",
        31000,
        "safe",
        [
            (
                "dz.crypto.java-ecb",
                "WARNING",
                "AES in ECB mode leaks structure of the plaintext",
                "src/main/java/Report.java",
                88,
            )
        ],
    ),
]


def build(root: pathlib.Path) -> pathlib.Path:
    shutil.rmtree(root, ignore_errors=True)
    work = root / "work" / "source_audit"
    store = StateStore(work)
    store.save_run(
        RunState(
            run_id="run_20260809_142211",
            pipeline="source_audit",
            target="github.com/example-org",
            model="claude-code/claude-opus-5",
            status=RunStatus.COMPLETED,
        )
    )

    for i, (name, language, loc, verdict, findings) in enumerate(REPOS):
        sample_id = f"r{i:02d}"
        sample = SampleState(
            sample_id=sample_id, filename=name, source_path=f"https://github.com/{name}"
        )
        sample.mark_stage_completed(
            "discover",
            data={
                "repo_full_name": name,
                "primary_language": language,
                "total_loc": loc,
                "total_files": loc // 90,
                "has_dependency_manifest": True,
                "commit_sha": "abcdef123456",
                "default_branch": "main",
            },
        )
        sample.mark_stage_completed("size_filter", data={})
        sample.mark_stage_completed(
            "scan", data={"finding_count": len(findings)}, artifacts={"findings": "findings.json"}
        )
        # the unjudged one keeps its findings and gets no verdict, which is the
        # outcome the report exists to keep separate from "nothing was found"
        if verdict != "suspicious":
            sample.mark_stage_completed(
                "assess",
                data={"classification": verdict},
                artifacts={"llm_output": "assessment.md"},
            )
        store.save_sample(sample)

        sample_dir = store.sample_dir(sample_id)
        if findings:
            (sample_dir / "findings.json").write_text(
                json.dumps(
                    [
                        {
                            "rule_id": rule,
                            "severity": severity,
                            "message": message,
                            "location": location,
                            "line": line,
                        }
                        for rule, severity, message, location, line in findings
                    ]
                ),
                encoding="utf-8",
            )
        if verdict == "vulnerable":
            (sample_dir / "assessment.md").write_text(
                f"[VULNERABLE] {name}\n\nThe flagged sink is reachable from an "
                f"unauthenticated handler, so an attacker controls the input that "
                f"reaches it.\n",
                encoding="utf-8",
            )

    config = ReportConfig.from_dict(
        {
            "title": "Source code audit",
            "entity": "repository",
            "entity_plural": "repositories",
            "target_label": "organisation",
            "classification_key": "classification",
            "positive_when": ["vulnerable"],
            "negative_when": ["safe"],
            "columns": ["scan.finding_count", "discover.primary_language", "discover.total_loc"],
        }
    )
    html_path, _ = write_report(work, config=config)
    return html_path


if __name__ == "__main__":
    path = build(pathlib.Path(".demo"))
    print(path.resolve().as_uri())
