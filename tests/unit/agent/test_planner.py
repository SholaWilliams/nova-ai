"""Tests for Planner — context assembly (docs/06 §2.1)."""

from __future__ import annotations

from datetime import UTC, datetime

from nova.agent.planner import Planner, load_system_prompt
from nova.core.models import ChatMessage, MemoryContext, UserInput


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


# ── memory-context injection (docs/09 §5, M5) ──────────────────────────


def test_no_memory_context_omits_the_memory_block() -> None:
    planner = Planner(system_prompt="you are NOVA")

    messages = planner.build(_user_input("hi"), [], None)

    assert [m.role for m in messages] == ["system", "user"]


def test_empty_memory_context_omits_the_memory_block() -> None:
    planner = Planner(system_prompt="you are NOVA")

    messages = planner.build(_user_input("hi"), [], MemoryContext(preferences=(), facts=()))

    assert [m.role for m in messages] == ["system", "user"]


def test_non_empty_memory_context_injects_a_labeled_system_block() -> None:
    planner = Planner(system_prompt="you are NOVA")
    context = MemoryContext(preferences=("Favorite color is blue",), facts=("Has a dog",))

    messages = planner.build(_user_input("hi"), [], context)

    assert [m.role for m in messages] == ["system", "system", "user"]
    memory_block = messages[1].content
    assert memory_block is not None
    assert "Things you remember about this user:" in memory_block
    assert "Favorite color is blue" in memory_block
    assert "Has a dog" in memory_block


def test_memory_block_comes_before_history() -> None:
    planner = Planner(system_prompt="you are NOVA")
    context = MemoryContext(preferences=("Favorite color is blue",), facts=())
    history = [ChatMessage(role="user", content="earlier question")]

    messages = planner.build(_user_input("hi"), history, context)

    assert [m.role for m in messages] == ["system", "system", "user", "user"]
    assert messages[2].content == "earlier question"
