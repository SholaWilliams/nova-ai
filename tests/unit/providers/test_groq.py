"""Tests for GroqProvider (docs/10 §2.2) — golden-fixture round-trips + error mapping.

See test_gemini.py's module docstring for the fixture-provenance note (synthetic, built from
the real SDK's Pydantic types — no live key was available at authoring time) and the
patch-at-the-SDK-boundary rationale.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from groq import _exceptions as groq_errors
from groq.types.chat.chat_completion import ChatCompletion

from nova.core.errors import AuthError, RateLimited, Transient
from nova.core.models import ChatMessage, ToolCall
from nova.providers.base import GenerateOptions
from nova.providers.groq import GroqProvider, _to_groq_message, _to_groq_tool

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "providers" / "groq"
_OPTS = GenerateOptions()


def _load_response(name: str) -> ChatCompletion:
    data = json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return ChatCompletion.model_validate(data)


def _status_error(
    cls: type[groq_errors.APIStatusError], message: str
) -> groq_errors.APIStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status_code=cls.status_code, request=request)
    return cls(message, response=response, body=None)


@pytest.fixture
def provider() -> GroqProvider:
    return GroqProvider(api_key="test-key", model="openai/gpt-oss-120b")


class TestOutboundConversion:
    def test_plain_messages_map_role_and_content(self) -> None:
        assert _to_groq_message(ChatMessage(role="user", content="hi")) == {
            "role": "user",
            "content": "hi",
        }
        assert _to_groq_message(ChatMessage(role="system", content="be nice")) == {
            "role": "system",
            "content": "be nice",
        }

    def test_tool_message_carries_tool_call_id(self) -> None:
        message = _to_groq_message(
            ChatMessage(role="tool", content="unknown tool", tool_call_id="call_1")
        )

        assert message == {"role": "tool", "content": "unknown tool", "tool_call_id": "call_1"}

    def test_assistant_message_with_tool_calls_serializes_arguments_as_json_string(self) -> None:
        call = ToolCall(call_id="call_1", tool_name="weather", arguments={"city": "Lagos"})

        message = _to_groq_message(ChatMessage(role="assistant", content=None, tool_calls=(call,)))

        assert message["role"] == "assistant"
        assert message["tool_calls"][0]["id"] == "call_1"
        assert message["tool_calls"][0]["function"]["name"] == "weather"
        assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"city": "Lagos"}

    def test_tool_schema_maps_to_function_definition(self) -> None:
        from nova.core.models import ToolSchema

        schema = ToolSchema(
            name="weather",
            description="get weather",
            parameters={"type": "object"},
        )

        tool = _to_groq_tool(schema)

        assert tool == {
            "type": "function",
            "function": {
                "name": "weather",
                "description": "get weather",
                "parameters": {"type": "object"},
            },
        }


class TestInboundParsing:
    def test_simple_text_response(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = _load_response("simple_text")
        monkeypatch.setattr(provider._client.chat.completions, "create", lambda **_kw: response)

        result = provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

        assert result.text == "Hello! How can I help?"
        assert result.tool_calls == ()
        assert result.finish_reason == "stop"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 7

    def test_tool_call_response_deserializes_json_arguments(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = _load_response("tool_call")
        monkeypatch.setattr(provider._client.chat.completions, "create", lambda **_kw: response)

        result = provider.generate([ChatMessage(role="user", content="weather?")], [], _OPTS)

        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].call_id == "call_xyz789"
        assert result.tool_calls[0].tool_name == "weather"
        assert result.tool_calls[0].arguments == {"city": "Lagos"}

    def test_max_tokens_maps_to_length(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = _load_response("max_tokens")
        monkeypatch.setattr(provider._client.chat.completions, "create", lambda **_kw: response)

        result = provider.generate([ChatMessage(role="user", content="tell a story")], [], _OPTS)

        assert result.finish_reason == "length"


class TestErrorMapping:
    def test_authentication_error_maps_to_auth_error(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_auth(**_kw: object) -> None:
            raise _status_error(groq_errors.AuthenticationError, "invalid key")

        monkeypatch.setattr(provider._client.chat.completions, "create", raise_auth)

        with pytest.raises(AuthError):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_rate_limit_error_maps_to_rate_limited(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_rate_limit(**_kw: object) -> None:
            raise _status_error(groq_errors.RateLimitError, "slow down")

        monkeypatch.setattr(provider._client.chat.completions, "create", raise_rate_limit)

        with pytest.raises(RateLimited):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_internal_server_error_maps_to_transient(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_500(**_kw: object) -> None:
            raise _status_error(groq_errors.InternalServerError, "oops")

        monkeypatch.setattr(provider._client.chat.completions, "create", raise_500)

        with pytest.raises(Transient):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_unexpected_exception_still_maps_to_a_provider_error(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_weird(**_kw: object) -> None:
            raise ConnectionResetError("network gone")

        monkeypatch.setattr(provider._client.chat.completions, "create", raise_weird)

        with pytest.raises(Transient):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)


class TestHealthCheck:
    def test_healthy_when_retrieve_succeeds(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(provider._client.models, "retrieve", lambda *_a, **_kw: object())

        health = provider.health_check()

        assert health.available is True

    def test_unhealthy_on_auth_error(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_auth(*_a: object, **_kw: object) -> None:
            raise _status_error(groq_errors.PermissionDeniedError, "forbidden")

        monkeypatch.setattr(provider._client.models, "retrieve", raise_auth)

        health = provider.health_check()

        assert health.available is False
        assert "Invalid API key" in health.detail


def test_capabilities_report_tool_calling_support(provider: GroqProvider) -> None:
    assert provider.capabilities.tool_calling is True
