"""ToolRegistry + the schema-drift golden test (docs/11 §7, T-301).

The golden fixture freezes the LLM-facing JSON Schemas of all seven v1.0 tools. A params
change that isn't a deliberate contract change fails here; a deliberate one regenerates the
golden with `pytest -m record tests/unit/tools/test_registry.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from nova.tools.app_launcher import AppLauncherTool
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec
from nova.tools.browser import BrowserTool
from nova.tools.calculator import CalculatorTool
from nova.tools.desktop_organizer import DesktopOrganizerTool
from nova.tools.file_search import FileSearchTool
from nova.tools.memory_tool import MemoryTool
from nova.tools.registry import ToolRegistry
from nova.tools.weather import WeatherTool

_GOLDEN = Path(__file__).parents[2] / "fixtures" / "tools" / "schemas.json"


def _full_registry(tmp_path: Path) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(WeatherTool())
    registry.register(BrowserTool())
    registry.register(AppLauncherTool(start_menu_dirs=[]))
    registry.register(FileSearchTool())
    registry.register(DesktopOrganizerTool(desktop=tmp_path, manifest_dir=tmp_path))
    registry.register(MemoryTool())
    return registry


class _EchoParams(BaseModel):
    text: str


class _EchoTool(Tool):
    spec = ToolSpec(
        name="echo",
        title="Echo",
        description="Repeats things.",
        parameters=_EchoParams,
        icon="volume-2",
        detail_template="Echoing {text}",
    )

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        assert isinstance(args, _EchoParams)
        return ToolOutput(data={"summary": args.text})


def test_register_and_get() -> None:
    registry = ToolRegistry()
    tool = _EchoTool()
    registry.register(tool)
    assert registry.get("echo") is tool
    assert registry.get("nope") is None
    assert registry.names == frozenset({"echo"})


def test_duplicate_registration_raises() -> None:
    registry = ToolRegistry()
    registry.register(_EchoTool())
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(_EchoTool())


def test_schemas_shape() -> None:
    registry = ToolRegistry()
    registry.register(_EchoTool())
    [schema] = registry.schemas()
    assert schema.name == "echo"
    assert schema.parameters["type"] == "object"
    assert schema.parameters["required"] == ["text"]
    assert "title" not in schema.parameters  # stripped noise


def test_output_requires_summary() -> None:
    with pytest.raises(ValueError):
        ToolOutput(data={"result": 1})


def test_all_seven_schemas_match_golden(tmp_path: Path) -> None:
    generated = {
        s.name: {"description": s.description, "parameters": s.parameters}
        for s in _full_registry(tmp_path).schemas()
    }
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert generated == golden, (
        "Tool schemas drifted from the committed golden. If this is a deliberate contract "
        "change (P-3): version-bump docs/11, then regenerate with `pytest -m record`."
    )


@pytest.mark.record
def test_record_golden(tmp_path: Path) -> None:
    generated = {
        s.name: {"description": s.description, "parameters": s.parameters}
        for s in _full_registry(tmp_path).schemas()
    }
    _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    _GOLDEN.write_text(json.dumps(generated, indent=2, sort_keys=True), encoding="utf-8")
