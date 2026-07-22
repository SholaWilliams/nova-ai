"""Unit tests for nova.ui.main_window — layout construction, chat/settings wiring (T-208/T-209)."""

from datetime import UTC, datetime

import pytest
from PySide6.QtCore import Qt, QTimer

from nova.core.config import Settings
from nova.core.events import EventBus, PipelineStage
from nova.core.models import (
    AssistantReply,
    MemoryItem,
    ProviderStatus,
    SessionMeta,
    Transcript,
    TurnRecord,
    UserInput,
)
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
    assert window._nav_buttons["history"].isEnabled()  # M5
    assert window._nav_buttons["brain"].isEnabled()  # M5


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


# ── voice (M4) ──────────────────────────────────────────────────────


def test_mic_click_when_idle_emits_mic_pressed_with_the_configured_device(
    window: MainWindow, qtbot: object
) -> None:
    window._settings.voice.input_device = 3

    with qtbot.waitSignal(window.mic_pressed, timeout=1000) as blocker:  # type: ignore[attr-defined]
        window._mic_button.click()

    assert blocker.args == [3]
    assert window._listening is True
    assert not window._entry.isEnabled()
    assert not window._send_button.isEnabled()


def test_mic_click_also_stops_any_ongoing_speech(window: MainWindow, qtbot: object) -> None:
    with qtbot.waitSignal(window.stop_speaking_requested, timeout=1000):  # type: ignore[attr-defined]
        window._mic_button.click()


def test_mic_click_while_listening_emits_mic_repressed(window: MainWindow, qtbot: object) -> None:
    window._mic_button.click()  # now listening

    with qtbot.waitSignal(window.mic_repressed, timeout=1000):  # type: ignore[attr-defined]
        window._mic_button.click()


def test_mic_click_is_ignored_while_awaiting_a_reply(window: MainWindow) -> None:
    window._entry.setText("hi")
    window._send_button.click()  # now awaiting a reply

    received: list[object] = []
    window.mic_pressed.connect(lambda device: received.append(device))
    window._mic_button.click()

    assert received == []


def test_escape_while_listening_emits_listening_cancelled_not_cancel_requested(
    window: MainWindow, qtbot: object
) -> None:
    window._mic_button.click()  # now listening
    cancel_received: list[bool] = []
    window.cancel_requested.connect(lambda: cancel_received.append(True))

    with qtbot.waitSignal(window.listening_cancelled, timeout=1000):  # type: ignore[attr-defined]
        qtbot.keyClick(window, Qt.Key.Key_Escape)  # type: ignore[attr-defined]

    assert cancel_received == []


def test_transcript_ready_with_text_adds_user_bubble_and_submits_as_voice(
    window: MainWindow, qtbot: object
) -> None:
    window._mic_button.click()

    with qtbot.waitSignal(window.submit_requested, timeout=1000) as blocker:  # type: ignore[attr-defined]
        window.on_transcript_ready(Transcript(request_id="req_v1", text="hi nova", confidence=0.9))

    user_input = blocker.args[0]
    assert user_input.source == "voice"
    assert user_input.request_id == "req_v1"
    assert window._chat_view.bubble_count() == 1
    assert window._listening is False


def test_transcript_ready_with_empty_text_shows_a_friendly_nudge(window: MainWindow) -> None:
    window._mic_button.click()

    window.on_transcript_ready(Transcript(request_id="req_v2", text="", confidence=None))

    assert window._chat_view.bubble_count() == 1  # only the nudge, no user bubble
    assert window._listening is False


def test_explicit_cancel_suppresses_the_friendly_nudge(window: MainWindow, qtbot: object) -> None:
    window._mic_button.click()
    qtbot.keyClick(window, Qt.Key.Key_Escape)  # type: ignore[attr-defined]

    window.on_transcript_ready(Transcript(request_id="req_v3", text="", confidence=None))

    assert window._chat_view.bubble_count() == 0  # silent discard, no bubble at all


def test_on_listen_failed_shows_message_and_resets_listening_state(window: MainWindow) -> None:
    window._mic_button.click()

    window.on_listen_failed("Something went wrong while I was listening.")

    assert window._listening is False
    assert window._chat_view.bubble_count() == 1


def test_set_mic_available_false_disables_the_mic_button(window: MainWindow) -> None:
    window.set_mic_available(False)

    assert not window._mic_button.isEnabled()


def test_set_mic_available_true_re_enables_the_mic_button(window: MainWindow) -> None:
    window.set_mic_available(False)
    window.set_mic_available(True)

    assert window._mic_button.isEnabled()


def test_sending_typed_text_also_stops_any_ongoing_speech(
    window: MainWindow, qtbot: object
) -> None:
    window._entry.setText("hello")

    with qtbot.waitSignal(window.stop_speaking_requested, timeout=1000):  # type: ignore[attr-defined]
        window._send_button.click()


def test_set_voice_mode_offline_shows_the_backup_voice_indicator(window: MainWindow) -> None:
    window.set_voice_mode("offline")
    assert not window._voice_status_label.isHidden()

    window.set_voice_mode("primary")
    assert window._voice_status_label.isHidden()


# ── Memory View / History drawer (M5) ──────────────────────────────────


