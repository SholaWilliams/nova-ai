"""Planner: assembles the provider-ready message list (docs/06 §2.1, §3).

Order: system prompt -> trimmed history -> user input. Memory-context injection (docs/06
§2.1 step 2) is a stub until `MemoryService` exists (M5) — `Agent` simply doesn't pass one
yet. Thinking-summary extraction (FR-18) is deferred wholesale to M3: it needs a `ToolSpec`
to synthesize a fallback summary from, and has no exercisable input while no tool call ever
happens (M2 has no tools).
"""

from __future__ import annotations

import importlib.resources
from collections.abc import Sequence

from nova.core.models import ChatMessage, UserInput


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
