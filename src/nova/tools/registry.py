"""ToolRegistry: name -> Tool lookup + LLM-facing schema generation (docs/11 §3).

Schemas are generated from each tool's Pydantic params model and cached — the schema-drift
golden test (docs/11 §7) diffs these against committed fixtures, so a params change that
isn't a deliberate contract change fails CI.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from nova.core.models import ToolSchema
from nova.tools.base import Tool


def _json_schema_for(params_model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema, stripped of the noise LLM providers don't want (titles)."""
    schema = params_model.model_json_schema()

    def strip_titles(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip_titles(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [strip_titles(item) for item in node]
        return node

    return strip_titles(schema)


class ToolRegistry:
    """All registered tools, keyed by spec name. `register()` raises on duplicates."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._schemas: list[ToolSchema] | None = None

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"duplicate tool name: {name!r}")
        self._tools[name] = tool
        self._schemas = None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def schemas(self) -> list[ToolSchema]:
        """LLM-facing schemas for every registered tool, in registration order. Cached."""
        if self._schemas is None:
            self._schemas = [
                ToolSchema(
                    name=tool.spec.name,
                    description=tool.spec.description,
                    parameters=_json_schema_for(tool.spec.parameters),
                )
                for tool in self._tools.values()
            ]
        return self._schemas
