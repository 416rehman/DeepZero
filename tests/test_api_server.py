import pytest
from pathlib import Path
from starlette.testclient import TestClient
from deepzero.api.server import create_app
from deepzero.engine.state import StateStore, SampleState, RunState


@pytest.fixture
def test_app(tmp_path: Path):
    store = StateStore(tmp_path)
    store.save_run(
        RunState(
            run_id="r1",
            pipeline="test_run",
            target="a",
            model="m",
            started_at="",
            completed_at="",
            status="running",
            stages=[],
            stats={},
        )
    )
    store.save_sample(
        SampleState(sample_id="123", filename="foo.exe", current_stage="discovery")
    )
    return create_app(tmp_path)


def test_health(test_app):
    client = TestClient(test_app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_get_runs(test_app):
    client = TestClient(test_app)
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) == 1
    assert resp.json()["runs"][0]["pipeline"] == "test_run"


def test_get_samples(test_app):
    client = TestClient(test_app)
    resp = client.get("/api/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["samples"][0]["sample_id"] == "123"


def test_get_sample(test_app):
    client = TestClient(test_app)
    resp = client.get("/api/samples/123")
    assert resp.status_code == 200
    assert resp.json()["sample_id"] == "123"


def test_get_sample_missing(test_app):
    client = TestClient(test_app)
    resp = client.get("/api/samples/missing")
    assert resp.status_code == 404
