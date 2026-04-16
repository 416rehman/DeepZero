from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

# -- fixtures --


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tools").mkdir()
    return tmp_path


@pytest.fixture
def make_tool(tmp_path):
    def _make(dir_name: str, file_name: str, code: str):
        tool_dir = tmp_path / "processors" / dir_name
        tool_dir.mkdir(parents=True, exist_ok=True)
        tool_file = tool_dir / file_name
        tool_file.write_text(textwrap.dedent(code), encoding="utf-8")
        return tool_file

    return _make


@pytest.fixture(autouse=True)
def _register_builtins():
    import deepzero.stages  # noqa: F401


# -- processor resolution --


class TestToolResolution:
    def test_builtin_resolves_by_bare_name(self):
        from deepzero.engine.stage import resolve_processor_class

        cls = resolve_processor_class("metadata_filter")
        assert cls.__name__ == "MetadataFilter"

    def test_all_builtins_resolvable(self):
        from deepzero.engine.stage import resolve_processor_class

        expected = [
            "file_discovery",
            "metadata_filter",
            "hash_exclude",
            "generic_llm",
            "generic_command",
            "top_k",
        ]
        for name in expected:
            cls = resolve_processor_class(name)
            assert cls is not None, f"built-in '{name}' not found"

    def test_unknown_bare_name_fails(self):
        from deepzero.engine.stage import resolve_processor_class

        with pytest.raises(ValueError, match="bare names match built-in processors only"):
            resolve_processor_class("nonexistent_tool")

    def test_slash_path_resolves_tool_file(self, make_tool):
        from deepzero.engine.stage import MapProcessor, resolve_processor_class

        make_tool(
            "my_filter",
            "my_filter.py",
            """
            from deepzero.engine.stage import MapProcessor, ProcessorContext, ProcessorResult
            class MyFilter(MapProcessor):
                def process(self, ctx: ProcessorContext, entry) -> ProcessorResult:
                    return ProcessorResult(status="completed", verdict="continue")
        """,
        )
        cls = resolve_processor_class("my_filter/my_filter.py")
        assert issubclass(cls, MapProcessor)
        assert cls.__name__ == "MyFilter"

    def test_slash_path_with_explicit_class(self, make_tool):
        from deepzero.engine.stage import resolve_processor_class

        make_tool(
            "multi",
            "multi.py",
            """
            from deepzero.engine.stage import MapProcessor, BulkMapProcessor, ProcessorContext, ProcessorResult, ProcessorEntry
            class ToolA(MapProcessor):
                def process(self, ctx, entry): return ProcessorResult(status="completed")
            class ToolB(BulkMapProcessor):
                def process(self, ctx, entries): return [ProcessorResult(status="completed")]
        """,
        )
        cls = resolve_processor_class("multi/multi.py:ToolB")
        assert cls.__name__ == "ToolB"

    def test_slash_path_missing_file_fails(self):
        from deepzero.engine.stage import resolve_processor_class

        with pytest.raises(FileNotFoundError):
            resolve_processor_class("does_not_exist/nope.py")

    def test_source_file_set_on_resolve(self, make_tool):
        from deepzero.engine.stage import resolve_processor_class

        make_tool(
            "src_test",
            "src_test.py",
            """
            from deepzero.engine.stage import MapProcessor, ProcessorContext, ProcessorResult
            class SrcTest(MapProcessor):
                def process(self, ctx, entry): return ProcessorResult(status="completed")
        """,
        )
        cls = resolve_processor_class("src_test/src_test.py")
        assert cls._source_file is not None
        assert cls._source_file.name == "src_test.py"


# -- processor base class --