def _fact(content: str = "Has a dog", fact_id: str = "f_1") -> MemoryItem:
    return MemoryItem(
        id=fact_id,
        kind="fact",
        content=content,
        keywords=(),
        created_at=datetime.now(UTC),
        source_request="req_1",
    )


def _session(session_id: str = "s_1", title: str = "hello") -> SessionMeta:
    return SessionMeta(session_id=session_id, started_at=datetime.now(UTC), title=title, turns=1)


def test_memory_nav_switches_to_memory_page_and_hides_input_bar(window: MainWindow) -> None:
    window._nav_buttons["brain"].click()

    assert window._stack.currentWidget() is window._memory_view
    assert window._input_bar.isHidden()


def test_set_memory_facts_forwards_to_the_memory_view(window: MainWindow) -> None:
    window.set_memory_facts([_fact(), _fact(fact_id="f_2")])
    assert window._memory_view.card_count() == 2


def test_memory_view_delete_forwards_to_delete_fact_requested(
    window: MainWindow, qtbot: object
) -> None:
    window.set_memory_facts([_fact(fact_id="f_9")])
    card = window._memory_view._column_layout.itemAt(0).widget()

    with qtbot.waitSignal(window.delete_fact_requested, timeout=1000) as blocker:  # type: ignore[attr-defined]
        card.delete_requested.emit("f_9")

    assert blocker.args == ["f_9"]


def test_history_dock_hidden_by_default(window: MainWindow) -> None:
    assert window._history_dock.isHidden()


def test_history_nav_toggles_the_dock(window: MainWindow) -> None:
    window._nav_buttons["history"].click()
    assert not window._history_dock.isHidden()

    window._nav_buttons["history"].click()
    assert window._history_dock.isHidden()


def test_set_sessions_populates_the_list(window: MainWindow) -> None:
    window.set_sessions([_session("s_1", "first chat"), _session("s_2", "second chat")])

    assert window._session_list.count() == 2
    assert "first chat" in window._session_list.item(0).text()


def test_clicking_a_session_emits_session_selected(window: MainWindow, qtbot: object) -> None:
    window.set_sessions([_session("s_42", "hello there")])

    with qtbot.waitSignal(window.session_selected, timeout=1000) as blocker:  # type: ignore[attr-defined]
        window._session_list.item(0).setSelected(True)
        window._on_session_item_clicked(window._session_list.item(0))

    assert blocker.args == ["s_42"]


def test_new_conversation_clears_chat_and_emits_signal(window: MainWindow, qtbot: object) -> None:
    window._entry.setText("hi")
    window._send_button.click()
    window.on_reply_ready(AssistantReply(request_id="req_1", text="hello!", spoken_text="hello!"))
    assert window._chat_view.bubble_count() == 2

    with qtbot.waitSignal(window.new_conversation_requested, timeout=1000):  # type: ignore[attr-defined]
        window._on_new_conversation_clicked()

    assert window._chat_view.bubble_count() == 0


def test_show_session_replay_populates_read_only_view_and_switches_page(
    window: MainWindow,
) -> None:
    turns = [
        TurnRecord(
            request_id="req_1",
            ts=datetime.now(UTC),
            user_text="what's the weather?",
            user_source="typed",
            assistant_text="It's sunny!",
            tools=(),
            stages=(),
        )
    ]

    window.show_session_replay(turns)

    assert window._history_chat_view.bubble_count() == 2
    assert window._stack.currentWidget() is window._stack.widget(3)
    assert window._input_bar.isHidden()


def test_back_to_today_returns_to_home_page(window: MainWindow) -> None:
    window.show_session_replay([])
    back_button = window._stack.widget(3).layout().itemAt(0).widget()

    back_button.click()

    assert window._stack.currentIndex() == 0
    assert not window._input_bar.isHidden()


class TestConfirmationGateWiring:
    """AWAITING_CONFIRMATION started -> dialog -> confirmation_answered (FR-20, M3)."""

    def _emit_confirmation_event(self, bus: EventBus) -> None:
        from datetime import UTC, datetime

        from nova.core.events import EventStatus, PipelineEvent

        bus.publish(
            PipelineEvent(
                request_id="req_c",
                stage=PipelineStage.AWAITING_CONFIRMATION,
                status=EventStatus.STARTED,
                detail="Asking your permission",
                payload={
                    "call_id": "call_9",
                    "detail": "Tidying up your Desktop",
                    "preview": ["Move a.png into Pictures"],
                },
                ts=datetime.now(UTC),
            )
        )

    @pytest.mark.parametrize("accepted", [True, False])
    def test_dialog_answer_is_emitted_with_call_id(
        self, qtbot: object, monkeypatch: pytest.MonkeyPatch, accepted: bool
    ) -> None:
        from PySide6.QtWidgets import QDialog

        from nova.ui.widgets.confirm_dialog import ConfirmDialog

        bus = EventBus()
        window = MainWindow(bus, Settings())
        qtbot.addWidget(window)  # type: ignore[attr-defined]
        code = QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
        monkeypatch.setattr(ConfirmDialog, "exec", lambda self: code)

        answers: list[tuple[str, bool]] = []
        window.confirmation_answered.connect(lambda cid, ok: answers.append((cid, ok)))

        self._emit_confirmation_event(bus)

        assert answers == [("call_9", accepted)]
