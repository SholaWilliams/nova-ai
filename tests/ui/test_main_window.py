"""Unit tests for nova.ui.main_window — layout construction, chat/settings wiring (T-208/T-209)."""

import pytest
from PySide6.QtCore import Qt, QTimer

from nova.core.config import Settings
from nova.core.events import EventBus, PipelineStage
from nova.core.models import AssistantReply, ProviderStatus, UserInput
from nova.ui.main_window import MainWindow
from nova.ui.theme import Color
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


def test_nav_buttons_enabled_state(window: MainWindow) -> None:
    assert len(window._nav_buttons) == 4
    assert window._nav_buttons["house"].isEnabled()
    assert window._nav_buttons["settings"].isEnabled()
    assert not window._nav_buttons["history"].isEnabled()  # History lands in M5
    assert not window._nav_buttons["brain"].isEnabled()  # Memory lands in M5


# ── settings navigation (T-209) ───────────────────────────────────────


def test_settings_nav_switches_to_settings_page_and_hides_input_bar(window: MainWindow) -> None:
    window._nav_buttons["settings"].click()

    assert window._stack.currentWidget() is window._settings_view
    assert window._input_bar.isHidden()


def test_home_nav_switches_back_to_chat_page_and_shows_input_bar(window: MainWindow) -> None:
    window._nav_buttons["settings"].click()
    window._nav_buttons["house"].click()

    assert window._stack.currentIndex() == 0
    assert not window._input_bar.isHidden()


# ── chat/input-bar wiring (T-208) ─────────────────────────────────────


def test_sending_a_message_adds_a_user_bubble_and_emits_submit_requested(
    window: MainWindow, qtbot: object
) -> None:
    window._entry.setText("what's the weather?")

    with qtbot.waitSignal(window.submit_requested, timeout=1000) as blocker:  # type: ignore[attr-defined]
        window._send_button.click()

    user_input = blocker.args[0]
    assert isinstance(user_input, UserInput)
    assert user_input.text == "what's the weather?"
    assert user_input.source == "typed"
    assert window._chat_view.bubble_count() == 1
    assert window._entry.text() == ""


def test_sending_disables_entry_and_send_button(window: MainWindow) -> None:
    window._entry.setText("hello")
    window._send_button.click()

    assert not window._entry.isEnabled()
    assert not window._send_button.isEnabled()


def test_return_pressed_also_sends(window: MainWindow, qtbot: object) -> None:
    window._entry.setText("hello")

    with qtbot.waitSignal(window.submit_requested, timeout=1000):  # type: ignore[attr-defined]
        qtbot.keyClick(window._entry, Qt.Key.Key_Return)  # type: ignore[attr-defined]

    assert window._chat_view.bubble_count() == 1


def test_blank_input_does_not_send(window: MainWindow) -> None:
    window._entry.setText("   ")
    window._send_button.click()

    assert window._chat_view.bubble_count() == 0


def test_double_submit_guard_ignores_a_second_send_while_awaiting_reply(
    window: MainWindow,
) -> None:
    window._entry.setText("first")
    window._send_button.click()  # now awaiting a reply

    # simulate a stray re-enable/race rather than relying on Qt's own disabled-click
    # suppression, so this test isolates the `_awaiting_reply` guard itself
    window._entry.setEnabled(True)
    window._entry.setText("second")
    window._send_button.setEnabled(True)
    window._send_button.click()

    assert window._chat_view.bubble_count() == 1  # the second send was ignored


def test_on_reply_ready_adds_nova_bubble_and_re_enables_input(window: MainWindow) -> None:
    window._entry.setText("hi")
    window._send_button.click()

    window.on_reply_ready(AssistantReply(request_id="req_1", text="hello!", spoken_text="hello!"))

    assert window._chat_view.bubble_count() == 2
    assert window._entry.isEnabled()
    assert window._send_button.isEnabled()


def test_on_request_failed_adds_friendly_message_and_re_enables_input(window: MainWindow) -> None:
    window._entry.setText("hi")
    window._send_button.click()

    window.on_request_failed("req_1", "Something went wrong — let's try again.")

    assert window._chat_view.bubble_count() == 2
    assert window._entry.isEnabled()


def test_on_request_cancelled_re_enables_input_without_adding_a_bubble(
    window: MainWindow,
) -> None:
    window._entry.setText("hi")
    window._send_button.click()

    window.on_request_cancelled("req_1")

    assert window._chat_view.bubble_count() == 1  # only the user's own message
    assert window._entry.isEnabled()


def test_on_request_rejected_re_enables_input(window: MainWindow) -> None:
    window._entry.setText("hi")
    window._send_button.click()

    window.on_request_rejected("req_1")

    assert window._chat_view.bubble_count() == 1
    assert window._entry.isEnabled()


def test_escape_cancels_while_awaiting_reply(window: MainWindow, qtbot: object) -> None:
    window._entry.setText("hi")
    window._send_button.click()

    with qtbot.waitSignal(window.cancel_requested, timeout=1000):  # type: ignore[attr-defined]
        qtbot.keyClick(window, Qt.Key.Key_Escape)  # type: ignore[attr-defined]


def test_escape_does_nothing_when_not_awaiting_reply(window: MainWindow, qtbot: object) -> None:
    received: list[bool] = []
    window.cancel_requested.connect(lambda: received.append(True))

    qtbot.keyClick(window, Qt.Key.Key_Escape)  # type: ignore[attr-defined]

    assert received == []


# ── provider status (FR-43) ───────────────────────────────────────────


def test_set_provider_status_normal_mode_shows_detail_text(window: MainWindow) -> None:
    window.set_provider_status(ProviderStatus(active="gemini", mode="normal", detail="Gemini"))
    assert window._status_label.text() == "Gemini"


def test_set_provider_status_down_mode_uses_error_color(window: MainWindow) -> None:
    window.set_provider_status(
        ProviderStatus(active="gemini", mode="down", detail="I can't reach my brain right now")
    )
    assert window._status_label.text() == "I can't reach my brain right now"
    assert Color.STATE_ERROR in window._status_label.styleSheet()
