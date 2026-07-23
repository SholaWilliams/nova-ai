"""file_opener: open one file already found by file_search (docs/07 §7).

The follow-up action file_search's spec always deferred to "future". Only ever opens a
path inside the same NFR-6 user-scoped folders file_search can search — never an arbitrary
path the LLM might otherwise be tempted to construct. Launch via `os.startfile`, the same
mechanism app_launcher uses for apps — never a shell string (A-1).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from nova.core.errors import ToolError
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec
from nova.tools.file_search import default_user_folders


class FileOpenerParams(BaseModel):
    """Arguments for the file opener tool."""

    folder: str = Field(description="The file's folder, from a file_search result.")
    name: str = Field(description="The file's name, from a file_search result.")


class FileOpenerTool(Tool):
    """Opens a file_search match with its default app — never a bare app instance."""

    spec = ToolSpec(
        name="file_opener",
        title="File Opener",
        description=(
            "Open a specific file with its default app, using the folder and name from a "
            "file_search result. Use this right after file_search when the user confirms "
            "they want that file opened, e.g. 'yes, open it' — never app_launcher, which "
            "only opens a blank app with nothing loaded."
        ),
        parameters=FileOpenerParams,
        sensitive=False,
        icon="external-link",
        detail_template="Opening {name}",
    )

    def __init__(
        self,
        allowed_folders: dict[str, Path] | None = None,
        launcher: Callable[[str], None] | None = None,
    ) -> None:
        self._allowed_folders = (
            allowed_folders if allowed_folders is not None else default_user_folders()
        )
        self._launcher = launcher or os.startfile

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        del ctx
        assert isinstance(args, FileOpenerParams)
        path = (Path(args.folder) / args.name).resolve()

        if not self._is_allowed(path):
            raise ToolError(
                f"{args.name} isn't in a folder I'm allowed to open files from.",
                code="location_unavailable",
            )
        if not path.is_file():
            raise ToolError(f"I can't find {args.name} anymore.", code="file_not_found")

        try:
            self._launcher(str(path))
        except OSError as exc:
            raise ToolError(
                f"Found {args.name} but couldn't open it: {exc}", code="open_failed"
            ) from exc

        return ToolOutput(
            data={"opened": True, "path": str(path), "summary": f"Opening {args.name}"}
        )

    def _is_allowed(self, path: Path) -> bool:
        return any(path.is_relative_to(root.resolve()) for root in self._allowed_folders.values())
