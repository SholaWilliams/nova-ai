"""memory_tool: store/recall against the M3 in-memory facade (docs/07 §8)."""

from __future__ import annotations

import pytest

from nova.core.config import Settings
from nova.core.errors import ToolError
from nova.tools.base import ToolContext
from nova.tools.memory_tool import InMemoryFacade, MemoryTool, MemoryToolParams


@pytest.fixture
def facade() -> InMemoryFacade:
    return InMemoryFacade()


@pytest.fixture
def mem_ctx(facade: InMemoryFacade) -> ToolContext:
    return ToolContext(settings=Settings(), memory=facade)


def test_store_fact(mem_ctx: ToolContext, facade: InMemoryFacade) -> None:
    data = (
        MemoryTool()
        .execute(MemoryToolParams(action="store", content="Has a dog named Rex"), mem_ctx)
        .data
    )
    assert data["stored"] is True
    assert data["kind"] == "fact"
    assert facade.facts == [("Has a dog named Rex", "fact")]


def test_store_preference_kind_heuristic(mem_ctx: ToolContext, facade: InMemoryFacade) -> None:
    MemoryTool().execute(
        MemoryToolParams(action="store", content="Favorite color is blue"), mem_ctx
    )
    assert facade.facts[0][1] == "preference"


def test_store_empty_content(mem_ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        MemoryTool().execute(MemoryToolParams(action="store", content="  "), mem_ctx)
    assert excinfo.value.code == "storage_error"


def test_recall_hit(mem_ctx: ToolContext, facade: InMemoryFacade) -> None:
    facade.add_fact("Favorite color is blue", "preference")
    data = (
        MemoryTool()
        .execute(MemoryToolParams(action="recall", query="favorite color"), mem_ctx)
        .data
    )
    assert data["memories"] == ["Favorite color is blue"]


def test_recall_miss_is_honest(mem_ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        MemoryTool().execute(MemoryToolParams(action="recall", query="favorite food"), mem_ctx)
    assert excinfo.value.code == "nothing_found"


def test_no_facade_wired(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        MemoryTool().execute(MemoryToolParams(action="recall", query="anything"), ctx)
    assert excinfo.value.code == "storage_error"
