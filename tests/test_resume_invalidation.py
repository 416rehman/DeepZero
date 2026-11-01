"""A resumed result must describe the current inputs, including cohort changes."""

from pathlib import Path

import pytest

from deepzero.engine.runner import PipelineRunner
from deepzero.engine.stage import (
    BulkMapProcessor,
    IngestProcessor,
    MapProcessor,
    ProcessorResult,
    Sample,
    StageSpec,
    stage_input_digest,
)
from deepzero.engine.state import RunState, StateStore
from deepzero.engine.types import SampleStatus
from deepzero.stages.top_k import TopKSelector


class Discover(IngestProcessor):
    cache_global_keys = ()

    def __init__(self, ids=("a", "b", "c")):
        super().__init__(StageSpec(name="discover", processor="discover"))
        self.ids = ids

    def process(self, ctx, target):
        return [Sample(sid, Path(sid), sid, {"score": ord(sid)}) for sid in self.ids]


class WriteValue(MapProcessor):
    cache_global_keys = ()

    def __init__(self, value=1):
        super().__init__(
            StageSpec(name="write", processor="write", parallel=1, config={"value": value})
        )
        self.calls = 0

    def should_skip(self, ctx, entry):
        if (entry.sample_dir / "value.txt").exists() and entry.cache_is_valid:
            return "output cached"
        return None

    def process(self, ctx, entry):
        self.calls += 1
        (entry.sample_dir / "value.txt").write_text(str(self.config["value"]))
        return ProcessorResult.ok(
            data={"value": self.config["value"]}, artifacts={"value": "value.txt"}
        )


class ReadValue(MapProcessor):
    cache_global_keys = ()

    def __init__(self):
        super().__init__(StageSpec(name="read", processor="read", parallel=1))
        self.calls = 0

    def process(self, ctx, entry):
        self.calls += 1
        value = (entry.sample_dir / "value.txt").read_text()
        return ProcessorResult.ok(data={"seen": int(value)})


class Assess(MapProcessor):
    cache_global_keys = ("model", "knowledge")

    def __init__(self):
        super().__init__(StageSpec(name="assess", processor="assess", parallel=1))
        self.calls = 0

    def process(self, ctx, entry):
        self.calls += 1
        return ProcessorResult.ok(data={"model": ctx.global_config.get("model")})


class Gate(MapProcessor):
    cache_global_keys = ()

    def __init__(self, reject):
        super().__init__(StageSpec(name="gate", processor="gate", config={"reject": reject}))

    def process(self, ctx, entry):
        if self.config["reject"]:
            return ProcessorResult.filter("excluded")
        return ProcessorResult.ok()


class CountCohort(BulkMapProcessor):
    cache_global_keys = ()

    def __init__(self):
        super().__init__(StageSpec(name="count", processor="count"))
        self.calls = 0

    def process(self, ctx, entries):
        self.calls += 1
        return [ProcessorResult.ok(data={"count": len(entries)}) for _ in entries]


def run(tmp_path, processors, *, ids=("a", "b", "c"), refresh=False, config=None):
    store = StateStore(tmp_path / "work")
    runner = PipelineRunner(
        Discover(ids),
        [(p.spec, p) for p in processors],
        store,
        tmp_path,
        config or {},
        refresh_ingest=refresh,
    )
    result = runner.run(tmp_path, store.load_run() or RunState(run_id="r", pipeline="test"))
    assert result.status == "completed", result.stats
    return store


def test_changed_upstream_replaces_artifact_and_reruns_consumer(tmp_path):
    run(tmp_path, [WriteValue(1), ReadValue()])
    producer, consumer = WriteValue(2), ReadValue()
    store = run(tmp_path, [producer, consumer])
    assert producer.calls == consumer.calls == 3
    assert all(s.history["read"].data["seen"] == 2 for s in store.list_samples())


def test_unchanged_pipeline_reuses_results(tmp_path):
    run(tmp_path, [WriteValue(), ReadValue()])
    producer, consumer = WriteValue(), ReadValue()
    run(tmp_path, [producer, consumer])
    assert producer.calls == consumer.calls == 0


def test_unrecorded_artifact_is_not_assumed_to_match_current_inputs(tmp_path):
    store = StateStore(tmp_path / "work")
    (store.sample_dir("a") / "value.txt").write_text("999")
    producer = WriteValue(1)
    store = run(tmp_path, [producer])
    assert producer.calls == 3
    assert store.load_sample("a").history["write"].data["value"] == 1


@pytest.mark.parametrize("changed", [{"model": "new"}, {"model": "old", "knowledge": {"v": 2}}])
def test_model_or_knowledge_change_keeps_expensive_config_only_stage(tmp_path, changed):
    run(tmp_path, [WriteValue(), Assess()], config={"model": "old"})
    producer, assessor = WriteValue(), Assess()
    store = run(tmp_path, [producer, assessor], config=changed)
    assert producer.calls == 0
    assert assessor.calls == 3
    assert all(s.history["assess"].data["model"] == changed["model"] for s in store.list_samples())


