from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

from deepzero.engine.state import SampleState, StageOutput


@runtime_checkable
class LLMProtocol(Protocol):
    # contract for any LLM provider - at minimum must support complete()
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
    # typed config passed to stages - replaces dict[str, Any]
    settings: dict[str, Any]
    tools: dict[str, Any]
    knowledge: dict[str, Any]
    model: str


class ToolType(str, Enum):
    INGEST = "ingest"
    MAP = "map"
    REDUCE = "reduce"
    BATCH = "batch"


class FailurePolicy(str, Enum):
    SKIP = "skip"
    RETRY = "retry"
    ABORT = "abort"


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
class StageContext:
    # the original sample file
    sample_path: Path
    # working directory for this sample (work/<pipeline>/samples/<id>/)
    sample_dir: Path
    # full provenance chain - history[stage_name].data for upstream access
    history: dict[str, StageOutput]
    # this stage's config block from the pipeline yaml
    config: dict[str, Any]
    # the pipeline directory root (for resolving relative paths)
    pipeline_dir: Path
    # global pipeline config (settings, tools, knowledge)
    global_config: GlobalConfig
    # llm provider if configured - must implement LLMProtocol
    llm: LLMProtocol | None
    # logger for this stage
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("deepzero.stage"))


@dataclass
class StageResult:
    status: Literal["completed", "failed"]
    # continue = proceed to next stage, skip = stop processing this sample
    verdict: Literal["continue", "skip"] = "continue"
    # name -> relative path of files this stage produced
    artifacts: dict[str, str] = field(default_factory=dict)
    # namespaced output - written to history[stage_name].data, never merged
    data: dict[str, Any] = field(default_factory=dict)
    # if failed, why
    error: str | None = None


@dataclass
class BatchEntry:
    # lightweight struct passed to BatchTool.execute_batch
    sample_id: str
    sample_dir: Path
    source_path: Path
    history: dict[str, StageOutput]


@dataclass
class StageSpec:
    # unique instance name within the pipeline
    name: str
    # tool reference (bare name for built-in, dir/file.py for tools/ directory)
    tool: str
    # stage config from yaml
    config: dict[str, Any] = field(default_factory=dict)
    # concurrency: how many samples to process in parallel for this stage
    parallel: int = 4
    # what to do when a sample fails this stage
    on_failure: FailurePolicy = FailurePolicy.SKIP
    # max retries on failure (only used when on_failure=retry)
    max_retries: int = 0
    # timeout in seconds (0 = no timeout)
    timeout: int = 0


# -- tool base classes --


class Tool(ABC):
    # root base class for all pipeline tools
    tool_type: ToolType

    # set by the resolver to the path of the .py file that defines this tool
    _source_file: Path | None = None

    def __init__(self, spec: StageSpec):
        self.spec = spec
        self.log = logging.getLogger(f"deepzero.tool.{spec.name}")

    @property
    def tool_dir(self) -> Path:
        # directory containing this tool's source file
        if self._source_file is not None:
            return self._source_file.parent
        import inspect
        return Path(inspect.getfile(type(self))).parent

    @property
    def cache_dir(self) -> Path:
        # persistent cache directory for this tool instance
        d = Path.cwd() / ".cache" / self.spec.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def setup(self, global_config: dict[str, Any]) -> None:
        # called once before batch execution
        pass

    def teardown(self) -> None:
        # called once after batch execution
        pass


class IngestTool(Tool):
    # discovers samples from a target path or source
    tool_type = ToolType.INGEST

    @abstractmethod
    def discover(self, target: Path, config: dict[str, Any], global_config: dict[str, Any]) -> list[Sample]:
        ...


class MapTool(Tool):
    # processes one sample at a time - engine fans out with ThreadPoolExecutor
    tool_type = ToolType.MAP

    @abstractmethod
    def process(self, ctx: StageContext) -> StageResult:
        ...

    def should_skip(self, ctx: StageContext) -> str | None:
        # override to skip already-processed samples (e.g. cached decompilation)
        return None


