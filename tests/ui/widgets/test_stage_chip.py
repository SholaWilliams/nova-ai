"""Unit tests for nova.ui.widgets.stage_chip — state rendering and click-to-expand."""

from datetime import UTC, datetime

import pytest
from PySide6.QtCore import Qt

from nova.core.events import EventStatus, PipelineEvent, PipelineStage
from nova.ui.widgets.stage_chip import ChipState, StageChip


@pytest.fixture
def chip(qtbot: object) -> StageChip:
    widget = StageChip(PipelineStage.EXECUTING)
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.show()  # isVisible() on children reflects ancestor visibility too — must show it
    return widget


def _event(
    stage: PipelineStage,
    status: EventStatus,
    detail: str = "some detail",
    payload: dict | None = None,
) -> PipelineEvent:
    return PipelineEvent(
        request_id="req_test",
        stage=stage,
        status=status,
        detail=detail,
        payload=payload,
        ts=datetime.now(UTC),
    )


def test_starts_pending(chip: StageChip) -> None:
    assert chip._chip_state == ChipState.PENDING


def test_started_event_makes_chip_active(chip: StageChip) -> None:
    chip.apply_event(_event(PipelineStage.EXECUTING, EventStatus.STARTED, "Doing it"))
    assert chip._chip_state == ChipState.ACTIVE


def test_completed_event_makes_chip_done_and_stores_duration(chip: StageChip) -> None:
    chip.apply_event(
        _event(PipelineStage.EXECUTING, EventStatus.COMPLETED, payload={"duration_ms": 642})
    )
    assert chip._chip_state == ChipState.DONE
    assert chip._duration_ms == 642
    assert "0.6s" in chip._status_label.text()


def test_skipped_event_makes_chip_skipped(chip: StageChip) -> None:
    chip.apply_event(_event(PipelineStage.EXECUTING, EventStatus.SKIPPED, "not needed"))
    assert chip._chip_state == ChipState.SKIPPED
    assert "skipped" in chip._status_label.text()


def test_failed_event_makes_chip_failed(chip: StageChip) -> None:
    chip.apply_event(_event(PipelineStage.EXECUTING, EventStatus.FAILED, "it broke"))
    assert chip._chip_state == ChipState.FAILED


def test_event_for_a_different_stage_is_ignored(chip: StageChip) -> None:
    chip.apply_event(_event(PipelineStage.THINKING, EventStatus.STARTED))
    assert chip._chip_state == ChipState.PENDING


def test_reset_returns_to_pending_and_clears_detail(chip: StageChip) -> None:
    chip.apply_event(_event(PipelineStage.EXECUTING, EventStatus.COMPLETED, "done thing"))
    chip.reset()
    assert chip._chip_state == ChipState.PENDING
    assert chip._detail == ""
    assert chip._duration_ms is None
    assert not chip._detail_label.isVisible()


def test_pending_chip_click_does_not_expand(chip: StageChip, qtbot: object) -> None:
    qtbot.mouseClick(chip, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
    assert chip._expanded is False
    assert not chip._detail_label.isVisible()


def test_clicking_a_completed_chip_expands_and_collapses_detail(
    chip: StageChip, qtbot: object
) -> None:
    chip.apply_event(
        _event(PipelineStage.EXECUTING, EventStatus.COMPLETED, "Checking the weather in Lagos")
    )

    qtbot.mouseClick(chip, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
    assert chip._expanded is True
    assert chip._detail_label.isVisible()
    assert chip._detail_label.text() == "Checking the weather in Lagos"

    qtbot.mouseClick(chip, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
    assert chip._expanded is False
    assert not chip._detail_label.isVisible()


@pytest.mark.parametrize(
    ("stage", "expects_icon"),
    [
        (PipelineStage.LISTENING, True),
        (PipelineStage.THINKING, True),
        (PipelineStage.TRANSCRIBING, False),
        (PipelineStage.OBSERVING, False),
    ],
)
def test_icon_presence_matches_docs_05_table(
    qtbot: object, stage: PipelineStage, expects_icon: bool
) -> None:
    widget = StageChip(stage)
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    has_pixmap = (
        widget._icon_label.pixmap() is not None and not widget._icon_label.pixmap().isNull()
    )
    assert has_pixmap is expects_icon


def test_failed_state_shows_alert_triangle_even_for_icon_less_stage(qtbot: object) -> None:
    widget = StageChip(PipelineStage.TRANSCRIBING)
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    widget.apply_event(_event(PipelineStage.TRANSCRIBING, EventStatus.FAILED, "mic died"))

    pixmap = widget._icon_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
