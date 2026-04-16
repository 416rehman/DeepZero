from pathlib import Path

from deepzero.engine.context import generate_context
from deepzero.engine.state import SampleState, StageOutput


def test_generate_context(tmp_path: Path):
    sample_dir = tmp_path / "sample1"
    sample_dir.mkdir()

    # Create an artifact file so it shows in artifacts
    art_path = sample_dir / "out.txt"
    art_path.write_text("hello")

    state = SampleState(
        sample_id="1",
        filename="test.exe",
        current_stage="disasm",
        verdict="malicious",
        history={
            "extract": StageOutput(
                status="completed",
                verdict="suspicious",
                artifacts={"txt": "out.txt"},
                data={"size": 1024, "long_string": "A" * 300},
            ),
            "disasm": StageOutput(status="failed", error="too large"),
        },
    )

    generate_context(sample_dir, state)

    context_file = sample_dir / "context.md"
    assert context_file.exists()
    content = context_file.read_text(encoding="utf-8")

    assert "# Target: test.exe" in content
    assert "**Verdict:** malicious" in content
    assert "### extract" in content
    assert "- status: completed" in content
    assert "- verdict: suspicious" in content
    assert "- size: 1024" in content
    # Truncated string test
    assert "A" * 200 + "..." in content
    assert "too large" in content
    assert "## Artifacts" in content
    assert "- `out.txt`" in content
