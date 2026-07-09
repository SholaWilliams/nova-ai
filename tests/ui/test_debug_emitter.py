"""Unit tests for nova.ui.debug_emitter — the scripted fake pipeline sequence."""

import pytest
from PySide6.QtCore import QTimer

from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.ui.debug_emitter import _SCRIPT, emit_fake_pipeline


@pytest.fixture(autouse=True)
def _run_timers_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse QTimer.singleShot delays so the scripted sequence runs synchronously in tests."""
    monkeypatch.setattr(QTimer, "singleShot", lambda _ms, callback: callback())


def test_publishes_every_scripted_event_in_order() -> None:
    bus = EventBus()
    received: list[PipelineEvent] = []
    bus.subscribe(received.append)

    emit_fake_pipeline(bus)

    assert len(received) == len(_SCRIPT)
    for event, (stage, status, detail, payload) in zip(received, _SCRIPT, strict=True):
        assert event.stage == stage
        assert event.status == status
        assert event.detail == detail
        assert event.payload == payload


def test_all_events_share_one_request_id() -> None:
    bus = EventBus()
    received: list[PipelineEvent] = []
    bus.subscribe(received.append)

    emit_fake_pipeline(bus)

    request_ids = {event.request_id for event in received}
    assert len(request_ids) == 1


def test_on_finished_callback_fires_once_after_the_last_event() -> None:
    bus = EventBus()
    calls = []
    bus.subscribe(lambda e: calls.append(("event", e.stage)))

    finished_calls: list[None] = []
    emit_fake_pipeline(bus, on_finished=lambda: finished_calls.append(None))

    assert len(finished_calls) == 1
    assert calls[-1][0] == "event"  # the last bus activity was an event, not something after


def test_remembering_stage_is_skipped_matching_the_docs_05_mockup() -> None:
    bus = EventBus()
    received: list[PipelineEvent] = []
    bus.subscribe(received.append)

    emit_fake_pipeline(bus)

    remembering_events = [e for e in received if e.stage == PipelineStage.REMEMBERING]
    assert len(remembering_events) == 1
    assert remembering_events[0].status == EventStatus.SKIPPED


def test_two_calls_use_different_request_ids() -> None:
    bus = EventBus()
    received: list[PipelineEvent] = []
    bus.subscribe(received.append)

    emit_fake_pipeline(bus)
    emit_fake_pipeline(bus)

    request_ids = {event.request_id for event in received}
    assert len(request_ids) == 2
