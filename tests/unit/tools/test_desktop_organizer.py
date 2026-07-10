"""desktop_organizer: plan/preview/act/undo with manifest — move, never delete (docs/07 §7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova.core.errors import ToolError
from nova.tools.base import ToolContext
from nova.tools.desktop_organizer import DesktopOrganizerParams, DesktopOrganizerTool


@pytest.fixture
def desktop(tmp_path: Path) -> Path:
    d = tmp_path / "Desktop"
    d.mkdir()
    (d / "photo.png").write_text("img")
    (d / "essay.docx").write_text("doc")
    (d / "song.mp3").write_text("mp3")
    (d / "weird.xyz").write_text("?")
    (d / "shortcut.lnk").write_text("lnk")  # never touched
    (d / ".hidden").write_text("h")  # never touched
    (d / "AFolder").mkdir()  # never touched
    return d


@pytest.fixture
def tool(desktop: Path, tmp_path: Path) -> DesktopOrganizerTool:
    return DesktopOrganizerTool(desktop=desktop, manifest_dir=tmp_path / "data")


def test_preview_lines_cover_only_loose_files(tool: DesktopOrganizerTool, ctx: ToolContext) -> None:
    lines = tool.preview(DesktopOrganizerParams(mode="organize"), ctx)
    assert sorted(lines) == [
        "Move essay.docx into Documents",
        "Move photo.png into Pictures",
        "Move song.mp3 into Music",
        "Move weird.xyz into Other",
    ]


def test_organize_moves_and_writes_manifest(
    tool: DesktopOrganizerTool, desktop: Path, tmp_path: Path, ctx: ToolContext
) -> None:
    data = tool.execute(DesktopOrganizerParams(mode="organize"), ctx).data
    assert data["moved"] == 4
    assert data["categories"] == {"Pictures": 1, "Documents": 1, "Music": 1, "Other": 1}
    assert (desktop / "Pictures" / "photo.png").is_file()
    assert (desktop / "shortcut.lnk").is_file()  # untouched
    assert (desktop / "AFolder").is_dir()  # untouched
    manifest = json.loads((tmp_path / "data" / "undo_manifest.json").read_text())
    assert len(manifest["moves"]) == 4


def test_collision_gets_numbered_suffix(
    tool: DesktopOrganizerTool, desktop: Path, ctx: ToolContext
) -> None:
    (desktop / "Pictures").mkdir()
    (desktop / "Pictures" / "photo.png").write_text("already there")
    tool.execute(DesktopOrganizerParams(mode="organize"), ctx)
    assert (desktop / "Pictures" / "photo (2).png").is_file()


def test_undo_restores_files(tool: DesktopOrganizerTool, desktop: Path, ctx: ToolContext) -> None:
    tool.execute(DesktopOrganizerParams(mode="organize"), ctx)
    data = tool.execute(DesktopOrganizerParams(mode="undo"), ctx).data
    assert data["moved"] == 4
    assert (desktop / "photo.png").is_file()
    assert not (desktop / "Pictures").exists()  # empty category folder tidied away


def test_undo_reports_files_moved_since(
    tool: DesktopOrganizerTool, desktop: Path, ctx: ToolContext
) -> None:
    tool.execute(DesktopOrganizerParams(mode="organize"), ctx)
    (desktop / "Music" / "song.mp3").unlink()  # user moved it elsewhere meanwhile
    data = tool.execute(DesktopOrganizerParams(mode="undo"), ctx).data
    assert data["moved"] == 3
    assert data["not_restored"] == ["song.mp3"]


def test_nothing_to_do(tmp_path: Path, ctx: ToolContext) -> None:
    empty = tmp_path / "EmptyDesktop"
    empty.mkdir()
    tool = DesktopOrganizerTool(desktop=empty, manifest_dir=tmp_path / "data")
    with pytest.raises(ToolError) as excinfo:
        tool.execute(DesktopOrganizerParams(mode="organize"), ctx)
    assert excinfo.value.code == "nothing_to_do"


def test_no_undo_available(tool: DesktopOrganizerTool, ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        tool.execute(DesktopOrganizerParams(mode="undo"), ctx)
    assert excinfo.value.code == "no_undo_available"


def test_preview_mode_moves_nothing(
    tool: DesktopOrganizerTool, desktop: Path, ctx: ToolContext
) -> None:
    data = tool.execute(DesktopOrganizerParams(mode="preview"), ctx).data
    assert data["moved"] == 0
    assert (desktop / "photo.png").is_file()


def test_spec_is_sensitive() -> None:
    """FR-20: the organizer is the gated tool — never accidentally un-gate it."""
    assert DesktopOrganizerTool.spec.sensitive is True
