"""Pipeline stages and the EventBus — the single source of truth for the UI and the logs (A-2).

Contract source: docs/03 §7.1 (stage list) and docs/11 §2 (wire shape). The visualization
can never lie (NG-9) because it has no separate data source: every consumer, including the
debug emitter (`nova.ui.debug_emitter`), goes through this same bus.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QObject, Signal


class PipelineStage(StrEnum):
    """Every stage a request can pass through, in canonical/display order (docs/03 §7.1)."""

    IDLE = "IDLE"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    SELECTING_TOOL = "SELECTING_TOOL"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    REMEMBERING = "REMEMBERING"
    RESPONDING = "RESPONDING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class EventStatus(StrEnum):
    """Lifecycle status of a single stage occurrence.

    A `started` for a given (request_id, stage) must be followed by exactly one of
    `completed | skipped | failed` (event law, ARCHITECTURE_RULES.md).
    """

    STARTED = "started"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class PipelineEvent:
    """One instrumentation record. `detail` is child-facing copy (docs/05 §9)."""

    request_id: str
    stage: PipelineStage
    status: EventStatus
    detail: str
    payload: dict[str, Any] | None
    ts: datetime


class EventBus(QObject):
    """Fans out PipelineEvents to subscribers, thread-safely.

    `publish()` may be called from any thread (main, AgentWorker, SpeechIn/Out — docs/03 §5).
    Two subscription mechanisms:

    - `subscribe(callback)`: a plain callback invoked synchronously, on the publishing
      thread, in publish order. For lightweight, thread-safe consumers such as the
      logging bridge (`core.logging.EventLogBridge`).
    - the `event_published` Qt signal: connect with the default `AutoConnection` and Qt
      redelivers on the *receiver's* thread via a queued connection — the mechanism UI
      widgets should use, since Qt only allows touching widgets from the main thread.

    Ordering guarantee: because only one request is processed at a time (docs/03 §5) and
    Qt's queued connections are FIFO per receiver, events for a given `request_id` arrive
    in publish order down both paths.
    """

    event_published = Signal(object)  # emits PipelineEvent

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[PipelineEvent], None]] = []

    def publish(self, event: PipelineEvent) -> None:
        """Publish an event to every subscriber. Safe to call from any thread."""
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            callback(event)
        self.event_published.emit(event)

    def subscribe(self, callback: Callable[[PipelineEvent], None]) -> None:
        """Register a plain-callback subscriber (e.g. the logging bridge)."""
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[PipelineEvent], None]) -> None:
        """Remove a previously registered subscriber. No-op if it isn't registered."""
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)
