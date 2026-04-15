from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("deepzero.llm")


class LLMProvider:
    """universal llm provider backed by litellm - supports openai, anthropic,
    google vertex, ollama, azure, and 100+ other providers through a single interface"""

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

                # success - decay backoff toward minimum
                backoff = max(initial_backoff, backoff * backoff_decay)

                return content

            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = any(k in err_str for k in ("429", "rate", "quota", "resource_exhausted"))
                is_token_limit = "token" in err_str and ("limit" in err_str or "exceeded" in err_str)

                if attempt == max_retries:
                    raise

                if is_rate_limit:
                    backoff = min(max_backoff, backoff * 2.0)
                    log.warning(
                        "rate limited (attempt %d/%d), backing off %.0fs",
                        attempt + 1, max_retries + 1, backoff,
                    )
                    time.sleep(backoff)
                elif is_token_limit:
                    # token limit errors won't be fixed by retry
                    raise
                else:
                    wait = min(max_backoff, 2 ** attempt)
                    log.warning(
                        "llm error (attempt %d/%d), retrying in %.0fs: %s",
                        attempt + 1, max_retries + 1, wait, e,
                    )
                    time.sleep(wait)

        raise RuntimeError("exhausted retries")

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
