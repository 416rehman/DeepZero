from __future__ import annotations

import pytest

from deepzero.engine.registry import (
    get_registered_processors,
    register_processor,
    resolve_processor_class,
)


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _register_builtins():
    import deepzero.stages  # noqa: F401


class TestRegistryModule:
    def test_register_and_retrieve(self):
        from deepzero.engine.stage import (
            MapProcessor,
            ProcessorContext,
            ProcessorResult,
        )

        class StubProcessor(MapProcessor):
            def process(self, ctx: ProcessorContext, entry) -> ProcessorResult:
                return ProcessorResult(status="completed")

        register_processor("_test_registry_stub", StubProcessor)
        result = get_registered_processors()
        assert "_test_registry_stub" in result
        assert result["_test_registry_stub"] is StubProcessor

    def test_resolve_builtin_via_registry(self):
        cls = resolve_processor_class("metadata_filter")
        assert cls.__name__ == "MetadataFilter"

    def test_resolve_unknown_raises(self):
        with pytest.raises(ValueError, match="bare names match built-in processors only"):
            resolve_processor_class("_definitely_not_registered_xyz")

    def test_resolve_file_path(self, tmp_path):
        tool_dir = tmp_path / "processors" / "reg_test"
        tool_dir.mkdir(parents=True)
        (tool_dir / "reg_test.py").write_text(
            "from deepzero.engine.stage import MapProcessor, ProcessorContext, ProcessorResult\n"
            "class RegTest(MapProcessor):\n"
            "    def process(self, ctx, entry): return ProcessorResult(status='completed')\n",
            encoding="utf-8",
        )
        cls = resolve_processor_class("reg_test/reg_test.py")
        assert cls.__name__ == "RegTest"

    @pytest.mark.parametrize("explicit_class", [False, True])
    @pytest.mark.parametrize("forward_slashes", [False, True])
    def test_resolve_absolute_file_path(self, tmp_path, explicit_class, forward_slashes):
        processor_file = tmp_path / "external processors" / "absolute.py"
        processor_file.parent.mkdir()
        processor_file.write_text(
            "from deepzero.engine.stage import MapProcessor, ProcessorResult\n"
            "class AbsoluteProcessor(MapProcessor):\n"
            "    def process(self, ctx, entry): return ProcessorResult.ok()\n",
            encoding="utf-8",
        )
        reference = processor_file.as_posix() if forward_slashes else str(processor_file)
        if explicit_class:
            reference += ":AbsoluteProcessor"

        cls = resolve_processor_class(reference)

        assert cls.__name__ == "AbsoluteProcessor"
        assert cls._source_file == processor_file
