"""Executor: validate -> confirm -> watchdog -> normalize (docs/06 §2.3, T-302)."""

from __future__ import annotations

import threading
import time

from pydantic import BaseModel, Field

from nova.agent.executor import Executor
from nova.core.config import Settings
from nova.core.errors import ToolError
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import ToolCall
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec
from nova.tools.registry import ToolRegistry


class _Params(BaseModel):
    value: int = Field(ge=0)


class _ScriptedTool(Tool):
    """behavior: 'ok' | 'tool_error' | 'crash' | 'hang'."""

    def __init__(self, behavior: str = "ok", sensitive: bool = False) -> None:
        self._behavior = behavior
        self.spec = ToolSpec(
            name="scripted",
            title="Scripted",
            description="test tool",
            parameters=_Params,
            sensitive=sensitive,
            icon="zap",
            detail_template="Doing thing {value}",
        )
        self.executed = False

    def preview(self, args: BaseModel, ctx: ToolContext) -> list[str]:
        return ["Move a.txt into Documents"]

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        if self._behavior == "tool_error":
            raise ToolError("declared failure", code="my_code")
        if self._behavior == "crash":
            raise RuntimeError("boom")
        if self._behavior == "hang":
            time.sleep(5)
        self.executed = True
        return ToolOutput(data={"summary": "did it"})


def _executor(
    tool: _ScriptedTool, tool_timeout_s: float = 2.0, confirm_timeout_s: float = 120.0
) -> tuple[Executor, list[PipelineEvent], EventBus]:
    registry = ToolRegistry()
    registry.register(tool)
    bus = EventBus()
    events: list[PipelineEvent] = []
    bus.subscribe(events.append)
    ctx = ToolContext(settings=Settings())
    return Executor(registry, bus, ctx, tool_timeout_s, confirm_timeout_s), events, bus


def _call(arguments: dict | None = None) -> ToolCall:
    return ToolCall(call_id="call_1", tool_name="scripted", arguments=arguments or {"value": 1})


def _stages(events: list[PipelineEvent]) -> list[tuple[PipelineStage, EventStatus]]:
    return [(e.stage, e.status) for e in events]


def test_happy_path_emits_executing_pair() -> None:
    executor, events, bus = _executor(_ScriptedTool())
    result = executor.execute(_call(), "req_1")
    assert result.status == "ok"
    assert result.data == {"summary": "did it"}
    assert _stages(events) == [
        (PipelineStage.EXECUTING, EventStatus.STARTED),
        (PipelineStage.EXECUTING, EventStatus.COMPLETED),
    ]
    assert events[0].detail == "Doing thing 1"


def test_unknown_tool_is_defensive_error() -> None:
    executor, _events, _bus = _executor(_ScriptedTool())
    result = executor.execute(ToolCall(call_id="c", tool_name="ghost", arguments={}), "req_1")
    assert result.status == "error"
    assert result.error_code == "unknown_tool"


def test_invalid_args_produce_llm_readable_error() -> None:
    executor, events, bus = _executor(_ScriptedTool())
    result = executor.execute(_call({"value": -3}), "req_1")
    assert result.status == "error"
    assert result.error_code == "invalid_args"
    assert "value" in (result.error_message or "")
    assert events == []  # rejected before EXECUTING ever started


def test_tool_error_normalized_with_declared_code() -> None:
    executor, events, bus = _executor(_ScriptedTool("tool_error"))
    result = executor.execute(_call(), "req_1")
    assert result.status == "error"
    assert result.error_code == "my_code"
    assert _stages(events)[-1] == (PipelineStage.EXECUTING, EventStatus.FAILED)


def test_crash_normalized_never_raises() -> None:
    executor, _events, _bus = _executor(_ScriptedTool("crash"))
    result = executor.execute(_call(), "req_1")
    assert result.status == "error"
    assert result.error_code == "tool_error"


def test_watchdog_timeout() -> None:
    executor, events, bus = _executor(_ScriptedTool("hang"), tool_timeout_s=0.1)
    result = executor.execute(_call(), "req_1")
    assert result.status == "timeout"
    assert result.error_code == "timeout"
    assert _stages(events)[-1] == (PipelineStage.EXECUTING, EventStatus.FAILED)


def test_sensitive_approved_runs_tool() -> None:
    tool = _ScriptedTool(sensitive=True)
    executor, events, bus = _executor(tool)

    def approve_on_event(event: PipelineEvent) -> None:
        if (
            event.stage == PipelineStage.AWAITING_CONFIRMATION
            and event.status == EventStatus.STARTED
        ):
            executor.resolve_confirmation(event.payload["call_id"], approved=True)

    # subscribers run synchronously on the publishing thread — the answer lands before wait()
    bus.subscribe(approve_on_event)
    result = executor.execute(_call(), "req_1")

    assert result.status == "ok"
    assert tool.executed is True
    confirmation_events = [
        (e.status, e.payload) for e in events if e.stage == PipelineStage.AWAITING_CONFIRMATION
    ]
    assert confirmation_events[0][0] == EventStatus.STARTED
    assert confirmation_events[0][1]["preview"] == ["Move a.txt into Documents"]
    assert confirmation_events[1][0] == EventStatus.COMPLETED


def test_sensitive_denied_returns_denied_and_skips_execution() -> None:
    tool = _ScriptedTool(sensitive=True)
    executor, events, bus = _executor(tool)

    def deny_on_event(event: PipelineEvent) -> None:
        if (
            event.stage == PipelineStage.AWAITING_CONFIRMATION
            and event.status == EventStatus.STARTED
        ):
            executor.resolve_confirmation(event.payload["call_id"], approved=False)

    bus.subscribe(deny_on_event)
    result = executor.execute(_call(), "req_1")

    assert result.status == "denied"
    assert tool.executed is False
    assert (PipelineStage.AWAITING_CONFIRMATION, EventStatus.FAILED) in _stages(events)
    assert (PipelineStage.EXECUTING, EventStatus.SKIPPED) in _stages(events)


def test_confirmation_decision_timeout_is_denial() -> None:
    tool = _ScriptedTool(sensitive=True)
    executor, events, bus = _executor(tool, confirm_timeout_s=0.05)
    result = executor.execute(_call(), "req_1")
    assert result.status == "denied"
    assert tool.executed is False


def test_resolve_from_another_thread() -> None:
    """The real shape: worker thread blocked, main thread answers."""
    tool = _ScriptedTool(sensitive=True)
    executor, _events, _bus = _executor(tool)
    call = _call()

    def answer_later() -> None:
        time.sleep(0.05)
        executor.resolve_confirmation(call.call_id, approved=True)

    thread = threading.Thread(target=answer_later)
    thread.start()
    result = executor.execute(call, "req_1")
    thread.join()
    assert result.status == "ok"


def test_resolve_unknown_call_id_is_noop() -> None:
    executor, _events, _bus = _executor(_ScriptedTool())
    executor.resolve_confirmation("ghost", approved=True)  # must not raise
