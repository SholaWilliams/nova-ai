"""Router: classifies a normalized LLMResponse into a route (docs/06 §2.2).

Validates structure only (does the tool name exist) — semantic/schema validation of
arguments is the Executor's job (FR-16), which doesn't exist until M3. `known_tool_names`
defaults to empty: in M2 there are no tools, so *any* tool call at all is structurally
unknown and falls into `RepairRoute` — the defensive path for a provider that hallucinates a
call despite receiving an empty tools list (adapters omit the `tools` parameter entirely
when empty, so this should be rare, but the Router can't assume providers behave).
"""

from __future__ import annotations

from dataclasses import dataclass

from nova.core.models import ToolCall
from nova.providers.base import LLMResponse


@dataclass(frozen=True)
class DirectAnswer:
    """The response is final text — no tool call, compose the reply and stop looping."""

    text: str


@dataclass(frozen=True)
class ToolRoute:
    """The response is one or more structurally valid tool calls (all known tool names)."""

    calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class RepairRoute:
    """The response referenced an unknown tool. `reason` is fed back to the LLM verbatim
    as a corrective tool-error message (docs/06 §6): "unknown tool X. Choose from: …".
    """

    reason: str


type Route = DirectAnswer | ToolRoute | RepairRoute


class Router:
    """Classifies each `LLMResponse` into a `Route` (docs/06 §2.2)."""

    def __init__(self, known_tool_names: frozenset[str] = frozenset()) -> None:
        self._known_tool_names = known_tool_names

    def route(self, response: LLMResponse) -> Route:
        if not response.tool_calls:
            return DirectAnswer(text=response.text or "")

        unknown = sorted({call.tool_name for call in response.tool_calls} - self._known_tool_names)
        if unknown:
            known = ", ".join(sorted(self._known_tool_names)) or "no tools are available"
            return RepairRoute(
                reason=f"Unknown tool(s): {', '.join(unknown)}. Choose from: {known}."
            )

        return ToolRoute(calls=response.tool_calls)
