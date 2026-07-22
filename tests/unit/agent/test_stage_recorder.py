"""Tests for StageRecorder (docs/09 §3 `stages` field) — real EventBus, synthetic events."""

from __future__ import annotations

from datetime import UTC, datetime

from nova.agent.stage_recorder import StageRecorder
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage


def _event(
    request_id: str,
    stage: PipelineStage,
    status: EventStatus,
    duration_ms: int | None = None,
) -> PipelineEvent:
    payload = {"duration_ms": duration_ms} if duration_ms is not None else None
    return PipelineEvent(
        request_id=request_id,
        stage=stage,
        status=status,
        detail="",
        payload=payload,
        ts=datetime.now(UTC),
    )


def test_records_terminal_events_with_their_duration() -> None:
    bus = EventBus()
    recorder = StageRecorder(bus)

    bus.publish(_event("req_1", PipelineStage.THINKING, EventStatus.STARTED))
    bus.publish(_event("req_1", PipelineStage.THINKING, EventStatus.COMPLETED, duration_ms=100))
    bus.publish(_event("req_1", PipelineStage.RESPONDING, EventStatus.COMPLETED, duration_ms=5))

    assert recorder.pop("req_1") == [("THINKING", 100), ("RESPONDING", 5)]


def test_started_events_are_not_recorded() -> None:
    bus = EventBus()
    recorder = StageRecorder(bus)

    bus.publish(_event("req_1", PipelineStage.THINKING, EventStatus.STARTED))

    assert recorder.pop("req_1") == []


def test_skipped_and_failed_are_recorded_with_zero_duration_default() -> None:
    bus = EventBus()
    recorder = StageRecorder(bus)

    bus.publish(_event("req_1", PipelineStage.LISTENING, EventStatus.SKIPPED))
    bus.publish(_event("req_1", PipelineStage.ERROR, EventStatus.FAILED))

    assert recorder.pop("req_1") == [("LISTENING", 0), ("ERROR", 0)]


def test_pop_clears_the_buffer() -> None:
    bus = EventBus()
    recorder = StageRecorder(bus)
    bus.publish(_event("req_1", PipelineStage.THINKING, EventStatus.COMPLETED, duration_ms=1))

    first = recorder.pop("req_1")
    second = recorder.pop("req_1")

    assert first == [("THINKING", 1)]
    assert second == []


def test_pop_of_unknown_request_id_returns_empty() -> None:
    bus = EventBus()
    recorder = StageRecorder(bus)

    assert recorder.pop("nonexistent") == []


def test_different_request_ids_are_buffered_independently() -> None:
    bus = EventBus()
    recorder = StageRecorder(bus)

    bus.publish(_event("req_1", PipelineStage.THINKING, EventStatus.COMPLETED, duration_ms=1))
    bus.publish(_event("req_2", PipelineStage.THINKING, EventStatus.COMPLETED, duration_ms=2))

    assert recorder.pop("req_1") == [("THINKING", 1)]
    assert recorder.pop("req_2") == [("THINKING", 2)]
