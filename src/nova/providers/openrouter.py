"""OpenRouterProvider: the `openrouter.ai` adapter (docs/10 §2.4).

OpenRouter is a meta-provider exposing many models behind one key, via an OpenAI-Chat-
Completions-compatible REST endpoint — so this adapter is plain `httpx`, not a vendor SDK
(docs/04 TD-4 amendment: no new dependency, `httpx` already covers "plain HTTP calls we own",
TD-11). Request shape reuses `_openai_compat` (same dialect Groq speaks); response parsing is
its own thing here since it's a raw JSON dict, not SDK response objects.

Adapters raise only `core.errors.ProviderError` subtypes — the manager and agent never see a
raw SDK/HTTP exception (A-4, A-6, docs/10 §1).
"""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx

from nova.core.errors import AuthError, RateLimited, Transient
from nova.core.models import ChatMessage, ToolCall, ToolSchema
from nova.providers._openai_compat import to_openai_message, to_openai_tool
from nova.providers.base import (
    GenerateOptions,
    LLMProvider,
    LLMResponse,
    ProviderCaps,
    ProviderHealth,
    TokenUsage,
)

_BASE_URL = "https://openrouter.ai/api/v1"

_FINISH_REASON_MAP: dict[str, Literal["stop", "tool_calls", "length", "error"]] = {
    "stop": "stop",
    "tool_calls": "tool_calls",
    "length": "length",
}


class OpenRouterProvider(LLMProvider):
    """Cloud LLM backend for OpenRouter, normalized to `LLMProvider` (docs/10 §2.4).

    OpenRouter has no dedicated hard-safety-block concept in its API surface (like Groq,
    unlike Gemini) — `SafetyBlocked` is never raised by this adapter.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self.name = "openrouter"
        self._model = model
        self._client = httpx.Client(
            base_url=_BASE_URL, headers={"Authorization": f"Bearer {api_key}"}
        )

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema],
        opts: GenerateOptions,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [to_openai_message(message) for message in messages],
            "temperature": opts.temperature,
            "max_tokens": opts.max_tokens,
            # ponytail: if a chosen model reasons and leaks chain-of-thought like Groq's
            # gpt-oss-120b did (docs/10 TD-4), OpenRouter's own `reasoning: {"exclude": true}`
            # is the knob — add it here if/when a documented default model needs it. Nemotron
            # 3 Super (the current default, docs/04 TD-4) is a plain chat model; skipped until
            # a real model needs it (YAGNI).
        }
        if tools:
            payload["tools"] = [to_openai_tool(tool) for tool in tools]

        try:
            response = self._client.post("/chat/completions", json=payload, timeout=opts.timeout_s)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise Transient(f"openrouter request timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise _map_status_error(exc) from exc
        except httpx.HTTPError as exc:
            raise Transient(f"openrouter request failed: {exc}") from exc

        return _to_llm_response(response.json())

    def health_check(self) -> ProviderHealth:
        try:
            response = self._client.get("/models", timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                return ProviderHealth(available=False, detail="Invalid API key")
            return ProviderHealth(available=False, detail=str(exc))
        except httpx.HTTPError as exc:  # boundary catch: health_check must never raise
            return ProviderHealth(available=False, detail=str(exc))
        return ProviderHealth(available=True, detail="ready")

    @property
    def capabilities(self) -> ProviderCaps:
        # docs/10 §2.4: varies per model in principle, but every OpenRouter model NOVA
        # documents as a supported default (Nemotron 3 Super) supports tool calling with a
        # comparable context window to the other two providers.
        return ProviderCaps(tool_calling=True, max_context=131_072, safety_settings=False)


def _map_status_error(exc: httpx.HTTPStatusError) -> Exception:
    status = exc.response.status_code
    if status in (401, 403):
        return AuthError(
            str(exc), friendly_message="My connection to OpenRouter needs a fresh key."
        )
    if status == 429:
        return RateLimited(str(exc), retry_after=_extract_retry_after(exc.response))
    return Transient(str(exc))


def _extract_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_llm_response(data: dict[str, Any]) -> LLMResponse:
    choice = data["choices"][0]
    message = choice["message"]

    raw_tool_calls = message.get("tool_calls") or []
    tool_calls = tuple(
        ToolCall(
            call_id=call["id"],
            tool_name=call["function"]["name"],
            arguments=_json_loads_or_empty(call["function"]["arguments"]),
        )
        for call in raw_tool_calls
    )

    finish_reason = _FINISH_REASON_MAP.get(choice.get("finish_reason", ""), "error")
    if tool_calls:
        finish_reason = "tool_calls"

    usage = data.get("usage") or {}
    token_usage = TokenUsage(
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
    )

    return LLMResponse(
        text=message.get("content"),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=token_usage,
    )


def _json_loads_or_empty(arguments: str) -> dict[str, Any]:
    return json.loads(arguments) if arguments else {}
