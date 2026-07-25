from __future__ import annotations

from unittest.mock import patch

from deepzero.engine.stage import ProcessorContext, StageSpec
from deepzero.engine.state import StageOutput
from processors.ghidra_decompile.ghidra_decompile import (
    _GHIDRA_MAX_AUTO_WORKERS,
    GhidraDecompile,
    _auto_ghidra_workers,
)


class TestDecompileParallelism:
    def test_ram_caps_workers(self):
        # each worker ~4 GiB; bounded by cpu, ram, and the hard cap
        assert _auto_ghidra_workers(cpu=32, ram_gb=128) == _GHIDRA_MAX_AUTO_WORKERS  # hard cap
        assert _auto_ghidra_workers(cpu=32, ram_gb=16) == 4  # 16 // 4
        assert _auto_ghidra_workers(cpu=2, ram_gb=128) == 2  # cpu-bound
        assert _auto_ghidra_workers(cpu=8, ram_gb=64) == 8  # cpu-bound

    def test_unknown_ram_is_conservative(self):
        with patch("processors.ghidra_decompile.ghidra_decompile._total_ram_gb", return_value=None):
            assert _auto_ghidra_workers(cpu=64) == 4

    def test_never_zero(self):
        assert _auto_ghidra_workers(cpu=1, ram_gb=1) == 1

    def test_config_max_parallel_overrides_auto(self):
        proc = GhidraDecompile(
            StageSpec(name="decompile", processor="ghidra_decompile", config={"max_parallel": 24})
        )
        assert proc.max_parallelism() == 24

    def test_auto_ceiling_is_bounded_when_unset(self):
        proc = GhidraDecompile(StageSpec(name="decompile", processor="ghidra_decompile", config={}))
        assert 1 <= proc.max_parallelism() <= _GHIDRA_MAX_AUTO_WORKERS


def _make_ctx(tmp_path, config=None, global_config=None):
    sample_path = tmp_path / "test.sys"
    sample_path.write_bytes(b"MZ")

    sample_dir = tmp_path / "samples" / "abc123"
    sample_dir.mkdir(parents=True)

    history = {"discover": StageOutput(status="completed", data={"sha256": "abc123"})}
    ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=locals().get("llm"))
    from deepzero.engine.stage import ProcessorEntry

    try:
        hist = history
    except NameError:
        hist = {}

    class MockStore:
        def __init__(self, history):
            self._history = history

        def load_sample(self, sid):
            class S:
                def __init__(self, history):
                    self._history = history

                @property
                def history(self):
                    return self._history

            return S(self._history)

    try:
        sample_path_val = sample_path
    except NameError:
        sample_path_val = tmp_path / "test.bin"

    try:
        sample_dir_val = sample_dir
    except NameError:
        sample_dir_val = tmp_path

    entry = ProcessorEntry(
        sample_id="test_sample",
        source_path=sample_path_val,
        filename=sample_path_val.name,
        sample_dir=sample_dir_val,
        _store=MockStore(hist),
    )
    return ctx, entry


class TestGhidraDecompileProcess:
    def _make_tool(self, tmp_path, config=None):
        spec = StageSpec(name="decompile", processor="ghidra_decompile", config=config or {})
        processor = GhidraDecompile(spec)
        processor._tool_dir = tmp_path / "processor"
        processor._tool_dir.mkdir(parents=True, exist_ok=True)
        return processor

    def test_no_ghidra_dir(self, tmp_path):
        processor = self._make_tool(tmp_path)
        ctx, entry = _make_ctx(tmp_path, global_config={"tools": {}})
        result = processor.process(ctx, entry)
        assert result.status == "failed"
        assert "ghidra" in result.error.lower()

    def test_ghidra_not_found(self, tmp_path):
        processor = self._make_tool(tmp_path, config={"ghidra_install_dir": "/nonexistent/ghidra"})
        ctx, entry = _make_ctx(tmp_path)
        result = processor.process(ctx, entry)
        assert result.status == "failed"
        assert "not found" in result.error

    def test_no_strategy(self, tmp_path):
        ghidra_dir = tmp_path / "ghidra"
        ghidra_dir.mkdir()
        processor = self._make_tool(tmp_path, config={"ghidra_install_dir": str(ghidra_dir)})
        ctx, entry = _make_ctx(tmp_path)
        result = processor.process(ctx, entry)
        assert result.status == "failed"
        assert "strategy" in result.error

    @patch("processors.ghidra_decompile.ghidra_decompile.GhidraDecompile._run_ghidra_headless")
    def test_successful_decompilation(self, mock_run, tmp_path):
        processor = self._make_tool(tmp_path)
        ghidra_dir = tmp_path / "ghidra"
        ghidra_dir.mkdir()

        scripts_dir = processor._tool_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "extract_dispatch.py").write_text("# post-script")

        mock_run.return_value = {
            "success": True,
            "device_name": "TestDriver",
            "function_count": 42,
        }

        processor = self._make_tool(
            tmp_path,
            config={
                "strategy": "extract_dispatch.py",
                "ghidra_install_dir": str(ghidra_dir),
            },
        )

        ctx, entry = _make_ctx(tmp_path)
        result = processor.process(ctx, entry)
        assert result.status == "completed"
        assert result.data["device_name"] == "TestDriver"
        assert result.data["function_count"] == 42
        mock_run.assert_called_once()

    @patch("processors.ghidra_decompile.ghidra_decompile.GhidraDecompile._run_ghidra_headless")
    def test_failed_decompilation(self, mock_run, tmp_path):
        processor = self._make_tool(tmp_path)
        ghidra_dir = tmp_path / "ghidra"
        ghidra_dir.mkdir()

        scripts_dir = processor._tool_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "extract_dispatch.py").write_text("# post-script")

        mock_run.return_value = {"success": False, "error": "timeout after 300s"}

        processor = self._make_tool(
            tmp_path,
            config={
                "strategy": "extract_dispatch.py",
                "ghidra_install_dir": str(ghidra_dir),
            },
        )

        ctx, entry = _make_ctx(tmp_path)
        result = processor.process(ctx, entry)
        assert result.status == "failed"
        assert "timeout" in result.error


class TestGhidraDecompileShouldSkip:
    def test_skips_when_cached(self, tmp_path):
        spec = StageSpec(name="decompile", processor="ghidra_decompile")
        processor = GhidraDecompile(spec)
        ctx, entry = _make_ctx(tmp_path)

        cached = entry.sample_dir / "decompiled" / "ghidra_result.json"
        cached.parent.mkdir(parents=True)
        cached.write_text('{"success": true}')

        reason = processor.should_skip(ctx, entry)
        assert reason is not None
        assert "cached" in reason

    def test_no_skip_when_not_cached(self, tmp_path):
        spec = StageSpec(name="decompile", processor="ghidra_decompile")
        processor = GhidraDecompile(spec)
        ctx, entry = _make_ctx(tmp_path)

        reason = processor.should_skip(ctx, entry)
        assert reason is None
