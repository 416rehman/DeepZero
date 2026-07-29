from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from deepzero.engine import liveness
from deepzero.engine.types import RunStatus, SampleStatus, StageStatus, Verdict

log = logging.getLogger("deepzero.state")

# enforced on load - reject incompatible state from v1 runs
STATE_VERSION = 2
_STATE_JSON = "state.json"


class SafeJSONEncoder(json.JSONEncoder):
    # community processors will shove Path, set, datetime into data dicts
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
    status: StageStatus = StageStatus.PENDING
    verdict: Verdict = Verdict.CONTINUE
    started_at: str = ""
    completed_at: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    # namespaced processor output - never merged across stages
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    # why this stage did no work (cached output, filtered out). kept separate from
    # error so a normal skip is never reported as a failure
    skip_reason: str = ""


@dataclass
class SampleState:
    sample_id: str
    sha256: str = ""
    source_path: str = ""
    filename: str = ""
    # lifecycle: pending -> active -> skipped | failed | completed
    verdict: SampleStatus = SampleStatus.PENDING
    current_stage: str = ""
    # per-stage namespaced output ledger
    history: dict[str, StageOutput] = field(default_factory=dict)
    error: str | None = None

    def mark_stage_running(self, stage_name: str) -> None:
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        self.history[stage_name].status = StageStatus.RUNNING
        self.history[stage_name].started_at = _now()
        self.current_stage = stage_name

    def mark_stage_completed(
        self,
        stage_name: str,
        verdict: Verdict = Verdict.CONTINUE,
        artifacts: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        stage = self.history[stage_name]
        stage.status = StageStatus.COMPLETED
        stage.verdict = verdict
        stage.completed_at = _now()
        if artifacts:
            stage.artifacts = artifacts
        if data:
            stage.data = data

        # promote skip verdict to sample level
        if verdict == Verdict.FILTER:
            self.verdict = SampleStatus.FILTERED

    def mark_stage_failed(self, stage_name: str, error: str) -> None:
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        stage = self.history[stage_name]
        stage.status = StageStatus.FAILED
        stage.error = error
        stage.completed_at = _now()
        self.error = error
        self.verdict = SampleStatus.FAILED

    def mark_stage_timed_out(self, stage_name: str, budget: int) -> None:
        """the stage ran out of time rather than going wrong.

        Recorded apart from a failure because it is a statement about the
        budget, not about the sample. The samples that hit it are the largest
        ones, which in a corpus of anything tend to be the most interesting, so
        filing them with genuine errors quietly biases a run away from its best
        targets. The budget is kept so a rerun can say what was already tried.
        """
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        stage = self.history[stage_name]
        stage.status = StageStatus.TIMED_OUT
        stage.error = f"timed out after {budget}s"
        stage.data = {**stage.data, "__timeout_budget": budget}
        stage.completed_at = _now()
        self.error = stage.error
        self.verdict = SampleStatus.TIMED_OUT

    def timed_out_budget(self) -> int:
        """the budget the stage that stopped this sample exceeded, if any."""
        for output in self.history.values():
            if output.status == StageStatus.TIMED_OUT:
                try:
                    return int(output.data.get("__timeout_budget", 0))
                except (TypeError, ValueError):
                    return 0
        return 0

    def clear_timed_out_stages(self) -> list[str]:
        """forget the stages that ran out of time so they are attempted again.

        Only those stages are dropped. Everything else the run produced for this
        sample stays, so retrying costs the time those stages need and nothing
        else - the rest of the run's results are never discarded to get them.
        """
        reset = [name for name, out in self.history.items() if out.status == StageStatus.TIMED_OUT]
        for name in reset:
            del self.history[name]
        if reset:
            self.error = None
            self.verdict = SampleStatus.ACTIVE
        return reset

    def mark_stage_cached(self, stage_name: str, reason: str = "") -> None:
        """work for this stage was already done (e.g. output already on disk).

        the sample stays in the pipeline: per MapProcessor.should_skip, a skipped
        sample counts as passed. this is NOT mark_stage_skipped, which filters the
        sample out of the run entirely.
        """
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        stage = self.history[stage_name]
        stage.status = StageStatus.COMPLETED
        stage.verdict = Verdict.CONTINUE
        stage.completed_at = _now()
        if reason:
            stage.skip_reason = reason

    def mark_stage_skipped(self, stage_name: str, reason: str = "") -> None:
        if stage_name not in self.history:
            self.history[stage_name] = StageOutput()
        stage = self.history[stage_name]
        stage.status = StageStatus.FILTERED
        stage.verdict = Verdict.FILTER
        stage.completed_at = _now()
        if reason:
            stage.skip_reason = reason
        self.verdict = SampleStatus.FILTERED

    def is_stage_done(self, stage_name: str) -> bool:
        s = self.history.get(stage_name)
        if s is None:
            return False
        return s.status in (
            StageStatus.COMPLETED,
            StageStatus.FILTERED,
            StageStatus.FAILED,
            # a resumed run does not silently retry these: the budget that was
            # too short last time is still too short. Retrying is asked for.
            StageStatus.TIMED_OUT,
        )

    def is_active(self) -> bool:
        return self.verdict in (SampleStatus.PENDING, SampleStatus.ACTIVE)


@dataclass
class RunState:
    run_id: str
    pipeline: str = ""
    target: str = ""
    model: str = ""
    started_at: str = ""
    completed_at: str = ""
    status: RunStatus = RunStatus.PENDING
    stages: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    # who is writing this run. a status of "running" is only a claim until the
    # process behind it can be checked, and a killed run never gets to withdraw
    # the claim itself.
    host: str = ""
    pid: int = 0
    pid_token: str = ""
    heartbeat_at: str = ""

    def mark_running(self) -> None:
        self.status = RunStatus.RUNNING
        self.started_at = _now()
        self.host = liveness.hostname()
        self.pid = os.getpid()
        self.pid_token = liveness.start_token(self.pid)
        self.heartbeat_at = self.started_at

    def touch(self) -> None:
        """Record that the run is still making progress."""
        self.heartbeat_at = _now()

    def mark_completed(self) -> None:
        self.status = RunStatus.COMPLETED
        self.completed_at = _now()

    def mark_interrupted(self) -> None:
        self.status = RunStatus.INTERRUPTED
        self.completed_at = _now()

    def mark_failed(self, error: str) -> None:
        self.status = RunStatus.FAILED
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
        path = d / _STATE_JSON
        self._atomic_write(path, self._dumps(sample_to_dict(state)))

    def load_sample(self, sample_id: str) -> SampleState | None:
        path = self.sample_dir(sample_id) / _STATE_JSON
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            version = data.get("_version", 1)
            if version < STATE_VERSION:
                log.warning(
                    "sample %s has v%d state, expected v%d - skipping",
                    sample_id,
                    version,
                    STATE_VERSION,
                )
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
            if d.is_dir() and (d / _STATE_JSON).exists():
                state = self.load_sample(d.name)
                if state is not None:
                    results.append(state)
        return results

    # -- manifest --

    def save_manifest(self, samples: list[SampleState]) -> None:
        entries = []
        for s in samples:
            entries.append(
                {
                    "sample_id": s.sample_id,
                    "filename": s.filename,
                    "verdict": s.verdict,
                    "current_stage": s.current_stage,
                    "sha256": s.sha256,
                }
            )

        manifest = {
            "_version": STATE_VERSION,
            "total": len(entries),
            "active": sum(
                1 for e in entries if e["verdict"] in (SampleStatus.PENDING, SampleStatus.ACTIVE)
            ),
            "filtered": sum(1 for e in entries if e["verdict"] == SampleStatus.FILTERED),
            "failed": sum(1 for e in entries if e["verdict"] == SampleStatus.FAILED),
            "completed": sum(1 for e in entries if e["verdict"] == SampleStatus.COMPLETED),
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


def sample_to_dict(state: SampleState) -> dict:
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
        history[name] = StageOutput(
            **{k: v for k, v in sd.items() if k in StageOutput.__dataclass_fields__}
        )

    return SampleState(
        sample_id=data["sample_id"],
        sha256=data.get("sha256", ""),
        source_path=data.get("source_path", ""),
        filename=data.get("filename", ""),
        verdict=data.get("verdict", SampleStatus.PENDING),
        current_stage=data.get("current_stage", ""),
        history=history,
        error=data.get("error"),
    )
