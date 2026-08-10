import logging
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
from deepzero.engine.state import RunState, StateStore


class E2EIngest(IngestProcessor):
    def __init__(self, samples: list[Sample]):
        from deepzero.engine.stage import StageSpec

        self.spec = StageSpec(name="discover", processor="e2e_ingest")
        self.samples = samples
        self.config = {}

    def process(self, ctx: ProcessorContext, target: Path) -> list[Sample]:
        return self.samples


class E2EMapProcessor(MapProcessor):
    def should_skip(self, ctx: ProcessorContext, entry: ProcessorEntry) -> str | None:
        if self.config.get("cache_marker"):
            return "simulated cache hit"
        return None

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        behavior = self.config.get("behavior", "continue")

        if behavior == "crash":
            raise RuntimeError("intentional map crash")
        if behavior == "fail":
            return ProcessorResult.fail("intentional graceful map error")
        if behavior in ("filter", "drop"):
            return ProcessorResult.filter(behavior)

        data = self.config.get("data", {"mapped": True})
        return ProcessorResult.ok(data=data)


class E2EBatchProcessor(BulkMapProcessor):
    def process(
        self, ctx: ProcessorContext, entries: list[ProcessorEntry]
    ) -> list[ProcessorResult]:
        if self.config.get("behavior") == "crash":
            raise ValueError("intentional batch crash")

        results = []
        for entry in entries:
            if self.config.get("require_map_data"):
                assert "m" in entry.history

            if entry.sample_id == self.config.get("target_fail"):
                results.append(ProcessorResult.fail("targeted batch failure"))
            else:
                results.append(ProcessorResult.ok(data={"batched_size": len(entries)}))
        return results


class E2EReduceProcessor(ReduceProcessor):
    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]:
        threshold = self.config.get("drop_threshold", 0)
        if threshold > 0:
            return [s.sample_id for i, s in enumerate(entries) if i < threshold]
        return [s.sample_id for s in entries]


