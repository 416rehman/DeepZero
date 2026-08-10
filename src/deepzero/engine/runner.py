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
from typing import TYPE_CHECKING, Any, Callable

from rich.console import Console

if TYPE_CHECKING:
    from deepzero.engine.ui import PipelineDashboard

from deepzero.engine.context import generate_context
from deepzero.engine.stage import (
    BulkMapProcessor,
    FailurePolicy,
    GlobalConfig,
    IngestProcessor,
    LLMProtocol,
    MapProcessor,
    Processor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
    ReduceProcessor,
    StageSpec,
    stage_input_digest,
)
from deepzero.engine.state import RunState, SampleState, StateStore, atomic_replace
from deepzero.engine.types import RunStatus, SampleStatus, StageStatus, Verdict

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


class _UIProgressAdapter:
    def __init__(self, dashboard: PipelineDashboard | None, name: str):
        self.dashboard = dashboard
        self.name = name

    def update(
        self, amount: int = 0, total: int | None = None, description: str | None = None
    ) -> None:
        if self.dashboard:
            self.dashboard.stage_update(
                self.name, advance=amount, total=total, description=description
            )


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
        dashboard: PipelineDashboard | None = None,
        progress_hook: Callable[[], None] | None = None,
    ):
        self.ingest = ingest
        self.stages = stages
        self.state_store = state_store
        self.pipeline_dir = pipeline_dir
        self.global_config = global_config
        self.llm = llm
        self.default_max_workers = default_max_workers
        self.console = console or Console()
        self.dashboard = dashboard
        # called when new results have landed, so a caller can refresh a live
        # view. never allowed to interrupt the run
        self.progress_hook = progress_hook
        self._shutdown_event = threading.Event()
        self._original_sigint = None

    def _notify_progress(self) -> None:
        # a report built later needs to know the run was still moving at this
        # point, not merely that it once started.
        run_state = getattr(self, "_active_run_state", None)
        if run_state is not None:
            try:
                run_state.touch()
                self.state_store.save_run(run_state)
            except OSError as exc:
                log.debug("could not record progress time: %s", exc)
        if self.progress_hook is None:
            return
        try:
            self.progress_hook()
        except Exception as exc:  # noqa: BLE001 - a view refresh must never fail a run
            log.debug("progress hook failed: %s", exc)

    def _conclusion_writer(self, spec: StageSpec):
        """the ctx.conclude a corpus-wide stage gets.

        Recorded on the run rather than on any sample, because that is what it is
        about, and saved as soon as it is written so an interrupted run still
        carries the conclusion it had already reached.
        """

        def conclude(**fields: Any) -> None:
            run_state = getattr(self, "_active_run_state", None)
            if run_state is None:
                log.warning("%s concluded before a run was open; ignored", spec.name)
                return
            entry = {k: v for k, v in fields.items() if v is not None}
            entry["stage"] = spec.name
            run_state.conclusion = {**run_state.conclusion, **entry}
            try:
                self.state_store.save_run(run_state)
            except OSError as exc:
                log.warning("could not record the conclusion from %s: %s", spec.name, exc)

        return conclude

    def _digest_for(self, spec: StageSpec) -> str:
        """this stage's input fingerprint, computed once per run.

        Recomputed per sample it would read the same rule set thousands of times.
        """
        if not hasattr(self, "_digest_cache"):
            self._digest_cache: dict[str, str] = {}
        if spec.name not in self._digest_cache:
            self._digest_cache[spec.name] = stage_input_digest(spec, self.pipeline_dir)
        return self._digest_cache[spec.name]

    def _make_entry(self, state: SampleState, spec: StageSpec | None = None) -> ProcessorEntry:
        # centralizes ProcessorEntry construction for map/reduce/batch
        cache_is_valid = True
        if spec is not None:
            previous = state.history.get(spec.name)
            if previous is not None and previous.input_digest:
                # the stage ran before with different inputs, so whatever it
                # wrote beside the sample describes those inputs, not these
                cache_is_valid = previous.input_digest == self._digest_for(spec)
        return ProcessorEntry(
            sample_id=state.sample_id,
            source_path=Path(state.source_path),
            filename=state.filename,
            sample_dir=self.state_store.sample_dir(state.sample_id),
            cache_is_valid=cache_is_valid,
            _store=self.state_store,
        )

    def run(
        self,
        target: Path,
        run_state: RunState,
    ) -> RunState:
        self._active_run_state = run_state
        self._install_signal_handler()
        run_state.mark_running()
        self.state_store.save_run(run_state)

        try:
            return self._execute_pipeline_stages(target, run_state)
        except KeyboardInterrupt:
            log.warning("interrupted by user - saving state")
            run_state.mark_interrupted()
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
        log.info("setup: initializing %d processors", len(stage_names))

        self.ingest.setup(self.global_config)
        for _, processor in self.stages:
            processor.setup(self.global_config)

        log.info("pipeline: %s", " -> ".join(stage_names))

        if self.dashboard:
            self.dashboard.start()

        try:
            return self._run_all_stages(target, run_state, stage_names)
        finally:
            if self.dashboard:
                status = (
                    run_state.status.value
                    if hasattr(run_state.status, "value")
                    else str(run_state.status)
                )
                self.dashboard.finish(status)

    def _run_all_stages(
        self,
        target: Path,
        run_state: RunState,
        stage_names: list[str],
    ) -> RunState:
        sample_states = self._resume_or_ingest(target, run_state, stage_names)
        self._active_sample_states = sample_states
        if sample_states is None:
            return run_state

        # breadth-first stage execution
        for spec, processor in self.stages:
            if self._shutdown_event.is_set():
                log.warning("shutdown requested - stopping pipeline")
                break

            from deepzero.engine.state import StageStatus, Verdict

            active = []
            for s in sample_states.values():
                if spec.name in s.history or s.is_active():
                    active.append(s)

            log.info("%s: %d active samples", spec.name, len(active))

            if not active:
                log.info("%s: no active samples, skipping", spec.name)
                if self.dashboard:
                    self.dashboard.stage_skip(spec.name)
                continue

            stage_stats = {"completed": 0, "filtered": 0, "failed": 0, "timed_out": 0}

            for s in active:
                output = s.history.get(spec.name)
                if output and output.status not in (StageStatus.PENDING, StageStatus.RUNNING):
                    if output.status == StageStatus.COMPLETED and output.verdict == Verdict.FILTER:
                        stage_stats["filtered"] += 1
                    elif output.status == StageStatus.FILTERED:
                        stage_stats["filtered"] += 1
                    elif output.status == StageStatus.FAILED:
                        stage_stats["failed"] += 1
                    elif output.status == StageStatus.TIMED_OUT:
                        stage_stats["timed_out"] += 1
                    elif output.status == StageStatus.COMPLETED:
                        stage_stats["completed"] += 1

            is_fully_cached = False
            if len(active) > 0:
                digest = self._digest_for(spec)
                pending_count = sum(1 for s in active if not s.is_stage_done(spec.name, digest))
                is_fully_cached = pending_count == 0

            if self.dashboard:
                self.dashboard.stage_start(
                    spec.name,
                    len(active),
                    passed=stage_stats["completed"],
                    filtered=stage_stats["filtered"],
                    failed=stage_stats["failed"],
                    timed_out=stage_stats["timed_out"],
                    is_fully_cached=is_fully_cached,
                )

            t0 = time.monotonic()

            if isinstance(processor, ReduceProcessor):
                ordered = self._run_reduce(processor, active, spec, stage_stats)
                # a reduce stage ranks what it keeps, so later stages work
                # through the samples in that order: if a long run is stopped
                # early, the ones it judged most important are already done
                if ordered:
                    self._reorder(sample_states, ordered)
            elif isinstance(processor, BulkMapProcessor):
                self._run_batch(processor, active, spec, stage_stats)
            else:
                self._run_map(processor, active, spec, stage_stats)

            self._notify_progress()

            self._apply_stage_limit(spec, sample_states, stage_stats)

            elapsed = time.monotonic() - t0

            passed = stage_stats["completed"]
            filtered = stage_stats["filtered"]
            failed = stage_stats["failed"]
            timed_out = stage_stats["timed_out"]
            # running out of time is reported on its own rather than folded into
            # either of the outcomes it is not: those samples neither passed nor
            # went wrong, and a longer budget is what they are waiting on
            log.info(
                "%s: %d passed, %d filtered, %d failed%s (%.1fs)",
                spec.name,
                passed,
                filtered,
                failed,
                f", {timed_out} out of time" if timed_out else "",
                elapsed,
            )

            if self.dashboard:
                self.dashboard.stage_done(
                    spec.name, passed, filtered, failed, elapsed, timed_out=timed_out
                )
                self.dashboard.set_transient_status("syncing state to disk...")

            # sync barrier
            self.state_store.save_manifest(list(sample_states.values()))
            self._generate_context_files(sample_states)

            if self.dashboard:
                self.dashboard.set_transient_status(None)

            if "per_stage" not in run_state.stats:
                run_state.stats["per_stage"] = {}
            run_state.stats["per_stage"][spec.name] = dict(stage_stats)
            self.state_store.save_run(run_state)

        if self._shutdown_event.is_set():
            run_state.mark_interrupted()
        elif run_state.status != RunStatus.FAILED:
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
        ingest_name = self.ingest.spec.name

        # fast resume: if states already exist on disk, skip the expensive ingest
        existing_states = self.state_store.list_samples()
        if existing_states:
            log.info(
                "resume: found %d existing samples, skipping ingest",
                len(existing_states),
            )
            sample_states: dict[str, SampleState] = {s.sample_id: s for s in existing_states}
            run_state.stats["discovered"] = len(sample_states)
            run_state.stages = stage_names
            self.state_store.save_run(run_state)

            if self.dashboard:
                self.dashboard.stage_start(
                    ingest_name,
                    len(sample_states),
                    passed=len(sample_states),
                    is_fully_cached=True,
                )
                self.dashboard.stage_done(ingest_name, len(sample_states), 0, 0, 0.0)

            return sample_states

        # fresh ingest
        if self.dashboard:
            self.dashboard.stage_start(ingest_name, 0)

        t0 = time.monotonic()
        log.info("%s: starting ingest", ingest_name)

        ctx = ProcessorContext(
            pipeline_dir=self.pipeline_dir,
            global_config=self.global_config,
            llm=self.llm,
            progress=_UIProgressAdapter(self.dashboard, ingest_name),
            shutdown_event=self._shutdown_event,
        )
        samples = self.ingest.process(ctx, target)
        elapsed = time.monotonic() - t0

        run_state.stats["discovered"] = len(samples)
        run_state.stages = stage_names
        self.state_store.save_run(run_state)

        log.info("%s: discovered %d samples (%.1fs)", ingest_name, len(samples), elapsed)

        if not samples or self._shutdown_event.is_set():
            if self.dashboard:
                self.dashboard.set_transient_status(None)
                self.dashboard.stage_done(
                    ingest_name,
                    len(samples) if not self._shutdown_event.is_set() else 0,
                    0,
                    0,
                    elapsed,
                )

            if not samples:
                run_state.mark_completed()
            else:
                run_state.mark_interrupted()

            self.state_store.save_run(run_state)
            return None

        if self.dashboard:
            self.dashboard.set_transient_status(
                f"syncing {len(samples)} discovered samples to disk..."
            )

        sample_states = {}
        collisions: list[tuple[str, str, str]] = []
        for sample in samples:
            # samples are keyed by id from here on, so two sharing one id means
            # the second replaces the first and the corpus quietly shrinks while
            # the discovered count still reports both. An ingest deriving its id
            # from something insufficiently unique is an easy mistake to make and
            # an almost impossible one to notice later, so it is named here.
            if sample.sample_id in sample_states:
                collisions.append(
                    (
                        sample.sample_id,
                        sample_states[sample.sample_id].filename,
                        sample.filename,
                    )
                )
                continue
            state = SampleState(
                sample_id=sample.sample_id,
                sha256=sample.data.get("sha256", ""),
                source_path=str(sample.source_path),
                filename=sample.filename,
                verdict=SampleStatus.ACTIVE,
            )
            state.mark_stage_completed(
                ingest_name,
                verdict=Verdict.CONTINUE,
                data=sample.data,
            )
            state.verdict = SampleStatus.ACTIVE
            sample_states[sample.sample_id] = state
            self.state_store.save_sample(state)

        if collisions:
            log.error(
                "%s produced %d sample(s) sharing an id with an earlier one; the "
                "later ones were dropped. The ingest is deriving ids from "
                "something that is not unique across this corpus.",
                ingest_name,
                len(collisions),
            )
            for sid, kept, dropped in collisions[:5]:
                log.error("  id %s: kept %s, dropped %s", sid, kept, dropped)
            if len(collisions) > 5:
                log.error("  ... and %d more", len(collisions) - 5)

        self.state_store.save_manifest(list(sample_states.values()))

        if self.dashboard:
            self.dashboard.set_transient_status(None)
            self.dashboard.stage_done(ingest_name, len(samples), 0, 0, elapsed)

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
            "%s: limit %d, truncating %d excess samples",
            spec.name,
            limit,
            len(excess),
        )
        for s in excess:
            s.mark_stage_skipped(spec.name, "limit reached")
            self.state_store.save_sample(s)
            # reclassify: was counted as completed, now truncated by limit
            if stage_stats["completed"] > 0:
                stage_stats["completed"] -= 1
            stage_stats["filtered"] += 1

    # -- map execution --

    def _resolve_parallelism(self, spec: StageSpec, processor: Processor) -> int:
        # explicit `parallel: N` is honored as-is; `parallel: 0` auto-scales to
        # cpu count but is clamped to whatever the pipeline's `max_workers`
        # setting allows and to the processor's own declared ceiling (if any),
        # so heavy stages don't spawn one worker per core.
        parallelism = spec.parallel
        if parallelism > 0:
            return parallelism
        parallelism = os.cpu_count() or 4
        for ceiling, why in (
            (processor.max_parallelism(), "processor limit"),
            (self.default_max_workers, "max_workers setting"),
        ):
            if ceiling is not None and 0 < ceiling < parallelism:
                log.info("%s: capping auto concurrency to %d workers (%s)", spec.name, ceiling, why)
                parallelism = ceiling
        log.debug("%s: auto-scaled to %d workers", spec.name, parallelism)
        return parallelism

    def _run_map(
        self,
        processor: MapProcessor,
        active: list[SampleState],
        spec: StageSpec,
        stage_stats: dict[str, int],
    ) -> None:

        # filter out samples that already completed this stage (resume granularity)
        digest = self._digest_for(spec)
        pending = [s for s in active if not s.is_stage_done(spec.name, digest)]
        cached = len(active) - len(pending)
        if cached > 0:
            log.info("%s: %d cached, %d pending", spec.name, cached, len(pending))
            if self.dashboard:
                self.dashboard.stage_update(spec.name, advance=cached)

        if not pending:
            return

        parallelism = self._resolve_parallelism(spec, processor)

        if parallelism <= 1:
            dirty: list[SampleState] = []
            last_flush = time.monotonic()
            for state in pending:
                if self._shutdown_event.is_set():
                    break
                result = self._process_one_map(state, spec, processor)
                if self._shutdown_event.is_set():
                    break
                self._apply_result(state, spec, result, persist=False)
                dirty.append(state)
                outcome = self._classify_outcome(state, spec.name)
                stage_stats[outcome] += 1
                if self.dashboard:
                    self.dashboard.stage_update(
                        spec.name,
                        advance=1,
                        passed=1 if outcome == "completed" else 0,
                        filtered=1 if outcome == "filtered" else 0,
                        failed=1 if outcome == "failed" else 0,
                    )
                if len(dirty) >= 50 or time.monotonic() - last_flush > 10:
                    for s in dirty:
                        self.state_store.save_sample(s)
                    dirty.clear()
                    last_flush = time.monotonic()
                    self._notify_progress()
            for s in dirty:
                self.state_store.save_sample(s)
        else:
            max_workers = min(parallelism, len(pending))
            dirty: list[SampleState] = []
            last_flush = time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(self._process_one_map, s, spec, processor): s for s in pending
                }
                for future in concurrent.futures.as_completed(future_map):
                    if self._shutdown_event.is_set():
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    state = future_map[future]
                    exc = future.exception()

                    if self._shutdown_event.is_set():
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    if exc:
                        log.error("%s: unhandled error on %s: %s", spec.name, state.filename, exc)
                        result = ProcessorResult.fail(f"{type(exc).__name__}: {exc}")
                    else:
                        result = future.result()

                    if self._shutdown_event.is_set() or result is None:
                        continue

                    self._apply_result(state, spec, result, persist=False)
                    dirty.append(state)

                    outcome = self._classify_outcome(state, spec.name)
                    stage_stats[outcome] += 1
                    if self.dashboard:
                        self.dashboard.stage_update(
                            spec.name,
                            advance=1,
                            passed=1 if outcome == "completed" else 0,
                            filtered=1 if outcome == "filtered" else 0,
                            failed=1 if outcome == "failed" else 0,
                            timed_out=1 if outcome == "timed_out" else 0,
                        )
                    if len(dirty) >= 50 or time.monotonic() - last_flush > 10:
                        for s in dirty:
                            self.state_store.save_sample(s)
                        dirty.clear()
                        last_flush = time.monotonic()
                        self._notify_progress()
            for s in dirty:
                self.state_store.save_sample(s)

    def _apply_result(
        self,
        state: SampleState,
        spec: StageSpec,
        result: ProcessorResult | None,
        persist: bool = True,
    ) -> None:
        if result is None:
            return

        if result.status == StageStatus.COMPLETED:
            if result.data and "__skipped" in result.data:
                # work that was already done counts as passed and the sample
                # continues to the next stage, per MapProcessor.should_skip
                state.mark_stage_cached(spec.name, result.data["__skipped"])
            else:
                state.mark_stage_completed(
                    spec.name,
                    verdict=result.verdict,
                    artifacts=result.artifacts,
                    data=result.data,
                    input_digest=self._digest_for(spec),
                )
        elif result.status == StageStatus.TIMED_OUT:
            budget = int((result.data or {}).get("__timeout_budget", spec.timeout) or 0)
            state.mark_stage_timed_out(spec.name, budget)
            log.warning(
                "[%s] %s ran out of time after %ds - rerun with --retry-timeouts to give it longer",
                spec.name,
                state.filename,
                budget,
            )
        else:
            state.mark_stage_failed(spec.name, result.error or "processor returned failed status")
            if result.error:
                log.error("[%s] %s failed: %s", spec.name, state.filename, result.error)

        if persist:
            self.state_store.save_sample(state)

        if result.status == StageStatus.FAILED and spec.on_failure == FailurePolicy.ABORT:
            self._shutdown_event.set()

    def _process_one_map(
        self,
        state: SampleState,
        spec: StageSpec,
        processor: MapProcessor,
    ) -> ProcessorResult | None:
        sample_dir = self.state_store.sample_dir(state.sample_id)

        ctx = ProcessorContext(
            pipeline_dir=self.pipeline_dir,
            global_config=self.global_config,
            llm=self.llm,
            log=logging.getLogger(f"deepzero.processor.{spec.name}"),
            progress=_UIProgressAdapter(self.dashboard, spec.name),
            shutdown_event=self._shutdown_event,
        )
        entry = self._make_entry(state, spec)
        sample_dir.mkdir(parents=True, exist_ok=True)

        # optional skip hook (e.g. cached decompilation)
        skip_reason = processor.should_skip(ctx, entry)
        if skip_reason:
            return ProcessorResult.ok(data={"__skipped": skip_reason})

        state.mark_stage_running(spec.name)

        attempts = 0
        max_attempts = spec.max_retries + 1 if spec.on_failure == FailurePolicy.RETRY else 1

        while attempts < max_attempts:
            attempts += 1
            try:
                result = self._execute_with_timeout(processor, ctx, entry, spec.timeout)

                if result.status == StageStatus.COMPLETED:
                    return result

                if self._shutdown_event.is_set():
                    return None

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

                    if self._shutdown_event.wait(backoff):
                        return None
                    continue

                if self._shutdown_event.is_set():
                    return None

                return result
            except TimeoutError:
                # TimeoutError is an OSError, so this has to come first or the
                # handler below files running out of time as something breaking
                if self._shutdown_event.is_set():
                    return None
                log.warning(
                    "[%s] %s exceeded its %ds budget", spec.name, state.filename, spec.timeout
                )
                return ProcessorResult.timed_out(spec.timeout)
            except PROCESSOR_ERRORS as exc:
                if self._shutdown_event.is_set():
                    return None

                error_msg = f"{type(exc).__name__}: {exc}"

                # capture traceback out of band
                err_log = sample_dir / f"{spec.name}_error.log"
                fd, tmp = tempfile.mkstemp(dir=str(sample_dir), suffix=".log")
                try:
                    os.write(fd, tb_module.format_exc().encode("utf-8"))
                    os.close(fd)
                    atomic_replace(Path(tmp), err_log)
                except OSError as exc:
                    try:
                        os.close(fd)
                    except OSError as cleanup_exc:
                        raise RuntimeError(
                            f"failed to explicitly close descriptor for {state.filename}"
                        ) from cleanup_exc
                    raise RuntimeError(f"failed to write error log for {state.filename}") from exc

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
                    if self._shutdown_event.wait(backoff):
                        return None
                    continue

                if self._shutdown_event.is_set():
                    return None

                return ProcessorResult.fail(error_msg)

        return ProcessorResult.fail("processor max attempts exceeded")

    def _invoke_stage(
        self, spec: StageSpec, call: Callable[[], Any]
    ) -> tuple[Any, Exception | None]:
        """run a whole-corpus stage under its failure policy.

        Reduce and bulk-map stages are one invocation for the entire corpus
        rather than one per sample, so `on_failure: retry` and `max_retries`
        apply to that invocation. Returns what the call produced, or the error
        it ended on; deciding what a failure means for the samples is the
        caller's, because a barrier and a batch answer that differently.
        """
        attempts = 0
        max_attempts = spec.max_retries + 1 if spec.on_failure == FailurePolicy.RETRY else 1
        last: Exception | None = None

        while attempts < max_attempts:
            attempts += 1
            try:
                return call(), None
            except PROCESSOR_ERRORS as exc:
                last = exc
                if self._shutdown_event.is_set():
                    return None, exc
                if attempts < max_attempts:
                    backoff = min(2**attempts, 30)
                    log.warning(
                        "[%s] stage failed (attempt %d/%d), retrying in %ds: %s",
                        spec.name,
                        attempts,
                        max_attempts,
                        backoff,
                        exc,
                    )
                    if self._shutdown_event.wait(backoff):
                        return None, exc

        return None, last

    @staticmethod
    def _reorder(sample_states: dict[str, SampleState], order: list[str]) -> None:
        ranked = [sid for sid in order if sid in sample_states]
        if not ranked:
            return
        rest = [sid for sid in sample_states if sid not in set(ranked)]
        reordered = {sid: sample_states[sid] for sid in ranked + rest}
        sample_states.clear()
        sample_states.update(reordered)

    # -- reduce execution --

    def _run_reduce(
        self,
        processor: ReduceProcessor,
        active: list[SampleState],
        spec: StageSpec,
        stage_stats: dict[str, int],
    ) -> list[str]:
        """run a reduce stage. returns the ids it kept, in the order it chose."""
        log.info("%s: reducing %d active samples", spec.name, len(active))
        ctx = ProcessorContext(
            pipeline_dir=self.pipeline_dir,
            global_config=self.global_config,
            llm=self.llm,
            progress=_UIProgressAdapter(self.dashboard, spec.name),
            shutdown_event=self._shutdown_event,
            conclude=self._conclusion_writer(spec),
        )
        entries = [self._make_entry(state, spec) for state in active]
        results, error = self._invoke_stage(spec, lambda: processor.process(ctx, entries))
        if error is not None:
            # a barrier decides who survives, so a barrier that did not run has
            # nothing to apply: every active sample carries on, unranked. Said
            # plainly, because a corpus meant to be cut to its best few arriving
            # at the next stage whole is expensive and easy to miss in a log.
            log.error(
                "%s: reduce processor crashed (%s) - nothing was ranked or dropped, "
                "all %d active samples continue",
                spec.name,
                error,
                len(active),
            )
            if spec.on_failure == FailurePolicy.ABORT:
                self._shutdown_event.set()
            return []

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

        return list(results)

    # -- batch execution --

    def _run_batch(
        self,
        processor: BulkMapProcessor,
        active: list[SampleState],
        spec: StageSpec,
        stage_stats: dict[str, int],
    ) -> None:
        # filter out already-completed samples (resume)
        pending = [s for s in active if not s.is_stage_done(spec.name, self._digest_for(spec))]
        cached = len(active) - len(pending)
        if cached > 0:
            log.info("  %d already completed (cached), %d pending", cached, len(pending))
            if self.dashboard:
                self.dashboard.stage_update(spec.name, advance=cached)

        if not pending:
            return

        entries = [self._make_entry(state, spec) for state in pending]

        log.info("%s: batch processing %d samples", spec.name, len(entries))

        ctx = ProcessorContext(
            pipeline_dir=self.pipeline_dir,
            global_config=self.global_config,
            llm=self.llm,
            progress=_UIProgressAdapter(self.dashboard, spec.name),
            shutdown_event=self._shutdown_event,
            conclude=self._conclusion_writer(spec),
        )
        results, error = self._invoke_stage(spec, lambda: processor.process(ctx, entries))

        if error is not None:
            # a crash immediately after ctrl+c is the shutdown reaching the
            # external process, not the batch failing, so let the flag arrive
            # before every sample is blamed for it
            if self._shutdown_event.wait(0.25):
                return
            log.error("  batch processor '%s' crashed: %s", spec.name, error)
            for state in pending:
                self._apply_result(
                    state, spec, ProcessorResult.fail(f"batch processor crashed: {error}")
                )
                stage_stats["failed"] += 1
                if self.dashboard:
                    self.dashboard.stage_update(spec.name, advance=1, failed=1)
            return

        # map results back to states by index
        for i, state in enumerate(pending):
            if self._shutdown_event.is_set():
                break

            if i < len(results):
                result = results[i]
            else:
                result = ProcessorResult.fail("batch processor returned fewer results than entries")

            # the same path a map stage's result takes, so a batch honors
            # on_failure and records running out of time the same way
            self._apply_result(state, spec, result)
            outcome = self._classify_outcome(state, spec.name)
            stage_stats[outcome] += 1
            if self.dashboard:
                self.dashboard.stage_update(
                    spec.name,
                    advance=1,
                    passed=1 if outcome == "completed" else 0,
                    filtered=1 if outcome == "filtered" else 0,
                    failed=1 if outcome == "failed" else 0,
                )

    # -- helpers --

    def _classify_outcome(self, state: SampleState, stage_name: str) -> str:
        output = state.history.get(stage_name)
        if output is None:
            return "failed"
        if output.status == StageStatus.COMPLETED and output.verdict == Verdict.FILTER:
            return "filtered"
        if output.status in (StageStatus.FILTERED, StageStatus.FAILED, StageStatus.TIMED_OUT):
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

        outcome: dict[str, Any] = {}
        finished = threading.Event()

        def _call() -> None:
            try:
                outcome["result"] = processor.process(ctx, entry)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread
                outcome["error"] = exc
            finally:
                finished.set()

        # a bare daemon thread rather than a pool: nothing can stop a thread
        # that is already running, so the only way to honor the budget is to
        # stop waiting on it. A pool joins its worker on the way out, which
        # would hand back "timed out after 30s" half an hour later, and a
        # non-daemon thread would go on to hold the interpreter open at exit.
        # The stage moves on and the sample is recorded as out of time.
        worker = threading.Thread(
            target=_call, name=f"deepzero-{entry.sample_id[:12]}", daemon=True
        )
        worker.start()
        if not finished.wait(timeout):
            raise TimeoutError(f"processor timed out after {timeout}s")

        error = outcome.get("error")
        if error is not None:
            raise error
        return outcome["result"]

    def _generate_context_files(self, sample_states: dict[str, SampleState]) -> None:
        active_items = [(sid, state) for sid, state in sample_states.items() if state.is_active()]
        if not active_items:
            return

        def _gen(sid: str, state: SampleState) -> None:
            sample_dir = self.state_store.sample_dir(sid)
            state_file = sample_dir / "state.json"
            context_file = sample_dir / "context.md"

            if context_file.exists() and state_file.exists():
                try:
                    if context_file.stat().st_mtime >= state_file.stat().st_mtime:
                        return
                except OSError:
                    pass

            try:
                generate_context(sample_dir, state)
            except PROCESSOR_ERRORS as exc:
                log.warning(
                    "context generation failed for %s: %s - %s", sid, type(exc).__name__, exc
                )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(32, (os.cpu_count() or 4) * 4)
        ) as executor:
            future_map = {executor.submit(_gen, sid, state): sid for sid, state in active_items}
            for _ in concurrent.futures.as_completed(future_map):
                if self._shutdown_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

    def _teardown_tools(self) -> None:
        errors: list[str] = []
        for _, processor in self.stages:
            try:
                processor.teardown()
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                errors.append(f"{processor.spec.name}: {e}")
                log.warning("processor '%s' teardown error: %s", processor.spec.name, e)
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
            if hasattr(self, "_active_run_state") and getattr(self, "_active_run_state", None):
                self._active_run_state.mark_interrupted()
                self.state_store.save_run(self._active_run_state)
            if hasattr(self, "_active_sample_states") and getattr(
                self, "_active_sample_states", None
            ):
                self.state_store.save_manifest(list(self._active_sample_states.values()))
            os._exit(1)
        log.warning("shutdown requested (press ctrl+c again to force)")
        self._shutdown_event.set()
