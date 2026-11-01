from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Protocol,
    TypedDict,
    runtime_checkable,
)

if TYPE_CHECKING:
    from deepzero.engine.state import StateStore

from deepzero.engine.state import StageOutput
from deepzero.engine.types import StageStatus, Verdict


class ProgressReporter(Protocol):
    def update(
        self, amount: int = 0, total: int | None = None, description: str | None = None
    ) -> None: ...


class _NullProgressReporter:
    def update(
        self, amount: int = 0, total: int | None = None, description: str | None = None
    ) -> None:
        pass


@runtime_checkable
class LLMProtocol(Protocol):
    def complete(
        self,
        messages: list[dict[str, str]],
        max_retries: int = ...,
        initial_backoff: float = ...,
        max_backoff: float = ...,
        backoff_decay: float = ...,
        **kwargs: Any,
    ) -> str: ...


class GlobalConfig(TypedDict, total=False):
    settings: dict[str, Any]
    knowledge: dict[str, Any]
    model: str
    # where the pipeline was loaded from. A config value naming a file that
    # ships with the pipeline (a blocklist, a rule set, a template) can only be
    # resolved against something, and the working directory is whatever the
    # reader happened to be in. setup() receives this config and no context, so
    # without it such a path is only ever cwd-relative.
    pipeline_dir: str


class ProcessorType(str, Enum):
    INGEST = "ingest"
    MAP = "map"
    REDUCE = "reduce"
    BULK_MAP = "bulk_map"


class FailurePolicy(str, Enum):
    SKIP = "skip"
    RETRY = "retry"
    ABORT = "abort"


# -- data structures --


@dataclass
class Sample:
    # unique identifier (typically sha256 prefix)
    sample_id: str
    # path to the original file
    source_path: Path
    # display name
    filename: str
    # initial data from discovery - goes into history["discover"].data
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessorEntry:
    # --- Populated dynamically by the Engine for downstream processors ---
    sample_id: str
    source_path: Path
    filename: str

    # working directory for this sample (work/<pipeline>/samples/<id>/)
    sample_dir: Path | None = None

    # whether this stage's own output on disk still describes the pipeline. A
    # processor that adopts its previous output instead of doing the work again
    # has to consult this: the file is only a valid cache while the stage that
    # wrote it had the same inputs. False means the file is from a prompt, rule
    # set or config that has since changed, and adopting it would report an
    # answer to a question nobody is asking any more.
    cache_is_valid: bool = True

    # attached automatically by the runner to enable memory-efficient lazy-loading
    _store: StateStore | None = field(default=None, repr=False, compare=False)

    @property
    def history(self) -> dict[str, StageOutput]:
        """Lazy load the execution history from disk only when actively accessed."""
        if hasattr(self, "_history"):
            return self._history
        if self._store is None:
            return {}
        loaded = self._store.load_sample(self.sample_id)
        if loaded is None:
            return {}
        return loaded.history

    def upstream(self, processor_name: str) -> StageOutput | None:
        # get the full output from a previous processor
        return self.history.get(processor_name)

    def upstream_data(self, processor_name: str, key: str, default: Any = None) -> Any:
        # shorthand to grab a specific data field from an upstream processor
        output = self.history.get(processor_name)
        if output is None:
            return default
        return output.data.get(key, default)


def _conclusion_not_available(**_: Any) -> None:
    """what ctx.conclude does in a lane that cannot soundly reach a conclusion.

    A conclusion is about the whole corpus, so only a stage that sees the whole
    corpus can author one. A map stage runs once per sample, across a thread
    pool: several of them writing a corpus verdict would be a race whose winner
    is whichever sample finished last. Rather than let that be written and read
    back as an answer, the call does nothing and says why.
    """
    logging.getLogger("deepzero.processor").warning(
        "ctx.conclude() is only available to a reduce or bulk_map stage, which are "
        "the ones that see every sample at once. The call was ignored."
    )


@dataclass
class ProcessorContext:
    # pipeline directory root (for resolving relative paths in config)
    pipeline_dir: Path
    # global pipeline config (settings, knowledge, model)
    global_config: GlobalConfig
    # llm provider if configured
    llm: LLMProtocol | None
    # logger scoped to this processor instance
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("deepzero.processor"))
    # custom progress reporting hook for external UI display
    progress: ProgressReporter = field(default_factory=_NullProgressReporter)
    # optional event to monitor for graceful or forced interruptions natively
    shutdown_event: threading.Event | None = None

    # record a finding about the corpus rather than about one sample. Available
    # to reduce and bulk_map stages, which see every sample in one call; in a map
    # stage it does nothing and says so, because a per-sample lane cannot speak
    # for the whole corpus without racing itself.
    conclude: Callable[..., None] = _conclusion_not_available

    def get_setting(self, key: str, default: Any = None) -> Any:
        # shorthand to grab a pipeline setting
        return self.global_config.get("settings", {}).get(key, default)

    def get_knowledge(self, key: str, default: Any = None) -> Any:
        # shorthand to grab pipeline knowledge
        return self.global_config.get("knowledge", {}).get(key, default)


