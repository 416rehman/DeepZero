from __future__ import annotations

import concurrent.futures
import logging
import signal
import sys
import threading
import time
import traceback as tb_module
from pathlib import Path
from typing import Any

from deepzero.engine.context import generate_context
from deepzero.engine.process import run_subprocess_with_kill
from deepzero.engine.stage import (
    BatchEntry,
    BatchTool,
    FailurePolicy,
    GlobalConfig,
    IngestTool,
    LLMProtocol,
    MapTool,
    ReduceTool,
    StageContext,
    StageResult,
    StageSpec,
    Tool,
)
from deepzero.engine.state import RunState, SampleState, StateStore

log = logging.getLogger("deepzero.runner")


class PipelineRunner:
    # breadth-first pipeline executor with sync barriers

    def __init__(
        self,
        ingest: IngestTool,
        stages: list[tuple[StageSpec, Tool]],
        state_store: StateStore,
        pipeline_dir: Path,
        global_config: GlobalConfig,
        llm: LLMProtocol | None = None,
        default_max_workers: int = 4,
    ):
        self.ingest = ingest
        self.stages = stages
        self.state_store = state_store
        self.pipeline_dir = pipeline_dir
        self.global_config = global_config
        self.llm = llm
        self.default_max_workers = default_max_workers
        self._shutdown_event = threading.Event()
        self._original_sigint = None

    def run(
        self,
        target: Path,
        run_state: RunState,
    ) -> RunState:
        self._install_signal_handler()
        run_state.mark_running()
        self.state_store.save_run(run_state)

        try:
            return self._execute_pipeline_stages(target, run_state)
        except KeyboardInterrupt:
            log.warning("interrupted by user - saving state")
            run_state.status = "interrupted"
            self.state_store.save_run(run_state)
            return run_state
        except Exception as e:
            log.error("pipeline failed: %s", e)
            run_state.mark_failed(str(e))
            self.state_store.save_run(run_state)
            return run_state
        finally:
            self._restore_signal_handler()
            self._teardown_tools()

    def _execute_pipeline_stages(
        self,
        target: Path,
        run_state: RunState,
    ) -> RunState:
        stage_names = [self.ingest.spec.name] + [s.name for s, _ in self.stages]
        log.info("--- setup --- initializing %d tools", len(stage_names))

        self.ingest.setup(self.global_config)
        for _, tool in self.stages:
            tool.setup(self.global_config)

        log.info("--- setup complete ---")
        log.info("pipeline: %s", " -> ".join(stage_names))

        # fast resume: if states already exist on disk, skip the expensive ingest
        existing_states = self.state_store.list_samples()
        if existing_states:
            log.info("--- resume --- found %d existing sample states, skipping ingest", len(existing_states))
            sample_states: dict[str, SampleState] = {s.sample_id: s for s in existing_states}
            run_state.stats["discovered"] = len(sample_states)
            run_state.stages = stage_names
            self.state_store.save_run(run_state)
        else:
            # fresh run — execute ingest
            log.info("--- %s (ingest) ---", self.ingest.spec.name)
            samples = self.ingest.discover(target, self.ingest.spec.config, self.global_config)

            run_state.stats["discovered"] = len(samples)
            run_state.stages = stage_names
            self.state_store.save_run(run_state)

            log.info("--- %s -> %d samples ---", self.ingest.spec.name, len(samples))

            if not samples:
                run_state.mark_completed()
                self.state_store.save_run(run_state)
                return run_state

            sample_states = {}
            for sample in samples:
                state = SampleState(
                    sample_id=sample.sample_id,
                    sha256=sample.data.get("sha256", ""),
                    source_path=str(sample.source_path),
                    filename=sample.filename,
                    verdict="active",
                )
                state.mark_stage_completed(
                    self.ingest.spec.name,
                    verdict="continue",
                    data=sample.data,
                )
                state.verdict = "active"
                sample_states[sample.sample_id] = state
                self.state_store.save_sample(state)

            self.state_store.save_manifest(list(sample_states.values()))

        # breadth-first stage execution
        for spec, tool in self.stages:
            if self._shutdown_event.is_set():
                log.warning("shutdown requested - stopping pipeline")
                break

            active = [s for s in sample_states.values() if s.is_active()]

            log.info("--- %s --- %d active samples", spec.name, len(active))

            if not active:
                log.info("--- %s --- no active samples, skipping stage", spec.name)
                continue

            stage_stats = {"completed": 0, "skipped": 0, "failed": 0}

            if isinstance(tool, ReduceTool):
                self._run_reduce(tool, active, spec, stage_stats)
            elif isinstance(tool, BatchTool):
                self._run_batch(tool, active, spec, stage_stats)
            else:
                self._run_map(tool, active, spec, stage_stats)

            # dumb limit — pure truncation, no sorting
            limit = spec.config.get("limit", 0)
            if limit > 0:
                still_active = [s for s in sample_states.values() if s.is_active()]
                if len(still_active) > limit:
                    excess = still_active[limit:]
                    log.info("  %s limit (%d): truncating %d excess samples", spec.name, limit, len(excess))
                    for s in excess:
                        s.mark_stage_skipped(spec.name, "limit reached")
                        self.state_store.save_sample(s)
                        stage_stats["skipped"] += 1

            # sync barrier
            self.state_store.save_manifest(list(sample_states.values()))
            self._generate_context_files(sample_states)

            if "per_stage" not in run_state.stats:
                run_state.stats["per_stage"] = {}
            run_state.stats["per_stage"][spec.name] = dict(stage_stats)
            self.state_store.save_run(run_state)

            passed = stage_stats["completed"]
            filtered = stage_stats["skipped"]
            failed = stage_stats["failed"]
            log.info("--- %s -> %d passed, %d filtered, %d failed ---", spec.name, passed, filtered, failed)

        run_state.mark_completed()
        self.state_store.save_run(run_state)
        self.state_store.save_manifest(list(sample_states.values()))
        return run_state

    # -- map execution --

    def _run_map(
        self,
        tool: MapTool,
        active: list[SampleState],
        spec: StageSpec,
        stage_stats: dict[str, int],
    ) -> None:

        # filter out samples that already completed this stage (resume granularity)
        pending = [s for s in active if not s.is_stage_done(spec.name)]
        cached = len(active) - len(pending)
        if cached > 0:
            log.info("  %d already completed (cached), %d pending", cached, len(pending))
            stage_stats["completed"] += cached

        if not pending:
            return

        if spec.parallel <= 1:
            for idx, state in enumerate(pending):
                if self._shutdown_event.is_set():
                    break
                self._process_one_map(state, spec, tool)
                outcome = self._classify_outcome(state, spec.name)
                stage_stats[outcome] += 1
                if (idx + 1) % max(1, len(pending) // 5) == 0 or (idx + 1) == len(pending):
                    log.info("  %d/%d processed", idx + 1, len(pending))
        else:
            max_workers = min(spec.parallel, len(pending))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(self._process_one_map, s, spec, tool): s
                    for s in pending
                }
                done_count = 0
                for future in concurrent.futures.as_completed(future_map):
                    if self._shutdown_event.is_set():
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    done_count += 1
                    state = future_map[future]
                    try:
                        future.result()
                    except Exception as exc:
                        log.error("  %s unhandled error: %s", state.filename, exc)
                        state.mark_stage_failed(spec.name, f"{type(exc).__name__}: {exc}")
                        self.state_store.save_sample(state)

                    outcome = self._classify_outcome(state, spec.name)
                    stage_stats[outcome] += 1

                    if done_count % max(1, len(pending) // 5) == 0 or done_count == len(pending):
                        log.info("  %d/%d processed", done_count, len(pending))

    def _process_one_map(
        self,
        state: SampleState,
        spec: StageSpec,
        tool: MapTool,
    ) -> None:
        sample_dir = self.state_store.sample_dir(state.sample_id)
        source_path = Path(state.source_path)

        ctx = StageContext(
            sample_path=source_path,
            sample_dir=sample_dir,
            history=dict(state.history),
            config=spec.config,
            pipeline_dir=self.pipeline_dir,
            global_config=self.global_config,
            llm=self.llm,
            log=logging.getLogger(f"deepzero.tool.{spec.name}"),
        )

        # optional skip hook (e.g. cached decompilation)
        skip_reason = tool.should_skip(ctx)
        if skip_reason:
            state.mark_stage_skipped(spec.name, skip_reason)
            self.state_store.save_sample(state)
            return

        state.mark_stage_running(spec.name)
        self.state_store.save_sample(state)

        attempts = 0
        max_attempts = spec.max_retries + 1 if spec.on_failure == FailurePolicy.RETRY else 1

        while attempts < max_attempts:
            attempts += 1
            try:
                result = self._execute_with_timeout(tool, ctx, spec.timeout)

                if result.status == "completed":
                    state.mark_stage_completed(
                        spec.name,
                        verdict=result.verdict,
                        artifacts=result.artifacts,
                        data=result.data,
                    )
                    # immediate save — don't wait for barrier (resume granularity)
                    self.state_store.save_sample(state)
                    return

                if attempts < max_attempts:
                    backoff = min(2 ** attempts, 30)
                    log.warning(
                        "[%s] %s failed (attempt %d/%d), retrying in %ds: %s",
                        spec.name, state.filename, attempts, max_attempts, backoff, result.error,
                    )
                    time.sleep(backoff)
                    continue

                state.mark_stage_failed(spec.name, result.error or "tool returned failed status")
                self.state_store.save_sample(state)

                if spec.on_failure == FailurePolicy.ABORT:
                    self._shutdown_event.set()
                return

            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"

                # capture traceback out of band
                err_log = sample_dir / f"{spec.name}_error.log"
                err_log.write_text(tb_module.format_exc(), encoding="utf-8")

                if attempts < max_attempts:
                    backoff = min(2 ** attempts, 30)
                    log.warning(
                        "[%s] %s exception (attempt %d/%d), retrying in %ds: %s",
                        spec.name, state.filename, attempts, max_attempts, backoff, error_msg,
                    )
                    time.sleep(backoff)
                    continue

                log.error("[%s] %s failed: %s", spec.name, state.filename, error_msg)
                state.mark_stage_failed(spec.name, error_msg)
                self.state_store.save_sample(state)

                if spec.on_failure == FailurePolicy.ABORT:
                    self._shutdown_event.set()
                return

    # -- reduce execution --

    def _run_reduce(
        self,
        tool: ReduceTool,
        active: list[SampleState],
        spec: StageSpec,
        stage_stats: dict[str, int],
    ) -> None:
        log.info("  reduce: %d active samples -> %s", len(active), spec.name)

        try:
            results = tool.reduce(active, spec.config)
        except Exception as exc:
            log.error("  reduce tool '%s' crashed: %s", spec.name, exc)
            # don't kill the pipeline — just log and continue with samples unchanged
            return

        for state in results:
            # record the reduce stage in history
            if not state.is_stage_done(spec.name):
                if state.is_active():
                    state.mark_stage_completed(spec.name, verdict="continue")
                    stage_stats["completed"] += 1
                else:
                    stage_stats["skipped"] += 1
            self.state_store.save_sample(state)

    # -- batch execution --

    def _run_batch(
        self,
        tool: BatchTool,
        active: list[SampleState],
        spec: StageSpec,
        stage_stats: dict[str, int],
    ) -> None:
        # filter out already-completed samples (resume)
        pending = [s for s in active if not s.is_stage_done(spec.name)]
        cached = len(active) - len(pending)
        if cached > 0:
            log.info("  %d already completed (cached), %d pending", cached, len(pending))
            stage_stats["completed"] += cached

        if not pending:
            return

        entries = []
        for state in pending:
            sample_dir = self.state_store.sample_dir(state.sample_id)
            entries.append(BatchEntry(
                sample_id=state.sample_id,
                sample_dir=sample_dir,
                source_path=Path(state.source_path),
                history=dict(state.history),
            ))

        log.info("  batch: processing %d samples with %s", len(entries), spec.name)

        try:
            results = tool.execute_batch(entries, spec.config)
        except Exception as exc:
            log.error("  batch tool '%s' crashed: %s", spec.name, exc)
            for state in pending:
                state.mark_stage_failed(spec.name, f"batch tool crashed: {exc}")
                self.state_store.save_sample(state)
                stage_stats["failed"] += 1
            return

        # map results back to states by index
        for i, state in enumerate(pending):
            if i < len(results):
                result = results[i]
                if result.status == "completed":
                    state.mark_stage_completed(
                        spec.name,
                        verdict=result.verdict,
                        artifacts=result.artifacts,
                        data=result.data,
                    )
                else:
                    state.mark_stage_failed(spec.name, result.error or "batch item failed")
            else:
                state.mark_stage_failed(spec.name, "batch tool returned fewer results than entries")

            self.state_store.save_sample(state)
            outcome = self._classify_outcome(state, spec.name)
            stage_stats[outcome] += 1

    # -- helpers --

    def _classify_outcome(self, state: SampleState, stage_name: str) -> str:
        output = state.history.get(stage_name)
        if output is None:
            return "failed"
        if output.status == "completed" and output.verdict == "skip":
            return "skipped"
        if output.status in ("skipped", "failed"):
            return output.status
        return "completed"

    def _execute_with_timeout(self, tool: MapTool, ctx: StageContext, timeout: int) -> StageResult:
        if timeout <= 0:
            return tool.process(ctx)

        result_holder: list[StageResult] = []
        error_holder: list[Exception] = []

        def _run():
            try:
                result_holder.append(tool.process(ctx))
            except Exception as e:
                error_holder.append(e)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            raise TimeoutError(f"tool timed out after {timeout}s")

        if error_holder:
            raise error_holder[0]

        if not result_holder:
            raise RuntimeError("tool completed without producing a result")

        return result_holder[0]

    def _generate_context_files(self, sample_states: dict[str, SampleState]) -> None:
        for sid, state in sample_states.items():
            if state.is_active():
                sample_dir = self.state_store.sample_dir(sid)
                try:
                    generate_context(sample_dir, state)
                except Exception as exc:
                    log.debug("context generation failed for %s: %s", sid, exc)

    def _teardown_tools(self) -> None:
        for _, tool in self.stages:
            try:
                tool.teardown()
            except Exception as e:
                log.warning("tool '%s' teardown error: %s", tool.spec.name, e)
        try:
            self.ingest.teardown()
        except Exception as e:
            log.warning("ingest tool teardown error: %s", e)

    def _install_signal_handler(self) -> None:
        try:
            self._original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_signal)
        except (OSError, ValueError):
            pass

    def _restore_signal_handler(self) -> None:
        if self._original_sigint is not None:
            try:
                signal.signal(signal.SIGINT, self._original_sigint)
            except (OSError, ValueError):
                pass

    def _handle_signal(self, signum, frame) -> None:
        if self._shutdown_event.is_set():
            log.warning("forced shutdown")
            os._exit(1)
        log.warning("shutdown requested (press ctrl+c again to force)")
        self._shutdown_event.set()
