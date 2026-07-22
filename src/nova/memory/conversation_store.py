"""ConversationStore: session `.jsonl` append/read + `index.json` (docs/09 §2, §3).

Conversation persistence is automatic and silent (a different lifecycle than explicit fact
writes, docs/09 §1) — every turn in the current process is appended to one session file,
indexed by `index.json` for the History drawer (FR-5/6). `index.json` is a bare JSON array
per docs/09 §3's own shape (unlike `facts.json`'s `{version, facts}` wrapper).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nova.core.atomic_io import atomic_write_text
from nova.core.ids import new_session_id
from nova.core.models import SessionMeta, ToolCallRecord, TurnRecord

logger = logging.getLogger(__name__)

_TITLE_MAX_CHARS = 60


def _quarantine(path: Path) -> None:
    if not path.is_file():
        return
    corrupt_path = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    try:
        path.rename(corrupt_path)
    except OSError:
        logger.exception("failed to quarantine corrupt %s", path)


class ConversationStore:
    def __init__(self, conversations_dir: Path) -> None:
        self._dir = conversations_dir
        self._index_path = conversations_dir / "index.json"
        self._current_session_id: str | None = None

    def current_session_id(self) -> str:
        """Lazily starts a session on first use — one session per process lifetime, matching
        docs/09's "session" granularity (a fresh app launch is a fresh session)."""
        if self._current_session_id is None:
            self._current_session_id = new_session_id()
        return self._current_session_id

    def start_new_session(self) -> str:
        """ "New conversation" (docs/05 §6.5) — unconditionally starts a fresh session even
        mid-process, unlike `current_session_id()`'s lazy-once behavior."""
        self._current_session_id = new_session_id()
        return self._current_session_id

    def persist_turn(self, turn: TurnRecord) -> None:
        session_id = self.current_session_id()
        session_path = self._dir / f"{session_id}.jsonl"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        with session_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_turn_to_dict(turn)) + "\n")

        self._append_or_bump_index(session_id, turn)

    def _append_or_bump_index(self, session_id: str, turn: TurnRecord) -> None:
        entries = self._load_index()
        for entry in entries:
            if entry.get("session_id") == session_id:
                entry["turns"] = entry.get("turns", 0) + 1
                break
        else:
            entries.append(
                {
                    "session_id": session_id,
                    "started_at": turn.ts.isoformat(),
                    "title": turn.user_text[:_TITLE_MAX_CHARS],
                    "turns": 1,
                }
            )
        atomic_write_text(self._index_path, json.dumps(entries, indent=2))

    def _load_index(self) -> list[dict[str, Any]]:
        if not self._index_path.is_file():
            return []
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("index.json is not a JSON array")
            return raw
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "%s is corrupt (%s); quarantining and starting empty", self._index_path, exc
            )
            _quarantine(self._index_path)
            return []

    def list_sessions(self) -> list[SessionMeta]:
        return [
            SessionMeta(
                session_id=entry["session_id"],
                started_at=datetime.fromisoformat(entry["started_at"]),
                title=entry["title"],
                turns=entry["turns"],
            )
            for entry in self._load_index()
        ]

    def load_session(self, session_id: str) -> list[TurnRecord]:
        path = self._dir / f"{session_id}.jsonl"
        if not path.is_file():
            return []
        turns: list[TurnRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                turns.append(_turn_from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("skipping corrupt line in %s", path)
        return turns


def _turn_to_dict(turn: TurnRecord) -> dict[str, Any]:
    return {
        "t": "turn",
        "request_id": turn.request_id,
        "ts": turn.ts.isoformat(),
        "user": {"text": turn.user_text, "source": turn.user_source},
        "assistant": {"text": turn.assistant_text},
        "tools": [
            {"name": t.name, "args": t.args, "status": t.status, "duration_ms": t.duration_ms}
            for t in turn.tools
        ],
        "stages": [[stage, ms] for stage, ms in turn.stages],
    }


def _turn_from_dict(data: dict[str, Any]) -> TurnRecord:
    return TurnRecord(
        request_id=data["request_id"],
        ts=datetime.fromisoformat(data["ts"]),
        user_text=data["user"]["text"],
        user_source=data["user"]["source"],
        assistant_text=data["assistant"]["text"],
        tools=tuple(
            ToolCallRecord(
                name=t["name"], args=t["args"], status=t["status"], duration_ms=t["duration_ms"]
            )
            for t in data.get("tools", [])
        ),
        stages=tuple((entry[0], entry[1]) for entry in data.get("stages", [])),
    )
