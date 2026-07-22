"""Tests for OpenRouterProvider (docs/10 §2.4) — golden-fixture round-trips + error mapping.

Fixtures are synthetic JSON, hand-built to OpenAI-Chat-Completions shape (the dialect
OpenRouter documents) — no live key was available at authoring time. Request-side mapping
(`to_openai_message`/`to_openai_tool`) is exercised in test_groq.py, which shares the same
`_openai_compat` functions; this file covers what's unique to this adapter: HTTP transport,
response parsing, and error mapping over `httpx` rather than an SDK.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from nova.core.errors import AuthError, RateLimited, Transient
from nova.core.models import ChatMessage
from nova.providers.base import GenerateOptions
from nova.providers.openrouter import OpenRouterProvider

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "providers" / "openrouter"
_OPTS = GenerateOptions()
_URL = "https://openrouter.ai/api/v1/chat/completions"


def _load_response(name: str) -> httpx.Response:
    data = json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return httpx.Response(200, json=data, request=httpx.Request("POST", _URL))


def _error_response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", _URL))


@pytest.fixture
def provider() -> OpenRouterProvider:
    return OpenRouterProvider(api_key="test-key", model="nvidia/nemotron-3-super-120b-a12b:free")


class TestInboundParsing:
    def test_simple_text_response(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", lambda *_a, **_kw: _load_response("simple_text")
        )

        result = provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

        assert result.text == "Hello! How can I help?"
        assert result.tool_calls == ()
        assert result.finish_reason == "stop"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 7

    def test_tool_call_response_deserializes_json_arguments(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", lambda *_a, **_kw: _load_response("tool_call")
        )

        result = provider.generate([ChatMessage(role="user", content="weather?")], [], _OPTS)

        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].call_id == "call_xyz789"
        assert result.tool_calls[0].tool_name == "weather"
        assert result.tool_calls[0].arguments == {"city": "Lagos"}

    def test_max_tokens_maps_to_length(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", lambda *_a, **_kw: _load_response("max_tokens")
        )

        result = provider.generate([ChatMessage(role="user", content="tell a story")], [], _OPTS)

        assert result.finish_reason == "length"


class TestErrorMapping:
    def test_401_maps_to_auth_error(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(provider._client, "post", lambda *_a, **_kw: _error_response(401))

        with pytest.raises(AuthError):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_429_maps_to_rate_limited(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(provider._client, "post", lambda *_a, **_kw: _error_response(429))

        with pytest.raises(RateLimited):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_500_maps_to_transient(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(provider._client, "post", lambda *_a, **_kw: _error_response(500))

        with pytest.raises(Transient):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_timeout_maps_to_transient(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_timeout(*_a: object, **_kw: object) -> None:
            raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(provider._client, "post", raise_timeout)

        with pytest.raises(Transient):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)

    def test_connection_error_maps_to_transient(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_connect_error(*_a: object, **_kw: object) -> None:
            raise httpx.ConnectError("network gone")

        monkeypatch.setattr(provider._client, "post", raise_connect_error)

        with pytest.raises(Transient):
            provider.generate([ChatMessage(role="user", content="hi")], [], _OPTS)


class TestHealthCheck:
    def test_healthy_when_models_endpoint_succeeds(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client,
            "get",
            lambda *_a, **_kw: httpx.Response(
                200, json={"data": []}, request=httpx.Request("GET", _URL)
            ),
        )

        health = provider.health_check()

        assert health.available is True

    def test_unhealthy_on_auth_error(
        self, provider: OpenRouterProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(provider._client, "get", lambda *_a, **_kw: _error_response(401))

        health = provider.health_check()

        assert health.available is False
        assert "Invalid API key" in health.detail


def test_capabilities_report_tool_calling_support(provider: OpenRouterProvider) -> None:
    assert provider.capabilities.tool_calling is True
