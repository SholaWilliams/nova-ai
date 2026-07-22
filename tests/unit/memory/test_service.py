"""Tests for MemoryService (docs/09 §4, docs/11 §4) — tmp_path-based, real file I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from nova.core.models import TurnRecord, UserInput
from nova.memory.service import MemoryService
from nova.tools.base import MemoryFacade


def _user_input(text: str) -> UserInput:
    return UserInput(request_id="req_1", text=text, source="typed", ts=datetime.now(UTC))


def _turn(request_id: str = "req_1") -> TurnRecord:
    return TurnRecord(
        request_id=request_id,
        ts=datetime.now(UTC),
        user_text="hi",
        user_source="typed",
        assistant_text="hello!",
        tools=(),
        stages=(),
    )


def test_satisfies_memory_facade_protocol(tmp_path: Path) -> None:
    service = MemoryService(tmp_path)
    assert isinstance(service, MemoryFacade)


class TestAddFactAndRecall:
    def test_add_fact_then_recall(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        service.add_fact("Favorite color is blue", "preference")

        assert service.recall("favorite color") == ["Favorite color is blue"]

    def test_recall_miss_returns_empty_list(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        assert service.recall("anything") == []

    def test_begin_request_tags_source_request(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        service.begin_request("req_42")

        service.add_fact("Has a dog", "fact")

        assert service.list_facts()[0].source_request == "req_42"

    def test_add_fact_without_begin_request_uses_empty_source(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        service.add_fact("Has a dog", "fact")
        assert service.list_facts()[0].source_request == ""


class TestGetContext:
    def test_preferences_always_included(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        service.add_fact("Favorite color is blue", "preference")

        context = service.get_context(_user_input("tell me a joke"))

        assert context.preferences == ("Favorite color is blue",)

    def test_facts_scored_against_the_query(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        service.add_fact("Has a dog named Rex", "fact")
        service.add_fact("Likes pizza", "fact")

        context = service.get_context(_user_input("what's my dog's name?"))

        assert context.facts == ("Has a dog named Rex",)

    def test_empty_when_nothing_stored(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        context = service.get_context(_user_input("hi"))
        assert context.is_empty()


class TestFactsManagement:
    def test_delete_fact(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        service.add_fact("Has a dog", "fact")
        fact_id = service.list_facts()[0].id

        service.delete_fact(fact_id)

        assert service.list_facts() == []

    def test_clear_facts(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        service.add_fact("Has a dog", "fact")
        service.add_fact("Has a cat", "fact")

        service.clear_facts()

        assert service.list_facts() == []


class TestConversationPersistence:
    def test_persist_and_list_sessions(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        service.persist_turn(_turn())

        sessions = service.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].turns == 1

    def test_persist_and_load_session(self, tmp_path: Path) -> None:
        service = MemoryService(tmp_path)
        service.persist_turn(_turn(request_id="req_a"))

        session_id = service.list_sessions()[0].session_id
        turns = service.load_session(session_id)

        assert [t.request_id for t in turns] == ["req_a"]
