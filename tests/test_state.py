from __future__ import annotations

import json
from pathlib import Path

# -- namespaced state --


class TestNamespacedState:
    def test_history_isolation(self):
        from deepzero.engine.state import SampleState

        s = SampleState(sample_id="x")
        s.mark_stage_completed("stage_a", data={"score": 10})
        s.mark_stage_completed("stage_b", data={"score": 99})
        # data is namespaced - no collision
        assert s.history["stage_a"].data["score"] == 10
        assert s.history["stage_b"].data["score"] == 99

    def test_mark_stage_running(self):
        from deepzero.engine.state import SampleState

        s = SampleState(sample_id="x")
        s.mark_stage_running("filter")
        assert s.current_stage == "filter"
        assert s.history["filter"].status == "running"

    def test_mark_stage_completed(self):
        from deepzero.engine.state import SampleState

        s = SampleState(sample_id="x")
        s.mark_stage_completed("filter", verdict="filter", data={"reason": "dedup"})
        assert s.history["filter"].status == "completed"
        assert s.history["filter"].verdict == "filter"
        assert s.history["filter"].data["reason"] == "dedup"
        assert s.verdict == "filtered"

    def test_mark_stage_failed(self):
        from deepzero.engine.state import SampleState

        s = SampleState(sample_id="x")
        s.mark_stage_failed("decompile", "ghidra crashed")
        assert s.history["decompile"].status == "failed"
        assert s.error == "ghidra crashed"
        assert s.verdict == "failed"

    def test_is_active(self):
        from deepzero.engine.state import SampleState

        s = SampleState(sample_id="x", verdict="active")
        assert s.is_active()
        s.mark_stage_completed("filter", verdict="filter")
        assert not s.is_active()

    def test_is_stage_done(self):
        from deepzero.engine.state import SampleState

        s = SampleState(sample_id="x")
        assert not s.is_stage_done("filter")
        s.mark_stage_completed("filter")
        assert s.is_stage_done("filter")


# -- state store --


class TestStateStore:
    def test_save_and_load_run(self, tmp_path):
        from deepzero.engine.state import StateStore, RunState

        store = StateStore(tmp_path / "work")
        run = RunState(run_id="test-001", pipeline="loldrivers", status="running")
        run.mark_running()
        store.save_run(run)

        loaded = store.load_run()
        assert loaded is not None
        assert loaded.run_id == "test-001"
        assert loaded.status == "running"

    def test_load_run_missing_returns_none(self, tmp_path):
        from deepzero.engine.state import StateStore

        store = StateStore(tmp_path / "empty")
        assert store.load_run() is None

    def test_save_and_load_sample(self, tmp_path):
        from deepzero.engine.state import StateStore, SampleState

        store = StateStore(tmp_path / "work")
        sample = SampleState(
            sample_id="abc123",
            sha256="deadbeef",
            filename="test.sys",
            verdict="active",
        )
        sample.mark_stage_completed("discover", verdict="continue", data={"score": 5})
        sample.verdict = "active"
        store.save_sample(sample)

        loaded = store.load_sample("abc123")
        assert loaded is not None
        assert loaded.sha256 == "deadbeef"
        assert loaded.history["discover"].data["score"] == 5
        assert loaded.is_stage_done("discover")

    def test_sample_dir_nested_under_samples(self, tmp_path):
        from deepzero.engine.state import StateStore

        store = StateStore(tmp_path / "work")
        d = store.sample_dir("abc")
        assert "samples" in str(d)
        assert d.name == "abc"

    def test_load_sample_rejects_v1(self, tmp_path):
        from deepzero.engine.state import StateStore

        store = StateStore(tmp_path / "work")
        sample_dir = store.sample_dir("old_sample")
        # write a v1 state file (no _version field)
        (sample_dir / "state.json").write_text(
            json.dumps(
                {
                    "sample_id": "old_sample",
                    "stages": {},
                    "metadata": {"foo": 1},
                }
            ),
            encoding="utf-8",
        )
        loaded = store.load_sample("old_sample")
        assert loaded is None

    def test_list_samples(self, tmp_path):
        from deepzero.engine.state import StateStore, SampleState

        store = StateStore(tmp_path / "work")
        for i in range(3):
            s = SampleState(
                sample_id=f"sample_{i}", filename=f"file_{i}.sys", verdict="active"
            )
            store.save_sample(s)
        samples = store.list_samples()
        assert len(samples) == 3

    def test_manifest_roundtrip(self, tmp_path):
        from deepzero.engine.state import StateStore, SampleState

        store = StateStore(tmp_path / "work")
        states = [
            SampleState(sample_id="a", filename="a.sys", verdict="active"),
            SampleState(sample_id="b", filename="b.sys", verdict="filtered"),
            SampleState(sample_id="c", filename="c.sys", verdict="failed"),
        ]
        store.save_manifest(states)
        entries = store.load_manifest()
        assert len(entries) == 3
        verdicts = {e["sample_id"]: e["verdict"] for e in entries}
        assert verdicts["a"] == "active"
        assert verdicts["b"] == "filtered"
        assert verdicts["c"] == "failed"

    def test_manifest_counts(self, tmp_path):
        from deepzero.engine.state import StateStore, SampleState

        store = StateStore(tmp_path / "work")
        store.save_manifest(
            [
                SampleState(sample_id="1", filename="1.sys", verdict="active"),
                SampleState(sample_id="2", filename="2.sys", verdict="active"),
                SampleState(sample_id="3", filename="3.sys", verdict="filtered"),
            ]
        )
        raw = json.loads((tmp_path / "work" / "run_manifest.json").read_text())
        assert raw["total"] == 3
        assert raw["active"] == 2
        assert raw["filtered"] == 1


