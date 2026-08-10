"""Regenerate the report screenshots used in the README and the docs site.

The data is invented. Screenshots of a real run would publish findings before the
people who own the code have seen them, and would also go stale the moment that
run was rerun. This builds fixed, fictional corpora instead, so the images can be
regenerated at any time and always look the same.

One demo per shipped pipeline, because the point the screenshots have to make is
that the same engine describes two unrelated disciplines in each one's own words.
Neither vocabulary is written here: each demo loads its pipeline's own `report:`
block, so an image can never show wording the shipped pipeline no longer uses.

    python .github/assets/make_demo_report.py

It prints one `chrome --headless` line per image, ready to run.
"""

from __future__ import annotations

import json
import pathlib
import shutil
from dataclasses import dataclass, field
from typing import Any

import deepzero.stages  # noqa: F401  registers the built-in processors by name
from deepzero.engine.pipeline import load_pipeline
from deepzero.engine.report import ReportConfig, write_report
from deepzero.engine.state import RunState, SampleState, StateStore
from deepzero.engine.types import RunStatus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

Finding = tuple[str, str, str, str, int]


@dataclass
class DemoSample:
    """One row of a demo run.

    `stages` is keyed by the pipeline's real stage names, because that is what the
    report's `columns` address. A stage listed here is recorded as completed even
    when its data is empty, which is how a filter stage that passed a sample
    through looks on disk.
    """

    name: str
    source: str
    verdict: str | None
    stages: dict[str, dict[str, Any]]
    findings: list[Finding] = field(default_factory=list)
    assessment: str = ""


@dataclass
class Demo:
    pipeline: str
    image: str
    run_id: str
    target: str
    findings_stage: str
    samples: list[DemoSample]


