from __future__ import annotations

import logging
import time
from typing import Any

from deepzero.engine.backends import create_backend

log = logging.getLogger("deepzero.llm")


class LLMProvider:
    # llm provider with adaptive retry and backoff.
    #
    # the backend is resolved from the model string by the backend registry
    # (see deepzero.engine.backends). this class knows nothing about any
    # specific backend - it only drives the retry roles each one declares.

    def __init__(self, model: str, **kwargs: Any):
        self.model = model
        self.default_kwargs = kwargs
        self.backend = create_backend(model, **kwargs)

    @property
    def _litellm(self) -> Any:
        # retained for backward compatibility with existing callers/tests
        return getattr(self.backend, "litellm", None)

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
        backend = self.backend
        # cli backends take their options via argv, not per-call kwargs
        merged = {**self.default_kwargs, **kwargs} if backend.accepts_generation_kwargs else {}
        backoff = initial_backoff

        for attempt in range(max_retries + 1):
            try:
                content = backend.raw_complete(messages, **merged)

                # decay backoff toward minimum on success
                backoff = max(initial_backoff, backoff * backoff_decay)
                return content

            except backend.rate_limit_error:
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

            except backend.context_window_error:
                # context window errors won't be fixed by retry
                raise

            except backend.non_retryable_errors:
                # e.g. auth failures - surface immediately instead of burning retries
                raise

            except backend.retryable_errors as e:
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
        return self.backend.provider_name

    @property
    def model_name(self) -> str:
        return self.backend.model_name
