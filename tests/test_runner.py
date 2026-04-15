from __future__ import annotations

from pathlib import Path

from deepzero.engine.runner import PipelineRunner
from deepzero.engine.stage import BatchEntry, BatchTool, MapTool, ReduceTool, StageContext, StageResult, StageSpec, Sample
from deepzero.engine.state import RunState, SampleState, StateStore


# -- mock tools --

class MockIngest:
    def __init__(self, samples: list[Sample]):
        self.spec = StageSpec(name="discover", tool="mock_ingest")
        self.samples = samples

    def setup(self, config): pass
    def teardown(self): pass

    def discover(self, target, config, global_config):
        return self.samples

class MockMapTool(MapTool):
    def process(self, ctx: StageContext) -> StageResult:
        if ctx.config.get("crash"):
            raise RuntimeError("intentional crash")
        if ctx.config.get("skip"):
            return StageResult(status="completed", verdict="skip")
        return StageResult(status="completed", data={"mapped": True})

class MockBatchTool(BatchTool):
    def execute_batch(self, entries: list[BatchEntry], config: dict) -> list[StageResult]:
        if config.get("crash"):
            raise RuntimeError("intentional batch crash")
        return [StageResult(status="completed", data={"batched": True})] * len(entries)

class MockReduceTool(ReduceTool):
    def reduce(self, states: list[SampleState], config: dict) -> list[SampleState]:
        if config.get("crash"):
            raise RuntimeError("intentional reduce crash")
        for s in states:
            s.history["rank"] = StageOutput(status="completed", data={"ranked": True})
        # truncate half
        mid = len(states) // 2
        for s in states[mid:]:
            s.verdict = "skipped"
        return states

class StageOutput: # helper
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

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
        map_tool = MockMapTool(StageSpec(name="m", tool="mock", parallel=1))
        batch_tool = MockBatchTool(StageSpec(name="b", tool="mock"))
        
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
            spec = StageSpec(name="discover", tool="crash")
            def setup(self, config): pass
            def teardown(self): pass
            def discover(self, *args): raise RuntimeError("should not happen")
            
        map_tool = MockMapTool(StageSpec(name="m", tool="mock", parallel=1))
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
        map_tool = MockMapTool(StageSpec(name="m", tool="mock", config={"crash": True}, parallel=1))
        
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
        batch_tool = MockBatchTool(StageSpec(name="b", tool="mock", config={"crash": True}))
        
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
        map_tool = MockMapTool(StageSpec(name="m", tool="mock", parallel=4))
        
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
        map_tool = MockMapTool(StageSpec(name="m", tool="mock", config={"limit": 2}, parallel=1))
        
        runner = PipelineRunner(ingest, [(map_tool.spec, map_tool)], store, tmp_path, {})
        result = runner.run(Path("."), run_state)
        
        assert result.status == "completed"
        # 2 map runs + 3 skips due to limit immediately after
        # actually, the limit triggers *after* the stage executes on active samples
        # Wait, in runner limit is applied on still_active post-stage execution.
        assert result.stats["per_stage"]["m"]["skipped"] == 3
        active_count = len([s for s in store.list_samples() if s.is_active()])
        assert active_count == 2
