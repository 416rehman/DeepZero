"""llm backend interface and shared implementations.

two layers live here:

  LLMBackend      - the contract LLMProvider talks to. anything that can turn
                    messages into text can be a backend.
  CLIAgentBackend - reusable plumbing for backends that shell out to a locally
                    installed coding-agent cli (claude code, codex, gemini cli,
                    ...). subclasses declare *what* to run and *how to read the
                    output*; process handling, prompt flattening, env
                    sanitization and error classification are inherited.

adding a new agent cli should mean subclassing CLIAgentBackend and registering
it - never editing LLMProvider or the dispatch logic.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

log = logging.getLogger("deepzero.llm.backend")


# -- generic error taxonomy -----------------------------------------------------
#
# the retry loop reasons about these, never about vendor-specific classes.
# backends either raise these directly or declare which of their own exception
# classes map onto each role (see the class attributes on LLMBackend).


class BackendError(RuntimeError):
    """backend call failed."""


class BackendNotFoundError(BackendError):
    """the backend's binary or dependency is not installed."""


class BackendAuthError(BackendError):
    """backend is present but not authenticated - retrying will not help."""


class BackendRateLimitError(BackendError):
    """rate/usage limit hit - worth retrying after backoff."""


class BackendContextWindowError(BackendError):
    """prompt exceeded the context window - retrying will not help."""


class _NeverRaised(Exception):
    """placeholder so a backend can opt out of an error role."""


class LLMBackend(ABC):
    """turns messages into response text.

    subclasses declare which exception classes fill each retry role, so
    LLMProvider's backoff loop needs no knowledge of any specific backend.
    """

    # registry identity. `scheme` is the part of the model string before the
    # first "/" (e.g. "claude-code" in "claude-code/sonnet").
    scheme: ClassVar[str] = ""
    aliases: ClassVar[tuple[str, ...]] = ()
    display_name: ClassVar[str] = ""

    # retry roles - override with backend-specific classes where needed
    rate_limit_error: ClassVar[type[BaseException]] = BackendRateLimitError
    context_window_error: ClassVar[type[BaseException]] = BackendContextWindowError
    non_retryable_errors: ClassVar[tuple[type[BaseException], ...]] = (BackendAuthError,)
    retryable_errors: ClassVar[tuple[type[BaseException], ...]] = (BackendError, OSError)

    def __init__(self, model: str, **kwargs: Any):
        self.model = model
        self.options = kwargs

    @abstractmethod
    def raw_complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """single completion attempt. raise on failure - retries are handled upstream."""

    @classmethod
    def validate_model(cls, model: str) -> list[str]:
        """pre-flight check run at pipeline load time. return problems, or []."""
        return []

    @classmethod
    def model_alias(cls, model: str) -> str:
        """the part after the scheme, e.g. "sonnet" for "claude-code/sonnet"."""
        m = (model or "").strip()
        return m.split("/", 1)[1].strip() if "/" in m else ""

    @property
    def provider_name(self) -> str:
        return self.scheme or "unknown"

    @property
    def model_name(self) -> str:
        return self.model_alias(self.model) or "default"


