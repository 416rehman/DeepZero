"""llm backend registry.

model strings are `<scheme>` or `<scheme>/<model>`. a registered scheme selects
that backend; anything unrecognised falls through to the default backend
(litellm), which covers every api-key endpoint it supports.

    claude-code            -> ClaudeCodeBackend (default model)
    claude-code/sonnet     -> ClaudeCodeBackend (sonnet)
    openai/gpt-4o          -> default backend (litellm)
    gpt-4o                 -> default backend (litellm)
"""

from __future__ import annotations

from typing import Any

from deepzero.engine.backends.base import LLMBackend

_BACKEND_REGISTRY: dict[str, type[LLMBackend]] = {}
_DEFAULT_BACKEND: type[LLMBackend] | None = None


def register_backend(cls: type[LLMBackend], *, default: bool = False) -> type[LLMBackend]:
    """register a backend under its `scheme` (and any `aliases`).

    usable as a decorator. pass default=True for the fallback backend that
    handles every unregistered scheme.
    """
    global _DEFAULT_BACKEND

    if default:
        _DEFAULT_BACKEND = cls

    if cls.scheme:
        _BACKEND_REGISTRY[cls.scheme.lower()] = cls
        for alias in cls.aliases:
            _BACKEND_REGISTRY[alias.lower()] = cls
    elif not default:
        raise ValueError(f"{cls.__name__} must define a 'scheme' to be registered")

    return cls


def get_registered_backends() -> dict[str, type[LLMBackend]]:
    return dict(_BACKEND_REGISTRY)


def model_scheme(model: str) -> str:
    m = (model or "").strip().lower()
    return m.split("/", 1)[0] if "/" in m else m


def resolve_backend_class(model: str) -> type[LLMBackend]:
    """map a model string to its backend class."""
    backend = _BACKEND_REGISTRY.get(model_scheme(model))
    if backend is not None:
        return backend

    if _DEFAULT_BACKEND is None:
        raise ValueError(
            f"no backend can handle model '{model}' and no default backend is registered. "
            f"known schemes: {sorted(_BACKEND_REGISTRY)}"
        )
    return _DEFAULT_BACKEND


def create_backend(model: str, **kwargs: Any) -> LLMBackend:
    return resolve_backend_class(model)(model, **kwargs)


def validate_model_binding(model: str) -> list[str]:
    """pre-flight check for a model string, delegated to its backend."""
    try:
        backend_cls = resolve_backend_class(model)
    except ValueError as exc:
        return [str(exc)]
    return backend_cls.validate_model(model)
