"""memory_tool: explicit store/recall of facts & preferences (docs/07 §8).

Writes are additive only — deletion lives exclusively in the Memory View UI (FR-33) and is
deliberately not LLM-invocable in v1.0. Works against the narrow `MemoryFacade` protocol;
M5's real `MemoryService` replaces the in-memory stub wired in M3.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from nova.core.errors import ToolError
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec

_PREFERENCE_MARKERS = ("likes", "favorite", "favourite", "prefers", "loves")


class InMemoryFacade:
    """ponytail: M3 stub so the memory tool is exercisable before M5's MemoryService.

    Facts live only for the process lifetime; keyword recall is a naive word-overlap scan.
    Replaced wholesale by MemoryService in M5 (same protocol).
    """

    def __init__(self) -> None:
        self.facts: list[tuple[str, str]] = []  # (content, kind)

    def add_fact(self, content: str, kind: str) -> None:
        self.facts.append((content, kind))

    def recall(self, query: str) -> list[str]:
        words = {w for w in query.lower().split() if len(w) > 2}
        scored = [
            (len(words & set(content.lower().split())), content) for content, _kind in self.facts
        ]
        return [content for overlap, content in sorted(scored, reverse=True) if overlap > 0][:3]


class MemoryToolParams(BaseModel):
    """Arguments for the memory tool."""

    action: Literal["store", "recall"] = Field(
        description="'store' saves a fact; 'recall' looks one up."
    )
    content: str | None = Field(
        default=None,
        description="For 'store': the fact, in third person, e.g. 'Favorite color is blue'.",
    )
    query: str | None = Field(
        default=None, description="For 'recall': words to look up, e.g. 'favorite color'."
    )


class MemoryTool(Tool):
    """Makes memory a visible tool choice (EO-5, US-10)."""

    spec = ToolSpec(
        name="memory_tool",
        title="Memory",
        description=(
            "Remember a fact about the user, or recall one. Use 'store' when the user asks "
            "you to remember something ('remember my favorite color is blue'), and 'recall' "
            "when they ask what you remember ('what's my favorite color?')."
        ),
        parameters=MemoryToolParams,
        sensitive=False,
        icon="brain",
        detail_template="Checking my memory",
    )

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        assert isinstance(args, MemoryToolParams)
        memory = ctx.memory
        if memory is None:
            raise ToolError("My memory isn't set up right now.", code="storage_error")

        if args.action == "store":
            content = (args.content or "").strip()
            if not content:
                raise ToolError(
                    "There was nothing to store — ask the user what to remember.",
                    code="storage_error",
                )
            kind = (
                "preference"
                if any(marker in content.lower() for marker in _PREFERENCE_MARKERS)
                else "fact"
            )
            try:
                memory.add_fact(content, kind)
            except Exception as exc:
                raise ToolError(f"Couldn't save that: {exc}", code="storage_error") from exc
            return ToolOutput(data={"stored": True, "kind": kind, "summary": "I'll remember that!"})

        query = (args.query or "").strip()
        memories: list[str] = memory.recall(query) if query else []
        if not memories:
            raise ToolError(
                f"I don't have anything remembered about {query!r}. Tell the user honestly.",
                code="nothing_found",
            )
        return ToolOutput(
            data={
                "memories": memories,
                "summary": f"I remember: {memories[0]}",
            }
        )
