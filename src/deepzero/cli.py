from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from types import MappingProxyType
from typing import Any

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.table import Table

from deepzero.engine.types import RunStatus


def _ensure_utf8_streams() -> None:
    # deepzero prints unicode status glyphs (checkmarks, arrows, box drawing).
    # on a legacy windows console or when stdout is redirected to a file, the
    # default cp1252 encoding raises UnicodeEncodeError and crashes the run.
    # force utf-8 with a non-fatal error handler before any Console is built.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            # stream is not a reconfigurable TextIOWrapper (e.g. already wrapped)
            pass


_ensure_utf8_streams()
console = Console()


# short name lookups for log formatting
_LOG_PREFIX_MAP: MappingProxyType[str, str] = MappingProxyType(
    {
        "deepzero.runner": "engine",
        "deepzero.pipeline": "pipeline",
    }
)

_LOG_COLORS: tuple[str, ...] = (
    "cyan",
    "magenta",
    "green",
    "yellow",
    "bright_cyan",
    "bright_magenta",
    "bright_green",
    "bright_yellow",
)


class _ShortNameFormatter(logging.Formatter):
    # strips deepzero prefix to keep log lines short and scannable

    def format(self, record: logging.LogRecord) -> str:
        name = record.name
        short = _LOG_PREFIX_MAP.get(name)
        if short is None:
            if name.startswith("deepzero.processor."):
                short = name[len("deepzero.processor.") :]
            elif name.startswith("deepzero."):
                short = name[len("deepzero.") :]
            else:
                short = name

        # force silence third-party stacktraces completely
        if not name.startswith("deepzero."):
            record.exc_info = None
            record.exc_text = None

        msg = super().format(record)

        msg_escaped = escape(msg)

        import zlib

        color = _LOG_COLORS[zlib.crc32(short.encode("utf-8")) % len(_LOG_COLORS)]

        # format dynamically and override the final payload that RichHandler receives
        return f"[{color}]\\[{short}][/{color}] {msg_escaped}"


def _latest_run_dir(base: Path) -> Path | None:
    """Pick the most recent corpus run directory under a pipeline's base dir.

    Runs are namespaced per corpus (``<base>/<corpus-key>/``), so ``status`` and
    ``report`` with only ``--pipeline`` resolve to the newest run. A ``run.json``
    directly in ``base`` (e.g. ``--work-dir`` pointed straight at a run) also works.
    """
    if not base.exists():
        return None
    runs = [d for d in base.iterdir() if d.is_dir() and (d / "run.json").exists()]
    if runs:
        return max(runs, key=lambda d: (d / "run.json").stat().st_mtime)
    return base if (base / "run.json").exists() else None


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = RichHandler(
        console=console,
        rich_tracebacks=verbose,
        show_path=False,
        show_level=False,
        show_time=True,
        log_time_format="%H:%M:%S",
        markup=True,
    )
    # the formatter now handles the full string construction and markup tagging
    handler.setFormatter(_ShortNameFormatter("%(message)s"))
    logging.basicConfig(level=level, handlers=[handler])
    if not verbose:
        for lib in ("httpx", "httpcore", "urllib3", "litellm", "openai"):
            logging.getLogger(lib).setLevel(logging.WARNING)


def _load_env() -> None:
    import importlib.util

    if importlib.util.find_spec("dotenv"):
        from dotenv import load_dotenv

        load_dotenv()


def _build_runner(pipeline_def: Any, dashboard: Any = None) -> tuple[Any, Any]:
    # shared setup for run/resume - builds PipelineRunner and optional LLM provider
    from deepzero.engine.llm import LLMProvider
    from deepzero.engine.runner import PipelineRunner
    from deepzero.engine.state import StateStore

    llm = LLMProvider(pipeline_def.model) if pipeline_def.model else None

    state_store = StateStore(pipeline_def.work_dir)

    runner = PipelineRunner(
        ingest=pipeline_def.ingest_processor,
        stages=pipeline_def.stages,
        state_store=state_store,
        pipeline_dir=pipeline_def.pipeline_dir,
        global_config=pipeline_def.to_global_config(),
        llm=llm,
        default_max_workers=pipeline_def.max_workers,
        console=console,
        dashboard=dashboard,
    )

    return runner, llm


@click.group()
@click.version_option(package_name="deepzero")
@click.pass_context
def main(ctx: click.Context):
    """deepzero - configurable, data-driven binary analysis pipeline"""
    ctx.ensure_object(dict)


