from deepzero.engine.stage import ProcessorContext, ProcessorEntry, StageSpec
from deepzero.engine.state import StageOutput
from deepzero.stages.sort import Sort


def test_sort_processor():
    spec = StageSpec(name="sort", processor="sort", config={"by": "parse.score", "order": "desc"})
    sorter = Sort(spec)

    ctx = ProcessorContext(pipeline_dir=None, global_config={}, llm=None)

    class MockState:
        def __init__(self, d):
            self.history = d

    class MockStore:
        def __init__(self):
            self.states = {}

        def load_sample(self, sid):
            return MockState(self.states.get(sid, {}))

    store = MockStore()
    store.states["1"] = {"parse": StageOutput(status="completed", data={"score": 10})}
    store.states["2"] = {"parse": StageOutput(status="completed", data={"score": 50})}
    store.states["3"] = {"parse": StageOutput(status="completed", data={"score": 30})}

    e1 = ProcessorEntry(
        sample_id="1", source_path=None, filename="1", sample_dir=None, _store=store
    )
    e2 = ProcessorEntry(
        sample_id="2", source_path=None, filename="2", sample_dir=None, _store=store
    )
    e3 = ProcessorEntry(
        sample_id="3", source_path=None, filename="3", sample_dir=None, _store=store
    )

    res = sorter.process(ctx, [e1, e2, e3])
    # descending: 2 (50) -> 3 (30) -> 1 (10)
    assert res == ["2", "3", "1"]

    spec = StageSpec(name="sort", processor="sort", config={"by": "parse.score", "order": "asc"})
    sorter = Sort(spec)
    res = sorter.process(ctx, [e1, e2, e3])
    assert res == ["1", "3", "2"]

    # test missing config validation hook
    spec = StageSpec(name="sort", processor="sort", config={})
    sorter = Sort(spec)
    errors = sorter.validate(ctx)
    assert len(errors) == 1
    assert "requires 'by'" in errors[0]
