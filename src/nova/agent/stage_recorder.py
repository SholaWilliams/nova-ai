"""StageRecorder: buffers `(stage, duration_ms)` pairs per `request_id` for `TurnRecord`
archival (docs/09 §3's `stages` field — the raw material for History's replay, FR-40
extension).

Subscribes to `EventBus` via its existing plain-callback mechanism (the same one
`core.logging.EventLogBridge` already uses) so it works regardless of which component
emitted a given stage — `Agent`/`Executor` publish on the main agent path, `SpeechService`
publishes LISTENING/TRANSCRIBING/SPEAKING from its own threads, all onto the same bus.
"""

from __future__ import annotations

from nova.core.events import EventBus, EventStatus, PipelineEvent

_TERMINAL_STATUSES = frozenset({EventStatus.COMPLETED, EventStatus.SKIPPED, EventStatus.FAILED})


class StageRecorder:
    def __init__(self, bus: EventBus) -> None:
        self._buffers: dict[str, list[tuple[str, int]]] = {}
        bus.subscribe(self._on_event)

    def _on_event(self, event: PipelineEvent) -> None:
        if event.status not in _TERMINAL_STATUSES:
            return
        duration_ms = (event.payload or {}).get("duration_ms", 0)
        self._buffers.setdefault(event.request_id, []).append((str(event.stage), duration_ms))

    def pop(self, request_id: str) -> list[tuple[str, int]]:
        """Returns and clears the buffered stages for `request_id` (call once per turn, at
        the point `Agent.handle()` is about to build the `TurnRecord`)."""
        return self._buffers.pop(request_id, [])
