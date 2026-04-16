from __future__ import annotations

import concurrent.futures
import logging
import os
import signal
import tempfile
import threading
import time
import traceback as tb_module
from pathlib import Path

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)

from deepzero.engine.context import generate_context
from deepzero.engine.stage import (
    FailurePolicy,
    GlobalConfig,
    IngestProcessor,
    LLMProtocol,
    MapProcessor,
    ReduceProcessor,
    BulkMapProcessor,
    ProcessorContext,
    ProcessorResult,
    StageSpec,
    Processor,
    ProcessorEntry,
)
from deepzero.engine.types import StageStatus, Verdict, SampleStatus, RunStatus
from deepzero.engine.state import RunState, SampleState, StateStore

log = logging.getLogger("deepzero.runner")

# exception types that processors are allowed to raise without being a framework bug
PROCESSOR_ERRORS = (
    RuntimeError,
    ValueError,
    TypeError,
    OSError,
    AttributeError,
    LookupError,
    AssertionError,
)


# suppresses info-level logs while a progress bar is active
class _ProgressFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


class PipelineRunner:
    # breadth-first pipeline executor with sync barriers

    def __init__(
        self,
        ingest: IngestProcessor,
        stages: list[tuple[StageSpec, Processor]],
        state_store: StateStore,
        pipeline_dir: Path,
        global_config: GlobalConfig,
        llm: LLMProtocol | None = None,
        default_max_workers: int = 4,
        console: Console | None = None,
    ):
        self.ingest = ingest
        self.stages = stages
        self.state_store = state_store
        self.pipeline_dir = pipeline_dir
        self.global_config = global_config
        self.llm = llm
        self.default_max_workers = default_max_workers
        self.console = console or Console()
        self._shutdown_event = threading.Event()
        self._original_sigint = None

    def _make_entry(self, state: SampleState) -> ProcessorEntry:
        # centralizes ProcessorEntry construction for map/reduce/batch
        return ProcessorEntry(
            sample_id=state.sample_id,
            source_path=Path(state.source_path),
            filename=state.filename,
            sample_dir=self.state_store.sample_dir(state.sample_id),
            _store=self.state_store,
        )

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
            run_state.status = RunStatus.INTERRUPTED
            self.state_store.save_run(run_state)
            return run_state
        except PROCESSOR_ERRORS as e:
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
        for _, processor in self.stages:
            processor.setup(self.global_config)

        log.info("--- setup complete ---")
        log.info("pipeline: %s", " -> ".join(stage_names))

        sample_states = self._resume_or_ingest(target, run_state, stage_names)
        if sample_states is None:
            return run_state

        # breadth-first stage execution
        for spec, processor in self.stages:
            if self._shutdown_event.is_set():
                log.warning("shutdown requested - stopping pipeline")
                break

            active = [s for s in sample_states.values() if s.is_active()]

            log.info("--- %s --- %d active samples", spec.name, len(active))

            if not active:
                log.info("--- %s --- no active samples, skipping stage", spec.name)
                continue

            stage_stats = {"completed": 0, "filtered": 0, "failed": 0}

            if isinstance(processor, ReduceProcessor):
                self._run_reduce(processor, active, spec, stage_stats)
            elif isinstance(processor, BulkMapProcessor):
                self._run_batch(processor, active, spec, stage_stats)
            else:
                self._run_map(processor, active, spec, stage_stats)

            self._apply_stage_limit(spec, sample_states, stage_stats)

            # sync barrier
            self.state_store.save_manifest(list(sample_states.values()))
            self._generate_context_files(sample_states)

            if "per_stage" not in run_state.stats:
                run_state.stats["per_stage"] = {}
            run_state.stats["per_stage"][spec.name] = dict(stage_stats)
            self.state_store.save_run(run_state)

            passed = stage_stats["completed"]
            filtered = stage_stats["filtered"]
            failed = stage_stats["failed"]
            log.info(
                "--- %s -> %d passed, %d filtered, %d failed ---",
                spec.name,
                passed,
                filtered,
                failed,
            )

        run_state.mark_completed()
        self.state_store.save_run(run_state)
        self.state_store.save_manifest(list(sample_states.values()))
        return run_state

    def _resume_or_ingest(
        self,
        target: Path,
        run_state: RunState,
        stage_names: list[str],
    ) -> dict[str, SampleState] | None:
        # fast resume: if states already exist on disk, skip the expensive ingest
        existing_states = self.state_store.list_samples()
        if existing_states:
            log.info(
                "--- resume --- found %d existing sample states, skipping ingest",
                len(existing_states),
            )
            sample_states: dict[str, SampleState] = {
                s.sample_id: s for s in existing_states
            }
            run_state.stats["discovered"] = len(sample_states)
            run_state.stages = stage_names
            self.state_store.save_run(run_state)
            return sample_states

        # fresh run
        log.info("--- %s (ingest) ---", self.ingest.spec.name)
        ctx = ProcessorContext(
            pipeline_dir=self.pipeline_dir,
            global_config=self.global_config,
            llm=self.llm,
        )
        samples = self.ingest.process(ctx, target)

        run_state.stats["discovered"] = len(samples)
        run_state.stages = stage_names
        self.state_store.save_run(run_state)

        log.info("--- %s -> %d samples ---", self.ingest.spec.name, len(samples))

        if not samples:
            run_state.mark_completed()
            self.state_store.save_run(run_state)
            return None

        sample_states = {}
        for sample in samples:
            state = SampleState(
                sample_id=sample.sample_id,
                sha256=sample.data.get("sha256", ""),
                source_path=str(sample.source_path),
                filename=sample.filename,
                verdict=SampleStatus.ACTIVE,
            )
            state.mark_stage_completed(
                self.ingest.spec.name,
                verdict=Verdict.CONTINUE,
                data=sample.data,
            )
            state.verdict = SampleStatus.ACTIVE
            sample_states[sample.sample_id] = state
            self.state_store.save_sample(state)

        self.state_store.save_manifest(list(sample_states.values()))
        return sample_states

    def _apply_stage_limit(
        self,
        spec: StageSpec,
        sample_states: dict[str, SampleState],
        stage_stats: dict[str, int],
    ) -> None:
        limit = spec.config.get("limit", 0)
        if limit <= 0:
            return
        still_active = [s for s in sample_states.values() if s.is_active()]
        if len(still_active) <= limit:
            return
        excess = still_active[limit:]
        log.info(
            "  %s limit (%d): truncating %d excess samples",
            spec.name,
            limit,
            len(excess),
        )
        for s in excess:
            s.mark_stage_skipped(spec.name, "limit reached")
            self.state_store.save_sample(s)
            stage_stats["filtered"] += 1

    # -- map execution --

    def _create_progress_bar(self, description: str, total: int) -> Progress:
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[cyan]{task.completed}/{task.total} completed"),
            TimeRemainingColumn(),
            console=self.console,
            transient=True,
        )

    def _run_map(
        self,
        processor: MapProcessor,
        active: list[SampleState],
        spec: StageSpec,
        stage_stats: dict[str, int],
    ) -> None:

        # filter out samples that already completed this stage (resume granularity)
        pending = [s for s in active if not s.is_stage_done(spec.name)]
        cached = len(active) - len(pending)
        if cached > 0:
            log.info(
                "  %d already completed (cached), %d pending", cached, len(pending)
            )
            stage_stats["completed"] += cached

        if not pending:
            return

        parallelism = spec.parallel
        if parallelism <= 0:
            parallelism = os.cpu_count() or 4
            log.info("  %s auto-scaled to %d workers", spec.name, parallelism)

        # suppress info logs during progress bar
        progress_filter = _ProgressFilter()
        dz_logger = logging.getLogger("deepzero")
        dz_logger.addFilter(progress_filter)

        try:
            with self._create_progress_bar(spec.name, len(pending)) as progress:
                task = progress.add_task(
                    f"[cyan]running {spec.name}[/]", total=len(pending)
                )

                if parallelism <= 1:
                    for state in pending:
                        if self._shutdown_event.is_set():
                            break
                        self._process_one_map(state, spec, processor)
                        outcome = self._classify_outcome(state, spec.name)
                        stage_stats[outcome] += 1
                        progress.advance(task)
                else:
                    max_workers = min(parallelism, len(pending))
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=max_workers
                    ) as executor:
                        future_map = {
                            executor.submit(
                                self._process_one_map, s, spec, processor
                            ): s
                            for s in pending
                        }
                        for future in concurrent.futures.as_completed(future_map):
                            if self._shutdown_event.is_set():
                                executor.shutdown(wait=False, cancel_futures=True)
                                break
                            state = future_map[future]
                            exc = future.exception()
                            if exc:
                                log.error(
                                    "  %s unhandled error: %s", state.filename, exc
                                )
                                state.mark_stage_failed(
                                    spec.name, f"{type(exc).__name__}: {exc}"
                                )
                                self.state_store.save_sample(state)

                            outcome = self._classify_outcome(state, spec.name)
                            stage_stats[outcome] += 1
                            progress.advance(task)
        finally:
            dz_logger.removeFilter(progress_filter)

    def _process_one_map(
        self,
        state: SampleState,
        spec: StageSpec,
        processor: MapProcessor,
    ) -> None:
        sample_dir = self.state_store.sample_dir(state.sample_id)

        ctx = ProcessorContext(
            pipeline_dir=self.pipeline_dir,
            global_config=self.global_config,
            llm=self.llm,
            log=logging.getLogger(f"deepzero.processor.{spec.name}"),
        )
        entry = self._make_entry(state)

        # optional skip hook (e.g. cached decompilation)
        skip_reason = processor.should_skip(ctx, entry)
        if skip_reason:
            state.mark_stage_skipped(spec.name, skip_reason)
            self.state_store.save_sample(state)
            return

        state.mark_stage_running(spec.name)
        self.state_store.save_sample(state)

        attempts = 0
        max_attempts = (
            spec.max_retries + 1 if spec.on_failure == FailurePolicy.RETRY else 1
        )

        while attempts < max_attempts:
            attempts += 1
            try:
                result = self._execute_with_timeout(processor, ctx, entry, spec.timeout)

                if result.status == StageStatus.COMPLETED:
                    state.mark_stage_completed(
                        spec.name,
                        verdict=result.verdict,
                        artifacts=result.artifacts,
                        data=result.data,
                    )
                    # immediate save - don't wait for barrier (resume granularity)
                    self.state_store.save_sample(state)
                    return

                if attempts < max_attempts:
                    backoff = min(2**attempts, 30)
                    log.warning(
                        "[%s] %s failed (attempt %d/%d), retrying in %ds: %s",
                        spec.name,
                        state.filename,
                        attempts,
                        max_attempts,
                        backoff,
                        result.error,
                    )
                    time.sleep(backoff)
                    continue

                state.mark_stage_failed(
                    spec.name, result.error or "processor returned failed status"
                )
                log.error("[%s] %s failed: %s", spec.name, state.filename, result.error)
                self.state_store.save_sample(state)

                if spec.on_failure == FailurePolicy.ABORT:
                    self._shutdown_event.set()
                return

            except PROCESSOR_ERRORS as exc:
                error_msg = f"{type(exc).__name__}: {exc}"

                # capture traceback out of band
                err_log = sample_dir / f"{spec.name}_error.log"
                fd, tmp = tempfile.mkstemp(dir=str(sample_dir), suffix=".log")
                try:
                    os.write(fd, tb_module.format_exc().encode("utf-8"))
                    os.close(fd)
                    os.replace(tmp, str(err_log))
                except OSError as exc:
                    try:
                        os.close(fd)
                    except OSError as cleanup_exc:
                        raise RuntimeError(
                            f"failed to explicitly close descriptor for {state.filename}"
                        ) from cleanup_exc
                    raise RuntimeError(
                        f"failed to write error log for {state.filename}"
                    ) from exc

                if attempts < max_attempts:
                    backoff = min(2**attempts, 30)
                    log.warning(
                        "[%s] %s exception (attempt %d/%d), retrying in %ds: %s",
                        spec.name,
                        state.filename,
                        attempts,
                        max_attempts,
                        backoff,
                        error_msg,
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
        processor: ReduceProcessor,
        active: list[SampleState],
        spec: StageSpec,
        stage_stats: dict[str, int],
    ) -> None:
        log.info("  reduce: %d active samples -> %s", len(active), spec.name)
        ctx = ProcessorContext(
            pipeline_dir=self.pipeline_dir,
            global_config=self.global_config,
            llm=self.llm,
        )
        entries = [self._make_entry(state) for state in active]
        try:
            results = processor.process(ctx, entries)
        except PROCESSOR_ERRORS as exc:
            log.error("  reduce processor '%s' crashed: %s", spec.name, exc)
            return

        kept_ids = set(results)
        for state in active:
            if state.sample_id in kept_ids:
                if not state.is_stage_done(spec.name):
                    state.mark_stage_completed(spec.name, verdict=Verdict.CONTINUE)
                    stage_stats["completed"] += 1
            else:
                if not state.is_stage_done(spec.name):
                    state.verdict = SampleStatus.FILTERED
                    state.mark_stage_skipped(spec.name, "filtered by reduce")
                    stage_stats["filtered"] += 1
            self.state_store.save_sample(state)

    # -- batch execution --

    def _run_batch(
        self,
        processor: BulkMapProcessor,
        active: list[SampleState],
        spec: StageSpec,
        stage_stats: dict[str, int],
    ) -> None:
        # filter out already-completed samples (resume)
        pending = [s for s in active if not s.is_stage_done(spec.name)]
        cached = len(active) - len(pending)
        if cached > 0:
            log.info(
                "  %d already completed (cached), %d pending", cached, len(pending)
            )
            stage_stats["completed"] += cached

        if not pending:
            return

        entries = [self._make_entry(state) for state in pending]

        log.info("  batch: processing %d samples with %s", len(entries), spec.name)

        try:
            ctx = ProcessorContext(
                pipeline_dir=self.pipeline_dir,
                global_config=self.global_config,
                llm=self.llm,
            )
            results = processor.process(ctx, entries)
        except PROCESSOR_ERRORS as exc:
            log.error("  batch processor '%s' crashed: %s", spec.name, exc)
            for state in pending:
                state.mark_stage_failed(spec.name, f"batch processor crashed: {exc}")
                self.state_store.save_sample(state)
                stage_stats["failed"] += 1
            return

        # map results back to states by index
        for i, state in enumerate(pending):
            if i < len(results):
                result = results[i]
                if result.status == StageStatus.COMPLETED:
                    state.mark_stage_completed(
                        spec.name,
                        verdict=result.verdict,
                        artifacts=result.artifacts,
                        data=result.data,
                    )
                else:
                    state.mark_stage_failed(
                        spec.name, result.error or "batch item failed"
                    )
            else:
                state.mark_stage_failed(
                    spec.name, "batch processor returned fewer results than entries"
                )

            self.state_store.save_sample(state)
            outcome = self._classify_outcome(state, spec.name)
            stage_stats[outcome] += 1

    # -- helpers --

    def _classify_outcome(self, state: SampleState, stage_name: str) -> str:
        output = state.history.get(stage_name)
        if output is None:
            return "failed"
        if output.status == StageStatus.COMPLETED and output.verdict == Verdict.FILTER:
            return "filtered"
        if output.status in (StageStatus.FILTERED, StageStatus.FAILED):
            return output.status.value
        return "completed"

    def _execute_with_timeout(
        self,
        processor: MapProcessor,
        ctx: ProcessorContext,
        entry: ProcessorEntry,
        timeout: int,
    ) -> ProcessorResult:
        if timeout <= 0:
            return processor.process(ctx, entry)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(processor.process, ctx, entry)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(f"processor timed out after {timeout}s")

    def _generate_context_files(self, sample_states: dict[str, SampleState]) -> None:
        for sid, state in sample_states.items():
            if state.is_active():
                sample_dir = self.state_store.sample_dir(sid)
                try:
                    generate_context(sample_dir, state)
                except (
                    ValueError,
                    TypeError,
                    OSError,
                    RuntimeError,
                    AttributeError,
                ) as exc:
                    log.warning(
                        "context generation failed for %s: %s - %s",
                        sid,
                        type(exc).__name__,
                        exc,
                    )

    def _teardown_tools(self) -> None:
        errors: list[str] = []
        for _, processor in self.stages:
            try:
                processor.teardown()
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                errors.append(f"{processor.name}: {e}")
                log.warning("processor '%s' teardown error: %s", processor.name, e)
        try:
            self.ingest.teardown()
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            errors.append(f"ingest: {e}")
            log.warning("ingest processor teardown error: %s", e)
        if errors:
            log.warning("%d processor(s) failed teardown", len(errors))

    def _install_signal_handler(self) -> None:
        if threading.current_thread() is threading.main_thread():
            self._original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_signal)

    def _restore_signal_handler(self) -> None:
        if (
            self._original_sigint is not None
            and threading.current_thread() is threading.main_thread()
        ):
            signal.signal(signal.SIGINT, self._original_sigint)

    def _handle_signal(self, signum, frame) -> None:
        if self._shutdown_event.is_set():
            log.warning("forced shutdown")
            os._exit(1)
        log.warning("shutdown requested (press ctrl+c again to force)")
        self._shutdown_event.set()
