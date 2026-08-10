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
        assert s.clear_stages_from(["assess"], ORDER) == []
        assert set(s.history) == {"discover", "decompile"}

    def test_an_unknown_stage_name_is_ignored_rather_than_clearing_everything(self):
        """the cli rejects unknown names, and the state layer must not fall back
        to dropping the whole history if one slips through."""
        s = _sample(*ORDER)
        assert s.clear_stages_from(["nonsense"], ORDER) == []
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
