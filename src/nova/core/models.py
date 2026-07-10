"""Typed, immutable data artifacts passed between NOVA's layers.

Frozen dataclasses per TD-10: created often, safe to pass across threads by value, no
validation needed (internal transfer, not an external boundary). Contract source: docs/11 §1.
Changing a shape here is a contract change (P-3): version bump + migration + golden-test
update + docs/11 amendment, in the same PR.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class UserInput:
    """A single user request entering the agent, typed or spoken."""

    request_id: str
    text: str
    source: Literal["voice", "typed"]
    ts: datetime


@dataclass(frozen=True)
class Transcript:
    """Speech-to-text output for a request."""

    request_id: str
    text: str
    confidence: float | None


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation as decided by the LLM — raw, not yet validated by the Executor."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The outcome of executing a ToolCall."""

    call_id: str
    status: Literal["ok", "error", "timeout", "denied"]
    data: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    duration_ms: int


@dataclass(frozen=True)
class AssistantReply:
    """NOVA's response: displayed text and (possibly shortened) spoken text."""

    request_id: str
    text: str
    spoken_text: str


@dataclass(frozen=True)
class ChatMessage:
    """One turn in the message list sent to an LLM provider."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolSchema:
    """A tool's shape as advertised to an LLM provider.

    Lives in `core` (not `providers` or `tools`) because `providers` and `tools` are sibling
    layers that must never import each other (D-2/D-3) yet both need to agree on this shape —
    ARCHITECTURE_RULES.md's decision tree names this exact case. Inert in M2: no tools exist
    yet, so `ProviderManager.generate()` is always called with `tools=()`; this type only
    needs to exist so the `LLMProvider.generate()` signature is real ahead of M3.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ProviderStatus:
    """The active LLM provider's health, for the header status cluster (FR-43).

    Lives in `core`, not `providers/manager.py`, because `ui` imports core only (D-5) — not
    even the ABCs `agent` gets. Putting this here lets `ProviderManager` emit it and
    `MainWindow` receive it without either importing the other; `app.py` wires the one
    connection between them.
    """

    active: str
    mode: Literal["normal", "fallback", "down"]
    detail: str