def test_loosening_filter_reactivates_samples(tmp_path):
    run(tmp_path, [Gate(True), WriteValue()])
    writer = WriteValue()
    store = run(tmp_path, [Gate(False), writer])
    assert writer.calls == 3
    assert all(s.verdict == SampleStatus.ACTIVE for s in store.list_samples())


def test_newly_filtered_samples_do_not_leave_old_downstream_counts(tmp_path):
    run(tmp_path, [Gate(False), WriteValue()])
    store = run(tmp_path, [Gate(True), WriteValue()])
    assert store.load_run().stats["per_stage"]["write"]["completed"] == 0


class ReadOptionalProducer(MapProcessor):
    cache_global_keys = ()

    def __init__(self):
        super().__init__(StageSpec(name="read", processor="optional_reader", parallel=1))
        self.calls = 0

    def process(self, ctx, entry):
        self.calls += 1
        producer = entry.history.get("write")
        return ProcessorResult.ok(data={"seen": producer.data["value"] if producer else 0})


def test_removing_stage_discards_its_history_artifacts_and_consumers(tmp_path):
    run(tmp_path, [WriteValue(7), ReadOptionalProducer()])
    reader = ReadOptionalProducer()
    store = run(tmp_path, [reader])
    assert reader.calls == 3
    for state in store.list_samples():
        assert "write" not in state.history
        assert state.history["read"].data == {"seen": 0}
        assert not (store.sample_dir(state.sample_id) / "value.txt").exists()
    assert "write" not in store.load_run().stats["per_stage"]


def test_reordering_stages_invalidates_changed_dependencies(tmp_path):
    run(tmp_path, [WriteValue(7), ReadOptionalProducer()])
    reader = ReadOptionalProducer()
    store = run(tmp_path, [reader, WriteValue(7)])
    assert reader.calls == 3
    assert all(s.history["read"].data == {"seen": 0} for s in store.list_samples())


def rank(keep):
    return TopKSelector(
        StageSpec(
            name="rank",
            processor="top_k",
            config={"metric_path": "discover.score", "keep_top": keep},
        )
    )


def test_increasing_top_k_reconsiders_old_filtered_samples(tmp_path):
    store = run(tmp_path, [rank(1), WriteValue()])
    assert sum(s.is_active() for s in store.list_samples()) == 1
    writer = WriteValue()
    store = run(tmp_path, [rank(3), writer])
    assert writer.calls == 3
    assert all(s.is_active() for s in store.list_samples())


def test_removing_top_ranked_sample_reconsiders_survivors(tmp_path):
    run(tmp_path, [rank(1), WriteValue()])
    store = run(tmp_path, [rank(1), WriteValue()], ids=("a", "b"), refresh=True)
    assert {s.sample_id for s in store.list_samples() if s.is_active()} == {"b"}
    assert store.load_sample("b").history["write"].data == {"value": 1}


def test_bulk_results_recompute_for_membership_change(tmp_path):
    run(tmp_path, [CountCohort()])
    counter = CountCohort()
    store = run(tmp_path, [counter], ids=("a", "b"), refresh=True)
    assert counter.calls == 1
    assert all(s.history["count"].data == {"count": 2} for s in store.list_samples())


def test_cached_reducer_preserves_order(tmp_path):
    store = run(tmp_path, [rank(2)])
    assert store.load_sample("c").history["rank"].data["__reduce_order"] == 0
    store = run(tmp_path, [rank(2)])
    assert {s.sample_id for s in store.list_samples() if s.is_active()} == {"b", "c"}


def test_nested_file_change_invalidates_stage(tmp_path):
    prompt = tmp_path / "prompt.j2"
    prompt.write_text("before")
    spec = StageSpec(name="s", processor="custom", config={"nested": {"files": ["prompt.j2"]}})
    before = stage_input_digest(spec, tmp_path)
    prompt.write_text("after!")
    assert stage_input_digest(spec, tmp_path) != before


def test_same_sized_large_file_change_invalidates_stage(tmp_path):
    prompt = tmp_path / "large.txt"
    prompt.write_bytes(b"a" * (4 * 1024 * 1024 + 1))
    spec = StageSpec(name="s", processor="custom", config={"input": str(prompt)})
    before = stage_input_digest(spec, tmp_path)
    with prompt.open("r+b") as content:
        content.write(b"b")
    assert stage_input_digest(spec, tmp_path) != before


def test_processor_source_change_invalidates_stage(tmp_path):
    source = tmp_path / "extension.py"
    source.write_text("before")
    processor = WriteValue()
    processor._source_file = source
    before = stage_input_digest(processor.spec, tmp_path, processor=processor)
    source.write_text("after!")
    assert stage_input_digest(processor.spec, tmp_path, processor=processor) != before
