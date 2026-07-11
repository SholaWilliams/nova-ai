"""Atomic text-file writes shared by every persisted-file writer (`settings.json`, `.env`,
`facts.json`, conversation index/JSONL — docs/03 §15, docs/09 §2): temp file in the same
directory, fsync, then `os.replace` — a crash or power loss mid-write never corrupts the real
file, it just loses the pending update.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, tmp_prefix: str | None = None) -> None:
    """Write `text` to `path` atomically. `tmp_prefix` defaults to `.{path.name}.`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = tmp_prefix if tmp_prefix is not None else f".{path.name}."

    fd, tmp_path_str = tempfile.mkstemp(dir=path.parent, prefix=prefix, suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
