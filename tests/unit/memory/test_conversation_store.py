"""Tests for ConversationStore (docs/09 §2, §3) — tmp_path-based, real file I/O."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from nova.core.models import ToolCallRecord, TurnRecord
from nova.memory.conversation_store import ConversationStore


def _turn(request_id: str = "req_1", text: str = "hello nova") -> TurnRecord:
    return TurnRecord(
        request_id=request_id,
        ts=datetime.now(UTC),
        user_text=text,
        user_source="typed",
        assistant_text="hi there!",
        tools=(
            ToolCallRecord(name="weather", args={"city": "Lagos"}, status="ok", duration_ms=42),
        ),
        stages=(("THINKING", 100), ("RESPONDING", 5)),
    )


def test_current_session_id_is_stable_within_one_store_instance(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    assert store.current_session_id() == store.current_session_id()


def test_persist_turn_creates_a_session_jsonl_file(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    store.persist_turn(_turn())

    session_path = tmp_path / f"{store.current_session_id()}.jsonl"
    assert session_path.is_file()
    line = json.loads(session_path.read_text(encoding="utf-8").splitlines()[0])
    assert line["t"] == "turn"
    assert line["user"] == {"text": "hello nova", "source": "typed"}
    assert line["assistant"] == {"text": "hi there!"}
    assert line["tools"] == [
        {"name": "weather", "args": {"city": "Lagos"}, "status": "ok", "duration_ms": 42}
    ]
    assert line["stages"] == [["THINKING", 100], ["RESPONDING", 5]]


def test_persist_turn_updates_index_with_title_and_turn_count(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    store.persist_turn(_turn(text="what's the weather in Lagos?"))
    store.persist_turn(_turn(text="second message"))

    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].title == "what's the weather in Lagos?"
    assert sessions[0].turns == 2


def test_load_session_round_trips_turn_records(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    store.persist_turn(_turn(request_id="req_a"))
    store.persist_turn(_turn(request_id="req_b"))

    turns = store.load_session(store.current_session_id())

    assert [t.request_id for t in turns] == ["req_a", "req_b"]
    assert turns[0].tools[0].name == "weather"
    assert turns[0].stages == (("THINKING", 100), ("RESPONDING", 5))


def test_load_session_for_unknown_id_returns_empty(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    assert store.load_session("nonexistent") == []


def test_list_sessions_empty_when_nothing_persisted(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    assert store.list_sessions() == []


def test_corrupt_index_is_quarantined_and_starts_empty(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("not valid json{{{", encoding="utf-8")

    store = ConversationStore(tmp_path)

    assert store.list_sessions() == []
    assert list(tmp_path.glob("index.json.corrupt-*"))


def test_title_is_truncated_to_60_chars(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    long_text = "x" * 100

    store.persist_turn(_turn(text=long_text))

    assert len(store.list_sessions()[0].title) == 60
