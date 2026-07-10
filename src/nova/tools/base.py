"""Tool contract: `ToolSpec`, `Tool` ABC, `ToolContext`, `ToolOutput` (docs/11 §3, docs/07 §1).

Tools are the only code that touches Windows on the LLM's behalf, and they do so *only*
after the Executor has validated the call (rule 1). Tools import `core` only (D-3) — never
agent, providers, or ui. Failures are raised as `core.errors.ToolError(message, code=...)`;
the Executor normalizes every outcome into a `ToolResult`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, field_validator

from nova.core.config import Settings

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")


@runtime_checkable
class MemoryFacade(Protocol):
    """The narrow memory surface the memory tool needs (docs/11 §3 `ToolContext.memory`).

    M5's real `MemoryService` satisfies this structurally; M3 wires an in-memory stub.
    """

    def add_fact(self, content: str, kind: str) -> None: ...

    def recall(self, query: str) -> list[str]: ...


class ToolContext(BaseModel):
    """Read-only context handed to every `execute()` call (docs/07 §1)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    settings: Settings
    memory: Any = None  # MemoryFacade, injected only for memory_tool (D-3)


class ToolOutput(BaseModel):
    """A successful tool result. `data` MUST include a `summary` string the LLM can speak."""

    data: dict[str, Any]

    @field_validator("data")
    @classmethod
    def _must_have_summary(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value.get("summary"), str) or not value["summary"]:
            raise ValueError("tool output data must include a non-empty 'summary' string")
        return value


class ToolSpec(BaseModel):
    """A tool's identity and shape (docs/11 §3). `description` is written for the LLM."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    title: str
    description: str
    parameters: type[BaseModel]
    sensitive: bool = False
    icon: str
    detail_template: str

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(f"tool name {value!r} must match {_NAME_RE.pattern}")
        return value


class Tool(ABC):
    """One capability the LLM can choose. Synchronous, ≤ tool_timeout_s, never deletes."""

    spec: ToolSpec

    @abstractmethod
    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        """Run the tool. Raise `core.errors.ToolError(message, code=...)` on failure —
        the Executor normalizes it; nothing propagates past the Executor."""
        raise NotImplementedError

    def preview(self, args: BaseModel, ctx: ToolContext) -> list[str]:
        """Plain-language lines shown in the confirmation dialog (sensitive tools only).

        Non-sensitive tools never have this called; the default suffices for sensitive
        tools whose `detail_template` alone describes the action.
        """
        del args, ctx
        return []
