"""GeminiProvider: the `google-genai` adapter (docs/10 §2.1).

Maps: system prompt -> `system_instruction`; `ChatMessage` history -> `contents` (role
`user`/`model`, tool results as `functionResponse` parts, correlated back to a tool *name*
by scanning the preceding assistant message's `ToolCall`s — Gemini correlates by name, but
`ChatMessage` only carries `tool_call_id`, docs/11 §1); `ToolSchema` -> `function_declarations`
(M2: `tools` is always empty, so the config's `tools` field is omitted entirely rather than
set to an empty list — some SDKs treat "tool mode, zero options" oddly). Safety settings
pinned to the strictest tier for the four standard harm categories (NFR-7); a hard prompt
block raises `SafetyBlocked`, a soft per-candidate safety filter is normalized into a plain
`LLMResponse(finish_reason="safety")` instead (see `agent.agent`'s handling of both cases).

Adapters raise only `core.errors.ProviderError` subtypes — the manager and agent never see a
raw SDK exception (A-4, A-6, docs/10 §1).
"""

from __future__ import annotations

from typing import Literal

from google.genai import Client
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from nova.core.errors import AuthError, ProviderError, RateLimited, SafetyBlocked, Transient
from nova.core.models import ChatMessage, ToolCall, ToolSchema
from nova.providers.base import (
    GenerateOptions,
    LLMProvider,
    LLMResponse,
    ProviderCaps,
    ProviderHealth,
    TokenUsage,
)

_STRICT_SAFETY_SETTINGS = [
    genai_types.SafetySetting(
        category=category, threshold=genai_types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE
    )
    for category in (
        genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    )
]

_SAFETY_FINISH_REASONS = frozenset(
    {
        genai_types.FinishReason.SAFETY,
        genai_types.FinishReason.PROHIBITED_CONTENT,
        genai_types.FinishReason.RECITATION,
        genai_types.FinishReason.SPII,
        genai_types.FinishReason.BLOCKLIST,
    }
)


class GeminiProvider(LLMProvider):
    """Cloud LLM backend for Google Gemini, normalized to `LLMProvider` (docs/10 §2.1)."""

    def __init__(self, api_key: str, model: str) -> None:
        self.name = "gemini"
        self._model = model
        self._client = Client(api_key=api_key)

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema],
        opts: GenerateOptions,
    ) -> LLMResponse:
        system_instruction, contents = _to_gemini_contents(messages)
        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=opts.temperature,
            max_output_tokens=opts.max_tokens,
            safety_settings=_STRICT_SAFETY_SETTINGS,
            http_options=genai_types.HttpOptions(timeout=int(opts.timeout_s * 1000)),
        )
        if tools:
            config.tools = [_to_gemini_tool(tools)]

        try:
            response = self._client.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except genai_errors.ClientError as exc:
            raise _map_client_error(exc) from exc
        except genai_errors.ServerError as exc:
            raise Transient(str(exc.message or exc)) from exc
        except Exception as exc:  # boundary: adapters raise only ProviderError (docs/10 §1)
            raise Transient(f"gemini request failed: {exc}") from exc

        return _to_llm_response(response)

    def health_check(self) -> ProviderHealth:
        try:
            self._client.models.get(model=self._model)
        except genai_errors.ClientError as exc:
            if exc.code in (401, 403):
                return ProviderHealth(available=False, detail="Invalid API key")
            return ProviderHealth(available=False, detail=str(exc.message or exc))
        except Exception as exc:  # boundary catch: health_check must never raise
            return ProviderHealth(available=False, detail=str(exc))
        return ProviderHealth(available=True, detail="ready")

    @property
    def capabilities(self) -> ProviderCaps:
        return ProviderCaps(tool_calling=True, max_context=1_000_000, safety_settings=True)


def _to_gemini_contents(
    messages: list[ChatMessage],
) -> tuple[str | None, list[genai_types.Content]]:
    """Split `messages` into Gemini's separate `system_instruction` + `contents` shape."""
    system_instruction: str | None = None
    contents: list[genai_types.Content] = []
    call_id_to_name: dict[str, str] = {}

    for message in messages:
        if message.role == "system":
            system_instruction = message.content
        elif message.role == "user":
            contents.append(
                genai_types.Content(
                    role="user", parts=[genai_types.Part(text=message.content or "")]
                )
            )
        elif message.role == "assistant":
            parts: list[genai_types.Part] = []
            if message.content:
                parts.append(genai_types.Part(text=message.content))
            for call in message.tool_calls:
                call_id_to_name[call.call_id] = call.tool_name
                parts.append(
                    genai_types.Part(
                        function_call=genai_types.FunctionCall(
                            id=call.call_id, name=call.tool_name, args=call.arguments
                        )
                    )
                )
            contents.append(genai_types.Content(role="model", parts=parts))
        elif message.role == "tool":
            call_id = message.tool_call_id or ""
            name = call_id_to_name.get(call_id, call_id)
            contents.append(
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part(
                            function_response=genai_types.FunctionResponse(
                                id=message.tool_call_id,
                                name=name,
                                response={"result": message.content},
                            )
                        )
                    ],
                )
            )

    return system_instruction, contents


def _to_gemini_tool(tools: list[ToolSchema]) -> genai_types.Tool:
    return genai_types.Tool(
        function_declarations=[
            genai_types.FunctionDeclaration(
                name=tool.name, description=tool.description, parameters=tool.parameters
            )
            for tool in tools
        ]
    )


def _to_llm_response(response: genai_types.GenerateContentResponse) -> LLMResponse:
    if response.prompt_feedback is not None and response.prompt_feedback.block_reason is not None:
        raise SafetyBlocked(f"Gemini blocked the prompt: {response.prompt_feedback.block_reason}")

    candidates = response.candidates or []
    if not candidates:
        raise SafetyBlocked("Gemini returned no candidates")

    candidate = candidates[0]
    parts = (candidate.content.parts if candidate.content else None) or []

    text = "".join(part.text for part in parts if part.text) or None
    tool_calls = tuple(
        ToolCall(
            call_id=part.function_call.id or f"call_{index}",
            tool_name=part.function_call.name or "",
            arguments=part.function_call.args or {},
        )
        for index, part in enumerate(parts)
        if part.function_call is not None
    )

    finish_reason: Literal["stop", "tool_calls", "length", "safety", "error"]
    if tool_calls:
        finish_reason = "tool_calls"
    elif candidate.finish_reason in _SAFETY_FINISH_REASONS:
        finish_reason = "safety"
    elif candidate.finish_reason == genai_types.FinishReason.MAX_TOKENS:
        finish_reason = "length"
    elif candidate.finish_reason in (None, genai_types.FinishReason.STOP):
        finish_reason = "stop"
    else:
        finish_reason = "error"

    usage = response.usage_metadata
    token_usage = TokenUsage(
        input_tokens=(usage.prompt_token_count if usage else None) or 0,
        output_tokens=(usage.candidates_token_count if usage else None) or 0,
    )

    return LLMResponse(
        text=text, tool_calls=tool_calls, finish_reason=finish_reason, usage=token_usage
    )


def _map_client_error(exc: genai_errors.ClientError) -> ProviderError:
    message = str(exc.message or exc)
    if exc.code in (401, 403):
        return AuthError(message, friendly_message="My connection to Gemini needs a fresh key.")
    if exc.code == 429:
        return RateLimited(message, retry_after=_extract_retry_after(exc))
    return Transient(message)


def _extract_retry_after(exc: genai_errors.APIError) -> float | None:
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
