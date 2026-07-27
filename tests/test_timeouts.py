"""running out of time is a statement about the budget, not about the sample."""

from __future__ import annotations

from deepzero.engine.state import SampleState, StateStore
from deepzero.engine.types import SampleStatus, StageStatus


class TestATimeoutIsNotAFailure:
    def test_it_is_recorded_as_its_own_outcome(self):
        s = SampleState(sample_id="a", filename="big.sys")
        s.mark_stage_timed_out("decompile", 600)
        assert s.history["decompile"].status == StageStatus.TIMED_OUT
        assert s.verdict == SampleStatus.TIMED_OUT
        # and never as the thing it is most easily mistaken for
        assert s.history["decompile"].status != StageStatus.FAILED
        assert s.verdict != SampleStatus.FAILED

    def test_the_budget_it_exceeded_is_kept(self):
        s = SampleState(sample_id="a", filename="big.sys")
        s.mark_stage_timed_out("decompile", 600)
        assert s.timed_out_budget() == 600
        assert "600s" in s.history["decompile"].error

    def test_a_resumed_run_does_not_silently_retry_it(self):
        # the budget that was too short is still too short; asking is the point
        s = SampleState(sample_id="a", filename="big.sys")
        s.mark_stage_timed_out("decompile", 600)
        assert s.is_stage_done("decompile")

    def test_it_does_not_keep_the_sample_active(self):
        s = SampleState(sample_id="a", filename="big.sys")
        s.mark_stage_timed_out("decompile", 600)
        assert not s.is_active()


class TestRetryingKeepsEverythingElse:
    def _sample(self) -> SampleState:
        s = SampleState(sample_id="a", filename="big.sys")
        s.mark_stage_completed("discover", data={"sha256": "abc", "size_bytes": 900})
        s.mark_stage_timed_out("decompile", 600)
        return s

    def test_only_the_timed_out_stage_is_forgotten(self):
        s = self._sample()
        assert s.clear_timed_out_stages() == ["decompile"]
        # the work already done is not thrown away to retry the part that was not
        assert "discover" in s.history
        assert s.history["discover"].data["sha256"] == "abc"
        assert "decompile" not in s.history

    def test_the_sample_becomes_runnable_again(self):
        s = self._sample()
        s.clear_timed_out_stages()
        assert s.is_active()
        assert s.verdict == SampleStatus.ACTIVE
        assert not s.error
        assert not s.is_stage_done("decompile")

    def test_a_sample_that_did_not_time_out_is_untouched(self):
        s = SampleState(sample_id="b", filename="ok.sys")
        s.mark_stage_completed("discover")
        s.mark_stage_failed("decompile", "ghidra crashed")
        assert s.clear_timed_out_stages() == []
        # a real error is not quietly cleared by asking to retry timeouts
        assert s.history["decompile"].status == StageStatus.FAILED
        assert s.verdict == SampleStatus.FAILED

    def test_it_survives_a_round_trip_through_disk(self, tmp_path):
        store = StateStore(tmp_path / "work")
        store.save_sample(self._sample())
        loaded = next(s for s in store.list_samples() if s.sample_id == "a")
        assert loaded.verdict == SampleStatus.TIMED_OUT
        assert loaded.timed_out_budget() == 600


class TestTheRunnerSeparatesThemFromCrashes:
    def test_a_generic_handler_would_claim_a_timeout_first(self):
        from deepzero.engine.runner import PROCESSOR_ERRORS

        # TimeoutError is an OSError, so the dedicated handler has to come
        # before this one or running out of time is filed as something breaking
        assert issubclass(TimeoutError, PROCESSOR_ERRORS)

    def test_a_stage_that_runs_long_is_recorded_as_out_of_time(self, tmp_path):
        import time
        from pathlib import Path

        from deepzero.engine.runner import PipelineRunner
        from deepzero.engine.stage import (
            MapProcessor,
            ProcessorContext,
            ProcessorEntry,
            ProcessorResult,
            Sample,
            StageSpec,
        )
        from deepzero.engine.state import RunState

        class Slow(MapProcessor):
            def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
                time.sleep(2)
                return ProcessorResult.ok()

        class Ingest:
            spec = StageSpec(name="discover", processor="mock_ingest")

            def setup(self, config):
                pass

            def teardown(self):
                pass

            def process(self, ctx, target):
                return [Sample("s0", Path("s0.sys"), "s0.sys", {})]

        store = StateStore(tmp_path / "work")
        run_state = RunState(run_id="t", pipeline="t")
        store.save_run(run_state)
        slow = Slow(StageSpec(name="slow", processor="mock", parallel=1, timeout=1))
        runner = PipelineRunner(Ingest(), [(slow.spec, slow)], store, tmp_path, {})
        runner.run(Path("."), run_state)

        state = next(s for s in store.list_samples() if s.sample_id == "s0")
        assert state.verdict == SampleStatus.TIMED_OUT, f"got {state.verdict}"
        assert state.history["slow"].status == StageStatus.TIMED_OUT
        assert state.timed_out_budget() == 1


class TestTheReportGivesThemTheirOwnGroup:
    def _work(self, tmp_path):
        from deepzero.engine.state import RunState
        from deepzero.engine.types import RunStatus

        work = tmp_path / "work" / "p"
        store = StateStore(work)
        store.save_run(
            RunState(run_id="r", pipeline="p", target="C:/corpus", status=RunStatus.COMPLETED)
        )
        big = SampleState(sample_id="big", filename="big.sys")
        big.mark_stage_completed("discover", data={"size_bytes": 900})
        big.mark_stage_timed_out("decompile", 600)
        store.save_sample(big)

        broken = SampleState(sample_id="broke", filename="broke.sys")
        broken.mark_stage_completed("discover")
        broken.mark_stage_failed("decompile", "ghidra crashed")
        store.save_sample(broken)
        return work

    def test_it_is_not_grouped_with_genuine_errors(self, tmp_path):
        from deepzero.engine.report import BUCKET_FAILED, BUCKET_TIMED_OUT, collect

        payload = collect(self._work(tmp_path))
        buckets = {i.sample_id: i.bucket for i in payload["items"]}
        assert buckets["big"] == BUCKET_TIMED_OUT
        assert buckets["broke"] == BUCKET_FAILED
        assert payload["buckets"][BUCKET_TIMED_OUT] == 1

    def test_it_is_not_counted_as_clear(self, tmp_path):
        from deepzero.engine.report import BUCKET_CLEAN, collect

        payload = collect(self._work(tmp_path))
        assert payload["buckets"].get(BUCKET_CLEAN, 0) == 0

    def test_the_page_shows_the_budget_that_was_exceeded(self, tmp_path):
        from deepzero.engine.report import collect, render_index

        out = render_index(collect(self._work(tmp_path)), tmp_path)
        assert "Ran out of time" in out
        assert "600s" in out
        # and says what to do about it rather than only that it happened
        assert "--retry-timeouts" in out
