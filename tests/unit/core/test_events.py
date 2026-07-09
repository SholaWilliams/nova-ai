"""Unit tests for nova.core.events — PipelineEvent and the EventBus (docs/11 §2)."""

import threading
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage


def _event(
    request_id: str = "req_1", stage: PipelineStage = PipelineStage.THINKING
) -> PipelineEvent:
    return PipelineEvent(
        request_id=request_id,
        stage=stage,
        status=EventStatus.STARTED,
        detail="Thinking...",
        payload=None,
        ts=datetime.now(UTC),
    )


def test_pipeline_event_is_frozen() -> None:
    event = _event()
    with pytest.raises(FrozenInstanceError):
        event.detail = "mutated"  # type: ignore[misc]


def test_subscribe_receives_published_event_synchronously() -> None:
    bus = EventBus()
    received: list[PipelineEvent] = []
    bus.subscribe(received.append)

    event = _event()
    bus.publish(event)

    assert received == [event]


def test_subscribers_receive_events_in_publish_order() -> None:
    bus = EventBus()
    received: list[PipelineStage] = []
    bus.subscribe(lambda e: received.append(e.stage))

    stages = [
        PipelineStage.THINKING,
        PipelineStage.SELECTING_TOOL,
        PipelineStage.EXECUTING,
        PipelineStage.RESPONDING,
    ]
    for stage in stages:
        bus.publish(_event(stage=stage))

    assert received == stages


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    received: list[PipelineEvent] = []
    bus.subscribe(received.append)
    bus.unsubscribe(received.append)

    bus.publish(_event())

    assert received == []


def test_unsubscribe_of_missing_callback_is_a_noop() -> None:
    bus = EventBus()
    bus.unsubscribe(lambda e: None)  # never subscribed — must not raise


def test_event_published_signal_delivers_on_main_thread(qtbot) -> None:  # noqa: ANN001
    bus = EventBus()
    main_thread = threading.current_thread()
    received: list[tuple[PipelineEvent, threading.Thread]] = []
    bus.event_published.connect(lambda e: received.append((e, threading.current_thread())))

    event = _event()
    worker = threading.Thread(target=lambda: bus.publish(event))

    with qtbot.waitSignal(bus.event_published, timeout=1000):
        worker.start()
    worker.join()

    assert len(received) == 1
    delivered_event, delivered_thread = received[0]
    assert delivered_event == event
    assert delivered_thread is main_thread


def test_event_published_signal_preserves_order_across_threads(qtbot) -> None:  # noqa: ANN001
    bus = EventBus()
    received: list[PipelineStage] = []
    stages = [
        PipelineStage.LISTENING,
        PipelineStage.TRANSCRIBING,
        PipelineStage.THINKING,
        PipelineStage.SELECTING_TOOL,
        PipelineStage.EXECUTING,
    ]
    bus.event_published.connect(lambda e: received.append(e.stage))

    def publish_all() -> None:
        for stage in stages:
            bus.publish(_event(stage=stage))

    worker = threading.Thread(target=publish_all)
    worker.start()
    worker.join()
    qtbot.wait_until(lambda: len(received) == len(stages), timeout=1000)

    assert received == stages
