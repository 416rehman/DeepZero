from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from deepzero.api.server import create_app
from deepzero.engine.state import RunState, SampleState, StateStore


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "work")


@pytest.fixture
def sample_state():
    s = SampleState(sample_id="abc123", sha256="deadbeef", filename="test.sys")
    s.mark_stage_running("discover")
    s.mark_stage_completed("discover", verdict="continue", data={"filename": "test.sys"})
    return s


@pytest.fixture
def run_state():
    r = RunState(run_id="run_001", pipeline="test_pipeline", target="/path/to/target")
    r.mark_running()
    return r


def _setup_store_with_sample(store, sample_state, run_state=None):
    store.save_sample(sample_state)
    if run_state:
        store.save_run(run_state)


class TestHealthEndpoint:
    def test_health_returns_ok(self, store):

        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert str(store.work_dir) in data["work_dir"]


class TestRunsEndpoints:
    def test_get_runs_empty(self, store):

        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json()["runs"] == []

    def test_get_runs_with_run(self, store, run_state):

        store.save_run(run_state)
        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run_001"

    def test_get_run_not_found(self, store):

        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get("/api/run")
        assert resp.status_code == 404

    def test_get_run_found(self, store, run_state):

        store.save_run(run_state)
        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get("/api/run")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == "run_001"


class TestSamplesEndpoints:
    def test_get_samples_empty(self, store):

        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get("/api/samples")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_get_samples_with_data(self, store, sample_state):

        _setup_store_with_sample(store, sample_state)
        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get("/api/samples")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["samples"][0]["sample_id"] == "abc123"

    def test_get_samples_filter_by_verdict(self, store, sample_state):

        # classification is stored in stage data
        sample_state.mark_stage_completed(
            "assess", verdict="continue",
            data={"classification": "vulnerable"},
        )
        _setup_store_with_sample(store, sample_state)
        app = create_app(store.work_dir)
        client = TestClient(app)

        # filter for a verdict that doesn't match
        resp = client.get("/api/samples?verdict=not_vulnerable")
        assert resp.json()["total"] == 0

    def test_get_sample_not_found(self, store):

        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get("/api/samples/nonexistent")
        assert resp.status_code == 404

    def test_get_sample_found(self, store, sample_state):

        _setup_store_with_sample(store, sample_state)
        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get(f"/api/samples/{sample_state.sample_id}")
        assert resp.status_code == 200
        assert resp.json()["sample_id"] == "abc123"


class TestArtifactEndpoint:
    def test_artifact_not_found_sample(self, store):

        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get("/api/samples/nonexistent/artifacts/test")
        assert resp.status_code == 404

    def test_artifact_found(self, store, sample_state):

        # add an artifact to stage output
        sample_state.mark_stage_completed(
            "decompile", verdict="continue",
            artifacts={"dispatch_ioctl": "decompiled/dispatch_ioctl.c"},
        )
        _setup_store_with_sample(store, sample_state)

        # create the artifact file
        artifact_dir = store.sample_dir(sample_state.sample_id) / "decompiled"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "dispatch_ioctl.c").write_text("int main() { return 0; }")

        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get(f"/api/samples/{sample_state.sample_id}/artifacts/dispatch_ioctl")
        assert resp.status_code == 200
        assert "int main()" in resp.json()["content"]

    def test_artifact_name_not_found(self, store, sample_state):

        _setup_store_with_sample(store, sample_state)
        app = create_app(store.work_dir)
        client = TestClient(app)
        resp = client.get(f"/api/samples/{sample_state.sample_id}/artifacts/nonexistent")
        assert resp.status_code == 404
