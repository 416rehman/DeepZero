"""litellm backend - api-key access to every endpoint litellm supports.

registered as the default, so any model string whose scheme is not claimed by a
more specific backend lands here ("openai/gpt-4o", "gemini/...", "gpt-4o", ...).
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any, ClassVar

from deepzero.engine.backends.base import LLMBackend, _NeverRaised

log = logging.getLogger("deepzero.llm.litellm")


class LiteLLMBackend(LLMBackend):
    display_name: ClassVar[str] = "litellm"
    # litellm surfaces auth problems as APIError subclasses that are also in the
    # retryable set, so there is no distinct fail-fast class to declare
    non_retryable_errors: ClassVar[tuple[type[BaseException], ...]] = (_NeverRaised,)

    @staticmethod
    def _resolve_exc(obj: Any, name: str) -> type[BaseException]:
        cls = getattr(obj, name, None)
        with suppress(TypeError):
            if isinstance(cls, type) and issubclass(cls, BaseException):
                return cls
        return _NeverRaised

    def __init__(self, model: str, **kwargs: Any):
        super().__init__(model, **kwargs)
        try:
            import litellm
        except ImportError as exc:
            raise ImportError(
                "litellm is required for LLM support. install with: pip install litellm"
            ) from exc

        self.litellm = litellm
        # suppress litellm's noisy logging and traceback spam
        litellm.suppress_debug_info = True
        logging.getLogger("litellm").setLevel(logging.CRITICAL)

        # instance-level overrides of the class retry roles, with safe fallbacks
        # for test mocks that lack the real exception classes
        self.rate_limit_error = self._resolve_exc(litellm, "RateLimitError")
        self.context_window_error = self._resolve_exc(litellm, "ContextWindowExceededError")
        api_errors = tuple(
            self._resolve_exc(litellm, name) for name in ("APIConnectionError", "APIError")
        )
        self.retryable_errors = api_errors + (OSError, ValueError, RuntimeError)

    def raw_complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        response = self.litellm.completion(model=self.model, messages=messages, **kwargs)
        return response.choices[0].message.content or ""

    @classmethod
    def validate_model(cls, model: str) -> list[str]:
        try:
            import litellm
        except ImportError:
            return ["LLM configured, but 'litellm' framework is not installed"]

        env_state = litellm.validate_environment(model=model)
        if not env_state.get("keys_in_environment", True):
            missing_keys = env_state.get("missing_keys", [])
            if missing_keys:
                return [
                    f"LLM backend '{model}' missing credentials in environment. "
                    f"Need: {missing_keys}"
                ]
        return []

    @property
    def provider_name(self) -> str:
        if "/" in self.model:
            return self.model.split("/")[0]
        return "unknown"

    @property
    def model_name(self) -> str:
        if "/" in self.model:
            return self.model.split("/", 1)[1]
        return self.model
