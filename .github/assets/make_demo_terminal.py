"""Regenerate the terminal dashboard image used in the README.

The numbers are invented, for the same reason the report screenshots are: an
image of a real corpus dates the moment that corpus changes. Everything else is
real. The stage names are read from the shipped pipeline, and the table is built
by the dashboard the runner actually uses, so the image cannot show a column
layout or a stage list the code no longer produces.

    python .github/assets/make_demo_terminal.py

Writes .github/terminal.svg.
"""

from __future__ import annotations

import io
import pathlib

from rich.console import Console

import deepzero.stages  # noqa: F401  registers the built-in processors by name
from deepzero.engine.pipeline import load_pipeline
from deepzero.engine.ui import PipelineDashboard

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PIPELINE = "pipelines/loldrivers/pipeline.yaml"
OUT = REPO_ROOT / ".github" / "terminal.svg"

# a mid-run snapshot: the cheap stages have finished, the expensive one is part
# way through, and the rest have not started. Keyed by stage name so a renamed or
# reordered stage is caught below rather than silently dropped from the picture.
#
#   name: (input, passed, filtered, failed, timed out, seconds)
DONE = {
    "discover": (12595, 12595, 0, 0, 0, 16.2),
    "kernel_filter": (12595, 7158, 5437, 0, 0, 45.2),
    "loldrivers_filter": (7158, 7148, 10, 0, 0, 31.3),
}
RUNNING = ("decompile", 7148, 3002, 0, 15, 4, 0.62)

# how long the running stage is meant to have been going. Without this the frame
# renders 62% complete in 0:00:00 with no estimate, which is the one part of the
# picture that would be visibly untrue.
ELAPSED_S = 755.0


def _age_the_progress_bar(dash: PipelineDashboard, seconds: float) -> None:
    """Backdate the live task so the elapsed and remaining columns read sensibly.

    Reaches into rich's Task to do it, because elapsed time is measured from a
    monotonic clock a caller cannot set. Both attributes are checked first: a rich
    release that renames them should stop this script rather than quietly emit an
    image claiming a stage did most of its work instantly.
    """
    progress = getattr(dash, "_progress", None)
    tasks = getattr(progress, "tasks", None)
    if not tasks:
        raise SystemExit("no progress task to age; the dashboard's internals have moved")
    task = tasks[0]
    if not hasattr(task, "start_time") or not hasattr(task, "_progress"):
        raise SystemExit("rich's Task no longer exposes start_time/_progress; update this script")

    now = progress.get_time()
    task.start_time = now - seconds
    # speed, and therefore the estimate, is read off these samples rather than off
    # the start time, so one at each end of the window is the minimum that works
    sample = type(task._progress[0]) if task._progress else None
    if sample is None:
        raise SystemExit("rich's Task recorded no progress samples; update this script")
    task._progress.clear()
    task._progress.append(sample(now - seconds, 0.0))
    task._progress.append(sample(now, float(task.completed)))


def build() -> str:
    pipeline = load_pipeline(str(REPO_ROOT / PIPELINE))
    # the same list the runner hands the dashboard: the ingest stage, then the rest
    stage_names = [spec.name for spec in pipeline.stage_specs]

    named = set(DONE) | {RUNNING[0]}
    unknown = named - set(stage_names)
    if unknown:
        raise SystemExit(
            f"{PIPELINE} has no stage(s) named {', '.join(sorted(unknown))}. "
            f"its stages are: {', '.join(stage_names)}. update this script rather "
            f"than shipping an image of a pipeline that does not exist."
        )

    # rendered into a buffer rather than to stdout: the frame is only wanted as
    # SVG, and a real Windows console cannot encode the glyphs the table uses
    console = Console(record=True, force_terminal=True, file=io.StringIO(), width=104)
    dash = PipelineDashboard(stage_names, console=console)
    dash.print_header(
        name=pipeline.name,
        target="C:/drivers",
        model=pipeline.model or "",
        # runs are scoped per corpus, so the path carries the corpus key
        work_dir=f"work/{pipeline.name}/drivers-1a2b3c4d",
    )

    for name, (inp, passed, filtered, failed, timed_out, elapsed) in DONE.items():
        dash.stage_start(name, inp)
        dash.stage_done(
            name,
            passed=passed,
            filtered=filtered,
            failed=failed,
            timed_out=timed_out,
            elapsed_s=elapsed,
        )

    name, inp, passed, filtered, failed, timed_out, fraction = RUNNING
    dash.stage_start(
        name,
        inp,
        passed=passed,
        filtered=filtered,
        failed=failed,
        timed_out=timed_out,
    )
    dash.stage_update(name, advance=int(inp * fraction), description="ExampleIo64.sys")
    _age_the_progress_bar(dash, seconds=ELAPSED_S)

    # the dashboard pins this renderable to the bottom of a live terminal, which
    # cannot be recorded off a non-tty. Printing it once produces the same frame.
    if not hasattr(dash, "_build_renderable"):
        raise SystemExit(
            "PipelineDashboard no longer exposes _build_renderable. this script "
            "renders one frame of the live dashboard and needs a replacement hook."
        )
    console.print(dash._build_renderable())
    console.print()

    return console.export_svg(title="deepzero", theme=None)


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
