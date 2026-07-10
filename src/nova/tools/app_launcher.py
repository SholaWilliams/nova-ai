"""app_launcher: launch installed apps by common name (docs/07 §4).

Resolution order: curated alias map -> Start Menu .lnk index (fuzzy >= 0.75) ->
`shutil.which`. Launch via `os.startfile` — never a shell string (A-1). No kill/close
capability exists (that would be sensitive and is out of v1.0).
"""

from __future__ import annotations

import difflib
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from nova.core.errors import ToolError
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec

_FUZZY_CUTOFF = 0.75

# Curated aliases: common child phrasings -> (display title, os.startfile target).
# Targets are exe names resolvable from PATH/App Paths or ms-* / shell URIs — never
# shell command strings.
_ALIASES: dict[str, tuple[str, str]] = {
    "notepad": ("Notepad", "notepad.exe"),
    "calculator": ("Calculator", "calc.exe"),
    "calc": ("Calculator", "calc.exe"),
    "paint": ("Paint", "mspaint.exe"),
    "mspaint": ("Paint", "mspaint.exe"),
    "explorer": ("File Explorer", "explorer.exe"),
    "files": ("File Explorer", "explorer.exe"),
    "file explorer": ("File Explorer", "explorer.exe"),
    "edge": ("Microsoft Edge", "msedge.exe"),
    "microsoft edge": ("Microsoft Edge", "msedge.exe"),
    "browser": ("Microsoft Edge", "msedge.exe"),
    "wordpad": ("WordPad", "wordpad.exe"),
    "word": ("Microsoft Word", "winword.exe"),
    "excel": ("Microsoft Excel", "excel.exe"),
    "powerpoint": ("Microsoft PowerPoint", "powerpnt.exe"),
    "chrome": ("Google Chrome", "chrome.exe"),
    "google chrome": ("Google Chrome", "chrome.exe"),
    "firefox": ("Firefox", "firefox.exe"),
    "settings": ("Windows Settings", "ms-settings:"),
    "camera": ("Camera", "microsoft.windows.camera:"),
    "snipping tool": ("Snipping Tool", "snippingtool.exe"),
    "task manager": ("Task Manager", "taskmgr.exe"),
    "cmd": ("Command Prompt", "cmd.exe"),
    "command prompt": ("Command Prompt", "cmd.exe"),
    "terminal": ("Terminal", "wt.exe"),
    "vlc": ("VLC", "vlc.exe"),
    "spotify": ("Spotify", "spotify.exe"),
}


def _default_start_menu_dirs() -> list[Path]:
    dirs = []
    program_data = os.environ.get("PROGRAMDATA")
    appdata = os.environ.get("APPDATA")
    if program_data:
        dirs.append(Path(program_data) / "Microsoft/Windows/Start Menu/Programs")
    if appdata:
        dirs.append(Path(appdata) / "Microsoft/Windows/Start Menu/Programs")
    return dirs


class AppLauncherParams(BaseModel):
    """Arguments for the app launcher tool."""

    app_name: str = Field(description="The app's common name, e.g. 'notepad' or 'paint'.")


class AppLauncherTool(Tool):
    """Alias map, then Start Menu shortcut index, then PATH lookup."""

    spec = ToolSpec(
        name="app_launcher",
        title="App Launcher",
        description=(
            "Open an app installed on this computer. Use when the user asks to open or "
            "start a program, e.g. 'open notepad' or 'start paint'."
        ),
        parameters=AppLauncherParams,
        sensitive=False,
        icon="rocket",
        detail_template="Opening {app_name} on your PC",
    )

    def __init__(
        self,
        start_menu_dirs: list[Path] | None = None,
        launcher: Callable[[str], None] | None = None,
    ) -> None:
        self._start_menu_dirs = (
            start_menu_dirs if start_menu_dirs is not None else _default_start_menu_dirs()
        )
        self._launcher = launcher or os.startfile  # type: ignore[attr-defined]
        # ponytail: index built lazily on first call, not at startup — keeps app boot
        # instant; first launch request pays the one-time scan (~tens of ms).
        self._lnk_index: dict[str, Path] | None = None

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        del ctx
        assert isinstance(args, AppLauncherParams)
        wanted = args.app_name.strip().lower()
        if not wanted:
            raise ToolError("No app name was given.", code="app_not_found")

        alias = _ALIASES.get(wanted)
        if alias:
            title, target = alias
            self._launch(target, title)
            return self._ok(title, "alias")

        index = self._index()
        # substring pass first ("minecraft" -> "Minecraft Launcher"), then fuzzy >= 0.75
        containing = sorted(k for k in index if wanted in k)
        match = containing[:1] or difflib.get_close_matches(
            wanted, index.keys(), n=1, cutoff=_FUZZY_CUTOFF
        )
        if match:
            title = match[0].title()
            self._launch(str(index[match[0]]), title)
            return self._ok(title, "startmenu")

        path = shutil.which(wanted)
        if path:
            title = Path(path).stem.title()
            self._launch(path, title)
            return self._ok(title, "path")

        closest = difflib.get_close_matches(
            wanted, list(_ALIASES) + list(index.keys()), n=3, cutoff=0.4
        )
        hint = f" Did you mean: {', '.join(closest)}?" if closest else ""
        raise ToolError(f"No app called {args.app_name!r} was found.{hint}", code="app_not_found")

    def _index(self) -> dict[str, Path]:
        if self._lnk_index is None:
            index: dict[str, Path] = {}
            for root in self._start_menu_dirs:
                if not root.is_dir():
                    continue
                for lnk in root.rglob("*.lnk"):
                    index.setdefault(lnk.stem.lower(), lnk)
            self._lnk_index = index
        return self._lnk_index

    def _launch(self, target: str, title: str) -> None:
        try:
            self._launcher(target)
        except OSError as exc:
            raise ToolError(
                f"Found {title} but couldn't start it: {exc}", code="launch_failed"
            ) from exc

    @staticmethod
    def _ok(title: str, via: str) -> ToolOutput:
        return ToolOutput(
            data={
                "launched": True,
                "app_title": title,
                "matched_via": via,
                "summary": f"Opening {title}",
            }
        )
