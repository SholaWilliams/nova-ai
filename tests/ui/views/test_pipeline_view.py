"""Unit tests for nova.ui.views.pipeline_view — event routing to the ring, word, and rail."""

from datetime import UTC, datetime

import pytest

from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.ui.views.pipeline_view import RAIL_STAGES, PipelineView, pulse_state_for
from nova.ui.widgets.pulse_ring import PulseState
from nova.ui.widgets.stage_chip import ChipState


@pytest.fixture
def view(qtbot: object) -> PipelineView:
    widget = PipelineView(EventBus())
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    return widget


def _event(
    stage: PipelineStage,
    status: EventStatus = EventStatus.STARTED,
    detail: str = "detail",
    request_id: str = "req_1",
    payload: dict | None = None,
) -> PipelineEvent:
    return PipelineEvent(
        request_id=request_id,
        stage=stage,
        status=status,
        detail=detail,
        payload=payload,
        ts=datetime.now(UTC),
    )


def test_builds_a_chip_for_every_rail_stage(view: PipelineView) -> None:
    assert set(view._chips.keys()) == set(RAIL_STAGES)


def test_idle_and_awaiting_confirmation_have_no_rail_chip(view: PipelineView) -> None:
    assert PipelineStage.IDLE not in view._chips
    assert PipelineStage.AWAITING_CONFIRMATION not in view._chips


def test_event_updates_the_matching_chip(view: PipelineView) -> None:
    view._bus.publish(_event(PipelineStage.THINKING, EventStatus.STARTED))
    assert view._chips[PipelineStage.THINKING]._chip_state == ChipState.ACTIVE


def test_event_updates_the_pulse_ring(view: PipelineView) -> None:
    view._bus.publish(_event(PipelineStage.THINKING, EventStatus.STARTED))
    assert view._pulse_ring._state == PulseState.THINKING


def test_event_updates_the_stage_word_from_detail(view: PipelineView) -> None:
    view._bus.publish(_event(PipelineStage.EXECUTING, detail="Checking the weather in Lagos"))
    assert view._stage_word.text() == "Checking the weather in Lagos"


def test_error_stage_updates_ring_but_has_no_chip(view: PipelineView) -> None:
    view._bus.publish(_event(PipelineStage.ERROR, detail="Oops — something went wrong"))
    assert view._pulse_ring._state == PulseState.ERROR
    assert PipelineStage.ERROR not in view._chips


def test_new_request_id_resets_all_chips_before_applying_its_event(view: PipelineView) -> None:
    view._bus.publish(_event(PipelineStage.EXECUTING, EventStatus.COMPLETED, request_id="req_1"))
    assert view._chips[PipelineStage.EXECUTING]._chip_state == ChipState.DONE

    view._bus.publish(_event(PipelineStage.LISTENING, EventStatus.STARTED, request_id="req_2"))

    assert view._chips[PipelineStage.EXECUTING]._chip_state == ChipState.PENDING
    assert view._chips[PipelineStage.LISTENING]._chip_state == ChipState.ACTIVE


def test_same_request_id_does_not_reset_completed_chips(view: PipelineView) -> None:
    view._bus.publish(_event(PipelineStage.LISTENING, EventStatus.COMPLETED, request_id="req_1"))
    view._bus.publish(_event(PipelineStage.THINKING, EventStatus.STARTED, request_id="req_1"))

    assert view._chips[PipelineStage.LISTENING]._chip_state == ChipState.DONE
    assert view._chips[PipelineStage.THINKING]._chip_state == ChipState.ACTIVE


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        (PipelineStage.IDLE, PulseState.IDLE),
        (PipelineStage.LISTENING, PulseState.LISTENING),
        (PipelineStage.TRANSCRIBING, PulseState.LISTENING),
        (PipelineStage.THINKING, PulseState.THINKING),
        (PipelineStage.AWAITING_CONFIRMATION, PulseState.EXECUTING),
        (PipelineStage.EXECUTING, PulseState.EXECUTING),
        (PipelineStage.SPEAKING, PulseState.SPEAKING),
        (PipelineStage.ERROR, PulseState.ERROR),
    ],
)
def test_pulse_state_for_mapping(stage: PipelineStage, expected: PulseState) -> None:
    assert pulse_state_for(stage) == expected
