"""file_opener: NFR-6 folder gating + open/error paths (docs/07 §7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nova.core.errors import ToolError
from nova.tools.base import ToolContext
from nova.tools.file_opener import FileOpenerParams, FileOpenerTool


class _Launcher:
    def __init__(self, fail: bool = False) -> None:
        self.targets: list[str] = []
        self._fail = fail

    def __call__(self, target: str) -> None:
        if self._fail:
            raise OSError("access denied")
        self.targets.append(target)


def _tool(allowed: Path, launcher: _Launcher) -> FileOpenerTool:
    return FileOpenerTool(allowed_folders={"downloads": allowed}, launcher=launcher)


def test_opens_file_within_allowed_folder(ctx: ToolContext, tmp_path: Path) -> None:
    target = tmp_path / "Pole Upload Tracker.xlsx"
    target.write_text("data")
    launcher = _Launcher()

    data = (
        _tool(tmp_path, launcher)
        .execute(FileOpenerParams(folder=str(tmp_path), name="Pole Upload Tracker.xlsx"), ctx)
        .data
    )

    assert launcher.targets == [str(target)]
    assert data == {
        "opened": True,
        "path": str(target),
        "summary": "Opening Pole Upload Tracker.xlsx",
    }


def test_rejects_path_outside_allowed_folders(ctx: ToolContext, tmp_path: Path) -> None:
    allowed = tmp_path / "downloads"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secrets.txt").write_text("nope")

    with pytest.raises(ToolError) as excinfo:
        _tool(allowed, _Launcher()).execute(
            FileOpenerParams(folder=str(outside), name="secrets.txt"), ctx
        )
    assert excinfo.value.code == "location_unavailable"


def test_rejects_traversal_out_of_allowed_folder(ctx: ToolContext, tmp_path: Path) -> None:
    allowed = tmp_path / "downloads"
    allowed.mkdir()
    (tmp_path / "secrets.txt").write_text("nope")

    with pytest.raises(ToolError) as excinfo:
        _tool(allowed, _Launcher()).execute(
            FileOpenerParams(folder=str(allowed), name="../secrets.txt"), ctx
        )
    assert excinfo.value.code == "location_unavailable"


def test_file_missing(ctx: ToolContext, tmp_path: Path) -> None:
    with pytest.raises(ToolError) as excinfo:
        _tool(tmp_path, _Launcher()).execute(
            FileOpenerParams(folder=str(tmp_path), name="ghost.xlsx"), ctx
        )
    assert excinfo.value.code == "file_not_found"


def test_open_failed(ctx: ToolContext, tmp_path: Path) -> None:
    target = tmp_path / "locked.xlsx"
    target.write_text("data")

    with pytest.raises(ToolError) as excinfo:
        _tool(tmp_path, _Launcher(fail=True)).execute(
            FileOpenerParams(folder=str(tmp_path), name="locked.xlsx"), ctx
        )
    assert excinfo.value.code == "open_failed"
