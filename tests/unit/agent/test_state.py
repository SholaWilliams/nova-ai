"""Tests for ConversationState — trimming and iteration cap (docs/06 §2.4, §5)."""

from __future__ import annotations

from typing import Literal

from nova.agent.state import ConversationState
from nova.core.models import ChatMessage


def _msg(i: int, role: Literal["user", "assistant"] = "user") -> ChatMessage:
    return ChatMessage(role=role, content=f"message {i}")


def test_snapshot_is_empty_for_a_new_session() -> None:
    state = ConversationState()

    assert state.snapshot() == ()


def test_snapshot_preserves_append_order() -> None:
    state = ConversationState()
    state.append(_msg(1, "user"))
    state.append(_msg(2, "assistant"))

    snapshot = state.snapshot()

    assert [m.content for m in snapshot] == ["message 1", "message 2"]


def test_snapshot_trims_to_last_12_turns() -> None:
    state = ConversationState()
    for i in range(30):  # 15 user+assistant pairs -> only the last 12 pairs (24 msgs) survive
        state.append(_msg(i, "user" if i % 2 == 0 else "assistant"))

    snapshot = state.snapshot()

    assert len(snapshot) == 24
    assert snapshot[0].content == "message 6"  # oldest 6 messages dropped
    assert snapshot[-1].content == "message 29"


def test_snapshot_is_immutable() -> None:
    state = ConversationState()
    state.append(_msg(1))

    snapshot = state.snapshot()

    assert isinstance(snapshot, tuple)


def test_max_iterations_defaults_to_five_per_fr17() -> None:
    state = ConversationState()

    assert state.max_iterations == 5


def test_max_iterations_is_configurable() -> None:
    state = ConversationState(max_iterations=3)

    assert state.max_iterations == 3