@dataclass
class ProcessorResult:
    # "completed" = processor ran to completion, "failed" = something broke
    status: StageStatus
    # "continue" = sample moves downstream, "filter" = sample intentionally excluded
    verdict: Verdict = Verdict.CONTINUE
    # name -> relative path of files this processor produced
    artifacts: dict[str, str] = field(default_factory=dict)
    # namespaced output - written to history[processor_name].data
    data: dict[str, Any] = field(default_factory=dict)
    # human-readable error message if status is "failed"
    error: str | None = None

    @classmethod
    def ok(
        cls, data: dict[str, Any] | None = None, artifacts: dict[str, str] | None = None
    ) -> ProcessorResult:
        # sample processed successfully, continue downstream
        return cls(status=StageStatus.COMPLETED, data=data or {}, artifacts=artifacts or {})

    @classmethod
    def filter(cls, reason: str = "", data: dict[str, Any] | None = None) -> ProcessorResult:
        # sample intentionally excluded from further processing
        d = dict(data) if data else {}
        if reason:
            d["filter_reason"] = reason
        return cls(status=StageStatus.COMPLETED, verdict=Verdict.FILTER, data=d)

    @classmethod
    def fail(cls, error: str) -> ProcessorResult:
        # processing failed - sample is dead
        return cls(status=StageStatus.FAILED, error=error)

    @classmethod
    def timed_out(cls, budget: int) -> ProcessorResult:
        # ran out of time rather than went wrong: the sample stops here, but a
        # longer budget may well get through it, so it is worth offering again
        return cls(
            status=StageStatus.TIMED_OUT,
            error=f"timed out after {budget}s",
            data={"__timeout_budget": budget},
        )


@dataclass
class StageSpec:
    # unique instance name within the pipeline
    name: str
    # processor reference - bare name for built-in, dir/file.py for external
    processor: str
    # processor config from yaml - parsed into a Config dataclass if the processor declares one.
    # the engine reads ENGINE_CONFIG_KEYS out of it as well, whatever the processor accepts
    config: dict[str, Any] = field(default_factory=dict)
    # concurrency: how many samples to process in parallel (0 = auto/max hardware)
    parallel: int = 0
    # what to do when a sample fails this processor
    on_failure: FailurePolicy = FailurePolicy.SKIP
    # max retries on failure (only used when on_failure=retry)
    max_retries: int = 0
    # timeout in seconds per sample (0 = no timeout)
    timeout: int = 0


def _digest_path(path: Path, into: Any) -> None:
    """fold a file, or a directory of files, into a running hash."""
    try:
        if path.is_file():
            into.update(path.name.encode("utf-8"))
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    into.update(block)
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    into.update(str(child.relative_to(path)).encode("utf-8"))
                    _digest_path(child, into)
    except OSError:
        # Defer unreadable-input errors to the processor.
        into.update(b"<unreadable>")


