from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from deepzero.engine.runner import PipelineRunner
from deepzero.engine.stage import IngestProcessor, Sample, StageSpec
from deepzero.engine.state import RunState, StateStore


class SnapshotIngest(IngestProcessor):
    def __init__(self, samples, config=None, interrupt=False):
        super().__init__(StageSpec("discover", "snapshot", config=config or {}))
        self.samples = samples
        self.calls = 0
        self.interrupt = interrupt

    def process(self, ctx, target):
        self.calls += 1
        if self.interrupt:
            ctx.shutdown_event.set()
        return self.samples


def sample(sample_id, revision=1):
    return Sample(sample_id, Path(f"{sample_id}.txt"), f"{sample_id}.txt", {"revision": revision})


def discover(tmp_path, ingest, refresh=False):
    store = StateStore(tmp_path / "work")
    runner = PipelineRunner(ingest, [], store, tmp_path, {}, refresh_ingest=refresh)
    run = store.load_run() or RunState("refresh-test")
    runner._active_run_state = run
    result = runner._resume_or_ingest(tmp_path, run, ["discover", "assess"])
    return runner, store, run, result


def seed_assessment(tmp_path, samples):
    _, store, _, _ = discover(tmp_path, SnapshotIngest(samples))
    for state in store.list_samples():
        artifact = store.sample_dir(state.sample_id) / "assessment.md"
        artifact.write_text("previous assessment", encoding="utf-8")
        state.mark_stage_completed(
            "assess", artifacts={"assessment": "assessment.md"}, data={"answer": "kept"}
        )
        store.save_sample(state)
    return store


def test_default_resume_keeps_frozen_discovery_snapshot(tmp_path):
    seed_assessment(tmp_path, [sample("old")])
    ingest = SnapshotIngest([sample("new")])

    _, store, _, result = discover(tmp_path, ingest)

    assert ingest.calls == 0
    assert set(result) == {"old"}
    assert store.load_sample("old").history["assess"].data == {"answer": "kept"}


def test_refresh_merges_new_ids_preserves_unchanged_and_retires_removed(tmp_path):
    store = seed_assessment(tmp_path, [sample("kept"), sample("removed")])
    kept_result = store.load_sample("kept").history["assess"]

    _, store, run, result = discover(
        tmp_path, SnapshotIngest([sample("kept"), sample("added")]), refresh=True
    )

    assert set(result) == {"kept", "added"}
    assert {state.sample_id for state in store.list_samples()} == {"kept", "added"}
    assert result["kept"].history["assess"] == kept_result
    assert "assess" not in result["added"].history
    assert run.stats["discovered"] == 2
    assert {row["sample_id"] for row in store.load_manifest()} == {"kept", "added"}
    archives = list((store.work_dir / "retired_samples").glob("removed-*"))
    assert len(archives) == 1
    assert (archives[0] / "assessment.md").read_text(encoding="utf-8") == "previous assessment"
    assert store.load_sample("removed") is None


@pytest.mark.parametrize(
    "changed",
    [
        sample("same", revision=2),
        replace(sample("same"), source_path=Path("moved.txt")),
        replace(sample("same"), filename="renamed.txt"),
    ],
)
def test_changed_discovery_invalidates_downstream_and_artifacts(tmp_path, changed):
    seed_assessment(tmp_path, [sample("same")])

    _, store, _, result = discover(tmp_path, SnapshotIngest([changed]), refresh=True)

    assert set(result["same"].history) == {"discover"}
    assert result["same"].history["discover"].data == changed.data
    assert not (store.sample_dir("same") / "assessment.md").exists()
    assert result["same"].history["discover"].input_digest


def test_changed_ingest_configuration_refreshes_discovery(tmp_path):
    seed_assessment(tmp_path, [sample("kept")])
    ingest = SnapshotIngest([sample("kept"), sample("added")], config={"include": "all"})

    runner, _, _, result = discover(tmp_path, ingest)

    assert ingest.calls == 1
    assert set(result) == {"kept", "added"}
    assert "assess" in result["kept"].history
    assert result["kept"].history["discover"].input_digest == runner._digest_for(ingest.spec)


def test_unchanged_refresh_preserves_corpus_conclusion(tmp_path):
    store = seed_assessment(tmp_path, [sample("kept")])
    run = store.load_run()
    run.conclusion = {"summary": "existing conclusion"}
    store.save_run(run)

    _, store, run, _ = discover(tmp_path, SnapshotIngest([sample("kept")]), refresh=True)

    assert run.conclusion == {"summary": "existing conclusion"}
    assert store.load_run().conclusion == run.conclusion


def test_reset_ingest_history_refreshes_instead_of_reusing_sample_membership(tmp_path):
    store = seed_assessment(tmp_path, [sample("old")])
    state = store.load_sample("old")
    del state.history["discover"]
    store.save_sample(state)
    ingest = SnapshotIngest([sample("new")])

    _, store, _, result = discover(tmp_path, ingest)

    assert ingest.calls == 1
    assert set(result) == {"new"}
    assert store.load_sample("old") is None


def test_empty_refresh_removes_old_samples_from_active_results(tmp_path):
    seed_assessment(tmp_path, [sample("old")])

    _, store, run, result = discover(tmp_path, SnapshotIngest([]), refresh=True)

    assert result is None
    assert store.list_samples() == []
    assert store.load_manifest() == []
    assert run.stats["discovered"] == 0
    assert run.status == "completed"


def test_interrupted_refresh_preserves_existing_snapshot(tmp_path):
    seed_assessment(tmp_path, [sample("old")])

    _, store, run, result = discover(
        tmp_path, SnapshotIngest([sample("new")], interrupt=True), refresh=True
    )

    assert result is None
    assert run.status == "interrupted"
    assert {state.sample_id for state in store.list_samples()} == {"old"}
    assert "assess" in store.load_sample("old").history
    assert not (store.work_dir / "retired_samples").exists()


def test_refresh_refuses_archive_link_outside_run(tmp_path):
    store = seed_assessment(tmp_path, [sample("old")])
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (store.work_dir / "retired_samples").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")

    with pytest.raises(ValueError, match="outside the run directory"):
        discover(tmp_path, SnapshotIngest([]), refresh=True)

    assert store.load_sample("old") is not None
    assert list(outside.iterdir()) == []
