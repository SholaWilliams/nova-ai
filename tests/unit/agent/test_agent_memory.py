"""Tests for Agent's M5 MemoryService wiring — memory-context injection, real REMEMBERING
semantics, and silent turn persistence (docs/09 §4/§5, docs/06 §2.1/§8).

`test_agent.py` covers the no-memory path (memory=None, the default) exhaustively already;
these tests only exercise what changes when a real MemoryService is wired in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nova.agent.agent import Agent
from nova.agent.executor import Executor
from nova.agent.planner import Planner
from nova.agent.router import Router
from nova.agent.stage_recorder import StageRecorder
from nova.agent.state import ConversationState
from nova.core.config import Settings
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import ToolCall, UserInput
from nova.memory.service import MemoryService
from nova.providers.base import LLMResponse, TokenUsage
from nova.providers.fake import FakeProvider
from nova.providers.manager import ProviderManager
from nova.tools.base import ToolContext
from nova.tools.memory_tool import MemoryTool
from nova.tools.registry import ToolRegistry

_USAGE = TokenUsage(input_tokens=10, output_tokens=5)


def _user_input(text: str = "hi", request_id: str = "req_test") -> UserInput:
    return UserInput(request_id=request_id, text=text, source="typed", ts=datetime.now(UTC))


def _reply(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=(), finish_reason="stop", usage=_USAGE)


def _memory_store_call(content: str) -> LLMResponse:
    call = ToolCall(
        call_id="call_1",
        tool_name="memory_tool",
        arguments={"action": "store", "content": content},
    )
    return LLMResponse(text=None, tool_calls=(call,), finish_reason="tool_calls", usage=_USAGE)


@pytest.fixture
def memory(tmp_path: Path) -> MemoryService:
    return MemoryService(tmp_path)


def _make_agent_with_memory(
    provider: FakeProvider, memory: MemoryService, *, with_tools: bool = False
) -> tuple[Agent, list[PipelineEvent], EventBus]:
    bus = EventBus()
    events: list[PipelineEvent] = []
    bus.subscribe(events.append)
    stage_recorder = StageRecorder(bus)
    manager = ProviderManager({"fake": provider}, active="fake")

    registry = None
    executor = None
    router = Router()
    if with_tools:
        registry = ToolRegistry()
        registry.register(MemoryTool())
        ctx = ToolContext(settings=Settings(), memory=memory)
        executor = Executor(registry, bus, ctx, tool_timeout_s=2.0)
        router = Router(known_tool_names=registry.names)

    agent = Agent(
        manager,
        Planner(system_prompt="you are NOVA"),
        router,
        ConversationState(),
        bus,
        registry=registry,
        executor=executor,
        memory=memory,
        stage_recorder=stage_recorder,
    )
    return agent, events, bus


class TestMemoryContextInjection:
    def test_preferences_reach_the_provider_call(self, memory: MemoryService) -> None:
        memory.add_fact("Favorite color is blue", "preference")
        provider = FakeProvider("fake", [_reply("hi there")])
        agent, _events, _bus = _make_agent_with_memory(provider, memory)

        agent.handle(_user_input("what should I paint my room?"))

        messages = provider.calls[0][0]
        memory_messages = [
            m for m in messages if m.role == "system" and m.content and "blue" in m.content
        ]
        assert len(memory_messages) == 1
        assert "Things you remember about this user:" in memory_messages[0].content

    def test_no_stored_facts_means_no_memory_block(self, memory: MemoryService) -> None:
        provider = FakeProvider("fake", [_reply("hi there")])
        agent, _events, _bus = _make_agent_with_memory(provider, memory)

        agent.handle(_user_input("hi"))

        messages = provider.calls[0][0]
        assert len([m for m in messages if m.role == "system"]) == 1  # just the system prompt


class TestRememberingStage:
    def test_no_memory_write_this_turn_stays_skipped(self, memory: MemoryService) -> None:
        provider = FakeProvider("fake", [_reply("hi there")])
        agent, events, _bus = _make_agent_with_memory(provider, memory)

        agent.handle(_user_input("hi"))

        remembering = [e for e in events if e.stage == PipelineStage.REMEMBERING]
        assert [e.status for e in remembering] == [EventStatus.SKIPPED]

    def test_real_memory_tool_store_emits_started_then_completed(
        self, memory: MemoryService
    ) -> None:
        provider = FakeProvider(
            "fake", [_memory_store_call("Favorite color is blue"), _reply("I'll remember that!")]
        )
        agent, events, _bus = _make_agent_with_memory(provider, memory, with_tools=True)

        agent.handle(_user_input("remember my favorite color is blue"))

        remembering = [e for e in events if e.stage == PipelineStage.REMEMBERING]
        assert [e.status for e in remembering] == [EventStatus.STARTED, EventStatus.COMPLETED]
        assert memory.list_facts()[0].content == "Favorite color is blue"


class TestTurnPersistence:
    def test_handle_persists_a_turn_silently(self, memory: MemoryService) -> None:
        provider = FakeProvider("fake", [_reply("hi there")])
        agent, events, _bus = _make_agent_with_memory(provider, memory)

        agent.handle(_user_input("hello", request_id="req_p1"))

        sessions = memory.list_sessions()
        assert len(sessions) == 1
        turns = memory.load_session(sessions[0].session_id)
        assert len(turns) == 1
        assert turns[0].request_id == "req_p1"
        assert turns[0].user_text == "hello"
        assert turns[0].assistant_text == "hi there"
        # persist_turn has no pipeline event of its own (docs/09 §1: automatic and silent)
        assert not any(
            e.stage == PipelineStage.REMEMBERING and "persist" in (e.detail or "") for e in events
        )

    def test_persisted_turn_carries_stages_from_the_whole_request(
        self, memory: MemoryService
    ) -> None:
        provider = FakeProvider("fake", [_reply("hi there")])
        agent, _events, _bus = _make_agent_with_memory(provider, memory)

        agent.handle(_user_input("hello", request_id="req_p2"))

        turns = memory.load_session(memory.list_sessions()[0].session_id)
        stage_names = [name for name, _ms in turns[0].stages]
        assert "THINKING" in stage_names
        assert "RESPONDING" in stage_names

    def test_persisted_turn_records_tool_calls(self, memory: MemoryService) -> None:
        provider = FakeProvider("fake", [_memory_store_call("Has a dog"), _reply("Got it!")])
        agent, _events, _bus = _make_agent_with_memory(provider, memory, with_tools=True)

        agent.handle(_user_input("remember I have a dog", request_id="req_p3"))

        turns = memory.load_session(memory.list_sessions()[0].session_id)
        assert len(turns[0].tools) == 1
        assert turns[0].tools[0].name == "memory_tool"
        assert turns[0].tools[0].status == "ok"

    def test_no_memory_wired_means_no_persistence_attempted(self) -> None:
        # same shape as test_agent.py's no-memory path — just confirms handle() doesn't
        # blow up without a MemoryService, since persist_turn is conditional on self._memory.
        provider = FakeProvider("fake", [_reply("hi there")])
        bus = EventBus()
        manager = ProviderManager({"fake": provider}, active="fake")
        agent = Agent(manager, Planner("sys"), Router(), ConversationState(), bus)

        reply = agent.handle(_user_input("hi"))

        assert reply.text == "hi there"
