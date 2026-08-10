from __future__ import annotations

from deepzero.engine.state import SampleState
from deepzero.engine.types import SampleStatus, Verdict

ORDER = ["discover", "decompile", "scan", "rank", "assess"]


def _sample(*stages: str) -> SampleState:
    s = SampleState(sample_id="a1", filename="a.sys")
    for name in stages:
        s.mark_stage_completed(name, data={"from": name})
    return s


class TestRedoingAStageKeepsTheWorkBeforeIt:
    """Re-running a prompt or a rule set must not mean decompiling everything
    again. Decompilation is the expensive stage and its output does not change
    when a later stage's configuration does."""

    def test_the_named_stage_and_everything_after_it_are_forgotten(self):
        s = _sample(*ORDER)
        reset = s.clear_stages_from(["scan"], ORDER)
        assert set(reset) == {"scan", "rank", "assess"}
        assert set(s.history) == {"discover", "decompile"}

    def test_the_expensive_earlier_stages_survive_untouched(self):
        s = _sample(*ORDER)
        s.clear_stages_from(["assess"], ORDER)
        assert s.history["decompile"].data == {"from": "decompile"}
        assert set(s.history) == {"discover", "decompile", "scan", "rank"}

    def test_a_later_stage_is_not_left_describing_output_that_is_gone(self):
        """an assessment written from findings that no longer exist would have a
        sample describing two different runs at once, so redoing a stage takes
        the stages that consumed it with it."""
        s = _sample(*ORDER)
        s.clear_stages_from(["decompile"], ORDER)
        assert "assess" not in s.history
        assert "scan" not in s.history

    def test_a_filtered_sample_rejoins_the_run(self):
        """a sample the old scan excluded must be reconsidered by the new one,
        otherwise redoing a stage silently keeps its previous verdict."""
        s = _sample("discover", "decompile")
        s.mark_stage_skipped("scan", "no findings")
        assert s.verdict == SampleStatus.FILTERED
        s.clear_stages_from(["scan"], ORDER)
        assert s.verdict == SampleStatus.ACTIVE
        assert "scan" not in s.history

    def test_naming_several_stages_starts_from_the_earliest(self):
        s = _sample(*ORDER)
        reset = s.clear_stages_from(["assess", "scan"], ORDER)
        assert set(reset) == {"scan", "rank", "assess"}

    def test_a_stage_the_sample_never_reached_changes_nothing(self):
        s = _sample("discover", "decompile")
        assert s.clear_stages_from(["assess"], ORDER) == {}
        assert set(s.history) == {"discover", "decompile"}

    def test_an_unknown_stage_name_is_ignored_rather_than_clearing_everything(self):
        """the cli rejects unknown names, and the state layer must not fall back
        to dropping the whole history if one slips through."""
        s = _sample(*ORDER)
        assert s.clear_stages_from(["nonsense"], ORDER) == {}
        assert set(s.history) == set(ORDER)

    def test_the_verdict_of_a_redone_sample_is_not_left_stale(self):
        s = _sample(*ORDER)
        s.error = "something failed earlier"
        s.clear_stages_from(["scan"], ORDER)
        assert s.error is None
        assert s.verdict == SampleStatus.ACTIVE
        assert s.current_stage == ""

    def test_verdict_enum_is_untouched_for_surviving_stages(self):
        s = _sample("discover", "decompile", "scan")
        s.clear_stages_from(["scan"], ORDER)
        assert s.history["decompile"].verdict == Verdict.CONTINUE


class TestRedoingAStageTheRunHasNotReachedYet:
    """Naming a stage that is ahead of where a sample got to must be harmless.
    A corpus is rarely uniform: a sample can fail early, be filtered early, or
    simply not have been reached when the run was interrupted."""

    def test_a_sample_that_stopped_early_is_left_alone(self):
        s = _sample("discover", "decompile")
        assert s.clear_stages_from(["assess"], ORDER) == {}
        assert set(s.history) == {"discover", "decompile"}
        # still active, so the run carries it forward through the stages it owes
        assert s.verdict != SampleStatus.FILTERED

    def test_a_sample_filtered_before_the_redone_stage_stays_filtered(self):
        """a driver dropped for having no ioctl surface must not be dragged back
        into the run by redoing a stage it never reached, or every redo would
        widen the corpus."""
        s = _sample("discover")
        s.mark_stage_skipped("decompile", "no ioctl surface")
        assert s.verdict == SampleStatus.FILTERED
        assert s.clear_stages_from(["assess"], ORDER) == {}
        assert s.verdict == SampleStatus.FILTERED

    def test_a_failed_earlier_stage_is_not_resurrected(self):
        s = _sample("discover")
        s.mark_stage_failed("decompile", "ghidra crashed")
        assert s.clear_stages_from(["assess"], ORDER) == {}
        assert s.history["decompile"].status.value == "failed"


class TestRedoingTakesTheStagesOutputWithIt:
    """Several processors treat their own output on disk as a cache and skip
    when it is present. Forgetting only the state would have them re-adopt the
    stale file and record it as fresh, which reads as done and is not."""

    def test_the_artifacts_of_a_dropped_stage_are_reported(self):
        s = SampleState(sample_id="a1", filename="a.sys")
        s.mark_stage_completed("discover")
        s.mark_stage_completed(
            "decompile", artifacts={"ghidra_result": "decompiled/ghidra_result.json"}
        )
        s.mark_stage_completed("scan", artifacts={"findings": "findings.json"})
        dropped = s.clear_stages_from(["scan"], ORDER)
        assert dropped == {"scan": ["findings.json"]}

    def test_earlier_artifacts_are_not_reported_for_deletion(self):
        """the expensive decompiler output is exactly what a redo is meant to
        keep, so it must never appear in the list of things to remove."""
        s = SampleState(sample_id="a1", filename="a.sys")
        s.mark_stage_completed(
            "decompile", artifacts={"ghidra_result": "decompiled/ghidra_result.json"}
        )
        s.mark_stage_completed("scan", artifacts={"findings": "findings.json"})
        dropped = s.clear_stages_from(["scan"], ORDER)
        assert "decompile" not in dropped
        assert all("decompiled" not in p for paths in dropped.values() for p in paths)

    def test_a_stage_with_no_artifacts_reports_an_empty_list(self):
        s = _sample("discover", "decompile", "scan")
        assert s.clear_stages_from(["scan"], ORDER) == {"scan": []}
