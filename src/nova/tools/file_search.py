"""file_search: find files by name in the user's own folders — read-only (docs/07 §6)."""

from __future__ import annotations

import difflib
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from nova.core.errors import ToolError
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec

_MAX_DEPTH = 6
_MAX_MATCHES_SCANNED = 200
_TIME_BUDGET_S = 8.0
_TOP_N = 10
_FUZZY_CUTOFF = 0.75

_TYPE_ALIASES: dict[str, frozenset[str]] = {
    "image": frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}),
    "doc": frozenset({".doc", ".docx", ".pdf", ".txt", ".md", ".rtf", ".odt", ".ppt", ".pptx"}),
    "video": frozenset({".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv"}),
}

Location = Literal["documents", "desktop", "downloads", "pictures", "all"]


def default_user_folders() -> dict[str, Path]:
    """The NFR-6 user-scoped folders — shared with `file_opener` so it can only open what
    `file_search` could have found."""
    home = Path.home()
    return {
        "documents": home / "Documents",
        "desktop": home / "Desktop",
        "downloads": home / "Downloads",
        "pictures": home / "Pictures",
    }


class FileSearchParams(BaseModel):
    """Arguments for the file search tool."""

    query: str = Field(description="Words from the file's name, e.g. 'dragon drawing'.")
    file_type: str | None = Field(
        default=None,
        description="Extension like 'png', or one of 'image', 'doc', 'video'. Null = any.",
    )
    location: Location = Field(
        default="all",
        description="Which folder to search: documents, desktop, downloads, pictures, or all.",
    )


def _score(query: str, name: str) -> float:
    """1.0 for a substring hit, else a fuzzy ratio (0 if below the cutoff)."""
    if query in name:
        return 1.0
    ratio = difflib.SequenceMatcher(None, query, name).ratio()
    return ratio if ratio >= _FUZZY_CUTOFF else 0.0


class FileSearchTool(Tool):
    """Bounded walk over the named user folders only (NFR-6): depth ≤ 6, ≤ 200 hits, ≤ 8 s."""

    spec = ToolSpec(
        name="file_search",
        title="File Search",
        description=(
            "Find files by name in the user's Documents, Desktop, Downloads or Pictures. "
            "Use when the user asks where a file is, e.g. 'find my dragon drawing' or "
            "'where is my homework'. It only looks — it never changes anything."
        ),
        parameters=FileSearchParams,
        sensitive=False,
        icon="file-search",
        detail_template="Looking for files named like '{query}'",
    )

    def __init__(self, folders: dict[str, Path] | None = None) -> None:
        self._folders = folders if folders is not None else default_user_folders()

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        del ctx
        assert isinstance(args, FileSearchParams)
        query = args.query.strip().lower()
        extensions = self._extensions_for(args.file_type)

        roots = (
            list(self._folders.values())
            if args.location == "all"
            else [self._folders[args.location]]
        )
        available = [root for root in roots if root.is_dir()]
        if not available:
            raise ToolError(
                f"The {args.location} folder isn't available on this computer.",
                code="location_unavailable",
            )

        matches: list[tuple[float, float, Path]] = []
        deadline = time.monotonic() + _TIME_BUDGET_S
        truncated = False
        for root in available:
            truncated |= self._walk(root, query, extensions, matches, deadline)
            if len(matches) >= _MAX_MATCHES_SCANNED or time.monotonic() > deadline:
                truncated = True
                break

        if not matches:
            raise ToolError(
                f"No files named like {args.query!r} were found. The user could try "
                "different words or tell you which folder to look in.",
                code="no_matches",
            )

        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        top = matches[:_TOP_N]
        results = [
            {
                "name": path.name,
                "folder": str(path.parent),
                "size_kb": max(1, path.stat().st_size // 1024),
                "modified": datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d"),
            }
            for _score_val, mtime, path in top
        ]
        count = len(matches)
        return ToolOutput(
            data={
                "matches": results,
                "count": count,
                "truncated": truncated,
                "summary": f"I found {count} file{'s' if count != 1 else ''} "
                f"named like '{args.query}'",
            }
        )

    def _walk(
        self,
        root: Path,
        query: str,
        extensions: frozenset[str] | None,
        matches: list[tuple[float, float, Path]],
        deadline: float,
    ) -> bool:
        """Depth-bounded scan; returns True if it stopped early (budget/limits hit)."""
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            folder, depth = stack.pop()
            if time.monotonic() > deadline or len(matches) >= _MAX_MATCHES_SCANNED:
                return True
            try:
                entries = list(folder.iterdir())
            except OSError:
                continue
            for entry in entries:
                name = entry.name
                if name.startswith("."):
                    continue
                if entry.is_dir():
                    if depth + 1 <= _MAX_DEPTH:
                        stack.append((entry, depth + 1))
                    continue
                if extensions is not None and entry.suffix.lower() not in extensions:
                    continue
                score = _score(query, name.lower())
                if score > 0:
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    matches.append((score, mtime, entry))
                    if len(matches) >= _MAX_MATCHES_SCANNED:
                        return True
        return False

    @staticmethod
    def _extensions_for(file_type: str | None) -> frozenset[str] | None:
        if not file_type:
            return None
        normalized = file_type.strip().lower().lstrip(".")
        if normalized in _TYPE_ALIASES:
            return _TYPE_ALIASES[normalized]
        return frozenset({f".{normalized}"})