class TestPipelineE2E:
    def _make_samples(self, n=5) -> list[Sample]:
        return [
            Sample(
                sample_id=f"s{i}",
                source_path=Path(f"s{i}.bin"),
                filename=f"s{i}.bin",
                data={"sha256": f"ABC{i}"},
            )
            for i in range(n)
        ]

    def test_clean_flow_and_data_passing(self, tmp_path):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test_clean", pipeline="e2e")
        store.save_run(run_state)

        ingest = E2EIngest(self._make_samples(10))
        m_proc = E2EMapProcessor(
            StageSpec(
                name="m",
                processor="mock",
                config={"data": {"passed_map": True}},
                parallel=2,
            )
        )
        b_proc = E2EBatchProcessor(
            StageSpec(name="b", processor="mock", config={"require_map_data": True})
        )
        r_proc = E2EReduceProcessor(StageSpec(name="r", processor="mock"))

        runner = PipelineRunner(
            ingest,
            [(m_proc.spec, m_proc), (b_proc.spec, b_proc), (r_proc.spec, r_proc)],
            store,
            tmp_path,
            {},
        )
        result = runner.run(Path("."), run_state)

        assert result.status == "completed"
        assert result.stats["discovered"] == 10
        assert result.stats["per_stage"]["m"]["completed"] == 10
        assert result.stats["per_stage"]["b"]["completed"] == 10

        manifest = store.load_manifest()
        assert len(manifest) == 10

        s0 = store.load_sample("s0")
        assert s0.is_active() is True
        assert s0.history["m"].data["passed_map"] is True
        assert s0.history["b"].data["batched_size"] == 10

    def test_pipeline_funnel_filtering(self, tmp_path):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test_filter", pipeline="e2e")

        ingest = E2EIngest(self._make_samples(5))
        m_proc = E2EMapProcessor(
            StageSpec(name="m", processor="mock", config={"behavior": "filter"}, parallel=1)
        )
        b_proc = E2EBatchProcessor(StageSpec(name="b", processor="mock"))

        runner = PipelineRunner(
            ingest, [(m_proc.spec, m_proc), (b_proc.spec, b_proc)], store, tmp_path, {}
        )
        result = runner.run(Path("."), run_state)

        assert result.stats["per_stage"]["m"]["filtered"] == 5
        # batch stage may be skipped entirely when no active samples remain
        b_stats = result.stats["per_stage"].get("b", {"completed": 0})
        assert b_stats["completed"] == 0

    def test_graceful_failures_logged(self, tmp_path, caplog):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test_fail", pipeline="e2e")

        ingest = E2EIngest(self._make_samples(1))
        m_proc = E2EMapProcessor(StageSpec(name="m", processor="mock", config={"behavior": "fail"}))

        logger = logging.getLogger("deepzero")
        logger.setLevel(logging.DEBUG)

        runner = PipelineRunner(ingest, [(m_proc.spec, m_proc)], store, tmp_path, {})

        with caplog.at_level(logging.ERROR, logger="deepzero"):
            runner.run(Path("."), run_state)

        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) >= 1
        assert any("intentional graceful map error" in r.message for r in errors)

    def test_interrupt_and_caching_simulation(self, tmp_path):
        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="test_int", pipeline="e2e")

        ingest = E2EIngest(self._make_samples(2))

        m_proc1 = E2EMapProcessor(StageSpec(name="m1", processor="mock_success"))

        from deepzero.engine.stage import FailurePolicy

        m_proc2_crash = E2EMapProcessor(
            StageSpec(name="m2", processor="mock_crash", config={"behavior": "crash"})
        )
        m_proc2_crash.spec.on_failure = FailurePolicy.ABORT

        runner1 = PipelineRunner(
            ingest,
            [(m_proc1.spec, m_proc1), (m_proc2_crash.spec, m_proc2_crash)],
            store,
            tmp_path,
            {},
        )
        runner1.run(Path("."), run_state)

        # abort causes the first crash to stop the pipeline - status depends on runner implementation
        assert run_state.status in ("interrupted", "completed", "failed")

        # resume with m1 unchanged, so its results still describe this pipeline
        # and the stage is not asked to do them again. Its config has to match:
        # a stage whose inputs changed is stale, which is tested below.
        m_proc1_resumed = E2EMapProcessor(StageSpec(name="m1", processor="mock_success"))
        m_proc2_resumed = E2EMapProcessor(StageSpec(name="m2", processor="mock_success"))

        runner2 = PipelineRunner(
            ingest,
            [
                (m_proc1_resumed.spec, m_proc1_resumed),
                (m_proc2_resumed.spec, m_proc2_resumed),
            ],
            store,
            tmp_path,
            {},
        )
        res = runner2.run(Path("."), run_state)

        assert res.status == "completed"
        assert res.stats["per_stage"]["m1"]["completed"] == 2

    def _processed_by(self, store, tmp_path, spec, ingest, run_id):
        """run a one-stage pipeline and report which samples it actually worked.

        Counted at the processor rather than read off the stage stats, because a
        cached sample is reported as completed there too. That is right for
        somebody watching progress and useless for deciding whether the work
        happened.
        """
        proc = E2EMapProcessor(spec)
        worked: list[str] = []
        inner = proc.process

        def counting(ctx, entry):
            worked.append(entry.sample_id)
            return inner(ctx, entry)

        proc.process = counting
        PipelineRunner(ingest, [(spec, proc)], store, tmp_path, {}).run(
            Path("."), RunState(run_id=run_id, pipeline="e2e")
        )
        return worked

    def test_editing_a_stage_makes_its_results_stale(self, tmp_path):
        """A result is only worth keeping while it still describes the pipeline
        that produced it. Change what a stage reads and its old answers are about
        a question nobody is asking any more, so a resumed run redoes that stage
        rather than reporting the previous answer as current."""
        store = StateStore(tmp_path / "work")
        ingest = E2EIngest(self._make_samples(2))

        first = self._processed_by(
            store,
            tmp_path,
            StageSpec(name="m1", processor="mock", config={"data": {"v": 1}}),
            ingest,
            "a",
        )
        assert len(first) == 2
        assert all(s.history["m1"].data == {"v": 1} for s in store.list_samples())

        second = self._processed_by(
            store,
            tmp_path,
            StageSpec(name="m1", processor="mock", config={"data": {"v": 2}}),
            ingest,
            "b",
        )
        assert len(second) == 2, "a stage whose config changed has to run again"
        assert all(s.history["m1"].data == {"v": 2} for s in store.list_samples())

    def test_an_untouched_stage_is_not_redone(self, tmp_path):
        """the other half of the same promise: nothing changed, nothing repeats,
        which is what makes resuming a long run worth anything."""
        store = StateStore(tmp_path / "work")
        ingest = E2EIngest(self._make_samples(2))
        config = {"data": {"v": 1}}

        first = self._processed_by(
            store, tmp_path, StageSpec(name="m1", processor="mock", config=config), ingest, "a"
        )
        assert len(first) == 2

        again = self._processed_by(
            store,
            tmp_path,
            StageSpec(name="m1", processor="mock", config=dict(config)),
            ingest,
            "b",
        )
        assert again == [], "an unchanged stage must not process anything again"