@main.command()
@click.argument("target", type=click.Path(exists=True))
@click.option("--pipeline", "-p", required=True, help="pipeline name or path")
@click.option("--model", "-m", default=None, help="llm model override (e.g. openai/gpt-4o)")
@click.option("--work-dir", "-w", default=None, help="work directory override")
@click.option("--verbose", "-v", is_flag=True, help="verbose logging")
@click.option("--clean", is_flag=True, help="permanently delete previous run data and start fresh")
@click.option(
    "--preflight",
    is_flag=True,
    help="verify the LLM backend is authenticated before running (makes one tiny call)",
)
def run(
    target: str,
    pipeline: str,
    model: str | None,
    work_dir: str | None,
    verbose: bool,
    clean: bool,
    preflight: bool,
):
    """run a pipeline against a target file or directory (resumes automatically)"""
    _setup_logging(verbose)

    _load_env()

    # ensure built-in stages are registered
    import deepzero.stages  # noqa: F401
    from deepzero.engine.pipeline import load_pipeline
    from deepzero.engine.report import write_report
    from deepzero.engine.state import RunState, StateStore

    log_report = logging.getLogger("deepzero.report")
    target_path = Path(target).resolve()

    try:
        pipeline_def = load_pipeline(pipeline, model_override=model, work_dir_override=work_dir)
    except ValueError as e:
        console.print(f"[bold red]X ERROR[/]: {e}")
        raise SystemExit(1)

    # scope the run to this corpus so different targets through the same pipeline
    # get isolated, independently resumable work directories under one root.
    pipeline_def.bind_corpus(target_path)

    import os
    import shutil
    import threading

    if clean and pipeline_def.work_dir.exists():
        console.print("[yellow]⚠ purging previous run data...[/]")
        trash_dir = pipeline_def.work_dir.with_name(
            f"trash_{pipeline_def.work_dir.name}_{int(time.time())}"
        )
        try:
            os.rename(pipeline_def.work_dir, trash_dir)
        except OSError as e:
            console.print("rename failed: {}".format(e))
            console.print("purging by rmtree...")
            shutil.rmtree(pipeline_def.work_dir, ignore_errors=True)

    # launch asynchronous garbage collection for all orphaned trash directories
    def _purge_trash() -> None:
        if not pipeline_def.work_dir.parent.exists():
            return
        for child in pipeline_def.work_dir.parent.iterdir():
            if child.is_dir() and child.name.startswith("trash_"):
                shutil.rmtree(child, ignore_errors=True)

    threading.Thread(target=_purge_trash, daemon=True).start()

    from deepzero.engine.ui import PipelineDashboard

    state_store = StateStore(pipeline_def.work_dir)
    existing_run = state_store.load_run()

    is_resume = existing_run is not None

    dashboard = PipelineDashboard(pipeline_def.stage_names, console=console)
    header_name = (
        f"{pipeline_def.name} (resuming run {existing_run.run_id})"
        if is_resume
        else pipeline_def.name
    )

    dashboard.print_header(
        name=header_name,
        target=str(target_path),
        model=pipeline_def.model,
        work_dir=str(pipeline_def.work_dir),
    )

    runner, llm = _build_runner(pipeline_def, dashboard=dashboard)

    if preflight and llm is not None:
        console.print("[dim]preflight: checking LLM backend authentication...[/]")
        problem = llm.check_auth()
        if problem:
            console.print(
                f"[bold red]X ERROR[/]: LLM backend '{pipeline_def.model}' is not ready: {problem}"
            )
            raise SystemExit(1)
        console.print("[green]\\[ok][/] LLM backend authenticated")

    if is_resume:
        run_state = existing_run
        run_state.status = RunStatus.RUNNING
        # the pipeline's model may have changed since the run was created; record
        # what this resumed run will actually call so status/reports don't lie
        if run_state.model != pipeline_def.model:
            log_msg = f"model changed since last run: {run_state.model or '(unset)'} -> {pipeline_def.model}"
            console.print(f"[yellow]![/] {log_msg}")
            run_state.model = pipeline_def.model
    else:
        # initialize fresh state
        state_store.save_pipeline_snapshot(pipeline_def.raw_yaml)
        run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}"
        run_state = RunState(
            run_id=run_id,
            pipeline=pipeline_def.name,
            target=str(target_path),
            model=pipeline_def.model,
        )

    # a live report the user can open straight away and watch fill in. it is
    # rebuilt when results actually land rather than on a timer, and rate
    # limited so a fast stage cannot spend the run's time writing html
    report_dir = pipeline_def.work_dir / "report"
    report_index = report_dir / "index.html"
    last_written = [0.0]

    def _refresh_report(force: bool = False) -> None:
        if not force and time.monotonic() - last_written[0] < 15:
            return
        try:
            write_report(pipeline_def.work_dir, report_dir, config=pipeline_def.report)
            last_written[0] = time.monotonic()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log_report.debug("could not refresh the report: %s", exc)

    _refresh_report(force=True)
    console.print(f" report   [bold]{report_index.resolve().as_uri()}[/]")
    console.print(" [dim]open it now - it updates itself as results land[/]\n")

    runner.progress_hook = _refresh_report
    try:
        run_state = runner.run(target_path, run_state)
    finally:
        _refresh_report(force=True)  # settle the final state, no reload banner
        console.print(f"\n report   [bold]{report_index.resolve().as_uri()}[/]")


