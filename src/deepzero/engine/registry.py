from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

_PROCESSOR_REGISTRY: dict[str, type[Any]] = {}


def register_processor(name: str, cls: type[Any]) -> None:
    _PROCESSOR_REGISTRY[name] = cls


def get_registered_processors() -> dict[str, type[Any]]:
    return dict(_PROCESSOR_REGISTRY)


def resolve_processor_class(processor_ref: str, pipeline_dir: Path | None = None) -> type[Any]:
    # resolution order:
    #   bare name              = built-in registry (e.g. "metadata_filter")
    #   dir/file.py            = processors/<dir>/<file>.py, first Processor subclass
    #   dir/file.py:ClassName  = processors/<dir>/<file>.py, specific class

    if "/" in processor_ref or "\\" in processor_ref:
        return _resolve_from_processors_dir(processor_ref, pipeline_dir)

    if processor_ref in _PROCESSOR_REGISTRY:
        return _PROCESSOR_REGISTRY[processor_ref]

    if ":" in processor_ref:
        return _resolve_from_dotted(processor_ref)

    raise ValueError(
        f"unknown processor '{processor_ref}'. bare names match built-in processors only. "
        f"for external processors use '<dir>/<file>.py' (relative to processors/). "
        f"built-ins: {list(_PROCESSOR_REGISTRY.keys())}"
    )


def _get_base_classes() -> tuple:
    from deepzero.engine.stage import (
        BulkMapProcessor,
        IngestProcessor,
        MapProcessor,
        Processor,
        ReduceProcessor,
    )

    return Processor, IngestProcessor, MapProcessor, ReduceProcessor, BulkMapProcessor


def _processor_roots(pipeline_dir: Path | None) -> list[Path]:
    """where a `dir/file.py` reference is looked for, in order.

    The working directory comes first, which is how this repository's own
    pipelines reference the processors beside them. Then the pipeline's own
    directory and its parent, so a pipeline kept anywhere can carry its
    processors without the engine dictating that they sit in a folder called
    `processors` next to wherever the command happened to be run. DEEPZERO_PROCESSORS
    overrides the lot, for a shared library of them.
    """
    roots: list[Path] = []
    env = os.environ.get("DEEPZERO_PROCESSORS", "").strip()
    if env:
        roots.extend(Path(p) for p in env.split(os.pathsep) if p.strip())
    roots.append(Path.cwd() / "processors")
    if pipeline_dir is not None:
        roots.append(pipeline_dir / "processors")
        roots.append(pipeline_dir.parent / "processors")
        # a pipeline that keeps a processor beside its yaml rather than in a
        # subdirectory of its own
        roots.append(pipeline_dir)
    return roots


def _resolve_from_processors_dir(processor_ref: str, pipeline_dir: Path | None = None) -> type[Any]:
    class_name = None
    path_part = processor_ref
    if ":" in processor_ref:
        path_part, class_name = processor_ref.rsplit(":", 1)

    tried: list[Path] = []
    abs_path = None
    for root in _processor_roots(pipeline_dir):
        candidate = (root / path_part).resolve()
        tried.append(candidate)
        if candidate.exists():
            abs_path = candidate
            break

    if abs_path is None:
        searched = "\n  ".join(str(t) for t in tried)
        raise FileNotFoundError(f"processor not found: '{processor_ref}'. searched:\n  {searched}")

    if abs_path.is_file():
        if class_name:
            cls = _load_specific_class(abs_path, class_name)
        else:
            cls = _load_processor_from_file(abs_path)
            if cls is None:
                raise ImportError(f"no Processor subclass found in {abs_path}")
        cls._source_file = abs_path
        return cls

    raise FileNotFoundError(
        f"'{processor_ref}' resolved to '{abs_path}' which is not a .py file. "
        f"use '<dir>/<file>.py' format, e.g. 'ghidra_decompile/ghidra_decompile.py'"
    )


def _load_specific_class(file_path: Path, class_name: str) -> type[Any]:
    Processor = _get_base_classes()[0]

    spec = importlib.util.spec_from_file_location(f"deepzero.custom.{file_path.stem}", file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load processor from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"processor file {file_path} has no class '{class_name}'")
    if not (isinstance(cls, type) and issubclass(cls, Processor)):
        raise TypeError(f"'{class_name}' in {file_path} is not a Processor subclass")

    cls._source_file = file_path
    return cls


def _load_processor_from_file(file_path: Path) -> type[Any] | None:
    bases = _get_base_classes()
    Processor = bases[0]

    spec = importlib.util.spec_from_file_location(f"deepzero.custom.{file_path.stem}", file_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    # module.__dict__ is in definition order, so a file holding more than one
    # processor gives up the one written first, which is what a reference
    # without a :ClassName means. dir() would sort the names and hand back
    # whichever happened to come first in the alphabet.
    for attr in vars(module).values():
        if not (isinstance(attr, type) and issubclass(attr, Processor)):
            continue
        if any(attr is base for base in bases):
            continue
        # a class the file imported belongs to whatever defines it; picking it
        # up here would silently run someone else's processor under this name
        if getattr(attr, "__module__", None) != module.__name__:
            continue
        return attr

    return None


def _resolve_from_dotted(processor_ref: str) -> type[Any]:
    Processor = _get_base_classes()[0]
    module_path, class_name = processor_ref.rsplit(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)

    if cls is None:
        raise AttributeError(f"module '{module_path}' has no attribute '{class_name}'")
    if not (isinstance(cls, type) and issubclass(cls, Processor)):
        raise TypeError(f"'{class_name}' in '{module_path}' is not a Processor subclass")

    return cls
