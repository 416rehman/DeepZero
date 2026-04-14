from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()


class _ShortNameFormatter(logging.Formatter):
    # strips deepzero prefix to keep log lines short and scannable

    _PREFIX_MAP = {
        "deepzero.runner": "engine",
        "deepzero.pipeline": "pipeline",
    }

    def format(self, record: logging.LogRecord) -> str:
        name = record.name
        short = self._PREFIX_MAP.get(name)
        if short is None:
            if name.startswith("deepzero.tool."):
                short = name[len("deepzero.tool."):]
            elif name.startswith("deepzero."):
                short = name[len("deepzero."):]
            else:
                short = name
        
        # force silence third-party stacktraces completely
        if not name.startswith("deepzero."):
            record.exc_info = None
            record.exc_text = None
            
        record.msg = f"{short:>20} | {record.msg}"
        return super().format(record)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = RichHandler(
        console=console, rich_tracebacks=verbose, show_path=False,
        show_level=False, show_time=True,
    )
    handler.setFormatter(_ShortNameFormatter("%(message)s"))
    logging.basicConfig(level=level, handlers=[handler])
    if not verbose:
        for lib in ("httpx", "httpcore", "urllib3", "litellm", "openai"):
            logging.getLogger(lib).setLevel(logging.WARNING)

def _load_env() -> None:
    # load .env if python-dotenv is installed — not a hard dependency
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _build_runner(pipeline_def: Any) -> tuple[Any, Any]:
    # shared setup for run/resume — builds PipelineRunner and optional LLM provider
    from deepzero.engine.runner import PipelineRunner
    from deepzero.engine.stage import GlobalConfig
    from deepzero.engine.state import StateStore
    from deepzero.providers.llm import LLMProvider

    llm = LLMProvider(pipeline_def.model) if pipeline_def.model else None

    global_config: GlobalConfig = {
        "settings": pipeline_def.settings,
        "tools": pipeline_def.tools,
        "knowledge": pipeline_def.knowledge,
        "model": pipeline_def.model,
    }

    state_store = StateStore(pipeline_def.work_dir)

    runner = PipelineRunner(
        ingest=pipeline_def.ingest_tool,
        stages=pipeline_def.stages,
        state_store=state_store,
        pipeline_dir=pipeline_def.pipeline_dir,
        global_config=global_config,
        llm=llm,
        default_max_workers=pipeline_def.max_workers,
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
def run(target: str, pipeline: str, model: str | None, work_dir: str | None, verbose: bool):
    """run a pipeline against a target file or directory"""
    _setup_logging(verbose)

    _load_env()

    from deepzero.engine.pipeline import load_pipeline
    from deepzero.engine.state import RunState, StateStore

    # ensure built-in stages are registered
    import deepzero.stages  # noqa: F401

    target_path = Path(target).resolve()
    console.print(f"\n[bold cyan]deepzero[/] - running pipeline [bold]{pipeline}[/]")
    console.print(f"  target: {target_path}")

    pipeline_def = load_pipeline(pipeline, model_override=model, work_dir_override=work_dir)
    console.print(f"  pipeline: {pipeline_def.name} ({len(pipeline_def.stage_specs)} stages)")
    console.print(f"  stages: {' -> '.join(pipeline_def.stage_names)}")

    runner, llm = _build_runner(pipeline_def)
    if llm:
        console.print(f"  model: {pipeline_def.model}")

    # initialize state store
    state_store = StateStore(pipeline_def.work_dir)
    state_store.save_pipeline_snapshot(pipeline_def.raw_yaml)

    # create run state
    run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}"
    run_state = RunState(
        run_id=run_id,
        pipeline=pipeline_def.name,
        target=str(target_path),
        model=pipeline_def.model,
    )

    console.print(f"  work_dir: {pipeline_def.work_dir}")
    console.print()

    run_state = runner.run(target_path, run_state)

    # print summary
    console.print()
    if run_state.status == "completed":
        console.print("[bold green]pipeline completed[/]")
    elif run_state.status == "interrupted":
        console.print("[bold yellow]pipeline interrupted - use 'deepzero resume' to continue[/]")
    else:
        console.print(f"[bold red]pipeline failed: {run_state.stats.get('error', 'unknown')}[/]")

    _print_stats(run_state)