@main.command()
@click.option("--pipeline", "-p", default=None, help="pipeline name or path")
@click.option("--work-dir", "-w", default=None, help="work directory (overrides --pipeline)")
@click.option("--out", "-o", default=None, help="output directory (default <work_dir>/report)")
@click.option("--open", "open_browser", is_flag=True, help="open the report when finished")
@click.option("--verbose", "-v", is_flag=True, help="verbose logging")
def report(
    pipeline: str | None, work_dir: str | None, out: str | None, open_browser: bool, verbose: bool
):
    """build a browsable HTML report from a run's results (safe mid-run)"""
    _setup_logging(verbose)

    from deepzero.engine.report import write_report

    report_cfg: dict = {}
    if work_dir:
        work_path = Path(work_dir)
    elif pipeline:
        import deepzero.stages  # noqa: F401
        from deepzero.engine.pipeline import load_pipeline

        _load_env()
        try:
            pipeline_def = load_pipeline(pipeline)
        except ValueError as e:
            console.print(f"[bold red]X ERROR[/]: {e}")
            raise SystemExit(1)
        work_path = _latest_run_dir(pipeline_def.base_work_dir)
        if work_path is None:
            console.print(f"[bold red]X ERROR[/]: no runs found under {pipeline_def.base_work_dir}")
            raise SystemExit(1)
        report_cfg = pipeline_def.report
    else:
        console.print("[bold red]X ERROR[/]: pass --pipeline or --work-dir")
        raise SystemExit(1)

    if not work_path.exists():
        console.print(f"[bold red]X ERROR[/]: work directory does not exist: {work_path}")
        raise SystemExit(1)

    html_path, json_path = write_report(work_path, Path(out) if out else None, config=report_cfg)
    console.print(f"[green]\\[ok][/] report written to [bold]{html_path}[/]")
    console.print(f"      machine-readable copy: {json_path}")

    if open_browser:
        import webbrowser

        webbrowser.open(html_path.resolve().as_uri())


@main.command()
@click.option("--pipeline", "-p", default=None, help="pipeline name")
@click.option("--work-dir", "-w", default=None, help="work directory")
@click.option("--verbose", "-v", is_flag=True, help="verbose logging")
def status(pipeline: str | None, work_dir: str | None, verbose: bool):
    """show current pipeline run status"""
    from deepzero.engine.state import StateStore

    _setup_logging(verbose)
    if work_dir:
        work_path = Path(work_dir)
    elif pipeline:
        import deepzero.stages  # noqa: F401
        from deepzero.engine.pipeline import load_pipeline

        _load_env()
        try:
            pipeline_def = load_pipeline(pipeline)
        except ValueError as e:
            console.print(f"[bold red]X ERROR[/]: {e}")
            raise SystemExit(1)

        work_path = _latest_run_dir(pipeline_def.base_work_dir)
        if work_path is None:
            console.print(f"[yellow]no runs found under {pipeline_def.base_work_dir}[/]")
            raise SystemExit(1)
    else:
        console.print("[red]specify --pipeline or --work-dir[/]")
        raise SystemExit(1)

    state_store = StateStore(work_path)
    run_state = state_store.load_run()

    if run_state is None:
        console.print("[yellow]no run found[/]")
        raise SystemExit(1)

    color = {
        "completed": "green",
        "running": "cyan",
        "interrupted": "yellow",
        "failed": "red",
    }.get(run_state.status, "white")
    console.print(f"[bold {color}]{run_state.pipeline}[/] - {run_state.status}")
    console.print(f"  run_id: {run_state.run_id}")
    console.print(f"  target: {run_state.target}")
    console.print(f"  model: {run_state.model}")
    console.print(f"  started: {run_state.started_at}")
    if run_state.completed_at:
        console.print(f"  completed: {run_state.completed_at}")

    manifest = state_store.load_manifest()
    _print_stats(run_state, manifest)

    # show manifest summary
    if manifest:
        verdicts: dict[str, int] = {}
        for entry in manifest:
            v = entry.get("verdict", "pending")
            verdicts[v] = verdicts.get(v, 0) + 1

        console.print(f"\n  [bold]samples[/]: {len(manifest)}")
        for v, count in sorted(verdicts.items()):
            console.print(f"    {v}: {count}")


