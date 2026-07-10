"""Planner: assembles the provider-ready message list (docs/06 §2.1, §3).

Order: system prompt -> trimmed history -> user input. Memory-context injection (docs/06
§2.1 step 2) is a stub until `MemoryService` exists (M5) — `Agent` simply doesn't pass one
yet. Thinking-summary extraction (FR-18) lives here too (`thinking_summary`), used by the
Agent at every SELECTING_TOOL emission.
"""

from __future__ import annotations

import importlib.resources
import re
from collections.abc import Sequence

from nova.core.models import ChatMessage, UserInput

_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def thinking_summary(prose: str | None, tool_title: str) -> str:
    """FR-18: the child-readable one-liner shown at SELECTING_TOOL.

    Providers can return prose alongside tool calls; the first sentence of that prose is
    the summary. If the model returned none, synthesize one from the tool spec — honest
    either way, since it describes the actual chosen action (NG-9).
    """
    if prose and prose.strip():
        return _SENTENCE_END.split(prose.strip(), maxsplit=1)[0]
    return f"I'll use the {tool_title} to help with this."


def load_system_prompt() -> str:
    """Read the versioned system prompt (docs/06 §3) bundled with the package."""
    return (
        importlib.resources.files("nova.agent.prompts")
        .joinpath("system.md")
        .read_text(encoding="utf-8")
    )


class Planner:
    """Builds the message list sent to `ProviderManager.generate()` for one turn."""

    def __init__(self, system_prompt: str) -> None:
        self._system_prompt = system_prompt

    def build(self, user_input: UserInput, history: Sequence[ChatMessage]) -> list[ChatMessage]:
        """Assemble one turn's message list: system prompt, trimmed history, user input."""
        return [
            ChatMessage(role="system", content=self._system_prompt),
            *history,
            ChatMessage(role="user", content=user_input.text),
        ]
