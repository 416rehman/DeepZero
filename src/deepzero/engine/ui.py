from __future__ import annotations

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich.table import Table


class PipelineDashboard:
    # manages a dynamic TUI for pipeline execution

    def __init__(self, stages: list[dict], console: Console | None = None):
        self._console = console or Console()
        self.stage_specs = stages
        self.stage_names = [s["name"] for s in stages]
        self.stats: dict[str, dict[str, int]] = {
            s: {"passed": 0, "filtered": 0, "failed": 0, "pending": 0}
            for s in self.stage_names
        }
        self.active_stage: str | None = None

        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[cyan]{task.completed}/{task.total} completed"),
            TimeRemainingColumn(),
            console=self._console,
            transient=True,
        )
        self._live: Live | None = None

    def start(self):
        self._live = Live(
            self._generate_layout(),
            console=self._console,
            refresh_per_second=4,
            transient=False,
        )
        self._live.start()

    def stop(self):
        # Force a final render
        if self._live:
            self._live.update(self._generate_layout())
            self._live.stop()

    def set_active_stage(self, stage: str):
        self.active_stage = stage
        self.refresh()

    def update_stats(
        self, stage: str, passed=None, filtered=None, failed=None, pending=None
    ):
        if passed is not None:
            self.stats[stage]["passed"] = passed
        if filtered is not None:
            self.stats[stage]["filtered"] = filtered
        if failed is not None:
            self.stats[stage]["failed"] = failed
        if pending is not None:
            self.stats[stage]["pending"] = pending
        self.refresh()

    def refresh(self):
        if self._live:
            self._live.update(self._generate_layout())

    def _generate_layout(self) -> RenderableType:
        # 1. Graph
        graph_parts = []
        for s in self.stage_names:
            if s == self.active_stage:
                graph_parts.append(f"[bold cyan]\\[ {s} ][/]")
            else:
                total_done = (
                    self.stats[s]["passed"]
                    + self.stats[s]["filtered"]
                    + self.stats[s]["failed"]
                )
                if (
                    total_done > 0
                    and self.stats[s]["pending"] == 0
                    and s != self.active_stage
                ):
                    graph_parts.append(f"[dim green]\\[ {s} ][/]")
                else:
                    graph_parts.append(f"[dim]\\[ {s} ][/]")

        graph = " ➔ ".join(graph_parts)
        if not graph_parts:
            graph = "[dim]Initializing...[/]"

        table = Table(show_header=True, expand=True)
        table.add_column("stage", style="cyan")
        table.add_column("type", style="magenta", justify="center")
        table.add_column("workers", style="blue", justify="right")
        table.add_column("passed", style="green", justify="right")
        table.add_column("filtered", style="yellow", justify="right")
        table.add_column("failed", style="red", justify="right")
        table.add_column("pending", style="bright_black", justify="right")

        for spec in self.stage_specs:
            s = spec["name"]
            st = self.stats[s]
            if sum(st.values()) > 0:
                # Resolve workers text
                w_val = spec.get("workers", 1)
                w_str = str(w_val) if w_val > 0 else "auto"
                if spec.get("type") in ("reduce", "batch", "ingest"):
                    w_str = "-"

                table.add_row(
                    s,
                    spec.get("type", "unknown"),
                    w_str,
                    str(st["passed"]),
                    str(st["filtered"]),
                    str(st["failed"]),
                    str(st["pending"]),
                )

        # 3. Overall Group
        # Render the task list inside if there are active tasks
        content: list[RenderableType] = [Panel(graph, title="Pipeline Flow"), table]

        if self.progress.tasks:
            content.append(self.progress)

        return Group(*content)
