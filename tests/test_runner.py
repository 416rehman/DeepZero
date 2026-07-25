from __future__ import annotations

from pathlib import Path

from deepzero.engine.runner import PipelineRunner
from deepzero.engine.stage import (
    BulkMapProcessor,
    IngestProcessor,
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


class TestResolveParallelism:
    # _resolve_parallelism uses no instance state, so call it unbound with None
    class _CeilingProc(MapProcessor):
        def max_parallelism(self):
            return 3

        def process(self, ctx, entry):
            return ProcessorResult.ok()

    class _NoCeilingProc(MapProcessor):
        def process(self, ctx, entry):
            return ProcessorResult.ok()

    def test_auto_is_capped_to_processor_ceiling(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 32)
        proc = self._CeilingProc(StageSpec(name="d", processor="x"))
        spec = StageSpec(name="d", processor="x", parallel=0)
        assert PipelineRunner._resolve_parallelism(None, spec, proc) == 3

    def test_explicit_parallel_is_honored_over_ceiling(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 32)
        proc = self._CeilingProc(StageSpec(name="d", processor="x"))
        spec = StageSpec(name="d", processor="x", parallel=20)
        assert PipelineRunner._resolve_parallelism(None, spec, proc) == 20

    def test_auto_uses_cpu_when_no_ceiling(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        proc = self._NoCeilingProc(StageSpec(name="d", processor="x"))
        spec = StageSpec(name="d", processor="x", parallel=0)
        assert PipelineRunner._resolve_parallelism(None, spec, proc) == 8


class TestCachedSamplesStayInThePipeline:
    """a sample whose work was already done still flows to the following
    stages. skipping work is not the same as filtering the sample out: a
    resumed run must analyse exactly what a fresh run would."""

    class _AlreadyDone(MapProcessor):
        def should_skip(self, ctx, entry):
            return "output already cached"

        def process(self, ctx, entry):
            raise AssertionError("process() must not run when should_skip returns a reason")

    class _Counting(MapProcessor):
        seen: list = []

        def process(self, ctx, entry):
            type(self).seen.append(entry.sample_id)
            return ProcessorResult.ok(data={"ran": True})

    def test_cached_stage_is_completed_not_filtered(self, tmp_path):
        from deepzero.engine.state import SampleState
        from deepzero.engine.types import SampleStatus, StageStatus, Verdict

        state = SampleState(sample_id="s1", filename="a.sys")
        state.mark_stage_cached("decompile", "output already cached")

        out = state.history["decompile"]
        assert out.status == StageStatus.COMPLETED
        assert out.verdict == Verdict.CONTINUE
        assert out.skip_reason == "output already cached"
        # a skip reason is not an error
        assert out.error is None
        # and the sample is still eligible for later stages
        assert state.verdict != SampleStatus.FILTERED

    def test_skip_reason_is_not_stored_as_an_error(self, tmp_path):
        from deepzero.engine.state import SampleState

        state = SampleState(sample_id="s1", filename="a.sys")
        state.mark_stage_skipped("kernel_filter", "not a kernel driver")
        out = state.history["kernel_filter"]
        assert out.skip_reason == "not a kernel driver"
        assert out.error is None

    def test_downstream_stage_still_sees_a_cached_sample(self, tmp_path):
        type(self._Counting).seen = []
        self._Counting.seen = []
        store = StateStore(tmp_path / "work")
        run = RunState(run_id="r1", pipeline="p")
        store.save_run(run)

        target = tmp_path / "a.sys"
        target.write_bytes(b"MZ")

        class OneSample(IngestProcessor):
            def __init__(self):
                self.spec = StageSpec(name="discover", processor="i")
                self.config = {}

            def setup(self, global_config):
                pass

            def process(self, ctx, t):
                return [Sample(sample_id="s1", source_path=target, filename="a.sys")]

        cached_spec = StageSpec(name="decompile", processor="x")
        after_spec = StageSpec(name="scan", processor="y")
        after = self._Counting(after_spec)

        runner = PipelineRunner(
            ingest=OneSample(),
            stages=[(cached_spec, self._AlreadyDone(cached_spec)), (after_spec, after)],
            state_store=store,
            pipeline_dir=tmp_path,
            global_config={},
        )
        runner.run(tmp_path, run)

        # the whole point: the cached sample reached the next stage
        assert after.seen == ["s1"], "cached sample was dropped before the next stage"
        final = store.load_sample("s1")
        assert "scan" in final.history
