from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from deepzero.engine.backends import ClaudeCodeBackend
from deepzero.engine.backends.base import (
    BackendAuthError,
    BackendContextWindowError,
    BackendError,
    BackendNotFoundError,
    BackendRateLimitError,
)
from deepzero.engine.llm import LLMProvider

_FIND = "deepzero.engine.backends.claude_code.ClaudeCodeBackend.find_binary"


def _backend(**kwargs) -> ClaudeCodeBackend:
    kwargs.setdefault("binary", "/usr/bin/claude")
    return ClaudeCodeBackend(kwargs.pop("model", "claude-code/sonnet"), **kwargs)


def _completed(stdout: str, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _result_json(**overrides) -> str:
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "hello from claude",
        "session_id": "abc",
        "total_cost_usd": 0.01,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestAliasParsing:
    def test_alias_parsing(self):
        assert _backend(model="claude-code/sonnet").alias == "sonnet"
        assert _backend(model="claude-code").alias == ""
        assert _backend(model="claude-code/claude-opus-5").alias == "claude-opus-5"


class TestBinaryResolution:
    def test_raises_when_not_installed(self):
        with patch(_FIND, return_value=None):
            with pytest.raises(BackendNotFoundError) as exc:
                ClaudeCodeBackend("claude-code")
        assert "not found" in str(exc.value).lower()

    def test_uses_explicit_binary(self):
        assert ClaudeCodeBackend("claude-code", binary="/custom/claude")._binary == "/custom/claude"


class TestMessageFlattening:
    def test_single_user_message_passes_through(self):
        system, prompt = ClaudeCodeBackend.split_messages([{"role": "user", "content": "analyze"}])
        assert system == ""
        assert prompt == "analyze"

    def test_system_is_separated(self):
        system, prompt = ClaudeCodeBackend.split_messages(
            [{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}]
        )
        assert system == "be terse"
        assert prompt == "hi"

    def test_multi_turn_is_rendered_inline(self):
        system, prompt = ClaudeCodeBackend.split_messages(
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
            ]
        )
        assert system == "sys"
        assert "User: q1" in prompt
        assert "Assistant: a1" in prompt
        assert "User: q2" in prompt

    def test_empty(self):
        assert ClaudeCodeBackend.split_messages([]) == ("", "")


class TestCommandConstruction:
    def test_core_flags(self):
        argv, inline = _backend().build_argv("")
        assert argv[:4] == ["/usr/bin/claude", "-p", "--output-format", "json"]
        assert "--model" in argv and "sonnet" in argv
        assert "--strict-mcp-config" in argv
        assert inline == ""

    def test_no_model_flag_for_bare_alias(self):
        argv, _ = _backend(model="claude-code").build_argv("")
        assert "--model" not in argv

    def test_dangerous_tools_denied_by_default(self):
        argv, _ = _backend().build_argv("")
        denied = argv[argv.index("--disallowed-tools") + 1]
        for tool in ("Bash", "Write", "Edit", "WebFetch"):
            assert tool in denied

    def test_max_turns_limits_agent_loop(self):
        argv, _ = _backend().build_argv("")
        assert "--max-turns" in argv

    def test_small_system_prompt_goes_to_argv(self):
        argv, inline = _backend().build_argv("be terse")
        assert "--append-system-prompt" in argv
        assert "be terse" in argv
        assert inline == ""

    def test_huge_system_prompt_moves_to_stdin(self):
        big = "x" * 20000
        argv, inline = _backend().build_argv(big)
        assert "--append-system-prompt" not in argv
        assert inline == big

    def test_never_uses_bare_flag(self):
        # --bare disables oauth/keychain reads, which would break subscription auth
        argv, _ = _backend().build_argv("sys")
        assert "--bare" not in argv


class TestEnvHandling:
    def test_env_is_passed_through_untouched(self):
        # deepzero does not strip or inject auth vars - the cli decides how to
        # authenticate from its own config and environment
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-x"}, clear=False):
            env = _backend().build_env()
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-x"