class TestToolBaseClass:
    def _make_spec(self, name="test_tool"):
        from deepzero.engine.stage import StageSpec

        return StageSpec(name=name, processor="metadata_filter")

    def test_log_scoped_to_tool_name(self):
        from deepzero.engine.stage import resolve_processor_class

        cls = resolve_processor_class("metadata_filter")
        instance = cls(self._make_spec("my_stage"))
        assert instance.log.name == "deepzero.processor.my_stage"

    def test_cache_dir_created(self, tmp_path):
        from deepzero.engine.stage import resolve_processor_class

        cls = resolve_processor_class("metadata_filter")
        instance = cls(self._make_spec("cache_test"))
        cache = instance.cache_dir
        assert cache.exists()
        assert cache.name == "cache_test"

    def test_cache_dir_isolated_per_tool(self, tmp_path):
        from deepzero.engine.stage import resolve_processor_class

        cls = resolve_processor_class("metadata_filter")
        a = cls(self._make_spec("tool_a"))
        b = cls(self._make_spec("tool_b"))
        assert a.cache_dir != b.cache_dir

    def test_setup_and_teardown_callable(self):
        from deepzero.engine.stage import resolve_processor_class

        cls = resolve_processor_class("metadata_filter")
        instance = cls(self._make_spec())
        instance.setup({})
        instance.teardown()


# -- processor types --


class TestToolTypes:
    def test_map_tool_type(self):
        from deepzero.engine.stage import ProcessorType
        from deepzero.stages.filter import MetadataFilter

        assert MetadataFilter.processor_type == ProcessorType.MAP

    def test_ingest_tool_type(self):
        from deepzero.engine.stage import ProcessorType
        from deepzero.stages.ingest import FileDiscovery

        assert FileDiscovery.processor_type == ProcessorType.INGEST

    def test_batch_tool_type(self):
        from deepzero.engine.stage import BulkMapProcessor, ProcessorType

        class DummyBulk(BulkMapProcessor):
            def process(self, ctx, entries):
                return []

        assert DummyBulk.processor_type == ProcessorType.BULK_MAP

    def test_reduce_tool_type(self):
        from deepzero.engine.stage import ProcessorType
        from deepzero.stages.top_k import TopKSelector

        assert TopKSelector.processor_type == ProcessorType.REDUCE


# -- data classes --


class TestDataClasses:
    def test_sample_creation(self):
        from deepzero.engine.stage import Sample

        s = Sample(sample_id="abc", source_path=Path("test.sys"), filename="test.sys")
        assert s.sample_id == "abc"
        assert s.data == {}

    def test_stage_result_defaults(self):
        from deepzero.engine.stage import ProcessorResult

        r = ProcessorResult(status="completed")
        assert r.verdict == "continue"
        assert r.artifacts == {}
        assert r.data == {}
        assert r.error is None

    def test_stage_spec_defaults(self):
        from deepzero.engine.stage import FailurePolicy, StageSpec

        s = StageSpec(name="test", processor="metadata_filter")
        assert s.config == {}
        assert s.parallel == 0
        assert s.on_failure == FailurePolicy.SKIP
        assert s.timeout == 0

    def test_stage_context_creation(self):
        from deepzero.engine.stage import GlobalConfig, ProcessorContext

        ctx = ProcessorContext(
            pipeline_dir=Path("."),
            global_config=GlobalConfig(settings={"opt": True}),
            llm=None,
        )
        assert ctx.get_setting("opt") is True

    def test_batch_entry_creation(self):
        from deepzero.engine.stage import ProcessorEntry

        entry = ProcessorEntry(
            sample_id="abc",
            sample_dir=Path("work/abc"),
            source_path=Path("test.sys"),
            filename="test.sys",
        )
        assert entry.sample_id == "abc"


# -- processor registry --


class TestToolRegistry:
    def test_register_and_resolve(self):
        from deepzero.engine.stage import (
            MapProcessor,
            ProcessorContext,
            ProcessorResult,
            register_processor,
            resolve_processor_class,
        )

        class CustomRegistered(MapProcessor):
            def process(self, ctx: ProcessorContext, entry) -> ProcessorResult:
                return ProcessorResult(status="completed")

        register_processor("_test_custom", CustomRegistered)
        cls = resolve_processor_class("_test_custom")
        assert cls is CustomRegistered

    def test_get_registered_tools(self):
        from deepzero.engine.stage import get_registered_processors

        tools = get_registered_processors()
        assert "metadata_filter" in tools
        assert "hash_exclude" in tools
        assert "top_k" in tools
