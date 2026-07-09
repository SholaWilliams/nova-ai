"""Unit tests for nova.ui.main_window — static layout construction and the debug button."""

import pytest
from PySide6.QtCore import QTimer

from nova.core.config import Settings
from nova.core.events import EventBus, PipelineStage
from nova.ui.main_window import MainWindow
from nova.ui.widgets.stage_chip import ChipState


@pytest.fixture(autouse=True)
def _run_timers_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """So a debug-button click's whole scripted sequence completes within the test, not ~9s."""
    monkeypatch.setattr(QTimer, "singleShot", lambda _ms, callback: callback())


@pytest.fixture
def window(qtbot: object) -> MainWindow:
    widget = MainWindow(EventBus(), Settings())
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    return widget


def test_constructs_without_error(window: MainWindow) -> None:
    assert window.windowTitle() == "NOVA"


def test_respects_minimum_size(window: MainWindow) -> None:
    assert (window.minimumWidth(), window.minimumHeight()) == (980, 640)


def test_pipeline_panel_visible_by_default(window: MainWindow) -> None:
    assert window._pipeline_view.isVisible() or not window._pipeline_view.isHidden()


def test_pipeline_panel_hidden_when_setting_disabled(qtbot: object) -> None:
    settings = Settings()
    settings.ui.pipeline_visible = False
    widget = MainWindow(EventBus(), settings)
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    assert widget._pipeline_view.isHidden()


def test_debug_button_runs_the_fake_pipeline_end_to_end(window: MainWindow) -> None:
    window._on_debug_button_clicked()

    # the (monkeypatched-synchronous) sequence has fully run and finished by the time
    # _on_debug_button_clicked returns, so the button should already be re-enabled.
    assert window._debug_button.isEnabled()
    assert window._debug_button.text() == "▶ Run demo pipeline"
    assert window._pipeline_view._chips[PipelineStage.SPEAKING]._chip_state == ChipState.DONE
    assert window._pipeline_view._chips[PipelineStage.REMEMBERING]._chip_state == (
        ChipState.SKIPPED
    )


def test_nav_buttons_are_present_but_disabled(window: MainWindow) -> None:
    nav_buttons = [
        child for child in window.findChildren(type(window._debug_button)) if child.width() == 32
    ]
    assert len(nav_buttons) == 4
    assert all(not button.isEnabled() for button in nav_buttons)
