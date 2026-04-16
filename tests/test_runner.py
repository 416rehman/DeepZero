from __future__ import annotations

from pathlib import Path

from deepzero.engine.runner import PipelineRunner
from deepzero.engine.stage import (
    BulkMapProcessor,
    MapProcessor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
    ReduceProcessor,
    Sample,
    StageSpec,
)
from deepzero.engine.state import RunState, SampleState, StateStore

# -- mock tools --


class MockIngest:
    def __init__(self, samples: list[Sample]):
        self.spec = StageSpec(name="discover", processor="mock_ingest")
        self.samples = samples

    def setup(self, config):
        pass

    def teardown(self):
        pass

    def process(self, ctx, target):
        return self.samples


class MockMapProcessor(MapProcessor):
    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        if self.config.get("crash"):
            raise RuntimeError("intentional crash")
        if self.config.get("skip"):
            return ProcessorResult(status="completed", verdict="skip")
        return ProcessorResult(status="completed", data={"mapped": True})


class MockBulkMapProcessor(BulkMapProcessor):
    def process(
        self, ctx: ProcessorContext, entries: list[ProcessorEntry]
    ) -> list[ProcessorResult]:
        if self.config.get("crash"):
            raise RuntimeError("intentional batch crash")
        return [ProcessorResult(status="completed", data={"batched": True})] * len(entries)


class MockReduceProcessor(ReduceProcessor):
    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]:
        if self.config.get("crash"):
            raise RuntimeError("intentional reduce crash")
        # truncate half
        mid = len(entries) // 2
        return [e.sample_id for e in entries[:mid]]


# -- tests --


class TestPipelineRunner:
    def _make_samples(self, n=5) -> list[Sample]:
        samples = []
        for i in range(n):
            samples.append(Sample(f"s{i}", Path(f"s{i}.sys"), f"s{i}.sys", {"sha256": f"s{i}"}))
        return samples

    def test_run_executes_pipeline(self, tmp_path):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test", pipeline="test")
        store.save_run(run_state)

        ingest = MockIngest(self._make_samples(3))
        map_tool = MockMapProcessor(StageSpec(name="m", processor="mock", parallel=1))
        batch_tool = MockBulkMapProcessor(StageSpec(name="b", processor="mock"))

        stages = [
            (map_tool.spec, map_tool),
            (batch_tool.spec, batch_tool),
        ]

        runner = PipelineRunner(ingest, stages, store, tmp_path, {})
        result = runner.run(Path("."), run_state)

        assert result.status == "completed"
        # 3 initial samples
        assert result.stats["discovered"] == 3
        # map step
        assert result.stats["per_stage"]["m"]["completed"] == 3
        assert result.stats["per_stage"]["b"]["completed"] == 3

    def test_fast_resume_skips_ingest(self, tmp_path):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test", pipeline="test")
        store.save_run(run_state)

        s = SampleState("pre", "pre", "pre.sys", "active")
        s.mark_stage_completed("discover", data={})
        s.verdict = "active"
        store.save_sample(s)

        # Ingest will crash if called, proving we skip it via manifest!
        class CrashIngest:
            spec = StageSpec(name="discover", processor="crash")

            def setup(self, config):
                pass

            def teardown(self):
                pass

            def process(self, *args):
                raise RuntimeError("should not happen")

        map_tool = MockMapProcessor(StageSpec(name="m", processor="mock", parallel=1))
        runner = PipelineRunner(CrashIngest(), [(map_tool.spec, map_tool)], store, tmp_path, {})
        result = runner.run(Path("."), run_state)

        assert result.status == "completed"
        assert result.stats["discovered"] == 1
        assert result.stats["per_stage"]["m"]["completed"] == 1

    def test_map_tool_exception_isolation(self, tmp_path):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test", pipeline="test")
        store.save_run(run_state)

        ingest = MockIngest(self._make_samples(2))
        map_tool = MockMapProcessor(
            StageSpec(name="m", processor="mock", config={"crash": True}, parallel=1)
        )

        runner = PipelineRunner(ingest, [(map_tool.spec, map_tool)], store, tmp_path, {})
        result = runner.run(Path("."), run_state)

        assert result.status == "completed"
        assert result.stats["per_stage"]["m"]["failed"] == 2

        s0 = store.load_sample("s0")
        assert s0.verdict == "failed"
        assert s0.error is not None

    def test_batch_tool_exception_isolation(self, tmp_path):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test", pipeline="test")
        store.save_run(run_state)

        ingest = MockIngest(self._make_samples(2))
        batch_tool = MockBulkMapProcessor(
            StageSpec(name="b", processor="mock", config={"crash": True})
        )

        runner = PipelineRunner(ingest, [(batch_tool.spec, batch_tool)], store, tmp_path, {})
        result = runner.run(Path("."), run_state)

        assert result.status == "completed"
        assert result.stats["per_stage"]["b"]["failed"] == 2

        s0 = store.load_sample("s0")
        assert s0.verdict == "failed"

    def test_map_tool_parallel_threads(self, tmp_path):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test", pipeline="test")
        store.save_run(run_state)

        ingest = MockIngest(self._make_samples(10))
        # use parallel=4
        map_tool = MockMapProcessor(StageSpec(name="m", processor="mock", parallel=4))

        runner = PipelineRunner(ingest, [(map_tool.spec, map_tool)], store, tmp_path, {})
        result = runner.run(Path("."), run_state)

        assert result.status == "completed"
        assert result.stats["per_stage"]["m"]["completed"] == 10

    def test_dumb_limit_truncation(self, tmp_path):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test", pipeline="test")
        store.save_run(run_state)

        ingest = MockIngest(self._make_samples(5))
        # Limit 2 - stage config
        map_tool = MockMapProcessor(
            StageSpec(name="m", processor="mock", config={"limit": 2}, parallel=1)
        )

        runner = PipelineRunner(ingest, [(map_tool.spec, map_tool)], store, tmp_path, {})
        result = runner.run(Path("."), run_state)

        assert result.status == "completed"
        # 2 map runs + 3 skips due to limit immediately after
        # actually, the limit triggers *after* the stage executes on active samples
        # Wait, in runner limit is applied on still_active post-stage execution.
        assert result.stats["per_stage"]["m"]["filtered"] == 3
        active_count = len([s for s in store.list_samples() if s.is_active()])
        assert active_count == 2
