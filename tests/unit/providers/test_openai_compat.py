"""Tests for `_openai_compat.py`'s shared request-side mapping (docs/10 §2.2).

Provider-independent: `to_openai_message`/`to_openai_tool` are pure functions consumed by
`OmniRouteProvider` (M9's sole LLM adapter). Previously exercised inside `test_groq.py`
(deleted at M9, alongside `GroqProvider`'s chat usage) — moved to a dedicated file since the
mapping itself has no per-adapter behavior worth re-testing per consumer.
"""

from __future__ import annotations

import json

from nova.core.models import ChatMessage, ToolCall, ToolSchema
from nova.providers._openai_compat import to_openai_message, to_openai_tool


def test_plain_messages_map_role_and_content() -> None:
    assert to_openai_message(ChatMessage(role="user", content="hi")) == {
        "role": "user",
        "content": "hi",
    }
    assert to_openai_message(ChatMessage(role="system", content="be nice")) == {
        "role": "system",
        "content": "be nice",
    }


def test_tool_message_carries_tool_call_id() -> None:
    message = to_openai_message(
        ChatMessage(role="tool", content="unknown tool", tool_call_id="call_1")
    )

    assert message == {"role": "tool", "content": "unknown tool", "tool_call_id": "call_1"}


def test_assistant_message_with_tool_calls_serializes_arguments_as_json_string() -> None:
    call = ToolCall(call_id="call_1", tool_name="weather", arguments={"city": "Lagos"})

    message = to_openai_message(ChatMessage(role="assistant", content=None, tool_calls=(call,)))

    assert message["role"] == "assistant"
    assert message["tool_calls"][0]["id"] == "call_1"
    assert message["tool_calls"][0]["function"]["name"] == "weather"
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"city": "Lagos"}


def test_tool_schema_maps_to_function_definition() -> None:
    schema = ToolSchema(
        name="weather",
        description="get weather",
        parameters={"type": "object"},
    )

    tool = to_openai_tool(schema)

    assert tool == {
        "type": "function",
        "function": {
            "name": "weather",
            "description": "get weather",
            "parameters": {"type": "object"},
        },
    }
