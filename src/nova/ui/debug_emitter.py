"""Dev-only pipeline emitter — exercises the UI end-to-end before the real agent exists (M2+).

AGENTS.md sanctions this explicitly: "UI work: run `python -m nova` and use the debug
pipeline emitter rather than burning API calls." This does not violate the "pipeline events
are never faked" production rule (AGENTS.md rule 3) — it is never imported by `agent`, never
reachable from a real request, and only ever wired to a clearly-labeled dev affordance.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QTimer

from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage

_STEP_DELAY_MS = 550

# Mirrors the walkthrough in docs/05 §6.1 (a "what's the weather in Lagos" request): every
# stage completes except Remembering, shown skipped — matching that mockup exactly, and
# exercising the skipped-chip rendering along the way.
_SCRIPT: list[tuple[PipelineStage, EventStatus, str, dict[str, Any] | None]] = [
    (PipelineStage.LISTENING, EventStatus.STARTED, "Listening…", None),
    (PipelineStage.LISTENING, EventStatus.COMPLETED, "Heard you", {"duration_ms": 810}),
    (PipelineStage.TRANSCRIBING, EventStatus.STARTED, "Understanding your words", None),
    (
        PipelineStage.TRANSCRIBING,
        EventStatus.COMPLETED,
        "What's the weather in Lagos?",
        {"text": "What's the weather in Lagos?", "confidence": 0.94, "duration_ms": 410},
    ),
    (PipelineStage.THINKING, EventStatus.STARTED, "Thinking…", None),
    (PipelineStage.THINKING, EventStatus.COMPLETED, "Figured out a plan", {"duration_ms": 1180}),
    (PipelineStage.SELECTING_TOOL, EventStatus.STARTED, "Choosing a tool", None),
    (
        PipelineStage.SELECTING_TOOL,
        EventStatus.COMPLETED,
        "Picked the Weather tool",
        {
            "tool_name": "weather",
            "tool_title": "Weather",
            "icon": "cloud-sun",
            "duration_ms": 90,
        },
    ),
    (PipelineStage.EXECUTING, EventStatus.STARTED, "Checking the weather in Lagos", None),
    (
        PipelineStage.EXECUTING,
        EventStatus.COMPLETED,
        "Checking the weather in Lagos",
        {"tool_name": "weather", "duration_ms": 640},
    ),
    (PipelineStage.OBSERVING, EventStatus.STARTED, "Checking the result", None),
    (PipelineStage.OBSERVING, EventStatus.COMPLETED, "Looks good", {"duration_ms": 60}),
    (PipelineStage.REMEMBERING, EventStatus.SKIPPED, "Nothing new to remember", None),
    (PipelineStage.RESPONDING, EventStatus.STARTED, "Getting my answer ready", None),
    (
        PipelineStage.RESPONDING,
        EventStatus.COMPLETED,
        "It's 31° and sunny in Lagos!",
        {"duration_ms": 220},
    ),
    (PipelineStage.SPEAKING, EventStatus.STARTED, "Speaking", None),
    (PipelineStage.SPEAKING, EventStatus.COMPLETED, "Done speaking", {"duration_ms": 1600}),
]


def _new_request_id() -> str:
    return f"req_{secrets.token_hex(4)}"


def emit_fake_pipeline(bus: EventBus, on_finished: Callable[[], None] | None = None) -> None:
    """Publish `_SCRIPT` as a QTimer-paced sequence of real PipelineEvents on `bus`.

    Main-thread only (drives Qt timers) — call from a button click handler, not a worker.
    """
    request_id = _new_request_id()

    def publish_step(index: int) -> None:
        if index >= len(_SCRIPT):
            if on_finished is not None:
                on_finished()
            return
        stage, status, detail, payload = _SCRIPT[index]
        bus.publish(
            PipelineEvent(
                request_id=request_id,
                stage=stage,
                status=status,
                detail=detail,
                payload=payload,
                ts=datetime.now(UTC),
            )
        )
        QTimer.singleShot(_STEP_DELAY_MS, lambda: publish_step(index + 1))

    publish_step(0)
