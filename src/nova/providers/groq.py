"""GroqProvider: the `groq` adapter (docs/10 §2.2).

OpenAI-style messages/tools/tool_calls — near-1:1 with NOVA's internal `ChatMessage`/
`ToolCall` shape, so this adapter is much thinner than the Gemini one. Groq also hosts STT
(TD-5, M4) via a separate thin client in `speech/` — no dependency from `speech` to
`providers` (D-2); they only share the API key via config.

Adapters raise only `core.errors.ProviderError` subtypes — the manager and agent never see a
raw SDK exception (A-4, A-6, docs/10 §1).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from groq import Groq
from groq import _exceptions as groq_errors

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

_FINISH_REASON_MAP: dict[str, Literal["stop", "tool_calls", "length", "error"]] = {
    "stop": "stop",
    "tool_calls": "tool_calls",
    "length": "length",
    "function_call": "tool_calls",  # deprecated alias; still map sensibly
}


class GroqProvider(LLMProvider):
    """Cloud LLM backend for Groq, normalized to `LLMProvider` (docs/10 §2.2).

    Groq has no dedicated "hard safety block" concept in its API surface (unlike Gemini's
    `prompt_feedback.block_reason`) — `SafetyBlocked` is never raised by this adapter.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self.name = "groq"
        self._model = model
        self._client = Groq(api_key=api_key)

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema],
        opts: GenerateOptions,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [to_openai_message(message) for message in messages],
            "temperature": opts.temperature,
            "max_tokens": opts.max_tokens,
            "timeout": opts.timeout_s,
            # gpt-oss-120b (docs/10 TD-4) is a reasoning model; without this its chain-of-
            # thought leaks straight into `content` and can eat the whole max_tokens budget
            # before the real answer, producing truncated/garbled replies (surfaced once
            # M5's memory block made prompts long enough to trigger longer reasoning).
            # ⚠️ Even with this set, the garble can still surface (2026-07-22 field report) —
            # if it recurs, docs/10 §5's OpenRouter provider is the documented escape hatch:
            # point Settings at a non-reasoning model instead of tuning this further.
            "reasoning_effort": "low",
            "reasoning_format": "hidden",
        }
        if tools:
            kwargs["tools"] = [to_openai_tool(tool) for tool in tools]

        try:
            response = self._client.chat.completions.create(**kwargs)
        except groq_errors.RateLimitError as exc:
            raise RateLimited(exc.message, retry_after=_extract_retry_after(exc)) from exc
        except (groq_errors.AuthenticationError, groq_errors.PermissionDeniedError) as exc:
            raise AuthError(
                exc.message, friendly_message="My connection to Groq needs a fresh key."
            ) from exc
        except (groq_errors.InternalServerError, groq_errors.APIConnectionError) as exc:
            raise Transient(str(exc)) from exc
        except groq_errors.APIStatusError as exc:
            raise Transient(exc.message) from exc
        except Exception as exc:  # boundary: adapters raise only ProviderError (docs/10 §1)
            raise Transient(f"groq request failed: {exc}") from exc

        return _to_llm_response(response)

    def health_check(self) -> ProviderHealth:
        try:
            self._client.models.retrieve(self._model)
        except (groq_errors.AuthenticationError, groq_errors.PermissionDeniedError):
            return ProviderHealth(available=False, detail="Invalid API key")
        except groq_errors.APIStatusError as exc:
            return ProviderHealth(available=False, detail=exc.message)
        except Exception as exc:  # boundary catch: health_check must never raise
            return ProviderHealth(available=False, detail=str(exc))
        return ProviderHealth(available=True, detail="ready")

    @property
    def capabilities(self) -> ProviderCaps:
        return ProviderCaps(tool_calling=True, max_context=131_072, safety_settings=False)


def _to_llm_response(response: Any) -> LLMResponse:
    choice = response.choices[0]
    message = choice.message

    tool_calls = tuple(
        ToolCall(
            call_id=call.id,
            tool_name=call.function.name,
            arguments=json.loads(call.function.arguments) if call.function.arguments else {},
        )
        for call in (message.tool_calls or [])
    )

    finish_reason = _FINISH_REASON_MAP.get(choice.finish_reason, "error")
    if tool_calls:
        finish_reason = "tool_calls"

    usage = response.usage
    token_usage = TokenUsage(
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
    )

    return LLMResponse(
        text=message.content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=token_usage,
    )


def _extract_retry_after(exc: groq_errors.APIStatusError) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
