from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

# glyph constants for stage flow visualization
_GLYPH_PENDING = "◦"
_GLYPH_RUNNING = "▸"
_GLYPH_DONE = "✓"
_GLYPH_FAILED = "✗"
_GLYPH_SKIPPED = "–"
_ARROW = " → "


class StageState:
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageInfo:
    name: str
    state: str = StageState.PENDING
    input_count: int = 0
    passed: int = 0
    filtered: int = 0
    failed: int = 0
    elapsed_s: float = 0.0
    is_ingest: bool = False
    is_fully_cached: bool = False


class PipelineDashboard:
    # live terminal dashboard for pipeline execution
    # pins a stage flow + stats table at the bottom of the terminal
    # log output from the same console scrolls above it

    def __init__(self, stage_names: list[str], console: Console | None = None):
        self._console = console or Console()
        self._stages: dict[str, StageInfo] = {}
        self._stage_order: list[str] = list(stage_names)

        for name in stage_names:
            self._stages[name] = StageInfo(name=name)

        # first stage is always ingest
        if stage_names:
            self._stages[stage_names[0]].is_ingest = True

        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self._console,
            transient=True,
        )
        self._progress_task_id: int | None = None
        self._active_stage: str | None = None
        self._live: Live | None = None

    @property
    def console(self) -> Console:
        return self._console

    def print_header(
        self,
        name: str,
        target: str,
        model: str = "",
        work_dir: str = "",
    ) -> None:
        self._console.print()
        self._console.print(f" [bold cyan]deepzero[/] [dim]-[/] [bold]{name}[/]")
        self._console.print(f" [dim]target[/]   {target}")
        if model:
            self._console.print(f" [dim]model[/]    {model}")
        if work_dir:
            self._console.print(f" [dim]work[/]     {work_dir}")
        self._console.print()

    def start(self) -> None:
        self._live = Live(
            get_renderable=self._build_renderable,
            console=self._console,
            refresh_per_second=10,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    def stage_start(
        self,
        name: str,
        input_count: int,
        passed: int = 0,
        filtered: int = 0,
        failed: int = 0,
        is_fully_cached: bool = False,
    ) -> None:
        info = self._stages.get(name)
        if not info:
            return
        info.state = StageState.RUNNING
        info.input_count = input_count
        info.passed = passed
        info.filtered = filtered
        info.failed = failed
        info.is_fully_cached = is_fully_cached
        self._active_stage = name

        # reset progress bar for this stage
        if self._progress_task_id is not None:
            self._progress.remove_task(self._progress_task_id)
            self._progress_task_id = None

        total_val = input_count if input_count > 0 else None
        self._progress_task_id = self._progress.add_task(f"[cyan]{name}[/]", total=total_val)

    def stage_update(
        self,
        name: str,
        advance: int = 0,
        total: int | None = None,
        description: str | None = None,
        passed: int = 0,
        filtered: int = 0,
        failed: int = 0,
    ) -> None:
        info = self._stages.get(name)
        if info:
            info.passed += passed
            info.filtered += filtered
            info.failed += failed

        if self._progress_task_id is not None and self._active_stage == name:
            if advance:
                self._progress.advance(self._progress_task_id, advance)
            if total is not None:
                self._progress.update(self._progress_task_id, total=total)
            if description is not None:
                self._progress.update(
                    self._progress_task_id, description=f"[cyan]{name}[/] {description}"
                )

    def stage_done(
        self,
        name: str,
        passed: int,
        filtered: int,
        failed: int,
        elapsed_s: float,
    ) -> None:
        info = self._stages.get(name)
        if not info:
            return
        info.state = StageState.DONE
        info.passed = passed
        info.filtered = filtered
        info.failed = failed
        info.elapsed_s = elapsed_s

        # clear progress bar
        if self._progress_task_id is not None:
            self._progress.remove_task(self._progress_task_id)
            self._progress_task_id = None

        self._active_stage = None

    def set_transient_status(self, text: str | None) -> None:
        if self._progress_task_id is not None:
            self._progress.remove_task(self._progress_task_id)
            self._progress_task_id = None

        if text:
            self._progress_task_id = self._progress.add_task(f"[dim]{text}[/]", total=None)
            self._active_stage = text
        else:
            self._active_stage = None

    def stage_skip(self, name: str) -> None:
        info = self._stages.get(name)
        if not info:
            return
        info.state = StageState.SKIPPED

    def finish(self, status: str) -> None:
        # clear any leftover progress bar
        if self._progress_task_id is not None:
            self._progress.remove_task(self._progress_task_id)
            self._progress_task_id = None
        self._active_stage = None

        self.stop()

        self._console.print()

        # print final summary table that was previously only transient
        table = self._build_table()
        if table:
            self._console.print(table)
            self._console.print()

        if status == "completed":
            self._console.print(" [bold green]✓ pipeline completed[/]")
        elif status == "interrupted":
            self._console.print(
                " [bold yellow]⚠ pipeline interrupted[/] [dim]─ re-run the same command without --clean to resume[/]"
            )
        else:
            self._console.print(f" [bold red]✗ pipeline failed[/] [dim]─ {status}[/]")
        self._console.print()

    def _build_renderable(self) -> RenderableType:
        parts: list[RenderableType] = []

        table = self._build_table()
        if table is not None:
            parts.append(table)

        # progress bar when a stage is actively running
        if self._progress_task_id is not None and self._active_stage:
            parts.append(self._progress)

        return Group(*parts)

    def _build_table(self) -> Table | None:

        table = Table(
            show_header=True, expand=False, box=box.SIMPLE, border_style="dim", padding=(0, 2)
        )
        table.add_column("stage", style="cyan", min_width=14)
        table.add_column("in", justify="right", min_width=7)
        table.add_column("passed", justify="right", style="green", min_width=7)
        table.add_column("filtered", justify="right", style="yellow", min_width=8)
        table.add_column("failed", justify="right", style="red", min_width=7)
        table.add_column("time", justify="right", style="dim", min_width=7)

        for name in self._stage_order:
            info = self._stages[name]

            if info.state == StageState.PENDING:
                table.add_row(
                    f"[dim]{_GLYPH_PENDING} {info.name}[/]",
                    "[dim]·[/]",
                    "[dim]·[/]",
                    "[dim]·[/]",
                    "[dim]·[/]",
                    "[dim]·[/]",
                )
            elif info.state == StageState.RUNNING:
                # still running, show live counts!
                in_str = "[dim]·[/]" if info.is_ingest else f"{info.input_count:,}"
                table.add_row(
                    f"[bold cyan]{_GLYPH_RUNNING} {info.name}[/]",
                    in_str,
                    f"{info.passed:,}",
                    _zero_or_val(info.filtered, info.is_ingest),
                    _zero_or_val(info.failed, info.is_ingest),
                    "[dim]…[/]",
                )
            elif info.state == StageState.SKIPPED:
                table.add_row(
                    f"[dim]{_GLYPH_SKIPPED} {info.name}[/]",
                    "[dim]·[/]",
                    "[dim]·[/]",
                    "[dim]·[/]",
                    "[dim]·[/]",
                    "[dim]·[/]",
                )
            elif info.state == StageState.FAILED:
                in_str = "[dim]·[/]" if info.is_ingest else f"{info.input_count:,}"
                time_str = _format_elapsed(info.elapsed_s)
                table.add_row(
                    f"[red]{_GLYPH_FAILED} {info.name}[/]",
                    in_str,
                    f"{info.passed:,}",
                    _zero_or_val(info.filtered, info.is_ingest),
                    _zero_or_val(info.failed, info.is_ingest),
                    time_str,
                )
            elif info.state == StageState.DONE:
                in_str = "[dim]·[/]" if info.is_ingest else f"{info.input_count:,}"
                time_str = (
                    "[dim]cached[/]" if info.is_fully_cached else _format_elapsed(info.elapsed_s)
                )
                glyph = "↻" if info.is_fully_cached else _GLYPH_DONE
                style = "dim blue" if info.is_fully_cached else "green"
                table.add_row(
                    f"[{style}]{glyph} {info.name}[/]",
                    in_str,
                    f"{info.passed:,}",
                    _zero_or_val(info.filtered, info.is_ingest),
                    _zero_or_val(info.failed, info.is_ingest),
                    time_str,
                )

        return table


def _zero_or_val(count: int, is_ingest: bool) -> str:
    if is_ingest:
        return "[dim]·[/]"
    return str(count) if count > 0 else "[dim]·[/]"


def _format_elapsed(seconds: float) -> str:
    if seconds < 0.1:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m{secs:04.1f}s"