@main.command()
@click.argument("pipeline_ref")
def validate(pipeline_ref: str):
    """validate a pipeline definition"""
    _setup_logging(False)
    _load_env()

    import deepzero.stages  # noqa: F401
    from deepzero.engine.pipeline import validate_pipeline

    console.print(f"validating pipeline: {pipeline_ref}\n")
    warnings = validate_pipeline(pipeline_ref)

    for w in warnings:
        if w.startswith("ERROR"):
            console.print(f"  [red]X[/] {w}")
        elif "valid" in w.lower():
            console.print(f"  [green]OK[/] {w}")
        else:
            console.print(f"  [yellow]![/] {w}")


@main.command("list-processors")
def list_processors():
    """list all registered processor types"""
    import deepzero.stages  # noqa: F401
    from deepzero.engine.stage import get_registered_processors

    processors = get_registered_processors()

    table = Table(title="registered processors")
    table.add_column("name", style="cyan")
    table.add_column("type", style="green")
    table.add_column("class", style="dim")

    for name, cls in sorted(processors.items()):
        ptype = getattr(cls, "processor_type", "unknown")
        table.add_row(
            name,
            str(ptype.value if hasattr(ptype, "value") else ptype),
            f"{cls.__module__}.{cls.__name__}",
        )

    console.print(table)


@main.command()
@click.argument("name")
def init(name: str):
    """scaffold a new pipeline directory"""
    pipeline_dir = Path.cwd() / "pipelines" / name

    if pipeline_dir.exists():
        console.print(f"[red]pipeline directory already exists: {pipeline_dir}[/]")
        return

    pipeline_dir.mkdir(parents=True)

    yaml_content = f"""name: {name}
description: custom analysis pipeline

# model: openai/gpt-4o

settings:
  work_dir: work
  max_workers: 4

stages:
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]
      recursive: true

  # add your stages here
  # bare name = built-in processor, path/with/slash = external processor in processors/ dir
  # processor types: map (1:1), reduce (N:1 ranking), batch (N:batch external)
"""

    target_path_yaml = pipeline_dir / "pipeline.yaml"
    target_path_yaml.write_text(yaml_content, encoding="utf-8")

    console.print(f"[green]pipeline scaffolded at {pipeline_dir}[/]")
    console.print(f"  edit {pipeline_dir / 'pipeline.yaml'} to configure your pipeline")


@main.command()
@click.option("--model", "-m", default="openai/gpt-4o", help="llm model for interactive mode")
@click.option("--work-dir", "-w", default="work", help="work directory for context")
@click.option("--verbose", "-v", is_flag=True, help="verbose logging")
def interactive(model: str, work_dir: str, verbose: bool):
    """interactive analysis repl with llm-backed conversation"""
    _setup_logging(verbose)

    _load_env()

    from deepzero.engine.llm import LLMProvider
    from deepzero.engine.state import StateStore

    console.print(f"[bold cyan]deepzero interactive[/] - model: {model}")
    console.print("type /help for commands, /quit to exit\n")

    llm = LLMProvider(model)
    state_store = StateStore(Path(work_dir))
    history: list[dict[str, str]] = []

    sys_prompt = _build_interactive_system_prompt(state_store)
    history.append({"role": "system", "content": sys_prompt})

    while True:
        try:
            user_input = console.input("[bold green]you>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]goodbye[/]")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            break

        if user_input == "/help":
            console.print("  /status  - show pipeline run status")
            console.print("  /findings [filter] - list findings")
            console.print("  /clear   - clear conversation history")
            console.print("  /quit    - exit")
            continue

        if user_input == "/status":
            run_state = state_store.load_run()
            if run_state:
                console.print(f"  pipeline: {run_state.pipeline}, status: {run_state.status}")
                _print_stats(run_state)
            else:
                console.print("  [dim]no run data found[/]")
            continue

        if user_input == "/clear":
            history = [history[0]]
            console.print("  [dim]history cleared[/]")
            continue

        history.append({"role": "user", "content": user_input})

        try:
            response = llm.complete(history)
            history.append({"role": "assistant", "content": response})
            console.print(f"\n[bold cyan]deepzero>[/] {response}\n")
        except Exception as e:
            console.print(f"[red]llm error ({type(e).__name__}): {e}[/]")