class TestResponseParsing:
    def test_success(self):
        with patch("subprocess.run", return_value=_completed(_result_json())) as mock_run:
            out = _backend().raw_complete([{"role": "user", "content": "hi"}])
        assert out == "hello from claude"
        # the prompt travels via stdin, never argv - no shell/argv injection surface
        assert mock_run.call_args.kwargs["input"] == "hi"

    def test_is_error_true_despite_success_subtype(self):
        # the cli reports subtype "success" even on failures; is_error is authoritative
        body = _result_json(is_error=True, subtype="success", result="boom")
        with patch("subprocess.run", return_value=_completed(body)):
            with pytest.raises(BackendError):
                _backend().raw_complete([{"role": "user", "content": "hi"}])

    def test_auth_error_is_classified(self):
        body = _result_json(
            is_error=True,
            api_error_status=401,
            result="Failed to authenticate. API Error: 401 OAuth access token has been revoked.",
        )
        with patch("subprocess.run", return_value=_completed(body)):
            with pytest.raises(BackendAuthError) as exc:
                _backend().raw_complete([{"role": "user", "content": "hi"}])
        msg = str(exc.value)
        assert "not authenticated" in msg
        # relay the cli's own message plus a fixed remedy - no credential probing
        assert "sign in" in msg

    def test_rate_limit_is_classified(self):
        body = _result_json(is_error=True, api_error_status=429, result="rate limit exceeded")
        with patch("subprocess.run", return_value=_completed(body)):
            with pytest.raises(BackendRateLimitError):
                _backend().raw_complete([{"role": "user", "content": "hi"}])

    def test_usage_limit_text_is_rate_limit(self):
        body = _result_json(is_error=True, result="Claude usage limit reached")
        with patch("subprocess.run", return_value=_completed(body)):
            with pytest.raises(BackendRateLimitError):
                _backend().raw_complete([{"role": "user", "content": "hi"}])

    def test_context_window_is_classified(self):
        body = _result_json(is_error=True, result="prompt is too long: context window exceeded")
        with patch("subprocess.run", return_value=_completed(body)):
            with pytest.raises(BackendContextWindowError):
                _backend().raw_complete([{"role": "user", "content": "hi"}])

    def test_unparseable_output(self):
        with patch("subprocess.run", return_value=_completed("not json")):
            with pytest.raises(BackendError):
                _backend().raw_complete([{"role": "user", "content": "hi"}])

    def test_nonzero_exit_with_stderr(self):
        with patch("subprocess.run", return_value=_completed("", 1, "command failed")):
            with pytest.raises(BackendError) as exc:
                _backend().raw_complete([{"role": "user", "content": "hi"}])
        assert "command failed" in str(exc.value)

    def test_timeout(self):
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5)
        ):
            with pytest.raises(BackendError) as exc:
                _backend().raw_complete([{"role": "user", "content": "hi"}])
        assert "timed out" in str(exc.value)

    def test_launch_failure(self):
        with patch("subprocess.run", side_effect=OSError("no exec")):
            with pytest.raises(BackendError):
                _backend().raw_complete([{"role": "user", "content": "hi"}])


