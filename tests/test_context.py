from __future__ import annotations


class TestContextGeneration:
    def test_generates_context_md(self, tmp_path):
        from deepzero.engine.context import generate_context
        from deepzero.engine.state import SampleState

        s = SampleState(
            sample_id="abc",
            filename="test.sys",
            verdict="active",
            current_stage="filter",
        )
        s.mark_stage_completed(
            "discover", data={"sha256": "deadbeef", "size_bytes": 1024}
        )
        s.verdict = "active"

        sample_dir = tmp_path / "samples" / "abc"
        sample_dir.mkdir(parents=True)
        generate_context(sample_dir, s)

        ctx_file = sample_dir / "context.md"
        assert ctx_file.exists()
        content = ctx_file.read_text(encoding="utf-8")
        assert "test.sys" in content
        assert "sha256" in content
        assert "deadbeef" in content
