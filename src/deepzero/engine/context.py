from __future__ import annotations

from pathlib import Path

from deepzero.engine.state import SampleState, atomic_replace


def generate_context(sample_dir: Path, state: SampleState) -> None:
    # auto-generate a human-readable context.md for LLM consumption
    lines = [
        f"# Target: {state.filename}",
        f"**Verdict:** {state.verdict}  |  **Stage:** {state.current_stage}",
        "",
    ]

    if state.history:
        lines.append("## History")
        for stage_name, output in state.history.items():
            lines.append(f"### {stage_name}")
            lines.append(f"- status: {output.status}")
            if output.verdict:
                lines.append(f"- verdict: {output.verdict}")
            if output.error:
                lines.append(f"- error: {output.error}")
            for key, value in output.data.items():
                # keep it readable - truncate long values
                val_str = str(value)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                lines.append(f"- {key}: {val_str}")
            lines.append("")

    # list artifact files that exist on disk
    artifacts = []
    for output in state.history.values():
        for rel_path in output.artifacts.values():
            full = sample_dir / rel_path
            if full.exists():
                artifacts.append(rel_path)

    if artifacts:
        lines.append("## Artifacts")
        for a in sorted(set(artifacts)):
            lines.append(f"- `{a}`")
        lines.append("")

    content = "\n".join(lines)
    path = sample_dir / "context.md"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    atomic_replace(tmp, path)
