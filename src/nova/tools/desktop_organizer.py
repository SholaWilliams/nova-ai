"""desktop_organizer: tidy the Desktop into category folders (docs/07 §7).

The only sensitive tool in v1.0 — the Executor runs its full plan -> preview -> confirm ->
act gate (FR-20, FR-26). *Move, never delete*: no destructive branch exists anywhere in
this file. Every act writes an undo manifest so "undo" can replay the moves in reverse.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from nova.core.errors import ToolError
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec

_MANIFEST_NAME = "undo_manifest.json"

_CATEGORIES: dict[str, frozenset[str]] = {
    "Pictures": frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".heic"}),
    "Documents": frozenset(
        {".doc", ".docx", ".pdf", ".txt", ".md", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx"}
    ),
    "Videos": frozenset({".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv"}),
    "Music": frozenset({".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma"}),
    "Archives": frozenset({".zip", ".rar", ".7z", ".tar", ".gz"}),
}
_CATEGORY_NAMES = frozenset(_CATEGORIES) | {"Other"}


def _category_for(path: Path) -> str:
    suffix = path.suffix.lower()
    for category, extensions in _CATEGORIES.items():
        if suffix in extensions:
            return category
    return "Other"


class DesktopOrganizerParams(BaseModel):
    """Arguments for the desktop organizer tool."""

    mode: Literal["preview", "organize", "undo"] = Field(
        description=(
            "'organize' tidies the Desktop into folders (the user is always asked first); "
            "'preview' only shows what would move; 'undo' puts the last tidy-up back."
        )
    )


class DesktopOrganizerTool(Tool):
    """Plan/preview/act/undo over the Desktop's top-level files only."""

    spec = ToolSpec(
        name="desktop_organizer",
        title="Desktop Organizer",
        description=(
            "Tidy up the user's Desktop by moving files into category folders (Pictures, "
            "Documents, Videos, Music, Archives, Other). Use when the user asks to clean "
            "up or organize their desktop. 'undo' puts everything back."
        ),
        parameters=DesktopOrganizerParams,
        sensitive=True,  # the reason the confirmation stage exists (FR-20)
        icon="layout-grid",
        detail_template="Tidying up your Desktop",
    )

    def __init__(self, desktop: Path, manifest_dir: Path) -> None:
        self._desktop = desktop
        self._manifest_path = manifest_dir / _MANIFEST_NAME

    # ── plan ──────────────────────────────────────────────────────────

    def _plan(self) -> list[tuple[Path, str]]:
        """Top-level *files* only: never folders, hidden/system files, or .lnk shortcuts."""
        if not self._desktop.is_dir():
            return []
        moves: list[tuple[Path, str]] = []
        for entry in sorted(self._desktop.iterdir()):
            if not entry.is_file() or entry.name.startswith((".", "~")):
                continue
            if entry.suffix.lower() in (".lnk", ".url"):
                continue
            if entry.name.lower() in ("desktop.ini", "thumbs.db"):
                continue
            moves.append((entry, _category_for(entry)))
        return moves

    def preview(self, args: BaseModel, ctx: ToolContext) -> list[str]:
        """Lines for the confirmation dialog (FR-26): one per planned move."""
        del ctx
        assert isinstance(args, DesktopOrganizerParams)
        if args.mode == "undo":
            moves = self._load_manifest()
            return [f"Put {Path(dst).name} back where it was" for _src, dst in moves]
        return [f"Move {path.name} into {category}" for path, category in self._plan()]

    # ── execute ───────────────────────────────────────────────────────

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        del ctx
        assert isinstance(args, DesktopOrganizerParams)
        if args.mode == "undo":
            return self._undo()
        plan = self._plan()
        if not plan:
            raise ToolError(
                "The Desktop has no loose files to tidy — it's already neat!",
                code="nothing_to_do",
            )
        if args.mode == "preview":
            return ToolOutput(
                data={
                    "moved": 0,
                    "categories": self._count(plan),
                    "undo_available": self._manifest_path.is_file(),
                    "preview": [f"{p.name} -> {c}" for p, c in plan],
                    "summary": f"I can tidy {len(plan)} files on the Desktop — say the word!",
                }
            )
        return self._organize(plan)

    def _organize(self, plan: list[tuple[Path, str]]) -> ToolOutput:
        moved: list[tuple[str, str]] = []
        failures: list[str] = []
        for src, category in plan:
            folder = self._desktop / category
            try:
                folder.mkdir(exist_ok=True)
                dst = self._collision_free(folder / src.name)
                shutil.move(str(src), str(dst))
                moved.append((str(src), str(dst)))
            except OSError as exc:
                failures.append(f"{src.name}: {exc}")

        if moved:
            # write the manifest even on partial failure — undo still covers what moved
            self._write_manifest(moved)

        if failures and not moved:
            raise ToolError(
                "None of the files could be moved: " + "; ".join(failures),
                code="partial_failure",
            )

        categories = self._count([(Path(src), Path(dst).parent.name) for src, dst in moved])
        summary = (
            f"I tidied {len(moved)} file{'s' if len(moved) != 1 else ''} into "
            f"{len(categories)} folder{'s' if len(categories) != 1 else ''} on your Desktop"
        )
        data = {
            "moved": len(moved),
            "categories": categories,
            "undo_available": True,
            "summary": summary,
        }
        if failures:
            data["failed"] = failures
        return ToolOutput(data=data)

    def _undo(self) -> ToolOutput:
        moves = self._load_manifest()
        if not moves:
            raise ToolError("There's no tidy-up to undo right now.", code="no_undo_available")
        restored = 0
        missing: list[str] = []
        for src, dst in reversed(moves):
            dst_path = Path(dst)
            if not dst_path.is_file():
                missing.append(dst_path.name)  # moved/renamed since — report, don't guess
                continue
            target = self._collision_free(Path(src))
            try:
                shutil.move(str(dst_path), str(target))
                restored += 1
            except OSError:
                missing.append(dst_path.name)
        self._manifest_path.unlink(missing_ok=True)
        self._cleanup_empty_category_folders()

        summary = f"I put {restored} file{'s' if restored != 1 else ''} back on the Desktop"
        data: dict[str, object] = {"moved": restored, "undo_available": False, "summary": summary}
        if missing:
            data["not_restored"] = missing
        return ToolOutput(data=data)

    # ── helpers ───────────────────────────────────────────────────────

    def _cleanup_empty_category_folders(self) -> None:
        """`rmdir` only ever removes *empty* dirs — still no deletion code path."""
        for name in _CATEGORY_NAMES:
            folder = self._desktop / name
            if folder.is_dir():
                with contextlib.suppress(OSError):  # not empty -> leave it alone
                    folder.rmdir()

    @staticmethod
    def _collision_free(path: Path) -> Path:
        if not path.exists():
            return path
        for n in range(2, 100):
            candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
            if not candidate.exists():
                return candidate
        raise ToolError(f"Too many files named {path.name!r}.", code="partial_failure")

    def _write_manifest(self, moves: list[tuple[str, str]]) -> None:
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "ts": datetime.now(UTC).isoformat(),
            "moves": [{"src": src, "dst": dst} for src, dst in moves],
        }
        self._manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_manifest(self) -> list[tuple[str, str]]:
        if not self._manifest_path.is_file():
            return []
        try:
            payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            return [(m["src"], m["dst"]) for m in payload.get("moves", [])]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return []

    @staticmethod
    def _count(plan: list[tuple[Path, str]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _path, category in plan:
            counts[category] = counts.get(category, 0) + 1
        return counts
