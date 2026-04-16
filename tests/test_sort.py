from __future__ import annotations

from pathlib import Path

import pytest

from deepzero.engine.stage import StageSpec, ProcessorContext, ProcessorEntry
from deepzero.engine.state import StageOutput, StageStatus
from deepzero.engine.types import Verdict
from deepzero.stages.sort import Sort


@pytest.fixture
def sort_spec():
    return StageSpec(
        name="test_sort",
        processor="sort",
        config={"by": "upstream.score", "order": "desc"},
    )


@pytest.fixture
def ctx():
    return ProcessorContext(pipeline_dir=Path("."), global_config={}, llm=None)


def _make_entry(
    sample_id: str, history: dict[str, StageOutput] | None = None
) -> ProcessorEntry:
    entry = ProcessorEntry(
        sample_id=sample_id,
        source_path=Path(f"{sample_id}.sys"),
        filename=f"{sample_id}.sys",
        sample_dir=Path(f"work/{sample_id}"),
    )
    if history:
        entry._history = history
    return entry


class TestSort:
    def test_sorts_descending_by_default(self, sort_spec, ctx):
        sorter = Sort(sort_spec)
        entries = [
            _make_entry(
                "a",
                {
                    "upstream": StageOutput(
                        status=StageStatus.COMPLETED,
                        verdict=Verdict.CONTINUE,
                        data={"score": 10},
                    )
                },
            ),
            _make_entry(
                "b",
                {
                    "upstream": StageOutput(
                        status=StageStatus.COMPLETED,
                        verdict=Verdict.CONTINUE,
                        data={"score": 30},
                    )
                },
            ),
            _make_entry(
                "c",
                {
                    "upstream": StageOutput(
                        status=StageStatus.COMPLETED,
                        verdict=Verdict.CONTINUE,
                        data={"score": 20},
                    )
                },
            ),
        ]
        result = sorter.process(ctx, entries)
        assert result == ["b", "c", "a"]

    def test_sorts_ascending(self, ctx):
        spec = StageSpec(
            name="test_sort",
            processor="sort",
            config={"by": "upstream.score", "order": "asc"},
        )
        sorter = Sort(spec)
        entries = [
            _make_entry(
                "a",
                {
                    "upstream": StageOutput(
                        status=StageStatus.COMPLETED,
                        verdict=Verdict.CONTINUE,
                        data={"score": 10},
                    )
                },
            ),
            _make_entry(
                "b",
                {
                    "upstream": StageOutput(
                        status=StageStatus.COMPLETED,
                        verdict=Verdict.CONTINUE,
                        data={"score": 30},
                    )
                },
            ),
        ]
        result = sorter.process(ctx, entries)
        assert result == ["a", "b"]

    def test_no_by_field_preserves_order(self, ctx):
        spec = StageSpec(name="test_sort", processor="sort", config={})
        sorter = Sort(spec)
        errors = sorter.validate(ctx)
        assert len(errors) == 1
        assert "requires 'by'" in errors[0]

    def test_invalid_by_format_preserves_order(self, ctx):
        spec = StageSpec(name="test_sort", processor="sort", config={"by": "no_dot"})
        sorter = Sort(spec)
        errors = sorter.validate(ctx)
        assert len(errors) == 1
        assert "must be 'processor_name.key'" in errors[0]

    def test_missing_upstream_data_returns_zero(self, sort_spec, ctx):
        sorter = Sort(sort_spec)
        entries = [
            _make_entry(
                "a",
                {
                    "upstream": StageOutput(
                        status=StageStatus.COMPLETED,
                        verdict=Verdict.CONTINUE,
                        data={"score": 5},
                    )
                },
            ),
            _make_entry("b"),
        ]
        result = sorter.process(ctx, entries)
        assert result == ["a", "b"]
