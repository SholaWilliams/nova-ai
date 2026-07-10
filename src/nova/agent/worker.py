"""AgentWorker: runs Agent.handle() off the main thread (docs/03 §5).

A `QObject` moved to a `QThread` via `.moveToThread()` (in `app.py`) — not a `QThread`
subclass — matching the only other cross-thread precedent in this codebase
(`core.events.EventBus`): Qt's signal/slot system is the app's one cross-thread idiom (TD-3),
not two competing ones. Not named in docs/03 §3's literal `agent/` file list, but docs/03 §5
requires the runtime component ("AgentWorker (QThread)") and docs/11 §4 says `Agent.handle`
runs on it.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from nova.agent.agent import Agent, AgentCancelled
from nova.core.models import UserInput

logger = logging.getLogger(__name__)

_DEFAULT_FRIENDLY_MESSAGE = "Something went wrong on my end — let's try that again."


class AgentWorker(QObject):
    """Owns the one in-flight `Agent.handle()` call. Lives on its own `QThread`."""

    reply_ready = Signal(object)  # AssistantReply
    request_rejected = Signal(str)  # request_id — arrived while one was already in flight
    request_cancelled = Signal(str)  # request_id
    failed = Signal(str, str)  # request_id, friendly_message — last-resort safety net

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agent = agent
        self._busy = False

    def handle_request(self, user_input: UserInput) -> None:
        """Slot — connect with a queued (cross-thread) connection from the main thread.

        `_busy` is a belt-and-suspenders backstop; `MainWindow` is expected to already gate
        submission on the main thread (disabling Send the instant a request goes out).
        """
        if self._busy:
            self.request_rejected.emit(user_input.request_id)
            return
        self._busy = True
        try:
            reply = self._agent.handle(user_input)
        except AgentCancelled:
            self.request_cancelled.emit(user_input.request_id)
        except Exception as exc:  # last-resort safety net (Agent already handles NovaErrors)
            logger.exception("Unhandled error in Agent.handle")
            friendly = getattr(exc, "friendly_message", _DEFAULT_FRIENDLY_MESSAGE)
            self.failed.emit(user_input.request_id, friendly)
        else:
            self.reply_ready.emit(reply)
        finally:
            self._busy = False

    def cancel_current(self) -> None:
        """Call directly (never via a queued connection) from any thread.

        `Agent.cancel()` must reach the running `handle()` call *while it's still blocked* —
        a queued Qt connection would sit undelivered in this object's own event queue until
        the busy `handle_request()` call returns, since both would share the same worker
        thread's single event loop. See `Agent.cancel()`'s docstring for the full reasoning.
        """
        self._agent.cancel()
