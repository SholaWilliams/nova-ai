"""Tests for GeminiProvider (docs/10 §2.1) — golden-fixture round-trips + error mapping.

Fixtures under tests/fixtures/providers/gemini/ capture the parseable GenerateContentResponse
shape (constructed via the real google-genai Pydantic types, then `model_dump()`'d — not a
raw HTTP cassette). They're SYNTHETIC: no live API key was available at authoring time. A
real `-m record` pass should refresh them against a live response once keys are available
(docs/13 §2's "recorded once via `record`, committed scrubbed of keys" policy) — nothing
needs scrubbing yet since no fixture here was ever built from a real response.

Patches at the SDK client boundary (`provider._client.models.generate_content`) rather than
loading fixtures into hand-rolled stand-ins — CODING_STANDARDS.md sanctions this as a "true
process edge," and it exercises the adapter's real error-mapping try/except structure too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from nova.core.errors import AuthError, RateLimited, SafetyBlocked, Transient
from nova.core.models import ChatMessage, ToolCall
from nova.providers.base import GenerateOptions
from nova.providers.gemini import GeminiProvider, _to_gemini_contents

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "providers" / "gemini"
_OPTS = GenerateOptions()


def _load_response(name: str) -> genai_types.GenerateContentResponse:
    data = json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return genai_types.GenerateContentResponse.model_validate(data)


@pytest.fixture
def provider() -> GeminiProvider:
    return GeminiProvider(api_key="test-key", model="gemini-3.5-flash")


class TestOutboundConversion:
    def test_system_message_becomes_system_instruction(self) -> None:
        system, contents = _to_gemini_contents([ChatMessage(role="system", content="be nice")])

        assert system == "be nice"
        assert contents == []

    def test_user_and_assistant_messages_map_to_user_and_model_roles(self) -> None:
        _, contents = _to_gemini_contents(
            [
                ChatMessage(role="user", content="hi"),
                ChatMessage(role="assistant", content="hello!"),
            ]
        )

        assert [c.role for c in contents] == ["user", "model"]
        assert contents[0].parts[0].text == "hi"
        assert contents[1].parts[0].text == "hello!"

    def test_tool_result_correlates_name_from_preceding_assistant_tool_call(self) -> None:
        call = ToolCall(call_id="call_1", tool_name="weather", arguments={"city": "Lagos"})

        _, contents = _to_gemini_contents(
            [
                ChatMessage(role="assistant", content=None, tool_calls=(call,)),
                ChatMessage(role="tool", content="unknown tool", tool_call_id="call_1"),
            ]
        )

        function_response = contents[1].parts[0].function_response
        assert function_response is not None
        assert function_response.name == "weather"
        assert function_response.id == "call_1"


class TestInboundParsing:
    def test_simple_text_response(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = _load_response("simple_text")
        monkeypatch.setattr(provider._client.models, "generate_content", lambda **_kw: response)

        result = provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

        assert result.text == "Hello! How can I help you today?"
        assert result.tool_calls == ()
        assert result.finish_reason == "stop"
        assert result.usage.input_tokens == 12
        assert result.usage.output_tokens == 9

    def test_tool_call_response(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = _load_response("tool_call")
        monkeypatch.setattr(provider._client.models, "generate_content", lambda **_kw: response)

        result = provider.generate([ChatMessage(role="user", content="weather?")], [], _OPTS)

        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "weather"
        assert result.tool_calls[0].arguments == {"city": "Lagos"}
        assert result.text is None

    def test_max_tokens_maps_to_length(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = _load_response("max_tokens")
        monkeypatch.setattr(provider._client.models, "generate_content", lambda **_kw: response)

        result = provider.generate([ChatMessage(role="user", content="tell a story")], [], _OPTS)

        assert result.finish_reason == "length"

    def test_hard_safety_block_raises_safety_blocked(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = _load_response("blocked_prompt")
        monkeypatch.setattr(provider._client.models, "generate_content", lambda **_kw: response)

        with pytest.raises(SafetyBlocked):
            provider.generate([ChatMessage(role="user", content="...")], [], _OPTS)


class TestErrorMapping:
    def test_401_maps_to_auth_error(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_401(**_kw: object) -> None:
            raise genai_errors.ClientError(401, {"error": {"message": "invalid key"}})

        monkeypatch.setattr(provider._client.models, "generate_content", raise_401)

        with pytest.raises(AuthError):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_429_maps_to_rate_limited(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_429(**_kw: object) -> None:
            raise genai_errors.ClientError(429, {"error": {"message": "slow down"}})

        monkeypatch.setattr(provider._client.models, "generate_content", raise_429)

        with pytest.raises(RateLimited):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_server_error_maps_to_transient(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_500(**_kw: object) -> None:
            raise genai_errors.ServerError(500, {"error": {"message": "oops"}})

        monkeypatch.setattr(provider._client.models, "generate_content", raise_500)

        with pytest.raises(Transient):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_unexpected_exception_still_maps_to_a_provider_error(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_weird(**_kw: object) -> None:
            raise ConnectionResetError("network gone")

        monkeypatch.setattr(provider._client.models, "generate_content", raise_weird)

        with pytest.raises(Transient):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)


class TestHealthCheck:
    def test_healthy_when_get_succeeds(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(provider._client.models, "get", lambda **_kw: object())

        health = provider.health_check()

        assert health.available is True

    def test_unhealthy_on_auth_error(
        self, provider: GeminiProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_403(**_kw: object) -> None:
            raise genai_errors.ClientError(403, {"error": {"message": "forbidden"}})

        monkeypatch.setattr(provider._client.models, "get", raise_403)

        health = provider.health_check()

        assert health.available is False
        assert "Invalid API key" in health.detail


def test_capabilities_report_tool_calling_support(provider: GeminiProvider) -> None:
    assert provider.capabilities.tool_calling is True
