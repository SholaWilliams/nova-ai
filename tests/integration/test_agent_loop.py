"""Integration suite: the full agent loop against FakeProvider (docs/13 §3 scenario matrix).

Constructs the real Agent + ProviderManager + Planner + Router + ConversationState stack,
exactly as `app.py` wires it, and asserts observable behavior — final replies and, most
importantly, the exact pipeline event sequence (NG-9's mechanical guarantee: "if the UI
stream lies, this suite fails"). M2's scenario matrix (docs/12 T-210) covers the tool-free
subset of docs/13 §3's list — the tool-specific rows (single/multi-step tool, tool timeout,
tool error, denial) land in M3 once Executor exists. Individual-component edge cases already
covered by tests/unit/agent/test_agent.py aren't repeated here; this file exists so the named
scenario matrix has one discoverable, literal home.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from nova.agent.agent import Agent, AgentCancelled
from nova.agent.planner import Planner
from nova.agent.router import Router
from nova.agent.state import ConversationState
from nova.core.errors import Transient
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import ToolCall, UserInput
from nova.providers.base import GenerateOptions, LLMResponse, TokenUsage
from nova.providers.fake import FakeProvider
from nova.providers.manager import ProviderManager

_USAGE = TokenUsage(input_tokens=10, output_tokens=5)


def _user_input(text: str = "hi", request_id: str = "req_1") -> UserInput:
    return UserInput(request_id=request_id, text=text, source="typed", ts=datetime.now(UTC))


def _reply(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=(), finish_reason="stop", usage=_USAGE)


def _tool_call_response() -> LLMResponse:
    call = ToolCall(call_id="call_1", tool_name="mystery", arguments={})
    return LLMResponse(text=None, tool_calls=(call,), finish_reason="tool_calls", usage=_USAGE)


def _build_stack(
    providers: dict[str, FakeProvider], active: str, max_iterations: int = 5
) -> tuple[Agent, list[PipelineEvent]]:
    bus = EventBus()
    events: list[PipelineEvent] = []
    bus.subscribe(events.append)
    manager = ProviderManager(dict(providers), active=active)
    agent = Agent(
        manager,
        Planner(system_prompt="you are NOVA, a friendly assistant"),
        Router(),  # M2: known_tool_names is always empty
        ConversationState(max_iterations=max_iterations),
        bus,
        opts=GenerateOptions(),
    )
    return agent, events


def _stage_sequence(events: list[PipelineEvent]) -> list[tuple[PipelineStage, EventStatus]]:
    return [(e.stage, e.status) for e in events]


class TestDirectAnswer:
    """A typed request with no tool call: THINKING and RESPONDING are the only real stages."""

    def test_event_sequence_and_reply(self) -> None:
        gemini = FakeProvider("gemini", [_reply("It's sunny today!")])
        agent, events = _build_stack({"gemini": gemini}, active="gemini")

        reply = agent.handle(_user_input("what's the weather?"))

        assert reply.text == "It's sunny today!"
        assert _stage_sequence(events) == [
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
        assert PipelineStage.ERROR not in {e.stage for e in events}


class TestProviderFallback:
    """Primary scripted to fail entirely: the fallback provider answers, status reflects it."""

    def test_falls_back_and_still_replies_with_no_error_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        gemini = FakeProvider("gemini", [Transient("primary is down"), Transient("still down")])
        groq = FakeProvider("groq", [_reply("Groq answering instead")])
        agent, events = _build_stack({"gemini": gemini, "groq": groq}, active="gemini")

        reply = agent.handle(_user_input("hello?"))

        assert reply.text == "Groq answering instead"
        assert PipelineStage.ERROR not in {e.stage for e in events}
        responding = next(
            e
            for e in events
            if e.stage == PipelineStage.RESPONDING and e.status == EventStatus.COMPLETED
        )
        assert responding.detail == "Groq answering instead"


class TestCancellationBetweenIterations:
    """Esc arrives while a repair round-trip is mid-flight: the loop stops, no reply issued."""

    def test_cancel_after_first_provider_call_raises_and_stops_the_loop(self) -> None:
        agent_holder: list[Agent] = []

        class CancellingProvider(FakeProvider):
            def generate(self, messages, tools, opts):  # noqa: ANN001
                result = super().generate(messages, tools, opts)
                agent_holder[0].cancel()  # simulate Esc arriving mid-call
                return result

        provider = CancellingProvider(
            "gemini", [_tool_call_response(), _reply("should never be reached")]
        )
        agent, events = _build_stack({"gemini": provider}, active="gemini")
        agent_holder.append(agent)

        with pytest.raises(AgentCancelled):
            agent.handle(_user_input())

        assert len(provider.calls) == 1
        assert not any(e.stage == PipelineStage.RESPONDING for e in events)


class TestIterationCap:
    """The provider never produces a direct answer: the loop exhausts its budget honestly."""

    def test_hits_cap_emits_error_and_still_apologizes_conversationally(self) -> None:
        provider = FakeProvider("gemini", [_tool_call_response() for _ in range(4)])
        agent, events = _build_stack({"gemini": provider}, active="gemini", max_iterations=4)

        reply = agent.handle(_user_input())

        assert "complicated" in reply.text.lower()
        assert len(provider.calls) == 4
        error_events = [e for e in events if e.stage == PipelineStage.ERROR]
        assert len(error_events) == 1
        assert error_events[0].payload == {"error_code": "iteration_cap"}
        # A-6: every error path still ends in a conversational reply, not a dead end.
        assert any(
            e.stage == PipelineStage.RESPONDING and e.status == EventStatus.COMPLETED
            for e in events
        )


class TestDefensiveRepairRoundTrip:
    """A provider hallucinates a tool call despite receiving none: repair recovers cleanly."""

    def test_unknown_tool_call_triggers_one_repair_round_trip_then_recovers(self) -> None:
        provider = FakeProvider(
            "gemini", [_tool_call_response(), _reply("Here's my answer without any tools")]
        )
        agent, events = _build_stack({"gemini": provider}, active="gemini")

        reply = agent.handle(_user_input())

        assert reply.text == "Here's my answer without any tools"
        assert len(provider.calls) == 2
        second_call_messages = provider.calls[1][0]
        tool_messages = [m for m in second_call_messages if m.role == "tool"]
        assert len(tool_messages) == 1
        assert "mystery" in (tool_messages[0].content or "")
        assert PipelineStage.ERROR not in {e.stage for e in events}
