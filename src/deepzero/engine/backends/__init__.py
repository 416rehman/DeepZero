"""pluggable llm backends.

to add support for another agent cli (codex, gemini cli, ...):

    # deepzero/engine/backends/mytool.py
    class MyToolBackend(CLIAgentBackend):
        scheme = "mytool"
        display_name = "my tool"
        binary_names = ("mytool",)

        def build_argv(self, system): ...
        def parse_output(self, returncode, stdout, stderr): ...

then register it below (or call register_backend() from your own code - the
registry is open, so third parties can add backends without patching deepzero).
nothing in LLMProvider, the pipeline, or the stages needs to change.
"""

from __future__ import annotations

from deepzero.engine.backends.base import (
    BackendAuthError,
    BackendContextWindowError,
    BackendError,
    BackendNotFoundError,
    BackendRateLimitError,
    CLIAgentBackend,
    LLMBackend,
)
from deepzero.engine.backends.claude_code import ClaudeCodeBackend
from deepzero.engine.backends.litellm_backend import LiteLLMBackend
from deepzero.engine.backends.registry import (
    create_backend,
    get_registered_backends,
    model_scheme,
    register_backend,
    resolve_backend_class,
    validate_model_binding,
)

# -- built-in backends --
register_backend(ClaudeCodeBackend)
# litellm is the fallback for any scheme no other backend claims
register_backend(LiteLLMBackend, default=True)

__all__ = [
    "BackendAuthError",
    "BackendContextWindowError",
    "BackendError",
    "BackendNotFoundError",
    "BackendRateLimitError",
    "CLIAgentBackend",
    "ClaudeCodeBackend",
    "LLMBackend",
    "LiteLLMBackend",
    "create_backend",
    "get_registered_backends",
    "model_scheme",
    "register_backend",
    "resolve_backend_class",
    "validate_model_binding",
]
