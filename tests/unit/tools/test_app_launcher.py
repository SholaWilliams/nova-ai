"""app_launcher: alias -> start menu -> PATH resolution order + errors (docs/07 §4)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nova.core.errors import ToolError
from nova.tools.app_launcher import AppLauncherParams, AppLauncherTool
from nova.tools.base import ToolContext


class _Launcher:
    def __init__(self, fail: bool = False) -> None:
        self.targets: list[str] = []
        self._fail = fail

    def __call__(self, target: str) -> None:
        if self._fail:
            raise OSError("access denied")
        self.targets.append(target)


def _tool(tmp_path: Path, launcher: _Launcher) -> AppLauncherTool:
    return AppLauncherTool(start_menu_dirs=[tmp_path], launcher=launcher)


def test_alias_hit(ctx: ToolContext, tmp_path: Path) -> None:
    launcher = _Launcher()
    data = _tool(tmp_path, launcher).execute(AppLauncherParams(app_name="Notepad"), ctx).data
    assert launcher.targets == ["notepad.exe"]
    assert data == {
        "launched": True,
        "app_title": "Notepad",
        "matched_via": "alias",
        "summary": "Opening Notepad",
    }


def test_start_menu_fuzzy_match(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    lnk = tmp_path / "sub" / "Minecraft Launcher.lnk"
    lnk.touch()
    launcher = _Launcher()
    data = _tool(tmp_path, launcher).execute(AppLauncherParams(app_name="minecraft"), ctx).data
    assert data["matched_via"] == "startmenu"
    assert launcher.targets == [str(lnk)]


def test_path_fallback(ctx: ToolContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: r"C:\Tools\mytool.exe")
    launcher = _Launcher()
    data = _tool(tmp_path, launcher).execute(AppLauncherParams(app_name="mytool"), ctx).data
    assert data["matched_via"] == "path"
    assert launcher.targets == [r"C:\Tools\mytool.exe"]


def test_not_found_offers_closest_matches(
    ctx: ToolContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ToolError) as excinfo:
        _tool(tmp_path, _Launcher()).execute(AppLauncherParams(app_name="notepda"), ctx)
    assert excinfo.value.code == "app_not_found"
    assert "notepad" in str(excinfo.value)  # closest-match hint for the LLM


def test_launch_failed(ctx: ToolContext, tmp_path: Path) -> None:
    with pytest.raises(ToolError) as excinfo:
        _tool(tmp_path, _Launcher(fail=True)).execute(AppLauncherParams(app_name="paint"), ctx)
    assert excinfo.value.code == "launch_failed"