class CLIAgentBackend(LLMBackend):
    """drives a locally installed, already-authenticated agent cli.

    deepzero never handles credentials for these: it invokes the user's own
    binary and inherits whatever auth that binary already has.
    """

    # -- subclass declares these --
    binary_names: ClassVar[tuple[str, ...]] = ()
    install_hint: ClassVar[str] = ""
    default_timeout: ClassVar[int] = 900
    # env vars to hide from the child so it uses its own login rather than a
    # metered api key that happens to be in .env for another backend
    subscription_auth_env_blocklist: ClassVar[tuple[str, ...]] = ()

    # argv has hard length limits (~32k on windows); larger text goes via stdin
    max_argv_text: ClassVar[int] = 8000

    def __init__(self, model: str, **kwargs: Any):
        super().__init__(model, **kwargs)
        self.alias = self.model_alias(model)
        self.timeout = int(kwargs.get("timeout", self.default_timeout))
        self.cwd = kwargs.get("cwd")
        # choosing an agent-cli backend signals intent to use its own login
        self.prefer_subscription_auth = bool(kwargs.get("prefer_subscription_auth", True))

        self._binary = kwargs.get("binary") or self.find_binary()
        if not self._binary:
            raise BackendNotFoundError(self.not_found_message())

    # -- discovery --------------------------------------------------------------

    @classmethod
    def find_binary(cls) -> str | None:
        for name in cls.binary_names:
            found = shutil.which(name)
            if found:
                return found
        for candidate in cls.extra_search_paths():
            try:
                if candidate.is_file():
                    return str(candidate)
            except OSError:
                continue
        return None

    @classmethod
    def extra_search_paths(cls) -> list[Path]:
        """non-PATH locations to probe. override for vendor-specific installs."""
        return []

    @classmethod
    def not_found_message(cls) -> str:
        label = cls.display_name or cls.scheme
        hint = f" {cls.install_hint}" if cls.install_hint else ""
        return (
            f"{label} cli not found (looked for: {', '.join(cls.binary_names) or 'n/a'})."
            f"{hint} alternatively use an api-key model instead."
        )

    @classmethod
    def validate_model(cls, model: str) -> list[str]:
        if not cls.find_binary():
            return [f"LLM backend '{model}' is unavailable: {cls.not_found_message()}"]
        return []

    # -- prompt assembly --------------------------------------------------------

    @staticmethod
    def split_messages(messages: list[dict[str, str]]) -> tuple[str, str]:
        """flatten a message list into (system_prompt, user_prompt).

        agent clis are single-shot, so prior turns are rendered inline. a lone
        user message - the pipeline's normal case - passes through untouched.
        """
        system_parts: list[str] = []
        convo: list[dict[str, str]] = []
        for msg in messages or []:
            role = (msg.get("role") or "").lower()
            content = msg.get("content") or ""
            if role == "system":
                if content:
                    system_parts.append(content)
            else:
                convo.append({"role": role or "user", "content": content})

        system = "\n\n".join(system_parts)

        if len(convo) == 1:
            return system, convo[0]["content"]

        rendered = [
            f"{'Assistant' if m['role'] == 'assistant' else 'User'}: {m['content']}" for m in convo
        ]
        return system, "\n\n".join(rendered)

    # -- subclass hooks ---------------------------------------------------------

    @abstractmethod
    def build_argv(self, system: str) -> tuple[list[str], str]:
        """returns (argv, system_text_to_inline).

        a system prompt too large for argv should be returned as the second
        element so the base class routes it through stdin instead.
        """

    @abstractmethod
    def parse_output(self, returncode: int, stdout: str, stderr: str) -> str:
        """extract response text, or raise a BackendError subclass."""

    def build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.prefer_subscription_auth:
            for var in self.subscription_auth_env_blocklist:
                env.pop(var, None)
        return env

    def classify_error(self, detail: str, status: Any = None) -> BackendError:
        """map a failure into the generic taxonomy. override to add vendor cases."""
        low = (detail or "").lower()
        try:
            code = int(status) if status is not None else None
        except (TypeError, ValueError):
            code = None

        label = self.display_name or self.scheme
        if code in (401, 403) or any(k in low for k in ("authenticat", "oauth", "unauthorized")):
            return BackendAuthError(f"{label} is not authenticated ({detail})")
        if code == 429 or any(
            k in low for k in ("rate limit", "usage limit", "quota", "overloaded", "too many")
        ):
            return BackendRateLimitError(detail)
        if "context" in low and any(k in low for k in ("too long", "exceed", "window")):
            return BackendContextWindowError(detail)
        if code is not None and 500 <= code < 600:
            return BackendError(f"{label} server error {code}: {detail}")
        return BackendError(detail)

    # -- execution --------------------------------------------------------------

    def raw_complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        system, prompt = self.split_messages(messages)
        argv, inline_system = self.build_argv(system)

        stdin_text = f"{inline_system}\n\n{prompt}" if inline_system else prompt
        timeout = int(kwargs.get("timeout", self.timeout))

        try:
            proc = subprocess.run(
                argv,
                input=stdin_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=self.build_env(),
                cwd=self.cwd,
            )
        except subprocess.TimeoutExpired as exc:
            label = self.display_name or self.scheme
            raise BackendError(f"{label} timed out after {timeout}s") from exc
        except OSError as exc:
            label = self.display_name or self.scheme
            raise BackendError(f"failed to launch {label}: {exc}") from exc

        return self.parse_output(proc.returncode, proc.stdout or "", proc.stderr or "")

    def check_binary(self) -> str | None:
        """returns None if the binary runs, else a description of the problem."""
        try:
            proc = subprocess.run(
                [str(self._binary), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                env=self.build_env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"could not run {self.display_name or self.scheme}: {exc}"
        if proc.returncode != 0:
            return f"exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
        return None
