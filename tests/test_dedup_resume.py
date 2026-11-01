from pathlib import Path

from deepzero.engine.runner import PipelineRunner
from deepzero.engine.stage import IngestProcessor, MapProcessor, ProcessorResult, Sample, StageSpec
from deepzero.engine.state import RunState, StateStore
from deepzero.stages.filter import MetadataFilter


class Discover(IngestProcessor):
    cache_global_keys = ()

    def __init__(self, groups):
        super().__init__(StageSpec("discover", "test_discover"))
        self.groups = groups

    def process(self, ctx, target):
        return [Sample(sid, Path(sid), sid, {"group": group}) for sid, group in self.groups.items()]


class CountingFilter(MetadataFilter):
    def __init__(self, dedup=True):
        config = {"dedup_field": "group"} if dedup else {}
        super().__init__(StageSpec("filter", "metadata_filter", config=config, parallel=1))
        self.seen = []

    def process(self, ctx, entry):
        self.seen.append(entry.sample_id)
        return super().process(ctx, entry)


class AfterFilter(MapProcessor):
    cache_global_keys = ()

    def __init__(self):
        super().__init__(StageSpec("after", "test_after", parallel=1))
        self.seen = []

    def process(self, ctx, entry):
        self.seen.append(entry.sample_id)
        return ProcessorResult.ok(data={"processed": True})


def run(tmp_path, groups, *, refresh=False, dedup=True):
    store = StateStore(tmp_path / "work")
    filter_stage, after_stage = CountingFilter(dedup), AfterFilter()
    runner = PipelineRunner(
        Discover(groups),
        [(filter_stage.spec, filter_stage), (after_stage.spec, after_stage)],
        store,
        tmp_path,
        {},
        refresh_ingest=refresh,
    )
    result = runner.run(tmp_path, store.load_run() or RunState("test"))
    assert result.status == "completed", result.stats
    return store, filter_stage, after_stage


def test_refresh_deduplicates_new_samples_against_cached_samples(tmp_path):
    run(tmp_path, {"a": "same", "b": "other"})
    store, filtered, after = run(tmp_path, {"a": "same", "b": "other", "c": "same"}, refresh=True)
    assert filtered.seen == ["a", "b", "c"]
    assert after.seen == ["a", "b"]
    assert {s.sample_id for s in store.list_samples() if s.is_active()} == {"a", "b"}
    assert "after" not in store.load_sample("c").history


def test_refresh_removal_reconsiders_a_previously_filtered_duplicate(tmp_path):
    run(tmp_path, {"a": "same", "b": "same"})
    store, filtered, after = run(tmp_path, {"b": "same"}, refresh=True)
    assert filtered.seen == after.seen == ["b"]
    assert store.load_sample("b").is_active()
    assert store.load_sample("a") is None


def test_unchanged_resume_keeps_deduplication_cached(tmp_path):
    groups = {"a": "same", "b": "same"}
    run(tmp_path, groups)
    store, filtered, after = run(tmp_path, groups)
    assert filtered.seen == after.seen == []
    assert {s.sample_id for s in store.list_samples() if s.is_active()} == {"a"}


def test_non_deduplicating_filters_preserve_unchanged_sample_results(tmp_path):
    run(tmp_path, {"a": "same"}, dedup=False)
    store, filtered, after = run(tmp_path, {"a": "same", "b": "same"}, refresh=True, dedup=False)
    assert filtered.seen == after.seen == ["b"]
    assert all(s.is_active() for s in store.list_samples())


def test_reusing_a_runner_starts_with_empty_deduplication_state(tmp_path):
    store = StateStore(tmp_path / "work")
    ingest = Discover({"a": "same"})
    filtered = CountingFilter()
    runner = PipelineRunner(ingest, [(filtered.spec, filtered)], store, tmp_path, {})
    assert runner.run(tmp_path, RunState("test")).status == "completed"
    ingest.groups = {"b": "same"}
    runner.refresh_ingest = True
    assert runner.run(tmp_path, store.load_run()).status == "completed"
    assert store.load_sample("b").is_active()
