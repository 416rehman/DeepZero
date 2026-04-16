from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TypedDict, runtime_checkable, ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from deepzero.engine.state import StateStore

from deepzero.engine.types import StageStatus, Verdict
from deepzero.engine.state import StageOutput


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


@dataclass
class ProcessorContext:
    # pipeline directory root (for resolving relative paths in config)
    pipeline_dir: Path
    # global pipeline config (settings, knowledge, model)
    global_config: GlobalConfig
    # llm provider if configured
    llm: LLMProtocol | None
    # logger scoped to this processor instance
    log: logging.Logger = field(
        default_factory=lambda: logging.getLogger("deepzero.processor")
    )

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
        return cls(
            status=StageStatus.COMPLETED, data=data or {}, artifacts=artifacts or {}
        )

    @classmethod
    def filter(
        cls, reason: str = "", data: dict[str, Any] | None = None
    ) -> ProcessorResult:
        # sample intentionally excluded from further processing
        d = dict(data) if data else {}
        if reason:
            d["filter_reason"] = reason
        return cls(status=StageStatus.COMPLETED, verdict=Verdict.FILTER, data=d)

    @classmethod
    def fail(cls, error: str) -> ProcessorResult:
        # processing failed - sample is dead
        return cls(status=StageStatus.FAILED, error=error)


@dataclass
class StageSpec:
    # unique instance name within the pipeline
    name: str
    # processor reference - bare name for built-in, dir/file.py for external
    processor: str
    # processor config from yaml - parsed into a Config dataclass if the processor declares one
    config: dict[str, Any] = field(default_factory=dict)
    # concurrency: how many samples to process in parallel (0 = auto/max hardware)
    parallel: int = 0
    # what to do when a sample fails this processor
    on_failure: FailurePolicy = FailurePolicy.SKIP
    # max retries on failure (only used when on_failure=retry)
    max_retries: int = 0
    # timeout in seconds per sample (0 = no timeout)
    timeout: int = 0


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


class Processor(ABC):
    # which lane of the pipeline this processor operates in
    processor_type: ProcessorType

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

    # set by the resolver to the path of the .py file that defines this processor
    _source_file: Path | None = None

    def __init__(self, spec: StageSpec):
        self.spec = spec
        self.log = logging.getLogger(f"deepzero.processor.{spec.name}")
        self.config = self._parse_config(spec.config)
        # set by the engine before setup() is called
        self.global_config: GlobalConfig = {}

    def _parse_config(self, raw: dict) -> Any:
        if self.Config is None:
            return raw
        valid = {f.name for f in fields(self.Config)}
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
    def process(
        self, ctx: ProcessorContext, entry: ProcessorEntry
    ) -> ProcessorResult: ...

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
    def process(
        self, ctx: ProcessorContext, entries: list[ProcessorEntry]
    ) -> list[str]: ...


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
    register_processor,
    get_registered_processors,
    resolve_processor_class,
)
