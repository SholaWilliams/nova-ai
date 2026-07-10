"""file_search: bounded, read-only search over named folders (docs/07 §6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nova.core.errors import ToolError
from nova.tools.base import ToolContext
from nova.tools.file_search import FileSearchParams, FileSearchTool


@pytest.fixture
def folders(tmp_path: Path) -> dict[str, Path]:
    docs = tmp_path / "Documents"
    desktop = tmp_path / "Desktop"
    docs.mkdir()
    desktop.mkdir()
    (docs / "dragon drawing.png").write_bytes(b"x" * 2048)
    (docs / "homework.docx").touch()
    (docs / ".hidden-dragon.png").touch()
    (desktop / "dragon photo.jpg").touch()
    return {
        "documents": docs,
        "desktop": desktop,
        "downloads": tmp_path / "nope",
        "pictures": tmp_path / "nope2",
    }


def test_substring_match_across_locations(ctx: ToolContext, folders: dict[str, Path]) -> None:
    data = FileSearchTool(folders).execute(FileSearchParams(query="dragon"), ctx).data
    names = {m["name"] for m in data["matches"]}
    assert names == {"dragon drawing.png", "dragon photo.jpg"}  # hidden file excluded
    assert data["count"] == 2
    assert "2 files" in data["summary"]


def test_type_filter(ctx: ToolContext, folders: dict[str, Path]) -> None:
    data = (
        FileSearchTool(folders).execute(FileSearchParams(query="dragon", file_type="jpg"), ctx).data
    )
    assert [m["name"] for m in data["matches"]] == ["dragon photo.jpg"]


def test_type_alias_image(ctx: ToolContext, folders: dict[str, Path]) -> None:
    data = (
        FileSearchTool(folders)
        .execute(FileSearchParams(query="dragon", file_type="image"), ctx)
        .data
    )
    assert {m["name"] for m in data["matches"]} == {"dragon drawing.png", "dragon photo.jpg"}


def test_single_location(ctx: ToolContext, folders: dict[str, Path]) -> None:
    data = (
        FileSearchTool(folders)
        .execute(FileSearchParams(query="dragon", location="desktop"), ctx)
        .data
    )
    assert [m["name"] for m in data["matches"]] == ["dragon photo.jpg"]


def test_no_matches(ctx: ToolContext, folders: dict[str, Path]) -> None:
    with pytest.raises(ToolError) as excinfo:
        FileSearchTool(folders).execute(FileSearchParams(query="unicorn"), ctx)
    assert excinfo.value.code == "no_matches"


def test_location_unavailable(ctx: ToolContext, folders: dict[str, Path]) -> None:
    with pytest.raises(ToolError) as excinfo:
        FileSearchTool(folders).execute(FileSearchParams(query="dragon", location="downloads"), ctx)
    assert excinfo.value.code == "location_unavailable"


def test_depth_bound(ctx: ToolContext, tmp_path: Path) -> None:
    deep = tmp_path / "Documents"
    current = deep
    for i in range(8):
        current = current / f"level{i}"
    current.mkdir(parents=True)
    (current / "deep-dragon.txt").touch()
    folders = {
        "documents": deep,
        "desktop": tmp_path / "x",
        "downloads": tmp_path / "y",
        "pictures": tmp_path / "z",
    }
    with pytest.raises(ToolError) as excinfo:
        FileSearchTool(folders).execute(FileSearchParams(query="dragon"), ctx)
    assert excinfo.value.code == "no_matches"  # beyond depth 6 -> never seen