def stage_input_digest(
    spec: StageSpec,
    pipeline_dir: Path | None = None,
    *,
    processor: Any = None,
    global_config: GlobalConfig | None = None,
) -> str:
    """Fingerprint declared inputs: config files, processor source, and globals.

    Corpus contents are tracked separately by discovery refresh.
    """
    import hashlib
    import json

    h = hashlib.sha256()
    h.update(spec.processor.encode("utf-8"))
    h.update(json.dumps(spec.config or {}, sort_keys=True, default=str).encode("utf-8"))

    if processor is not None:
        import inspect

        # In-place code edits invalidate cached results. Extensions must declare
        # dependencies outside these implementation files.
        sources: set[Path] = set()
        source_file = getattr(processor, "_source_file", None)
        if source_file:
            sources.add(Path(source_file).resolve())
        for cls in type(processor).__mro__:
            try:
                sources.add(Path(inspect.getfile(cls)).resolve())
            except (TypeError, OSError):
                continue
        for source in sorted(sources):
            _digest_path(source, h)
        cache_files = getattr(processor, "cache_files", None)
        if cache_files is not None:
            for dependency in sorted(cache_files(pipeline_dir or Path.cwd())):
                _digest_path(Path(dependency), h)

    if global_config is not None:
        keys = getattr(processor, "cache_global_keys", None)
        inputs = global_config if keys is None else {k: global_config.get(k) for k in keys}
        h.update(json.dumps(inputs, sort_keys=True, default=str).encode("utf-8"))

    roots = [Path.cwd()] + ([pipeline_dir] if pipeline_dir else [])

    def values(value: Any):
        if isinstance(value, dict):
            for nested in value.values():
                yield from values(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                yield from values(nested)
        else:
            yield value

    path_keys = getattr(processor, "cache_path_keys", None)
    path_config = spec.config or {}
    if path_keys is not None:
        path_config = {key: path_config[key] for key in path_keys if key in path_config}
    for value in values(path_config):
        if not isinstance(value, str) or not value:
            continue
        for root in roots:
            candidate = Path(value) if Path(value).is_absolute() else root / value
            if candidate.exists():
                _digest_path(candidate, h)
                break
    return h.hexdigest()[:16]


# -- processor base classes --
#
# a pipeline is a sequence of processors that transform a sample stream.
# community authors subclass one of these four base classes.
# each type has a different relationship with the sample stream:
#
#   IngestProcessor  - discovers samples from a source
#   MapProcessor     - transforms one sample at a time
#   ReduceProcessor  - sees all samples, decides who survives
#   BulkMapProcessor   - processes all samples in one invocation


def template_key_for_artifact(relative_path: str) -> str:
    """the name a prompt uses to reach an artifact this pipeline wrote.

    An artifact is addressed by its path with the separators and the extension
    folded into the name, so `decompiled/dispatch_ioctl.c` is reached as
    `decompiled_dispatch_ioctl_c`. Prompt rendering and `deepzero validate`
    both go through here, so the name a prompt is checked against is the same
    name it will be given at run time.
    """
    return str(relative_path).replace("\\", "/").replace("/", "_").replace(".", "_")


# available to every prompt regardless of which stages ran before it
ALWAYS_PROVIDED: tuple[str, ...] = ("sample_name", "sample_path", "history", "config")

# keys the engine itself reads out of a stage's `config` block. a processor is
# not expected to declare them, and is not warned about them.
ENGINE_CONFIG_KEYS: frozenset[str] = frozenset({"limit"})


class Processor(ABC):
    # which lane of the pipeline this processor operates in
    processor_type: ProcessorType

    # None conservatively fingerprints all global configuration. Extensions
    # may name just the keys they read, or () when their inputs are entirely
    # stage configuration and upstream results.
    cache_global_keys: ClassVar[tuple[str, ...] | None] = None
    requires_full_cohort: ClassVar[bool] = False
    # None follows every config path; () is useful for output/cache/tool
    # directories. Such processors declare their actual files via cache_files.
    cache_path_keys: ClassVar[tuple[str, ...] | None] = None

    # subclass with a @dataclass to declare accepted config fields.
    # the engine instantiates it from the YAML config dict at pipeline load time.
    # if None, the processor receives the raw config dict.
    #
    # config fields can read from environment variables via YAML syntax:
    #   config:
    #     install_dir: ${GHIDRA_INSTALL_DIR}
    #     java_home: ${JAVA_HOME:-/usr/lib/jvm/default}
    #
    # the engine expands ${VAR} and ${VAR:-default} before parsing.
    # use validate() to check if required fields are empty after expansion.
    Config: ClassVar[type | None] = None

    # human-readable metadata - used by `deepzero list-processors` and future web UI
    description: ClassVar[str] = ""
    version: ClassVar[str] = "1.0"

    # the names a later stage's prompt can reference because this processor
    # records them: every key it puts in `data`, plus one name per artifact it
    # writes (see template_key_for_artifact for how a path becomes a name).
    #
    # `deepzero validate` checks each prompt against the names its upstream
    # stages declare, so a prompt asking for something no stage produces is
    # reported before a run starts rather than rendering as nothing.
    provides: ClassVar[tuple[str, ...]] = ()

    # set by the resolver to the path of the .py file that defines this processor
    _source_file: Path | None = None

    def __init__(self, spec: StageSpec):
        self.spec = spec
        self.log = logging.getLogger(f"deepzero.processor.{spec.name}")
        self.config = self._parse_config(spec.config)
        # set by the engine before setup() is called
        self.global_config: GlobalConfig = {}

    def _parse_config(self, raw: dict) -> Any:
        raw = raw or {}
        if self.Config is None:
            return raw
        valid = {f.name for f in fields(self.Config)}
        unknown = sorted(set(raw) - valid - ENGINE_CONFIG_KEYS)
        if unknown:
            # a key this processor does not read does nothing at all, which is
            # indistinguishable from it working until the run ends up wrong. a
            # misspelling is the usual cause, so the accepted names go with it.
            self.log.warning(
                "config key(s) %s are not read by %s and were ignored - it accepts: %s",
                ", ".join(unknown),
                type(self).__name__,
                ", ".join(sorted(valid)) or "no config fields",
            )
        filtered = {k: v for k, v in raw.items() if k in valid}
        return self.Config(**filtered)

    def validate(self, ctx: ProcessorContext) -> list[str]:
        # override to check dependencies at pipeline load time, before any sample is touched.
        # return a list of problems. empty list = all good.
        #
        # examples:
        #   - check that a required config field is not empty
        #   - check that an external binary exists on disk
        #   - check that a rules directory contains .yaml files
        return []

    def cache_files(self, pipeline_dir: Path) -> list[Path]:
        """Additional inputs, such as imported templates or analysis scripts."""
        return []

    @property
    def processor_dir(self) -> Path:
        # directory containing this processor's source file - useful for locating
        # co-located assets like scripts, templates, or rule files
        if self._source_file is not None:
            return self._source_file.parent
        import inspect

        return Path(inspect.getfile(type(self))).parent

    @property
    def cache_dir(self) -> Path:
        # persistent cache directory for this processor instance
        d = Path.cwd() / ".cache" / self.spec.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def max_parallelism(self) -> int | None:
        # optional hard ceiling on AUTO (parallel: 0) concurrency for this
        # processor. return an int to stop auto-scaling from using every core;
        # None means no ceiling. heavy processors that spawn external, memory-
        # hungry workers (e.g. one JVM per sample) override this so a default
        # `parallel: 0` cannot exhaust the machine. an explicit `parallel: N`
        # in the pipeline is always honored as-is.
        return None

    def setup(self, global_config: dict[str, Any]) -> None:
        # called once before pipeline execution begins
        pass

    def teardown(self) -> None:
        # called once after pipeline execution completes
        pass


class IngestProcessor(Processor):
    # discovers samples from a target path, API, or manifest.
    # always the first stage in a pipeline. runs once, not per-sample.
    #
    #   /target/path ──▶ [ IngestProcessor ] ──▶ sample_a, sample_b, sample_c ...
    #
    # use for: file discovery, PE parsing, API ingestion, manifest loading.
    # access self.config for typed config, self.global_config for pipeline-level settings.
    processor_type = ProcessorType.INGEST

    @abstractmethod
    def process(self, ctx: ProcessorContext, target: Path) -> list[Sample]: ...


class MapProcessor(Processor):
    # processes one sample at a time. the engine fans out via ThreadPoolExecutor.
    # must be thread-safe - no shared mutable state in process().
    #
    #   sample_a ──▶ [ MapProcessor ] ──▶ result_a   (ok / filter / fail)
    #   sample_b ──▶ [ MapProcessor ] ──▶ result_b   ← parallel via thread pool
    #   sample_c ──▶ [ MapProcessor ] ──▶ result_c
    #
    # use for: filtering, decompilation, LLM analysis, metadata extraction.
    # return ProcessorResult.ok(), .filter(), or .fail().
    processor_type = ProcessorType.MAP

    @abstractmethod
    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult: ...

    def should_skip(self, ctx: ProcessorContext, entry: ProcessorEntry) -> str | None:
        # override to skip already-processed samples (e.g. cached output files).
        # return a reason string to skip, or None to process normally.
        # skipped samples count as "passed" - the work was already done previously.
        return None


class ReduceProcessor(Processor):
    # sees ALL active samples at once. returns which survive and in what order.
    # guarantees INTERDEPENDENCE: must have access to 100% of the active pipeline corpus.
    # by design, the engine cannot auto-chunk Reduce processors.
    # It acts as a global synchronization barrier for the pipeline.
    #
    #   ┌ sample_a ┐                      ┌ sample_c ┐
    #   │ sample_b │ ──▶ [ Reduce ] ──▶   │ sample_a │  (reordered, sample_b filtered)
    #   │ sample_c │                      └──────────┘
    #   └──────────┘
    #
    # use for: top-k selection, sorting by priority, deduplication, global ranking.
    # return a list of sample_ids to KEEP, in the desired order.
    # everything not returned is filtered out.
    processor_type = ProcessorType.REDUCE

    @abstractmethod
    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]: ...


class BulkMapProcessor(Processor):
    # all active samples processed in one external invocation.
    # more efficient than MapProcessor when the external process has high startup cost.
    #
    #   ┌ sample_a ┐                      ┌ result_a ┐
    #   │ sample_b │ ──▶ [ Batch ] ──▶    │ result_b │  (one process invocation)
    #   │ sample_c │                      │ result_c │
    #   └──────────┘                      └──────────┘
    #
    # use for: semgrep scanning, batch static analysis, bulk API calls.
    # return one ProcessorResult per entry, matched by index.
    # if fewer results than entries, extras are marked as failed.
    processor_type = ProcessorType.BULK_MAP

    @abstractmethod
    def process(
        self, ctx: ProcessorContext, entries: list[ProcessorEntry]
    ) -> list[ProcessorResult]: ...


# re-export registry functions so existing imports from stage.py keep working
from deepzero.engine.registry import (  # noqa: E402, F401
    get_registered_processors,
    register_processor,
    resolve_processor_class,
)
