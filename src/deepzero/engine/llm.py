from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("deepzero.llm")


# sentinel exception that is never raised, used as a safe fallback
# when litellm exception classes are unavailable (e.g. in mock envs)
class _NeverRaised(Exception):
    pass


def _resolve_exc(obj: Any, name: str) -> type[BaseException]:
    cls = getattr(obj, name, None)
    try:
        if isinstance(cls, type) and issubclass(cls, BaseException):
            return cls
    except TypeError:
        pass
    return _NeverRaised


class LLMProvider:
    # litellm-backed llm provider with adaptive retry and backoff

    def __init__(self, model: str, **kwargs: Any):
        self.model = model
        self.default_kwargs = kwargs
        self._ensure_litellm()

    def _ensure_litellm(self) -> None:
        try:
            import litellm

            self._litellm = litellm
            # suppress litellm's noisy logging and traceback spam
            litellm.suppress_debug_info = True
            logging.getLogger("litellm").setLevel(logging.CRITICAL)

            # capture exception classes with safe fallbacks for test mocks
            self._rate_limit_error = _resolve_exc(litellm, "RateLimitError")
            self._context_window_error = _resolve_exc(
                litellm, "ContextWindowExceededError"
            )

            # build the retryable error tuple once at init
            api_errors = tuple(
                _resolve_exc(litellm, name)
                for name in ("APIConnectionError", "APIError")
            )
            self._retryable_errors = api_errors + (OSError, ValueError, RuntimeError)

        except ImportError as exc:
            raise ImportError(
                "litellm is required for LLM support. install with: pip install litellm"
            ) from exc

    def complete(
        self,
        messages: list[dict[str, str]],
        max_retries: int = 3,
        initial_backoff: float = 2.0,
        max_backoff: float = 60.0,
        backoff_decay: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """send messages to the llm and return the response text.
        handles rate limiting with adaptive backoff."""
        merged = {**self.default_kwargs, **kwargs}
        backoff = initial_backoff

        for attempt in range(max_retries + 1):
            try:
                response = self._litellm.completion(
                    model=self.model,
                    messages=messages,
                    **merged,
                )
                content = response.choices[0].message.content or ""

                # decay backoff toward minimum on success
                backoff = max(initial_backoff, backoff * backoff_decay)
                return content

            except self._rate_limit_error:
                if attempt == max_retries:
                    raise
                backoff = min(max_backoff, backoff * 2.0)
                log.warning(
                    "rate limited (attempt %d/%d), backing off %.0fs",
                    attempt + 1,
                    max_retries + 1,
                    backoff,
                )
                time.sleep(backoff)

            except self._context_window_error:
                # context window errors won't be fixed by retry
                raise

            except self._retryable_errors as e:
                if attempt == max_retries:
                    raise
                wait = min(max_backoff, 2**attempt)
                log.warning(
                    "llm error (attempt %d/%d), retrying in %.0fs: %s",
                    attempt + 1,
                    max_retries + 1,
                    wait,
                    e,
                )
                time.sleep(wait)

        raise RuntimeError("exhausted retries without raising")

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
