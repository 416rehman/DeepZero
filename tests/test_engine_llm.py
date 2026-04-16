import pytest
from deepzero.engine.llm import LLMProvider


def test_llm_provider_init(monkeypatch):
    import sys

    # Mock litellm module
    class MockLitellm:
        suppress_debug_info = False

        def completion(self, *args, **kwargs):
            class Choice:
                class Message:
                    content = "hello"

                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    monkeypatch.setitem(sys.modules, "litellm", MockLitellm())

    provider = LLMProvider("openai/gpt-4")
    assert provider.provider_name == "openai"
    assert provider.model_name == "gpt-4"
    assert provider._litellm.suppress_debug_info is True


def test_llm_provider_complete(monkeypatch):
    import sys

    class MockLitellm:
        def completion(self, *args, **kwargs):
            class Choice:
                class Message:
                    content = "mock_response"

                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    monkeypatch.setitem(sys.modules, "litellm", MockLitellm())

    provider = LLMProvider("test/model")
    res = provider.complete([{"role": "user", "content": "hi"}])
    assert res == "mock_response"


def test_llm_provider_missing(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "litellm", None)

    with pytest.raises(ImportError):
        LLMProvider("test")
