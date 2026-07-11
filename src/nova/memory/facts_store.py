"""FactsStore: owns `facts.json` (docs/09 §2, §3) — atomic writes, corrupt-file quarantine,
the 200-fact soft cap, and keyword extraction at write time (the v1 retrieval index).

Not thread-safe on its own — `MemoryService` provides the one sanctioned lock
(ARCHITECTURE_RULES.md's threading law).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from nova.core.atomic_io import atomic_write_text
from nova.core.errors import MemoryError as NovaMemoryError
from nova.core.ids import new_fact_id
from nova.core.models import MemoryItem
from nova.memory.retrieval import extract_keywords

logger = logging.getLogger(__name__)

_VERSION = 1
_SOFT_CAP = 200
_AT_CAP_MESSAGE = "I'm holding a lot already — can you help me forget something first?"


def _quarantine(path: Path) -> None:
    """Rename a corrupt file aside and let the caller recreate empty (docs/09 §2: "memory
    loss is graceful, never a crash")."""
    if not path.is_file():
        return
    corrupt_path = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    try:
        path.rename(corrupt_path)
    except OSError:
        logger.exception("failed to quarantine corrupt %s", path)


class FactsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._facts = self._load()

    def _load(self) -> list[MemoryItem]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("facts.json is not a JSON object")
            return [_item_from_dict(entry) for entry in raw.get("facts", [])]
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.warning("%s is corrupt (%s); quarantining and starting empty", self._path, exc)
            _quarantine(self._path)
            return []

    def _save(self) -> None:
        payload = {"version": _VERSION, "facts": [_item_to_dict(item) for item in self._facts]}
        atomic_write_text(self._path, json.dumps(payload, indent=2))

    def list_facts(self) -> list[MemoryItem]:
        return list(self._facts)

    def add_fact(self, content: str, kind: str, source_request: str) -> MemoryItem:
        if len(self._facts) >= _SOFT_CAP:
            # deliberate: forgetting is a user decision (FR-33), not automatic eviction
            raise NovaMemoryError(
                f"facts.json at the {_SOFT_CAP}-fact soft cap",
                friendly_message=_AT_CAP_MESSAGE,
            )
        item = MemoryItem(
            id=new_fact_id(),
            kind=kind,  # type: ignore[arg-type]
            content=content,
            keywords=extract_keywords(content),
            created_at=datetime.now(UTC),
            source_request=source_request,
        )
        self._facts.append(item)
        self._save()
        return item

    def delete_fact(self, fact_id: str) -> None:
        self._facts = [item for item in self._facts if item.id != fact_id]
        self._save()

    def clear_facts(self) -> None:
        self._facts = []
        self._save()


def _item_to_dict(item: MemoryItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "content": item.content,
        "keywords": list(item.keywords),
        "created_at": item.created_at.isoformat(),
        "source_request": item.source_request,
    }


def _item_from_dict(data: dict[str, Any]) -> MemoryItem:
    kind: Literal["fact", "preference"] = data["kind"]
    return MemoryItem(
        id=data["id"],
        kind=kind,
        content=data["content"],
        keywords=tuple(data["keywords"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        source_request=data["source_request"],
    )
