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
class AudioDeviceInfo:
    """One enumerated input/output audio device (docs/08 §5, FR-12).

    Lives in `core`, not `speech`, for the same reason as `ProviderStatus`: `ui` needs this
    shape for the Settings device dropdowns but can never import `speech` (D-5) — `speech`
    and `ui` are sibling/parent layers that must agree on a shape without either importing
    the other (ARCHITECTURE_RULES.md's "cross-layer data shape" row).
    """

    index: int
    name: str


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


@dataclass(frozen=True)
class MemoryItem:
    """One stored fact or preference (docs/09 §3 `facts.json`, M5).

    Lives in `core`, not `memory/`, because `ui` needs this shape for the Memory View
    (FR-32/33) but can never import `memory` (D-5) — same reasoning as `ProviderStatus`/
    `AudioDeviceInfo`. Deferred from M2 ("docs/03 §7.2 additionally lists MemoryItem... to
    the agent/memory milestones that actually produce them" — M5 is that milestone).
    """

    id: str
    kind: Literal["fact", "preference"]
    content: str
    keywords: tuple[str, ...]
    created_at: datetime
    source_request: str


@dataclass(frozen=True)
class ToolCallRecord:
    """One tool invocation as archived in a session's `stages`/`tools` record (docs/09 §3)."""

    name: str
    args: dict[str, Any]
    status: Literal["ok", "error", "timeout", "denied"]
    duration_ms: int


@dataclass(frozen=True)
class TurnRecord:
    """One conversation turn, archived to a session `.jsonl` file (docs/09 §3).

    `stages` is `(stage_name, duration_ms)` pairs in emission order — the raw material for
    History's replay (FR-40 extension). Conversation persistence is automatic and silent
    (a different lifecycle than explicit fact writes, docs/09 §1) — this record has no
    corresponding pipeline event of its own.
    """

    request_id: str
    ts: datetime
    user_text: str
    user_source: Literal["voice", "typed"]
    assistant_text: str
    tools: tuple[ToolCallRecord, ...]
    stages: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class SessionMeta:
    """One entry in the History drawer's session list (docs/09 §3 `index.json`, FR-5/6)."""

    session_id: str
    started_at: datetime
    title: str
    turns: int


@dataclass(frozen=True)
class MemoryContext:
    """What the Planner injects as the labeled "Things you remember about this user" block
    (docs/09 §5). `preferences` (kind="preference" facts, always included) and `facts` (top-
    scored kind="fact" facts) are kept separate only so the Planner can label/order them;
    both are plain content strings, already trimmed to the retrieval budget.
    """

    preferences: tuple[str, ...]
    facts: tuple[str, ...]

    def is_empty(self) -> bool:
        return not self.preferences and not self.facts
