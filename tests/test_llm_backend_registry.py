"""proves the extensibility contract: a new agent-cli backend can be added by
subclassing CLIAgentBackend and registering it, with no changes to LLMProvider,
the registry internals, the pipeline, or the stages.
"""

from __future__ import annotations

import json
import subprocess
from typing import ClassVar
from unittest.mock import patch

import pytest

from deepzero.engine.backends import (
    ClaudeCodeBackend,
    CLIAgentBackend,
    LiteLLMBackend,
    get_registered_backends,
    model_scheme,
    register_backend,
    resolve_backend_class,
    validate_model_binding,
)
from deepzero.engine.backends.base import BackendError
from deepzero.engine.backends.registry import _BACKEND_REGISTRY
from deepzero.engine.llm import LLMProvider


# a stand-in for a future backend (codex, gemini cli, ...). the only things it
# has to supply are argv construction and output parsing.
class FakeAgentBackend(CLIAgentBackend):
    scheme: ClassVar[str] = "faketool"
    aliases: ClassVar[tuple[str, ...]] = ("ft",)
    display_name: ClassVar[str] = "fake tool"
    binary_names: ClassVar[tuple[str, ...]] = ("faketool",)
    subscription_auth_env_blocklist: ClassVar[tuple[str, ...]] = ("FAKETOOL_API_KEY",)

    def build_argv(self, system: str) -> tuple[list[str], str]:
        argv = [str(self._binary), "exec", "--json"]
        if self.alias:
            argv += ["--model", self.alias]
        if system:
            argv += ["--system", system]
        return argv, ""

    def parse_output(self, returncode: int, stdout: str, stderr: str) -> str:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise BackendError(f"bad output: {stdout[:100]}") from exc
        if payload.get("error"):
            raise self.classify_error(payload["error"], payload.get("status"))
        return payload["text"]


@pytest.fixture
def registered_fake():
    """register the fake backend, then restore the registry."""
    saved = dict(_BACKEND_REGISTRY)
    register_backend(FakeAgentBackend)
    try:
        yield FakeAgentBackend
    finally:
        _BACKEND_REGISTRY.clear()
        _BACKEND_REGISTRY.update(saved)


def _completed(stdout: str, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestSchemeParsing:
    @pytest.mark.parametrize(
        "model,expected",
        [
            ("claude-code", "claude-code"),
            ("claude-code/sonnet", "claude-code"),
            ("CLAUDE-CODE/Sonnet", "claude-code"),
            ("openai/gpt-4o", "openai"),
            ("gpt-4o", "gpt-4o"),
            ("", ""),
        ],
    )
    def test_scheme(self, model, expected):
        assert model_scheme(model) == expected


class TestBuiltInResolution:
    @pytest.mark.parametrize("model", ["claude-code", "claude-code/sonnet", "claude-code/opus"])
    def test_claude_code_schemes(self, model):
        assert resolve_backend_class(model) is ClaudeCodeBackend

    @pytest.mark.parametrize(
        "model", ["openai/gpt-4o", "anthropic/claude-opus-5", "gemini/pro", "gpt-4o", "test"]
    )
    def test_unclaimed_schemes_fall_back_to_litellm(self, model):
        assert resolve_backend_class(model) is LiteLLMBackend

    def test_claude_code_prefix_is_not_over_matched(self):
        # "claude-code-extra" is a different scheme, not claude code
        assert resolve_backend_class("claude-code-extra/x") is LiteLLMBackend

    def test_registry_lists_known_schemes(self):
        assert "claude-code" in get_registered_backends()


class TestAddingANewBackend:
    def test_scheme_and_alias_resolve(self, registered_fake):
        assert resolve_backend_class("faketool") is FakeAgentBackend
        assert resolve_backend_class("faketool/big-model") is FakeAgentBackend
        assert resolve_backend_class("ft/big-model") is FakeAgentBackend

    def test_does_not_disturb_existing_backends(self, registered_fake):
        assert resolve_backend_class("claude-code") is ClaudeCodeBackend
        assert resolve_backend_class("openai/gpt-4o") is LiteLLMBackend

    def test_provider_drives_it_end_to_end(self, registered_fake):
        with patch.object(FakeAgentBackend, "find_binary", return_value="/usr/bin/faketool"):
            provider = LLMProvider("faketool/big-model")

        assert provider.provider_name == "faketool"
        assert provider.model_name == "big-model"

        with patch("subprocess.run", return_value=_completed('{"text": "fake says hi"}')) as run:
            assert provider.complete([{"role": "user", "content": "hi"}]) == "fake says hi"

        argv = run.call_args.args[0]
        assert argv == ["/usr/bin/faketool", "exec", "--json", "--model", "big-model"]
        assert run.call_args.kwargs["input"] == "hi"

    def test_inherits_retry_semantics_for_free(self, registered_fake):
        with patch.object(FakeAgentBackend, "find_binary", return_value="/usr/bin/faketool"):
            provider = LLMProvider("faketool")

        limited = _completed(json.dumps({"error": "rate limit hit", "status": 429}))
        ok = _completed('{"text": "recovered"}')
        with patch("subprocess.run", side_effect=[limited, ok]):
            with patch("time.sleep"):
                assert provider.complete([{"role": "user", "content": "hi"}]) == "recovered"

    def test_inherits_auth_fail_fast_for_free(self, registered_fake):
        with patch.object(FakeAgentBackend, "find_binary", return_value="/usr/bin/faketool"):
            provider = LLMProvider("faketool")

        denied = _completed(json.dumps({"error": "unauthorized", "status": 401}))
        with patch("subprocess.run", return_value=denied) as run:
            with patch("time.sleep"):
                with pytest.raises(BackendError):
                    provider.complete([{"role": "user", "content": "hi"}], max_retries=3)
        assert run.call_count == 1

    def test_inherits_env_sanitization_for_free(self, registered_fake):
        with patch.dict("os.environ", {"FAKETOOL_API_KEY": "secret"}, clear=False):
            with patch.object(FakeAgentBackend, "find_binary", return_value="/usr/bin/faketool"):
                env = FakeAgentBackend("faketool").build_env()
        assert "FAKETOOL_API_KEY" not in env

    def test_inherits_validation_wiring_for_free(self, registered_fake):
        with patch.object(FakeAgentBackend, "find_binary", return_value=None):
            errors = validate_model_binding("faketool")
        assert errors and "fake tool cli not found" in errors[0].lower()

        with patch.object(FakeAgentBackend, "find_binary", return_value="/usr/bin/faketool"):
            assert validate_model_binding("faketool") == []


class TestRegistrationRules:
    def test_backend_without_scheme_is_rejected(self):
        class Anonymous(CLIAgentBackend):
            def build_argv(self, system):
                return [], ""

            def parse_output(self, returncode, stdout, stderr):
                return ""

        with pytest.raises(ValueError, match="scheme"):
            register_backend(Anonymous)

    def test_register_returns_class_for_decorator_use(self):
        saved = dict(_BACKEND_REGISTRY)
        try:

            class Decorated(CLIAgentBackend):
                scheme = "decorated"

                def build_argv(self, system):
                    return [], ""

                def parse_output(self, returncode, stdout, stderr):
                    return ""

            assert register_backend(Decorated) is Decorated
        finally:
            _BACKEND_REGISTRY.clear()
            _BACKEND_REGISTRY.update(saved)