# -- safe json encoder --


class TestSafeJSONEncoder:
    def test_path_serialization(self):
        from deepzero.engine.state import SafeJSONEncoder

        result = json.dumps({"p": Path("/foo/bar")}, cls=SafeJSONEncoder)
        data = json.loads(result)
        assert data["p"] == "/foo/bar" or data["p"] == "\\foo\\bar"

    def test_set_serialization(self):
        from deepzero.engine.state import SafeJSONEncoder

        result = json.dumps({"s": {3, 1, 2}}, cls=SafeJSONEncoder)
        data = json.loads(result)
        assert data["s"] == [1, 2, 3]

    def test_unknown_type_stringified(self):
        from deepzero.engine.state import SafeJSONEncoder

        class Weird:
            def __str__(self):
                return "weird_thing"

        result = json.dumps({"w": Weird()}, cls=SafeJSONEncoder)
        data = json.loads(result)
        assert data["w"] == "weird_thing"


# -- atomic writes --


class TestAtomicWrites:
    def test_atomic_replace_creates_file(self, tmp_path):
        from deepzero.engine.state import atomic_replace

        src = tmp_path / "test.tmp"
        dst = tmp_path / "test.json"
        src.write_text("hello", encoding="utf-8")
        atomic_replace(src, dst)
        assert dst.read_text() == "hello"
        assert not src.exists()

    def test_atomic_write_via_state_store(self, tmp_path):
        from deepzero.engine.state import StateStore, SampleState

        store = StateStore(tmp_path / "work")
        s = SampleState(sample_id="atomic_test", filename="test.sys", verdict="active")
        store.save_sample(s)
        # no .tmp file left behind
        sample_dir = store.sample_dir("atomic_test")
        assert not (sample_dir / "state.json.tmp").exists()
        assert (sample_dir / "state.json").exists()


# -- run state --


class TestRunState:
    def test_mark_running(self):
        from deepzero.engine.state import RunState

        r = RunState(run_id="r1")
        r.mark_running()
        assert r.status == "running"
        assert r.started_at != ""

    def test_mark_completed(self):
        from deepzero.engine.state import RunState

        r = RunState(run_id="r1")
        r.mark_completed()
        assert r.status == "completed"

    def test_mark_failed(self):
        from deepzero.engine.state import RunState

        r = RunState(run_id="r1")
        r.mark_failed("boom")
        assert r.status == "failed"
        assert r.stats["error"] == "boom"
