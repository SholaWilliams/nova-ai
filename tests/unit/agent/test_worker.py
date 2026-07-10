"""Tests for AgentWorker — thread-boundary signal wiring (docs/03 §5).

Uses a minimal stub in place of a real Agent: Agent's own behavior is covered by
test_agent.py, so this file tests only AgentWorker's own signal wiring and busy-guard.
"""

from __future__ import annotations

from datetime import UTC, datetime

from nova.agent.agent import AgentCancelled
from nova.agent.worker import AgentWorker
from nova.core.models import AssistantReply, UserInput


class _StubAgent:
    def __init__(self) -> None:
        self.cancel_called = False
        self._outcome: AssistantReply | Exception | None = None

    def script(self, outcome: AssistantReply | Exception) -> None:
        self._outcome = outcome

    def handle(self, user_input: UserInput) -> AssistantReply:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        assert isinstance(self._outcome, AssistantReply)
        return self._outcome

    def cancel(self) -> None:
        self.cancel_called = True


def _user_input(request_id: str = "req_test") -> UserInput:
    return UserInput(request_id=request_id, text="hi", source="typed", ts=datetime.now(UTC))


def test_successful_request_emits_reply_ready(qtbot) -> None:  # noqa: ANN001
    agent = _StubAgent()
    reply = AssistantReply(request_id="req_test", text="hello", spoken_text="hello")
    agent.script(reply)
    worker = AgentWorker(agent)  # type: ignore[arg-type]

    with qtbot.waitSignal(worker.reply_ready, timeout=1000) as blocker:
        worker.handle_request(_user_input())

    assert blocker.args == [reply]


def test_cancelled_request_emits_request_cancelled(qtbot) -> None:  # noqa: ANN001
    agent = _StubAgent()
    agent.script(AgentCancelled())
    worker = AgentWorker(agent)  # type: ignore[arg-type]

    with qtbot.waitSignal(worker.request_cancelled, timeout=1000) as blocker:
        worker.handle_request(_user_input("req_5"))

    assert blocker.args == ["req_5"]


def test_unexpected_exception_emits_failed_with_friendly_message(qtbot) -> None:  # noqa: ANN001
    agent = _StubAgent()
    agent.script(RuntimeError("boom"))
    worker = AgentWorker(agent)  # type: ignore[arg-type]

    with qtbot.waitSignal(worker.failed, timeout=1000) as blocker:
        worker.handle_request(_user_input("req_9"))

    assert blocker.args[0] == "req_9"
    assert blocker.args[1]


def test_busy_worker_rejects_a_second_request(qtbot) -> None:  # noqa: ANN001
    agent = _StubAgent()
    agent.script(AssistantReply(request_id="req_test", text="x", spoken_text="x"))
    worker = AgentWorker(agent)  # type: ignore[arg-type]
    worker._busy = True  # simulate a request already in flight

    with qtbot.waitSignal(worker.request_rejected, timeout=1000) as blocker:
        worker.handle_request(_user_input("req_late"))

    assert blocker.args == ["req_late"]


def test_cancel_current_forwards_to_agent_cancel() -> None:
    agent = _StubAgent()
    worker = AgentWorker(agent)  # type: ignore[arg-type]

    worker.cancel_current()

    assert agent.cancel_called is True
