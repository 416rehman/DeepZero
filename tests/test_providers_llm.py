from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class TestLLMProviderProperties:
    def _make_provider(self, model: str):
        # mock litellm so we don't need it installed
        mock_litellm = MagicMock()
        mock_litellm.suppress_debug_info = False
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            from deepzero.engine.llm import LLMProvider

            provider = LLMProvider(model)
        return provider

    def test_provider_name_with_slash(self):
        p = self._make_provider("openai/gpt-4o")
        assert p.provider_name == "openai"

    def test_provider_name_without_slash(self):
        p = self._make_provider("gpt-4o")
        assert p.provider_name == "unknown"

    def test_model_name_with_slash(self):
        p = self._make_provider("anthropic/claude-3-sonnet")
        assert p.model_name == "claude-3-sonnet"

    def test_model_name_without_slash(self):
        p = self._make_provider("gpt-4o")
        assert p.model_name == "gpt-4o"

    def test_model_name_multiple_slashes(self):
        p = self._make_provider("vertex_ai/google/gemini-pro")
        assert p.model_name == "google/gemini-pro"


class TestLLMProviderComplete:
    def _make_provider_with_mock(self):
        mock_litellm = MagicMock()
        mock_litellm.suppress_debug_info = False
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            from deepzero.engine.llm import LLMProvider

            provider = LLMProvider("openai/gpt-4o")
        return provider, mock_litellm

    def test_successful_completion(self):
        provider, mock_litellm = self._make_provider_with_mock()

        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello world"))]
        )
        mock_litellm.completion.return_value = mock_response

        result = provider.complete([{"role": "user", "content": "hi"}])
        assert result == "hello world"
        mock_litellm.completion.assert_called_once()

    def test_empty_content_returns_empty_string(self):
        provider, mock_litellm = self._make_provider_with_mock()

        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        )
        mock_litellm.completion.return_value = mock_response

        result = provider.complete([{"role": "user", "content": "hi"}])
        assert result == ""

    def test_default_kwargs_merged(self):
        mock_litellm = MagicMock()
        mock_litellm.suppress_debug_info = False
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            from deepzero.engine.llm import LLMProvider

            provider = LLMProvider("openai/gpt-4o", temperature=0.5)

        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )
        mock_litellm.completion.return_value = mock_response

        provider.complete([{"role": "user", "content": "hi"}], max_tokens=100)
        call_kwargs = mock_litellm.completion.call_args
        assert call_kwargs.kwargs["temperature"] == 0.5
        assert call_kwargs.kwargs["max_tokens"] == 100

    @patch("time.sleep")
    def test_generic_runtime_error_retries_then_raises(self, mock_sleep):
        provider, mock_litellm = self._make_provider_with_mock()
        mock_litellm.completion.side_effect = RuntimeError("token limit exceeded")

        with pytest.raises(RuntimeError, match="token limit exceeded"):
            provider.complete([{"role": "user", "content": "hi"}], max_retries=3)

        # retries all attempts since RuntimeError is retryable without real litellm types
        assert mock_litellm.completion.call_count == 4

    @patch("time.sleep")
    def test_rate_limit_retries(self, mock_sleep):
        provider, mock_litellm = self._make_provider_with_mock()

        success_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="recovered"))]
        )
        mock_litellm.completion.side_effect = [
            RuntimeError("429 rate limit"),
            success_response,
        ]

        result = provider.complete(
            [{"role": "user", "content": "hi"}],
            max_retries=2,
            initial_backoff=0.01,
            max_backoff=0.1,
        )
        assert result == "recovered"
        assert mock_litellm.completion.call_count == 2
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    def test_exhausted_retries_raises(self, mock_sleep):
        provider, mock_litellm = self._make_provider_with_mock()
        mock_litellm.completion.side_effect = RuntimeError("server error")

        with pytest.raises(RuntimeError, match="server error"):
            provider.complete(
                [{"role": "user", "content": "hi"}],
                max_retries=1,
                initial_backoff=0.01,
            )
        # 2 calls: attempt 0 + attempt 1 (max_retries=1)
        assert mock_litellm.completion.call_count == 2


class TestLLMProviderImportGuard:
    def test_missing_litellm_raises(self):
        # simulate litellm not installed
        import sys

        saved = sys.modules.get("litellm")
        sys.modules["litellm"] = None  # force ImportError on import

        try:
            from deepzero.engine.llm import LLMProvider

            with pytest.raises(ImportError, match="litellm"):
                LLMProvider("openai/gpt-4o")
        finally:
            if saved is not None:
                sys.modules["litellm"] = saved
            else:
                sys.modules.pop("litellm", None)