class ReduceTool(Tool):
    # sees ALL active samples at once - the synchronization barrier
    tool_type = ToolType.REDUCE

    @abstractmethod
    def reduce(self, states: list[SampleState], config: dict[str, Any]) -> list[SampleState]:
        # mutate verdict on losers to "skipped", return the full list
        ...


class BatchTool(Tool):
    # processes all active samples in one external invocation
    tool_type = ToolType.BATCH

    @abstractmethod
    def execute_batch(self, entries: list[BatchEntry], config: dict[str, Any]) -> list[StageResult]:
        # return one StageResult per entry, matched by index
        ...


# -- tool registry --

_TOOL_REGISTRY: dict[str, type[Tool]] = {}


def register_tool(name: str, cls: type[Tool]) -> None:
    _TOOL_REGISTRY[name] = cls


def get_registered_tools() -> dict[str, type[Tool]]:
    return dict(_TOOL_REGISTRY)


def resolve_tool_class(tool_ref: str) -> type[Tool]:
    # resolution:
    #   bare name              = built-in registry (e.g. "metadata_filter")
    #   dir/file.py            = tools/<dir>/<file>.py, first Tool subclass
    #   dir/file.py:ClassName  = tools/<dir>/<file>.py, specific class

    # contains a slash = path within tools/
    if "/" in tool_ref or "\\" in tool_ref:
        return _resolve_from_tools_dir(tool_ref)

    # built-in registry
    if tool_ref in _TOOL_REGISTRY:
        return _TOOL_REGISTRY[tool_ref]

    # dotted import (has colon but no slash, e.g. "my_package.tools:MyTool")
    if ":" in tool_ref:
        return _resolve_from_dotted(tool_ref)

    raise ValueError(
        f"unknown tool '{tool_ref}'. bare names only match built-in tools. "
        f"for project tools use '<dir>/<file>.py' (relative to tools/). "
        f"built-ins: {list(_TOOL_REGISTRY.keys())}"
    )


def _resolve_from_tools_dir(tool_ref: str) -> type[Tool]:
    tools_root = Path.cwd() / "tools"

    # split optional :ClassName
    class_name = None
    path_part = tool_ref
    if ":" in tool_ref:
        path_part, class_name = tool_ref.rsplit(":", 1)

    abs_path = (tools_root / path_part).resolve()

    if not abs_path.exists():
        raise FileNotFoundError(
            f"tool not found: {abs_path} "
            f"(resolved '{tool_ref}' relative to tools/)"
        )

    if abs_path.is_file():
        if class_name:
            cls = _load_specific_class(abs_path, class_name)
        else:
            cls = _load_tool_from_file(abs_path)
            if cls is None:
                raise ImportError(f"no Tool subclass found in {abs_path}")
        cls._source_file = abs_path
        return cls

    raise FileNotFoundError(
        f"'{tool_ref}' resolved to '{abs_path}' which is not a .py file. "
        f"use '<dir>/<file>.py' format, e.g. 'pe_ingest/pe_ingest.py'"
    )


def _load_specific_class(file_path: Path, class_name: str) -> type[Tool]:
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"deepzero.custom.{file_path.stem}", file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load tool from {file_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"tool file {file_path} has no class '{class_name}'")
    if not (isinstance(cls, type) and issubclass(cls, Tool)):
        raise TypeError(f"'{class_name}' in {file_path} is not a Tool subclass")

    cls._source_file = file_path
    return cls


def _load_tool_from_file(file_path: Path) -> type[Tool] | None:
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"deepzero.custom.{file_path.stem}", file_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, Tool) and attr is not Tool:
            if any(attr is base for base in (IngestTool, MapTool, ReduceTool, BatchTool)):
                continue
            return attr

    return None


def _resolve_from_dotted(tool_ref: str) -> type[Tool]:
    module_path, class_name = tool_ref.rsplit(":", 1)
    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)

    if cls is None:
        raise AttributeError(f"module '{module_path}' has no attribute '{class_name}'")
    if not (isinstance(cls, type) and issubclass(cls, Tool)):
        raise TypeError(f"'{class_name}' in '{module_path}' is not a Tool subclass")

    return cls
