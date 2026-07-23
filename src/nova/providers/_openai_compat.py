"""Shared request-side mapping for OpenAI-Chat-Completions-dialect providers (docs/10 §2.3).

Groq and OpenRouter both speak this dialect for the *request* shape (messages/tools) — this
module is the one place that mapping is written. Response *parsing* stays per-adapter: Groq
reads the `groq` SDK's Pydantic response types, OpenRouter reads a plain JSON dict from httpx,
different enough that sharing a parser would force an unneeded abstraction over both.
"""

from __future__ import annotations

import json
from typing import Any

from nova.core.models import ChatMessage, ToolSchema


def to_openai_message(message: ChatMessage) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "tool",
            "content": message.content or "",
            "tool_call_id": message.tool_call_id or "",
        }
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.tool_name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.content or ""}


def to_openai_tool(tool: ToolSchema) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
