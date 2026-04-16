from __future__ import annotations

from deepzero.engine.stage import ProcessorContext, StageSpec
from deepzero.engine.state import StageOutput
from deepzero.stages.command import GenericCommand


class TestGenericCommand:
    def _make_ctx(self, tmp_path, config: dict):
        sample_path = tmp_path / "test.sys"
        sample_path.write_bytes(b"hello")

        sample_dir = tmp_path / "work" / "abc"
        sample_dir.mkdir(parents=True)

        history = {"discover": StageOutput(status="completed", data={"sha256": "abc"})}
        ctx = ProcessorContext(
            pipeline_dir=tmp_path, global_config={}, llm=locals().get("llm")
        )
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

    def test_rendering_and_capture(self, tmp_path, monkeypatch):
        spec = StageSpec(
            name="cmd",
            processor="generic_command",
            config={"run": "echo '{filename} is mapped'", "stdout_to": "out.txt"},
        )
        processor = GenericCommand(spec)
        ctx, entry = self._make_ctx(tmp_path, spec.config)

        def mock_run_async(self_obj, cmd_list, timeout, cwd):
            async def _inner():
                return 0, b"test.sys is mapped\n", b""

            return _inner()

        monkeypatch.setattr(GenericCommand, "_run_async", mock_run_async)

        result = processor.process(ctx, entry)
        assert result.verdict == "continue"
        assert (entry.sample_dir / "out.txt").read_text() == "test.sys is mapped\n"
        assert result.data["command_exit_code"] == 0

    def test_command_failure(self, tmp_path, monkeypatch):
        spec = StageSpec(
            name="cmd", processor="generic_command", config={"run": "false"}
        )
        processor = GenericCommand(spec)
        ctx, entry = self._make_ctx(tmp_path, spec.config)

        def mock_run_async(self_obj, cmd_list, timeout, cwd):
            async def _inner():
                return 1, b"", b"command not found"

            return _inner()

        monkeypatch.setattr(GenericCommand, "_run_async", mock_run_async)

        result = processor.process(ctx, entry)
        assert result.status == "failed"
        assert result.error is not None
