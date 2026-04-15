from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("deepzero.state")

# enforced on load - reject incompatible state from v1 runs
STATE_VERSION = 2


class SafeJSONEncoder(json.JSONEncoder):
    # community tools will shove Path, set, datetime into data dicts
    def default(self, obj):
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, set):
            return sorted(obj)
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def atomic_replace(src: Path, dst: Path, retries: int = 5) -> None:
    # windows defender briefly locks .tmp files for scanning after close
    for i in range(retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == retries - 1 or os.name != "nt":
                raise
            time.sleep(0.05)


@dataclass
class StageOutput:
    status: str = "pending"
    verdict: str = ""
    started_at: str = ""
    completed_at: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    # namespaced tool output - never merged across stages
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class SampleState:
    sample_id: str
    sha256: str = ""
    source_path: str = ""
    filename: str = ""
    # lifecycle: pending -> active -> skipped | failed | completed
    verdict: str = "pending"
    current_stage: str = ""
    # per-stage namespaced output ledger
    history: dict[str, StageOutput] = field(default_factory=dict)
    error: str | None = None

    def mark_stage_running(self, stage_name: str) -> None:
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        self.history[stage_name].status = "running"
        self.history[stage_name].started_at = _now()
        self.current_stage = stage_name

    def mark_stage_completed(
        self,
        stage_name: str,
        verdict: str = "continue",
        artifacts: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        stage = self.history[stage_name]
        stage.status = "completed"
        stage.verdict = verdict
        stage.completed_at = _now()
        if artifacts:
            stage.artifacts = artifacts
        if data:
            stage.data = data

        # promote skip verdict to sample level
        if verdict == "skip":
            self.verdict = "skipped"

    def mark_stage_failed(self, stage_name: str, error: str) -> None:
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        stage = self.history[stage_name]
        stage.status = "failed"
        stage.error = error
        stage.completed_at = _now()
        self.error = error
        self.verdict = "failed"

    def mark_stage_skipped(self, stage_name: str, reason: str = "") -> None:
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        stage = self.history[stage_name]
        stage.status = "skipped"
        stage.verdict = "skip"
        stage.completed_at = _now()
        if reason:
            stage.error = reason
        self.verdict = "skipped"

    def is_stage_done(self, stage_name: str) -> bool:
        s = self.history.get(stage_name)
        if s is None:
            return False
        return s.status in ("completed", "skipped", "failed")

    def is_active(self) -> bool:
        return self.verdict in ("pending", "active")


@dataclass
class RunState:
    run_id: str
    pipeline: str = ""
    target: str = ""
    model: str = ""
    started_at: str = ""
    completed_at: str = ""
    status: str = "pending"
    stages: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def mark_running(self) -> None:
        self.status = "running"
        self.started_at = _now()

    def mark_completed(self) -> None:
        self.status = "completed"
        self.completed_at = _now()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.completed_at = _now()
        self.stats["error"] = error


class StateStore:
    # file-based state persistence with atomic writes

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._samples_dir = work_dir / "samples"
        self._samples_dir.mkdir(parents=True, exist_ok=True)

    # -- atomic write helpers --

    def _atomic_write(self, path: Path, content: str) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        atomic_replace(tmp, path)

    def _dumps(self, obj: Any) -> str:
        return json.dumps(obj, indent=2, cls=SafeJSONEncoder)

    # -- run state --

    def save_run(self, run: RunState) -> None:
        path = self.work_dir / "run.json"
        self._atomic_write(path, self._dumps(asdict(run)))

    def load_run(self) -> RunState | None:
        path = self.work_dir / "run.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return RunState(**{k: v for k, v in data.items() if k in RunState.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError) as e:
            log.warning("failed to load run state: %s", e)
            return None

    # -- sample state --

    def sample_dir(self, sample_id: str) -> Path:
        d = self._samples_dir / sample_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_sample(self, state: SampleState) -> None:
        d = self.sample_dir(state.sample_id)
        path = d / "state.json"
        self._atomic_write(path, self._dumps(_sample_to_dict(state)))

    def load_sample(self, sample_id: str) -> SampleState | None:
        path = self.sample_dir(sample_id) / "state.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            version = data.get("_version", 1)
            if version < STATE_VERSION:
                log.warning("sample %s has v%d state, expected v%d - skipping", sample_id, version, STATE_VERSION)
                return None
            return _sample_from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            log.warning("failed to load sample state %s: %s", sample_id, e)
            return None

    def list_samples(self) -> list[SampleState]:
        results = []
        if not self._samples_dir.exists():
            return results
        for d in self._samples_dir.iterdir():
            if d.is_dir() and (d / "state.json").exists():
                state = self.load_sample(d.name)
                if state is not None:
                    results.append(state)
        return results

    # -- manifest --

    def save_manifest(self, samples: list[SampleState]) -> None:
        entries = []
        for s in samples:
            entries.append({
                "sample_id": s.sample_id,
                "filename": s.filename,
                "verdict": s.verdict,
                "current_stage": s.current_stage,
                "sha256": s.sha256,
            })

        manifest = {
            "_version": STATE_VERSION,
            "total": len(entries),
            "active": sum(1 for e in entries if e["verdict"] in ("pending", "active")),
            "skipped": sum(1 for e in entries if e["verdict"] == "skipped"),
            "failed": sum(1 for e in entries if e["verdict"] == "failed"),
            "completed": sum(1 for e in entries if e["verdict"] == "completed"),
            "samples": entries,
        }
        path = self.work_dir / "run_manifest.json"
        self._atomic_write(path, self._dumps(manifest))

    def load_manifest(self) -> list[dict]:
        path = self.work_dir / "run_manifest.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("samples", [])
        except (json.JSONDecodeError, TypeError):
            return []

    # -- pipeline snapshot --

    def save_pipeline_snapshot(self, yaml_content: str) -> None:
        path = self.work_dir / "pipeline.yaml"
        self._atomic_write(path, yaml_content)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sample_to_dict(state: SampleState) -> dict:
    d: dict[str, Any] = {
        "_version": STATE_VERSION,
        "sample_id": state.sample_id,
        "sha256": state.sha256,
        "source_path": state.source_path,
        "filename": state.filename,
        "verdict": state.verdict,
        "current_stage": state.current_stage,
        "history": {},
        "error": state.error,
    }
    for name, stage in state.history.items():
        d["history"][name] = asdict(stage)
    return d


def _sample_from_dict(data: dict) -> SampleState:
    history = {}
    for name, sd in data.get("history", {}).items():
        history[name] = StageOutput(**{k: v for k, v in sd.items() if k in StageOutput.__dataclass_fields__})

    return SampleState(
        sample_id=data["sample_id"],
        sha256=data.get("sha256", ""),
        source_path=data.get("source_path", ""),
        filename=data.get("filename", ""),
        verdict=data.get("verdict", "pending"),
        current_stage=data.get("current_stage", ""),
        history=history,
        error=data.get("error"),
    )
