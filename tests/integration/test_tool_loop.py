"""M3 scenario matrix: the agent loop with real tools via the Executor (docs/13 §3).

Same construction shape as `app.py`: real Agent + Router(known names) + Executor + registry,
FakeProvider scripting the LLM side. Asserts final replies and the exact pipeline stream —
including the tool trio actually running instead of being skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from nova.agent.agent import Agent
from nova.agent.executor import Executor
from nova.agent.planner import Planner
from nova.agent.router import Router
from nova.agent.state import ConversationState
from nova.core.config import Settings
from nova.core.errors import ToolError
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import ToolCall, UserInput
from nova.providers.base import LLMResponse, TokenUsage
from nova.providers.fake import FakeProvider
from nova.providers.manager import ProviderManager
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec
from nova.tools.calculator import CalculatorTool
from nova.tools.registry import ToolRegistry

_USAGE = TokenUsage(input_tokens=10, output_tokens=5)


class _NoParams(BaseModel):
    pass


class _GatedTool(Tool):
    spec = ToolSpec(
        name="gated",
        title="Gated",
        description="a sensitive test tool",
        parameters=_NoParams,
        sensitive=True,
        icon="layout-grid",
        detail_template="Doing the sensitive thing",
    )

    def __init__(self) -> None:
        self.executed = False

    def preview(self, args: BaseModel, ctx: ToolContext) -> list[str]:
        return ["Move photo.png into Pictures"]

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        self.executed = True
        return ToolOutput(data={"summary": "done"})


class _FailingTool(Tool):
    spec = ToolSpec(
        name="failing",
        title="Failing",
        description="always fails",
        parameters=_NoParams,
        sensitive=False,
        icon="zap",
        detail_template="Trying something",
    )

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        raise ToolError("it broke", code="broke")


def _user_input(text: str = "hi") -> UserInput:
    return UserInput(request_id="req_t", text=text, source="typed", ts=datetime.now(UTC))


def _reply(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=(), finish_reason="stop", usage=_USAGE)


def _tool_call(name: str, arguments: dict, prose: str | None = None) -> LLMResponse:
    call = ToolCall(call_id="call_1", tool_name=name, arguments=arguments)
    return LLMResponse(text=prose, tool_calls=(call,), finish_reason="tool_calls", usage=_USAGE)


def _build(
    script: list[LLMResponse], tools: list[Tool]
) -> tuple[Agent, list[PipelineEvent], EventBus, FakeProvider]:
    bus = EventBus()
    events: list[PipelineEvent] = []
    bus.subscribe(events.append)
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    executor = Executor(registry, bus, ToolContext(settings=Settings()), tool_timeout_s=2.0)
    provider = FakeProvider("gemini", script)
    agent = Agent(
        ProviderManager({"gemini": provider}, active="gemini"),
        Planner(system_prompt="you are NOVA"),
        Router(known_tool_names=registry.names),
        ConversationState(),
        bus,
        registry=registry,
        executor=executor,
    )
    return agent, events, bus, provider


def _stages(events: list[PipelineEvent]) -> list[tuple[PipelineStage, EventStatus]]:
    return [(e.stage, e.status) for e in events]


class TestSingleStepTool:
    def test_calculator_round_trip_event_stream(self) -> None:
        agent, events, _bus, provider = _build(
            [
                _tool_call("calculator", {"expression": "12 * 9"}, prose="I'll work that out."),
                _reply("12 times 9 is 108!"),
            ],
            [CalculatorTool()],
        )

        reply = agent.handle(_user_input("what is 12 * 9?"))

        assert reply.text == "12 times 9 is 108!"
        assert _stages(events) == [
            (PipelineStage.LISTENING, EventStatus.SKIPPED),
            (PipelineStage.TRANSCRIBING, EventStatus.SKIPPED),
            (PipelineStage.THINKING, EventStatus.STARTED),
            (PipelineStage.SELECTING_TOOL, EventStatus.STARTED),
            (PipelineStage.SELECTING_TOOL, EventStatus.COMPLETED),
            (PipelineStage.EXECUTING, EventStatus.STARTED),
            (PipelineStage.EXECUTING, EventStatus.COMPLETED),
            (PipelineStage.OBSERVING, EventStatus.STARTED),
            (PipelineStage.OBSERVING, EventStatus.COMPLETED),
            (PipelineStage.THINKING, EventStatus.COMPLETED),
            (PipelineStage.REMEMBERING, EventStatus.SKIPPED),
            (PipelineStage.RESPONDING, EventStatus.STARTED),
            (PipelineStage.RESPONDING, EventStatus.COMPLETED),
        ]
        # FR-18: the prose sentence became the SELECTING_TOOL detail
        selecting = next(e for e in events if e.stage == PipelineStage.SELECTING_TOOL)
        assert selecting.detail == "I'll work that out."
        assert selecting.payload["icon"] == "calculator"
        # the tool result actually reached the LLM
        second_call_messages = provider.calls[1][0]
        tool_message = next(m for m in second_call_messages if m.role == "tool")
        assert '"status": "ok"' in tool_message.content
        assert "108" in tool_message.content

    def test_schemas_are_sent_to_the_provider(self) -> None:
        agent, _events, _bus, provider = _build([_reply("hi")], [CalculatorTool()])
        agent.handle(_user_input())
        _messages, tools, _opts = provider.calls[0]
        assert [t.name for t in tools] == ["calculator"]


class TestToolErrorFedBack:
    def test_error_envelope_reaches_llm_and_reply_stays_conversational(self) -> None:
        agent, events, _bus, provider = _build(
            [
                _tool_call("failing", {}),
                _reply("Oops, that didn't work — sorry!"),
            ],
            [_FailingTool()],
        )

        reply = agent.handle(_user_input())

        assert reply.text == "Oops, that didn't work — sorry!"
        tool_message = next(m for m in provider.calls[1][0] if m.role == "tool")
        assert '"error_code": "broke"' in tool_message.content
        assert (PipelineStage.EXECUTING, EventStatus.FAILED) in _stages(events)
        assert PipelineStage.ERROR not in {e.stage for e in events}  # honest, not fatal


class TestConfirmationGate:
    def _run(self, approved: bool) -> tuple[str, _GatedTool, list[PipelineEvent], FakeProvider]:
        tool = _GatedTool()
        final = "Done!" if approved else "Okay, I won't touch anything!"
        agent, events, bus, provider = _build([_tool_call("gated", {}), _reply(final)], [tool])

        def answer(event: PipelineEvent) -> None:
            if (
                event.stage == PipelineStage.AWAITING_CONFIRMATION
                and event.status == EventStatus.STARTED
            ):
                agent.confirm(event.payload["call_id"], approved)

        bus.subscribe(answer)
        reply = agent.handle(_user_input("tidy my desktop"))
        return reply.text, tool, events, provider

    def test_approved_runs_the_tool(self) -> None:
        text, tool, events, _provider = self._run(approved=True)
        assert text == "Done!"
        assert tool.executed is True
        assert (PipelineStage.AWAITING_CONFIRMATION, EventStatus.COMPLETED) in _stages(events)

    def test_denied_feeds_denial_back_and_tool_never_runs(self) -> None:
        text, tool, events, provider = self._run(approved=False)
        assert text == "Okay, I won't touch anything!"
        assert tool.executed is False
        tool_message = next(m for m in provider.calls[1][0] if m.role == "tool")
        assert '"status": "denied"' in tool_message.content
        assert (PipelineStage.AWAITING_CONFIRMATION, EventStatus.FAILED) in _stages(events)


class TestMultiToolResponse:
    def test_two_calls_execute_sequentially_in_order(self) -> None:
        calls = (
            ToolCall(call_id="call_a", tool_name="calculator", arguments={"expression": "1+1"}),
            ToolCall(call_id="call_b", tool_name="calculator", arguments={"expression": "2+2"}),
        )
        response = LLMResponse(
            text=None, tool_calls=calls, finish_reason="tool_calls", usage=_USAGE
        )
        agent, _events, _bus, provider = _build([response, _reply("2 and 4")], [CalculatorTool()])

        agent.handle(_user_input())

        tool_messages = [m for m in provider.calls[1][0] if m.role == "tool"]
        assert [m.tool_call_id for m in tool_messages] == ["call_a", "call_b"]