@main.command()
@click.option("--pipeline", "-p", required=True, help="pipeline name or path (for tool resolution)")
@click.option("--model", "-m", default=None, help="llm model override (e.g. openai/gpt-4o)")
@click.option("--verbose", "-v", is_flag=True, help="verbose logging")
def resume(pipeline: str, model: str | None, verbose: bool):
    """resume an interrupted pipeline run"""
    _setup_logging(verbose)

    _load_env()

    import deepzero.stages  # noqa: F401
    from deepzero.engine.pipeline import load_pipeline
    from deepzero.engine.state import StateStore

    pipeline_def = load_pipeline(pipeline)

    # allow model override on resume
    if model:
        pipeline_def.model = model

    state_store = StateStore(pipeline_def.work_dir)
    run_state = state_store.load_run()

    if run_state is None:
        console.print("[red]no run state found in work directory[/]")
        raise SystemExit(1)

    console.print(f"[bold cyan]resuming[/] pipeline '{run_state.pipeline}' (run {run_state.run_id})")
    console.print(f"  status: {run_state.status}")
    _print_stats(run_state)

    runner, _ = _build_runner(pipeline_def)

    run_state.status = "running"
    run_state = runner.run(Path(run_state.target), run_state)

    console.print()
    if run_state.status == "completed":
        console.print("[bold green]pipeline completed[/]")
    else:
        console.print(f"[bold yellow]pipeline status: {run_state.status}[/]")
    _print_stats(run_state)


@main.command()
@click.option("--pipeline", "-p", default=None, help="pipeline name")
@click.option("--work-dir", "-w", default=None, help="work directory")
@click.option("--verbose", "-v", is_flag=True, help="verbose logging")
def status(pipeline: str | None, work_dir: str | None, verbose: bool):
    """show current pipeline run status"""
    from deepzero.engine.state import StateStore

    if work_dir:
        work_path = Path(work_dir)
    elif pipeline:
        import deepzero.stages  # noqa: F401
        from deepzero.engine.pipeline import load_pipeline
        _setup_logging(False)
        pipeline_def = load_pipeline(pipeline)
        work_path = pipeline_def.work_dir
    else:
        console.print("[red]specify --pipeline or --work-dir[/]")
        raise SystemExit(1)

    state_store = StateStore(work_path)
    run_state = state_store.load_run()

    if run_state is None:
        console.print("[yellow]no run found[/]")
        raise SystemExit(1)

    color = {"completed": "green", "running": "cyan", "interrupted": "yellow", "failed": "red"}.get(
        run_state.status, "white"
    )
    console.print(f"[bold {color}]{run_state.pipeline}[/] - {run_state.status}")
    console.print(f"  run_id: {run_state.run_id}")
    console.print(f"  target: {run_state.target}")
    console.print(f"  model: {run_state.model}")
    console.print(f"  started: {run_state.started_at}")
    if run_state.completed_at:
        console.print(f"  completed: {run_state.completed_at}")

    _print_stats(run_state)

    # show manifest summary
    manifest = state_store.load_manifest()
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


@main.command("list-tools")
def list_tools():
    """list all registered tool types"""
    import deepzero.stages  # noqa: F401
    from deepzero.engine.stage import get_registered_tools

    tools = get_registered_tools()

    table = Table(title="registered tools")
    table.add_column("name", style="cyan")
    table.add_column("type", style="green")
    table.add_column("class", style="dim")

    for name, cls in sorted(tools.items()):
        tool_type = getattr(cls, "tool_type", "unknown")
        table.add_row(name, str(tool_type.value if hasattr(tool_type, "value") else tool_type), f"{cls.__module__}.{cls.__name__}")

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
    tool: file_discovery
    config:
      extensions: ["*"]
      recursive: true

  # add your stages here
  # bare name = built-in tool, path/with/slash = project tool in tools/ dir
  # tool types: map (1:1), reduce (N:1 ranking), batch (N:batch external)
"""

    (pipeline_dir / "pipeline.yaml").write_text(yaml_content, encoding="utf-8")

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

    from deepzero.providers.llm import LLMProvider
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
            console.print(f"[red]error: {e}[/]")


@main.command()
@click.option("--host", default="127.0.0.1", help="bind host (use 0.0.0.0 for all interfaces)")
@click.option("--port", default=8420, type=int, help="bind port")
@click.option("--work-dir", "-w", default="work", help="work directory")
def serve(host: str, port: int, work_dir: str):
    """start the rest api server"""
    if host not in ("127.0.0.1", "localhost", "::1"):
        console.print(f"[bold yellow]⚠ binding to {host} — server will be accessible on the network[/]")
    console.print(f"[bold cyan]deepzero serve[/] - http://{host}:{port}")
    console.print(f"  work_dir: {work_dir}")

    from deepzero.api.server import create_app

    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn required: pip install deepzero[serve][/]")
        raise SystemExit(1)

    app = create_app(Path(work_dir))
    uvicorn.run(app, host=host, port=port)


def _print_stats(run_state) -> None:
    per_stage = run_state.stats.get("per_stage", {})
    if not per_stage:
        discovered = run_state.stats.get("discovered", 0)
        if discovered:
            console.print(f"  discovered: {discovered}")
        return

    table = Table(show_header=True)
    table.add_column("stage", style="cyan")
    table.add_column("completed", style="green", justify="right")
    table.add_column("skipped", style="yellow", justify="right")
    table.add_column("failed", style="red", justify="right")

    for stage_name, counts in per_stage.items():
        table.add_row(
            stage_name,
            str(counts.get("completed", 0)),
            str(counts.get("skipped", 0)),
            str(counts.get("failed", 0)),
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
