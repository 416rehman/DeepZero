from __future__ import annotations

from unittest.mock import patch, MagicMock

from deepzero.engine.stage import StageContext, StageSpec
from deepzero.engine.state import StageOutput
from tools.ghidra_decompile.ghidra_decompile import GhidraDecompile


def _make_ctx(tmp_path, config=None, global_config=None):
    sample_path = tmp_path / "test.sys"
    sample_path.write_bytes(b"MZ")

    sample_dir = tmp_path / "samples" / "abc123"
    sample_dir.mkdir(parents=True)

    history = {"discover": StageOutput(status="completed", data={"sha256": "abc123"})}
    return StageContext(
        sample_path=sample_path,
        sample_dir=sample_dir,
        history=history,
        config=config or {},
        pipeline_dir=tmp_path,
        global_config=global_config or {},
        llm=None,
    )


class TestGhidraDecompileProcess:
    def _make_tool(self, tmp_path):
        spec = StageSpec(name="decompile", tool="ghidra_decompile")
        tool = GhidraDecompile(spec)
        tool._tool_dir = tmp_path / "tool"
        tool._tool_dir.mkdir(parents=True, exist_ok=True)
        return tool

    def test_no_ghidra_dir(self, tmp_path):
        tool = self._make_tool(tmp_path)
        ctx = _make_ctx(tmp_path, global_config={"tools": {}})
        result = tool.process(ctx)
        assert result.status == "failed"
        assert "ghidra" in result.error.lower()

    def test_ghidra_not_found(self, tmp_path):
        tool = self._make_tool(tmp_path)
        ctx = _make_ctx(
            tmp_path,
            global_config={"tools": {"ghidra": {"install_dir": "/nonexistent/ghidra"}}},
        )
        result = tool.process(ctx)
        assert result.status == "failed"
        assert "not found" in result.error

    def test_no_strategy(self, tmp_path):
        tool = self._make_tool(tmp_path)
        ghidra_dir = tmp_path / "ghidra"
        ghidra_dir.mkdir()
        ctx = _make_ctx(
            tmp_path,
            config={},
            global_config={"tools": {"ghidra": {"install_dir": str(ghidra_dir)}}},
        )
        result = tool.process(ctx)
        assert result.status == "failed"
        assert "strategy" in result.error

    @patch("tools.ghidra_decompile.ghidra_decompile.run_ghidra_headless")
    def test_successful_decompilation(self, mock_run, tmp_path):
        tool = self._make_tool(tmp_path)
        ghidra_dir = tmp_path / "ghidra"
        ghidra_dir.mkdir()

        scripts_dir = tool._tool_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "extract_dispatch.py").write_text("# post-script")

        mock_run.return_value = {
            "success": True,
            "device_name": "TestDriver",
            "function_count": 42,
        }

        ctx = _make_ctx(
            tmp_path,
            config={"strategy": "extract_dispatch.py"},
            global_config={"tools": {"ghidra": {"install_dir": str(ghidra_dir)}}},
        )
        result = tool.process(ctx)
        assert result.status == "completed"
        assert result.data["device_name"] == "TestDriver"
        assert result.data["function_count"] == 42
        mock_run.assert_called_once()

    @patch("tools.ghidra_decompile.ghidra_decompile.run_ghidra_headless")
    def test_failed_decompilation(self, mock_run, tmp_path):
        tool = self._make_tool(tmp_path)
        ghidra_dir = tmp_path / "ghidra"
        ghidra_dir.mkdir()

        scripts_dir = tool._tool_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "extract_dispatch.py").write_text("# post-script")

        mock_run.return_value = {"success": False, "error": "timeout after 300s"}

        ctx = _make_ctx(
            tmp_path,
            config={"strategy": "extract_dispatch.py"},
            global_config={"tools": {"ghidra": {"install_dir": str(ghidra_dir)}}},
        )
        result = tool.process(ctx)
        assert result.status == "failed"
        assert "timeout" in result.error


class TestGhidraDecompileShouldSkip:
    def test_skips_when_cached(self, tmp_path):
        spec = StageSpec(name="decompile", tool="ghidra_decompile")
        tool = GhidraDecompile(spec)
        ctx = _make_ctx(tmp_path)

        cached = ctx.sample_dir / "decompiled" / "ghidra_result.json"
        cached.parent.mkdir(parents=True)
        cached.write_text('{"success": true}')

        reason = tool.should_skip(ctx)
        assert reason is not None
        assert "cached" in reason

    def test_no_skip_when_not_cached(self, tmp_path):
        spec = StageSpec(name="decompile", tool="ghidra_decompile")
        tool = GhidraDecompile(spec)
        ctx = _make_ctx(tmp_path)

        reason = tool.should_skip(ctx)
        assert reason is None