class TestProviderIntegration:
    def test_provider_selects_claude_code_without_litellm(self, monkeypatch):
        import sys

        # litellm intentionally unavailable - the claude code path must not need it
        monkeypatch.setitem(sys.modules, "litellm", None)
        with patch(_FIND, return_value="/usr/bin/claude"):
            provider = LLMProvider("claude-code/sonnet")

        assert isinstance(provider.backend, ClaudeCodeBackend)
        assert provider.provider_name == "claude-code"
        assert provider.model_name == "sonnet"

    def test_provider_completes_through_backend(self):
        with patch(_FIND, return_value="/usr/bin/claude"):
            provider = LLMProvider("claude-code")
        with patch("subprocess.run", return_value=_completed(_result_json())):
            assert provider.complete([{"role": "user", "content": "hi"}]) == "hello from claude"

    def test_generation_kwargs_not_forwarded_to_cli(self):
        # litellm-style kwargs must not leak into the subprocess call
        with patch(_FIND, return_value="/usr/bin/claude"):
            provider = LLMProvider("claude-code", temperature=0.7)
        with patch("subprocess.run", return_value=_completed(_result_json())) as mock_run:
            provider.complete([{"role": "user", "content": "hi"}])
        assert "temperature" not in mock_run.call_args.kwargs

    def test_rate_limit_retries_then_succeeds(self):
        with patch(_FIND, return_value="/usr/bin/claude"):
            provider = LLMProvider("claude-code")

        failure = _completed(_result_json(is_error=True, api_error_status=429, result="rate limit"))
        success = _completed(_result_json())
        with patch("subprocess.run", side_effect=[failure, success]):
            with patch("time.sleep"):
                assert provider.complete([{"role": "user", "content": "hi"}]) == "hello from claude"

    def test_auth_error_fails_fast_without_retrying(self):
        with patch(_FIND, return_value="/usr/bin/claude"):
            provider = LLMProvider("claude-code")

        failure = _completed(
            _result_json(is_error=True, api_error_status=401, result="authentication failed")
        )
        with patch("subprocess.run", return_value=failure) as mock_run:
            with patch("time.sleep"):
                with pytest.raises(BackendAuthError):
                    provider.complete([{"role": "user", "content": "hi"}], max_retries=3)

        assert mock_run.call_count == 1

    def test_context_window_error_not_retried(self):
        with patch(_FIND, return_value="/usr/bin/claude"):
            provider = LLMProvider("claude-code")

        failure = _completed(_result_json(is_error=True, result="context window exceeded"))
        with patch("subprocess.run", return_value=failure) as mock_run:
            with patch("time.sleep"):
                with pytest.raises(BackendContextWindowError):
                    provider.complete([{"role": "user", "content": "hi"}], max_retries=3)

        assert mock_run.call_count == 1


class TestValidation:
    def _stage(self):
        from deepzero.engine.stage import StageSpec
        from deepzero.stages.llm import GenericLLM

        return GenericLLM(StageSpec(name="assess", processor="generic_llm", config={}))

    def _validate(self, model: str) -> list[str]:
        from deepzero.engine.stage import ProcessorContext

        ctx = ProcessorContext(
            pipeline_dir=__import__("pathlib").Path("."),
            global_config={"model": model},
            llm=None,
        )
        # only inspect llm-binding errors, not the unrelated prompt-config error
        return [e for e in self._stage().validate(ctx) if "backend" in e.lower()]

    def test_claude_code_binding_ok_when_installed(self):
        with patch(_FIND, return_value="/usr/bin/claude"):
            assert self._validate("claude-code/sonnet") == []

    def test_claude_code_binding_reports_missing_cli(self):
        with patch(_FIND, return_value=None):
            errors = self._validate("claude-code")
        assert errors and "claude code cli not found" in errors[0].lower()

    def test_claude_code_binding_does_not_require_api_keys(self, monkeypatch):
        # no api keys anywhere, yet a valid subscription credential validates.
        # (clears only the key vars - wiping the whole env would also remove the
        # credential location, which is a different failure)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        with patch(_FIND, return_value="/usr/bin/claude"):
            assert self._validate("claude-code") == []


class TestAuthPreflight:
    def test_check_auth_ok_when_authenticated(self):
        with patch("subprocess.run", return_value=_completed(_result_json())):
            assert _backend().check_auth() is None

    def test_check_auth_reports_401(self):
        body = _result_json(
            is_error=True, api_error_status=401, result="OAuth access token has been revoked"
        )
        with patch("subprocess.run", return_value=_completed(body)):
            msg = _backend().check_auth()
        assert msg and "not authenticated" in msg

    def test_check_auth_does_not_block_on_transient(self):
        # a rate limit during preflight is not an auth failure
        body = _result_json(is_error=True, api_error_status=429, result="rate limit")
        with patch("subprocess.run", return_value=_completed(body)):
            assert _backend().check_auth() is None

    def test_provider_check_auth_delegates(self):
        with patch(_FIND, return_value="/usr/bin/claude"):
            provider = LLMProvider("claude-code")
        with patch("subprocess.run", return_value=_completed(_result_json())):
            assert provider.check_auth() is None
        with patch(
            "subprocess.run",
            return_value=_completed(
                _result_json(is_error=True, api_error_status=401, result="revoked")
            ),
        ):
            assert provider.check_auth() is not None