SOURCE_AUDIT = Demo(
    pipeline="pipelines/source_audit/pipeline.yaml",
    image="report-source-audit.png",
    run_id="run_20260809_142211",
    target="repos.txt",
    findings_stage="scan",
    samples=[
        DemoSample(
            name="example-org/checkout-api",
            source="https://github.com/example-org/checkout-api",
            verdict="vulnerable",
            stages={
                "discover": {
                    "primary_language": "go",
                    "source_files": 412,
                    "commit_sha": "a1c9f0e",
                },
                "size_filter": {},
                "scan": {"finding_count": 3, "files_scanned": 1183},
                "rank": {},
            },
            findings=[
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
            assessment=(
                "[VULNERABLE] example-org/checkout-api\n\n"
                "The flagged sink is reachable from an unauthenticated handler, so an "
                "attacker controls the input that reaches it.\n"
            ),
        ),
        DemoSample(
            name="example-org/billing-worker",
            source="https://github.com/example-org/billing-worker",
            verdict="vulnerable",
            stages={
                "discover": {
                    "primary_language": "python",
                    "source_files": 188,
                    "commit_sha": "77b4d21",
                },
                "size_filter": {},
                "scan": {"finding_count": 1, "files_scanned": 402},
                "rank": {},
            },
            findings=[
                (
                    "dz.deserialization.py-pickle-untrusted",
                    "ERROR",
                    "pickle.loads on queue data gives an attacker code execution",
                    "worker/tasks.py",
                    77,
                )
            ],
            assessment=(
                "[VULNERABLE] example-org/billing-worker\n\n"
                "Any producer that can reach the queue reaches the deserializer, and the "
                "queue accepts messages from the public ingest endpoint.\n"
            ),
        ),
        # found but never judged: the outcome the report exists to keep separate
        # from "nothing was found"
        DemoSample(
            name="example-org/admin-console",
            source="https://github.com/example-org/admin-console",
            verdict=None,
            stages={
                "discover": {
                    "primary_language": "typescript",
                    "source_files": 664,
                    "commit_sha": "0e35aa8",
                },
                "size_filter": {},
                "scan": {"finding_count": 2, "files_scanned": 1990},
                "rank": {},
            },
            findings=[
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
        DemoSample(
            name="example-org/legacy-reports",
            source="https://github.com/example-org/legacy-reports",
            verdict="not exploitable",
            stages={
                "discover": {
                    "primary_language": "java",
                    "source_files": 310,
                    "commit_sha": "c40f9b2",
                },
                "size_filter": {},
                "scan": {"finding_count": 1, "files_scanned": 774},
                "rank": {},
            },
            findings=[
                (
                    "dz.crypto.java-ecb",
                    "WARNING",
                    "AES in ECB mode leaks structure of the plaintext",
                    "src/main/java/Report.java",
                    88,
                )
            ],
            assessment=(
                "[NOT EXPLOITABLE] example-org/legacy-reports\n\n"
                "The cipher is applied to a build identifier that is already published in "
                "the release notes, so the leak discloses nothing an attacker lacks.\n"
            ),
        ),
        DemoSample(
            name="example-org/design-tokens",
            source="https://github.com/example-org/design-tokens",
            verdict="not exploitable",
            stages={
                "discover": {
                    "primary_language": "typescript",
                    "source_files": 21,
                    "commit_sha": "5ff1c03",
                },
                "size_filter": {},
                "scan": {"finding_count": 1, "files_scanned": 63},
                "rank": {},
            },
            findings=[
                (
                    "dz.injection.js-command-concat",
                    "WARNING",
                    "a template literal reaches execSync in a build script",
                    "scripts/build.ts",
                    44,
                )
            ],
            assessment=(
                "[NOT EXPLOITABLE] example-org/design-tokens\n\n"
                "The interpolated value is a filename this script generated a line "
                "earlier. Nothing outside the build reaches it.\n"
            ),
        ),
        DemoSample(
            name="example-org/docs-site",
            source="https://github.com/example-org/docs-site",
            verdict="not exploitable",
            stages={
                "discover": {
                    "primary_language": "javascript",
                    "source_files": 98,
                    "commit_sha": "e2810df",
                },
                "size_filter": {},
                "scan": {"finding_count": 2, "files_scanned": 265},
                "rank": {},
            },
            findings=[
                (
                    "dz.xss.js-innerhtml",
                    "WARNING",
                    "innerHTML assigned from a variable",
                    "src/search.js",
                    120,
                ),
                (
                    "dz.crypto.js-weak-hash",
                    "WARNING",
                    "md5 used to name a cache file",
                    "src/cache.js",
                    17,
                ),
            ],
            assessment=(
                "[NOT EXPLOITABLE] example-org/docs-site\n\n"
                "Both hits are on values the generator produced at build time from files "
                "in the repository. Neither is reachable from a request.\n"
            ),
        ),
    ],
)


LOLDRIVERS = Demo(
    pipeline="pipelines/loldrivers/pipeline.yaml",
    image="report-loldrivers.png",
    run_id="run_20260809_170402",
    target="C:/drivers",
    findings_stage="semgrep_scanner",
    samples=[
        DemoSample(
            name="ExampleIo64.sys",
            source="C:/drivers/DP_Vendor/ExampleIo64.sys",
            verdict="vulnerable",
            stages={
                "discover": {
                    "priority_score": 94,
                    "dangerous_imports": ["MmMapIoSpace", "MmGetPhysicalAddress"],
                },
                "kernel_filter": {},
                "loldrivers_filter": {},
                "decompile": {"device_on_load_path": True, "function_count": 61},
                "semgrep_scanner": {"finding_count": 3},
                "rank_by_findings": {},
            },
            findings=[
                (
                    "dz.kernel.mmmapiospace-unbounded",
                    "ERROR",
                    "caller-supplied physical address and length reach MmMapIoSpace unchecked",
                    "dispatch_ioctl.c",
                    212,
                ),
                (
                    "dz.kernel.port-io-write",
                    "ERROR",
                    "caller-supplied port and value reach an out instruction",
                    "dispatch_ioctl.c",
                    340,
                ),
                (
                    "dz.kernel.iocreatedevice-no-sddl",
                    "WARNING",
                    "IoCreateDevice with no security descriptor, so the default one applies",
                    "driver_entry.c",
                    48,
                ),
            ],
            assessment=(
                "[VULNERABLE] ExampleIo64.sys\n\n"
                "IOCTL 0x9C402088 maps an arbitrary physical page into the caller's "
                "address space and returns the mapping. Nothing bounds the address.\n"
            ),
        ),
        DemoSample(
            name="ExampleSmb.sys",
            source="C:/drivers/DP_Chipset/ExampleSmb.sys",
            verdict="vulnerable",
            stages={
                "discover": {"priority_score": 81, "dangerous_imports": ["HalSetBusDataByOffset"]},
                "kernel_filter": {},
                "loldrivers_filter": {},
                "decompile": {"device_on_load_path": True, "function_count": 34},
                "semgrep_scanner": {"finding_count": 1},
                "rank_by_findings": {},
            },
            findings=[
                (
                    "dz.kernel.pci-config-write",
                    "ERROR",
                    "bus, device and offset all come from the caller and reach a PCI config write",
                    "dispatch_ioctl.c",
                    96,
                )
            ],
            assessment=(
                "[VULNERABLE] ExampleSmb.sys\n\n"
                "The handler forwards the caller's bus and slot straight to the config "
                "space write, which reaches any device on the machine.\n"
            ),
        ),
        # decompiled and scanned, never assessed
        DemoSample(
            name="ExampleFltr64.sys",
            source="C:/drivers/DP_Touchpad/ExampleFltr64.sys",
            verdict=None,
            stages={
                "discover": {"priority_score": 55, "dangerous_imports": ["ZwMapViewOfSection"]},
                "kernel_filter": {},
                "loldrivers_filter": {},
                "decompile": {"device_on_load_path": False, "function_count": 22},
                "semgrep_scanner": {"finding_count": 1},
                "rank_by_findings": {},
            },
            findings=[
                (
                    "dz.kernel.section-map-user-handle",
                    "WARNING",
                    "a user-supplied handle is mapped without ObReferenceObjectByHandle",
                    "dispatch_ioctl.c",
                    77,
                )
            ],
        ),
        DemoSample(
            name="ExampleNic64.sys",
            source="C:/drivers/DP_LAN_Intel/ExampleNic64.sys",
            verdict="safe",
            stages={
                "discover": {"priority_score": 40, "dangerous_imports": ["MmMapIoSpace"]},
                "kernel_filter": {},
                "loldrivers_filter": {},
                "decompile": {"device_on_load_path": False, "function_count": 118},
                "semgrep_scanner": {"finding_count": 2},
                "rank_by_findings": {},
            },
            findings=[
                (
                    "dz.kernel.mmmapiospace-unbounded",
                    "ERROR",
                    "MmMapIoSpace reached from the dispatch path",
                    "dispatch_ioctl.c",
                    155,
                ),
                (
                    "dz.kernel.memcpy-user-length",
                    "WARNING",
                    "memcpy length derived from the input buffer",
                    "dispatch_ioctl.c",
                    168,
                ),
            ],
            assessment=(
                "[SAFE] ExampleNic64.sys\n\n"
                "The physical address is not the caller's: it is read from the adapter's "
                "own BAR, and the length is clamped to the mapped window.\n"
            ),
        ),
        DemoSample(
            name="ExampleCrd.sys",
            source="C:/drivers/DP_CardReader/ExampleCrd.sys",
            verdict="safe",
            stages={
                "discover": {"priority_score": 33, "dangerous_imports": ["MmMapLockedPages"]},
                "kernel_filter": {},
                "loldrivers_filter": {},
                "decompile": {"device_on_load_path": False, "function_count": 47},
                "semgrep_scanner": {"finding_count": 1},
                "rank_by_findings": {},
            },
            findings=[
                (
                    "dz.kernel.memcpy-user-length",
                    "WARNING",
                    "memcpy into a fixed buffer with a length from the request",
                    "dispatch_ioctl.c",
                    58,
                )
            ],
            assessment=(
                "[SAFE] ExampleCrd.sys\n\n"
                "The length is compared against the destination size two lines earlier "
                "and the request is failed when it does not fit.\n"
            ),
        ),
        DemoSample(
            name="ExampleBio.sys",
            source="C:/drivers/DP_Biometric/ExampleBio.sys",
            verdict="safe",
            stages={
                "discover": {"priority_score": 29, "dangerous_imports": []},
                "kernel_filter": {},
                "loldrivers_filter": {},
                "decompile": {"device_on_load_path": False, "function_count": 19},
                "semgrep_scanner": {"finding_count": 1},
                "rank_by_findings": {},
            },
            findings=[
                (
                    "dz.kernel.iocreatedevice-no-sddl",
                    "WARNING",
                    "IoCreateDevice with no security descriptor",
                    "driver_entry.c",
                    31,
                )
            ],
            assessment=(
                "[SAFE] ExampleBio.sys\n\n"
                "The device is created under a PnP node the class installer restricts, "
                "and IRP_MJ_CREATE fails for a token without the class GUID.\n"
            ),
        ),
    ],
)


DEMOS = [SOURCE_AUDIT, LOLDRIVERS]


def _check_columns(demo: Demo, cfg: ReportConfig) -> None:
    """refuse to render a column the demo data cannot fill.

    A column the pipeline declares and the demo omits renders as an empty cell,
    which is exactly the kind of quietly wrong picture a screenshot should never
    be. Adding a column to a shipped pipeline should break this script, not the
    image.
    """
    missing = []
    for column in cfg.columns:
        stage, _, key = column.partition(".")
        if not key:
            continue
        if not any(key in s.stages.get(stage, {}) for s in demo.samples):
            missing.append(column)
    if missing:
        raise SystemExit(
            f"{demo.pipeline} declares columns no demo sample provides: {', '.join(missing)}. "
            f"add the field to the demo samples' stage data, or the screenshot will show "
            f"an empty column."
        )


def build(demo: Demo, root: pathlib.Path) -> tuple[pathlib.Path, ReportConfig]:
    pipeline = load_pipeline(str(REPO_ROOT / demo.pipeline))
    cfg = ReportConfig.from_dict(pipeline.report)
    _check_columns(demo, cfg)

    work = root / "work" / pipeline.name
    shutil.rmtree(work, ignore_errors=True)
    store = StateStore(work)
    store.save_run(
        RunState(
            run_id=demo.run_id,
            pipeline=pipeline.name,
            target=demo.target,
            model=pipeline.model or "claude-code/claude-opus-5",
            status=RunStatus.COMPLETED,
        )
    )

    for i, spec in enumerate(demo.samples):
        sample_id = f"s{i:02d}"
        sample = SampleState(sample_id=sample_id, filename=spec.name, source_path=spec.source)
        for stage_name, data in spec.stages.items():
            artifacts = (
                {"findings": "findings.json"}
                if stage_name == demo.findings_stage and spec.findings
                else {}
            )
            sample.mark_stage_completed(stage_name, data=data, artifacts=artifacts)
        if spec.verdict is not None:
            sample.mark_stage_completed(
                "assess",
                data={cfg.classification_key: spec.verdict},
                artifacts={"llm_output": "assessment.md"},
            )
        store.save_sample(sample)

        sample_dir = store.sample_dir(sample_id)
        if spec.findings:
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
                        for rule, severity, message, location, line in spec.findings
                    ]
                ),
                encoding="utf-8",
            )
        if spec.assessment:
            (sample_dir / "assessment.md").write_text(spec.assessment, encoding="utf-8")

    html_path, _ = write_report(work, config=cfg)
    return html_path, cfg


if __name__ == "__main__":
    out = REPO_ROOT / ".github" / "assets"
    for demo in DEMOS:
        html, cfg = build(demo, REPO_ROOT / ".demo")
        print(f"\n{cfg.title}")
        print(f"  {html.resolve().as_uri()}")
        print(
            f"  chrome --headless=new --window-size=1400,760 --hide-scrollbars \\\n"
            f'      --screenshot="{out / demo.image}" \\\n'
            f'      "{html.resolve().as_uri()}"'
        )
