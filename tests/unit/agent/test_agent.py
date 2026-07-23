"""Tests for Agent.handle() — the full loop against FakeProvider (docs/06 §1, plan §4)."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from nova.agent.agent import Agent, AgentCancelled, _looks_degenerate
from nova.agent.planner import Planner
from nova.agent.router import Router
from nova.agent.state import ConversationState
from nova.core.errors import SafetyBlocked, Transient
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import ToolCall, UserInput
from nova.providers.base import LLMResponse, TokenUsage
from nova.providers.fake import FakeProvider
from nova.providers.manager import ProviderManager

_USAGE = TokenUsage(input_tokens=10, output_tokens=5)


def _user_input(text: str = "hi", request_id: str = "req_test") -> UserInput:
    return UserInput(request_id=request_id, text=text, source="typed", ts=datetime.now(UTC))


def _reply(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=(), finish_reason="stop", usage=_USAGE)


def _tool_call_response(name: str = "mystery") -> LLMResponse:
    call = ToolCall(call_id="call_1", tool_name=name, arguments={})
    return LLMResponse(text=None, tool_calls=(call,), finish_reason="tool_calls", usage=_USAGE)


def _degenerate_reply() -> LLMResponse:
    return _reply("<unk><unk><unk><unk> garbled nonsense")


def _make_agent(
    provider: FakeProvider, max_iterations: int = 5
) -> tuple[Agent, list[PipelineEvent]]:
    bus = EventBus()
    events: list[PipelineEvent] = []
    bus.subscribe(events.append)
    manager = ProviderManager({"fake": provider}, active="fake")
    agent = Agent(
        manager,
        Planner(system_prompt="you are NOVA"),
        Router(),  # M2: no known tools anywhere
        ConversationState(max_iterations=max_iterations),
        bus,
    )
    return agent, events


def test_handle_direct_answer_emits_correct_event_sequence_for_typed_input() -> None:
    provider = FakeProvider("fake", [_reply("hello there")])
    agent, events = _make_agent(provider)

    reply = agent.handle(_user_input())

    assert reply.text == "hello there"
    assert reply.spoken_text == "hello there"
    assert [(e.stage, e.status) for e in events] == [
        (PipelineStage.LISTENING, EventStatus.SKIPPED),
        (PipelineStage.TRANSCRIBING, EventStatus.SKIPPED),
        (PipelineStage.THINKING, EventStatus.STARTED),
        (PipelineStage.THINKING, EventStatus.COMPLETED),
        (PipelineStage.SELECTING_TOOL, EventStatus.SKIPPED),
        (PipelineStage.EXECUTING, EventStatus.SKIPPED),
        (PipelineStage.OBSERVING, EventStatus.SKIPPED),
        (PipelineStage.REMEMBERING, EventStatus.SKIPPED),
        (PipelineStage.RESPONDING, EventStatus.STARTED),
        (PipelineStage.RESPONDING, EventStatus.COMPLETED),
    ]
    assert all(e.request_id == "req_test" for e in events)


def test_speaking_stage_is_never_emitted_in_m2() -> None:
    provider = FakeProvider("fake", [_reply("hi")])
    agent, events = _make_agent(provider)

    agent.handle(_user_input())

    assert PipelineStage.SPEAKING not in {e.stage for e in events}


def test_responding_completed_detail_carries_the_reply_text() -> None:
    provider = FakeProvider("fake", [_reply("the actual answer")])
    agent, events = _make_agent(provider)

    agent.handle(_user_input())

    responding_completed = next(
        e
        for e in events
        if e.stage == PipelineStage.RESPONDING and e.status == EventStatus.COMPLETED
    )
    assert responding_completed.detail == "the actual answer"


def test_handle_records_the_turn_in_conversation_state() -> None:
    provider = FakeProvider("fake", [_reply("hi there")])
    bus = EventBus()
    manager = ProviderManager({"fake": provider}, active="fake")
    state = ConversationState()
    agent = Agent(manager, Planner("sys"), Router(), state, bus)

    agent.handle(_user_input("hello"))

    snapshot = state.snapshot()
    assert [m.role for m in snapshot] == ["user", "assistant"]
    assert snapshot[0].content == "hello"
    assert snapshot[1].content == "hi there"


def test_second_turn_sends_prior_history_to_the_provider() -> None:
    provider = FakeProvider("fake", [_reply("first answer"), _reply("second answer")])
    bus = EventBus()
    manager = ProviderManager({"fake": provider}, active="fake")
    agent = Agent(manager, Planner("sys"), Router(), ConversationState(), bus)

    agent.handle(_user_input("first question"))
    agent.handle(_user_input("second question", request_id="req_2"))

    second_call_messages = provider.calls[1][0]
    contents = [m.content for m in second_call_messages]
    assert "first question" in contents
    assert "first answer" in contents
    assert "second question" in contents


def test_hallucinated_tool_call_triggers_repair_then_recovers() -> None:
    provider = FakeProvider("fake", [_tool_call_response(), _reply("recovered answer")])
    agent, events = _make_agent(provider)

    reply = agent.handle(_user_input())

    assert reply.text == "recovered answer"
    assert len(provider.calls) == 2
    second_call_messages = provider.calls[1][0]
    assert any(m.role == "tool" for m in second_call_messages)
    assert any(m.role == "assistant" and m.tool_calls for m in second_call_messages)
    assert not any(e.stage == PipelineStage.ERROR for e in events)


def test_repeated_hallucinated_tool_calls_hit_the_iteration_cap() -> None:
    provider = FakeProvider("fake", [_tool_call_response() for _ in range(3)])
    agent, events = _make_agent(provider, max_iterations=3)

    reply = agent.handle(_user_input())

    assert "complicated" in reply.text.lower()
    assert len(provider.calls) == 3
    error_events = [e for e in events if e.stage == PipelineStage.ERROR]
    assert len(error_events) == 1
    assert error_events[0].payload == {"error_code": "iteration_cap"}


def test_safety_blocked_short_circuits_to_gentle_refusal_without_error_event() -> None:
    provider = FakeProvider("fake", [SafetyBlocked("blocked")])
    agent, events = _make_agent(provider)

    reply = agent.handle(_user_input("something unsafe"))

    assert reply.text
    assert not any(e.stage == PipelineStage.ERROR for e in events)


def test_soft_safety_finish_reason_with_no_text_also_refuses_gently() -> None:
    response = LLMResponse(text=None, tool_calls=(), finish_reason="safety", usage=_USAGE)
    provider = FakeProvider("fake", [response])
    agent, events = _make_agent(provider)

    reply = agent.handle(_user_input())

    assert reply.text
    assert not any(e.stage == PipelineStage.ERROR for e in events)


def test_provider_unavailable_emits_error_and_apologizes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    # single configured provider, no fallback: retry consumes both scripted failures
    provider = FakeProvider("fake", [Transient("down"), Transient("still down")])
    agent, events = _make_agent(provider)

    reply = agent.handle(_user_input())

    assert "internet" in reply.text.lower()
    error_events = [e for e in events if e.stage == PipelineStage.ERROR]
    assert len(error_events) == 1
    assert error_events[0].payload == {"error_code": "provider_unavailable"}


def test_looks_degenerate_flags_unk_spam_but_not_normal_text() -> None:
    assert _looks_degenerate("<unk><unk><unk><unk> nonsense")
    assert not _looks_degenerate("The weather in Lagos is sunny today.")
    assert not _looks_degenerate(None)
    assert not _looks_degenerate("")


def test_degenerate_response_is_retried_and_the_clean_answer_wins() -> None:
    provider = FakeProvider("fake", [_degenerate_reply(), _reply("clean answer")])
    agent, events = _make_agent(provider)

    reply = agent.handle(_user_input())

    assert reply.text == "clean answer"
    assert len(provider.calls) == 2
    assert not any(e.stage == PipelineStage.ERROR for e in events)


def test_degenerate_response_twice_apologizes_instead_of_showing_garbage() -> None:
    provider = FakeProvider("fake", [_degenerate_reply(), _degenerate_reply()])
    agent, events = _make_agent(provider)

    reply = agent.handle(_user_input())

    assert "garbled" in reply.text.lower()
    error_events = [e for e in events if e.stage == PipelineStage.ERROR]
    assert len(error_events) == 1
    assert error_events[0].payload == {"error_code": "degenerate_response"}


def test_cancel_flag_resets_at_the_start_of_each_new_request() -> None:
    provider = FakeProvider("fake", [_reply("first"), _reply("second")])
    bus = EventBus()
    manager = ProviderManager({"fake": provider}, active="fake")
    agent = Agent(manager, Planner("sys"), Router(), ConversationState(), bus)

    agent.handle(_user_input("first"))
    agent.cancel()  # no request is running; this should not affect the next one

    reply = agent.handle(_user_input("second", request_id="req_2"))

    assert reply.text == "second"


def test_cancel_during_loop_raises_agent_cancelled_at_the_next_boundary() -> None:
    agent_holder: list[Agent] = []

    class CancellingProvider(FakeProvider):
        def generate(self, messages, tools, opts):  # noqa: ANN001
            result = super().generate(messages, tools, opts)
            agent_holder[0].cancel()  # simulate Esc arriving while this call was in flight
            return result

    provider = CancellingProvider("fake", [_tool_call_response(), _reply("should not be reached")])
    bus = EventBus()
    manager = ProviderManager({"fake": provider}, active="fake")
    agent = Agent(manager, Planner("sys"), Router(), ConversationState(), bus)
    agent_holder.append(agent)

    with pytest.raises(AgentCancelled):
        agent.handle(_user_input())

    assert len(provider.calls) == 1  # never reached a second provider call
