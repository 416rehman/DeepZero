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

    def test_historical_resumption_math(self, tmp_path):
        from deepzero.engine.state import Verdict

        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test", pipeline="test")
        store.save_run(run_state)

        # simulate an aborted run with 4 discovered samples
        # 2 passed stage1, 1 filtered, 1 failed
        s0 = SampleState("s0", "h0", "s0.sys", "active")
        s0.mark_stage_completed("discover", data={})
        s0.mark_stage_completed("stage1", verdict=Verdict.CONTINUE)

        s1 = SampleState("s1", "h1", "s1.sys", "active")
        s1.mark_stage_completed("discover", data={})
        s1.mark_stage_completed("stage1", verdict=Verdict.CONTINUE)

        s2 = SampleState("s2", "h2", "s2.sys", "filtered")
        s2.mark_stage_completed("discover", data={})
        s2.mark_stage_completed("stage1", verdict=Verdict.FILTER)

        s3 = SampleState("s3", "h3", "s3.sys", "failed")
        s3.mark_stage_completed("discover", data={})
        s3.mark_stage_failed("stage1", "synthetic err")

        store.save_sample(s0)
        store.save_sample(s1)
        store.save_sample(s2)
        store.save_sample(s3)

        class CrashIngest:
            spec = StageSpec(name="discover", processor="crash")

            def setup(self, config):
                pass

            def teardown(self):
                pass

            def process(self, *args):
                raise RuntimeError()

        map_tool = MockMapProcessor(StageSpec(name="stage1", processor="mock"))
        runner = PipelineRunner(CrashIngest(), [(map_tool.spec, map_tool)], store, tmp_path, {})

        result = runner.run(Path("."), run_state)

        assert result.status == "completed"
        assert result.stats["discovered"] == 4

        stats = result.stats["per_stage"]["stage1"]
        assert stats["completed"] == 2
        assert stats["filtered"] == 1
        assert stats["failed"] == 1
        active_count = len([s for s in store.list_samples() if s.is_active()])
        assert active_count == 2

    def test_shutdown_event_aborts_state_mutation(self, tmp_path):
        import threading
        import time

        from deepzero.engine.stage import ProcessorResult, StageStatus

        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test", pipeline="test")
        store.save_run(run_state)

        ingest = MockIngest(self._make_samples(10))

        class LateFailProcessor:
            spec = StageSpec(name="late_fail", processor="late", parallel=4)

            def setup(self, config):
                pass

            def teardown(self):
                pass

            def process(self, ctx, entry):
                time.sleep(0.1)
                return ProcessorResult.fail("synthetic delayed failure")

            def should_skip(self, ctx, entry):
                return False

        map_tool = LateFailProcessor()

        runner = PipelineRunner(ingest, [(map_tool.spec, map_tool)], store, tmp_path, {})

        def _simulate_interrupt():
            time.sleep(0.05)
            runner._shutdown_event.set()

        t = threading.Thread(target=_simulate_interrupt)
        t.start()

        runner.run(Path("."), run_state)
        t.join()

        samples = store.list_samples()
        for s in samples:
            if "late_fail" in s.history:
                assert s.history["late_fail"].status != StageStatus.FAILED
