"""Tests for Planner — context assembly (docs/06 §2.1)."""

from __future__ import annotations

from datetime import UTC, datetime

from nova.agent.planner import Planner, load_system_prompt
from nova.core.models import ChatMessage, UserInput


def _user_input(text: str) -> UserInput:
    return UserInput(request_id="req_test", text=text, source="typed", ts=datetime.now(UTC))


def test_build_orders_system_then_history_then_user_input() -> None:
    planner = Planner(system_prompt="you are NOVA")
    history = [
        ChatMessage(role="user", content="earlier question"),
        ChatMessage(role="assistant", content="earlier answer"),
    ]

    messages = planner.build(_user_input("new question"), history)

    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[0].content == "you are NOVA"
    assert messages[1].content == "earlier question"
    assert messages[2].content == "earlier answer"
    assert messages[3].content == "new question"


def test_build_with_empty_history() -> None:
    planner = Planner(system_prompt="you are NOVA")

    messages = planner.build(_user_input("hello"), [])

    assert [m.role for m in messages] == ["system", "user"]


def test_load_system_prompt_reads_bundled_file() -> None:
    prompt = load_system_prompt()

    assert "NOVA" in prompt
    assert len(prompt) > 0