@main.command()
@click.option("--host", default="127.0.0.1", help="bind host (use 0.0.0.0 for all interfaces)")
@click.option("--port", default=8420, type=int, help="bind port")
@click.option("--work-dir", "-w", default="work", help="work directory")
def serve(host: str, port: int, work_dir: str):
    """start the rest api server"""
    if host not in ("127.0.0.1", "localhost", "::1"):
        console.print(
            f"[bold yellow]⚠ binding to {host} - server will be accessible on the network[/]"
        )
    console.print(f"[bold cyan]deepzero serve[/] - http://{host}:{port}")
    console.print(f"  work_dir: {work_dir}")

    _load_env()

    from deepzero.api.server import create_app

    try:
        import uvicorn
    except ImportError as exc:
        console.print("[red]uvicorn required: pip install deepzero[serve][/]")
        raise SystemExit(1) from exc

    app = create_app(Path(work_dir))
    uvicorn.run(app, host=host, port=port)


def _print_stats(run_state, manifest: list[dict[str, Any]] | None = None) -> None:
    # `manifest` is accepted for caller compatibility, but current manifest
    # entries do not persist per-stage history, so stage statistics must come
    # from the run state's cached per-stage counters.
    _ = manifest
    per_stage: dict[str, dict[str, int]] = dict(run_state.stats.get("per_stage", {}))

    if not run_state.stages:
        discovered = run_state.stats.get("discovered", 0)
        if discovered:
            console.print(f"  discovered: {discovered}")
        return

    table = Table(show_header=True)
    table.add_column("stage", style="cyan")
    table.add_column("completed", style="green", justify="right")
    table.add_column("filtered", style="yellow", justify="right")
    table.add_column("failed", style="red", justify="right")

    for i, stage_name in enumerate(run_state.stages):
        if i == 0:
            # first stage is always ingest, stats are held in discovered
            discovered = run_state.stats.get("discovered", 0)
            table.add_row(
                stage_name,
                str(discovered) if discovered else "[dim white]·[/]",
                "[dim white]·[/]",
                "[dim white]·[/]",
            )
        else:
            counts = per_stage.get(stage_name, {})
            if not counts:
                # stage completely unstarted (force dim white to strip column colors)
                table.add_row(
                    f"[dim white]◦ {stage_name}[/]",
                    "[dim white]·[/]",
                    "[dim white]·[/]",
                    "[dim white]·[/]",
                )
            else:
                p = counts.get("completed", 0)
                f = counts.get("filtered", 0)
                err = counts.get("failed", 0)
                table.add_row(
                    stage_name,
                    str(p) if p else "[dim white]·[/]",
                    str(f) if f else "[dim white]·[/]",
                    str(err) if err else "[dim white]·[/]",
                )

    console.print(table)


def _build_interactive_system_prompt(state_store) -> str:
    prompt_parts = [
        "you are deepzero, an expert binary analysis assistant. "
        "you help users understand the results of automated analysis pipelines.",
    ]

    run_state = state_store.load_run()
    if run_state:
        prompt_parts.append(
            f"\ncurrent pipeline run: {run_state.pipeline} "
            f"(status: {run_state.status}, target: {run_state.target})"
        )

        manifest = state_store.load_manifest()
        if manifest:
            active = [e for e in manifest if e.get("verdict") in ("active", "completed")]
            prompt_parts.append(f"\ntotal samples: {len(manifest)}")
            if active:
                prompt_parts.append(f"active/completed: {len(active)}")
                for e in active[:10]:
                    prompt_parts.append(f"  - {e.get('filename', '?')} ({e.get('sample_id', '?')})")

    return "\n".join(prompt_parts)
