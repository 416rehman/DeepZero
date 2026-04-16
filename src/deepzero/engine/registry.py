from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any


_PROCESSOR_REGISTRY: dict[str, type[Any]] = {}


def register_processor(name: str, cls: type[Any]) -> None:
    _PROCESSOR_REGISTRY[name] = cls


def get_registered_processors() -> dict[str, type[Any]]:
    return dict(_PROCESSOR_REGISTRY)


def resolve_processor_class(processor_ref: str) -> type[Any]:
    # resolution order:
    #   bare name              = built-in registry (e.g. "metadata_filter")
    #   dir/file.py            = processors/<dir>/<file>.py, first Processor subclass
    #   dir/file.py:ClassName  = processors/<dir>/<file>.py, specific class

    if "/" in processor_ref or "\\" in processor_ref:
        return _resolve_from_processors_dir(processor_ref)

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
        Processor,
        IngestProcessor,
        MapProcessor,
        ReduceProcessor,
        BulkMapProcessor,
    )

    return Processor, IngestProcessor, MapProcessor, ReduceProcessor, BulkMapProcessor


def _resolve_from_processors_dir(processor_ref: str) -> type[Any]:
    Processor, IngestProcessor, MapProcessor, ReduceProcessor, BulkMapProcessor = (
        _get_base_classes()
    )
    processors_root = Path.cwd() / "processors"

    class_name = None
    path_part = processor_ref
    if ":" in processor_ref:
        path_part, class_name = processor_ref.rsplit(":", 1)

    abs_path = (processors_root / path_part).resolve()

    if not abs_path.exists():
        raise FileNotFoundError(
            f"processor not found: {abs_path} "
            f"(resolved '{processor_ref}' relative to processors/)"
        )

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

    spec = importlib.util.spec_from_file_location(
        f"deepzero.custom.{file_path.stem}", file_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load processor from {file_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"processor file {file_path} has no class '{class_name}'")
    if not (isinstance(cls, type) and issubclass(cls, Processor)):
        raise TypeError(f"'{class_name}' in {file_path} is not a Processor subclass")

    cls._source_file = file_path
    return cls


def _load_processor_from_file(file_path: Path) -> type[Any] | None:
    Processor, IngestProcessor, MapProcessor, ReduceProcessor, BulkMapProcessor = (
        _get_base_classes()
    )

    spec = importlib.util.spec_from_file_location(
        f"deepzero.custom.{file_path.stem}", file_path
    )
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, Processor)
            and attr is not Processor
        ):
            if any(
                attr is base
                for base in (
                    IngestProcessor,
                    MapProcessor,
                    ReduceProcessor,
                    BulkMapProcessor,
                )
            ):
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
        raise TypeError(
            f"'{class_name}' in '{module_path}' is not a Processor subclass"
        )

    return cls
