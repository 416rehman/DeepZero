import pytest
from deepzero.engine.registry import (
    register_processor,
    resolve_processor_class,
    get_registered_processors,
)
from deepzero.engine.stage import (
    IngestProcessor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
)


class DummyProcessor(IngestProcessor):
    description = "test"

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        pass


def test_registry():
    register_processor("dummy_test", DummyProcessor)
    assert "dummy_test" in get_registered_processors()
    proc = resolve_processor_class("dummy_test")
    assert proc == DummyProcessor

    with pytest.raises(ValueError):
        resolve_processor_class("nonexistent_test")
