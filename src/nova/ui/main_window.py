"""MainWindow: header, chat pane, pipeline panel, input bar (docs/05 §6.1).

M2 (T-208/T-209): the input bar and chat pane are wired to the agent stack via
`submit_requested`/`cancel_requested` signals — `app.py` connects these to `AgentWorker` and
routes its completion signals back to `on_reply_ready`/`on_request_failed`/
`on_request_cancelled`/`on_request_rejected`. Settings nav swaps in `SettingsView` via a
`QStackedWidget`. The dev-only "Run demo pipeline" button (T-109) remains alongside the real
wiring — see `nova.ui.debug_emitter` for why that doesn't violate the no-fake-events rule.
"""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nova.core.config import Settings
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.ids import new_request_id
from nova.core.models import (
    AssistantReply,
    MemoryItem,
    ProviderStatus,
    SessionMeta,
    Transcript,
    TurnRecord,
    UserInput,
)
from nova.ui import theme
from nova.ui.debug_emitter import emit_fake_pipeline
from nova.ui.theme import Color, Spacing
from nova.ui.views.chat_view import ChatView
from nova.ui.views.memory_view import MemoryView
from nova.ui.views.pipeline_view import PipelineView
from nova.ui.views.settings_view import SettingsView
from nova.ui.widgets.confirm_dialog import ConfirmDialog

_WINDOW_SIZE = (1200, 760)
_MIN_WINDOW_SIZE = (980, 640)
_HEADER_HEIGHT = 56
_INPUT_BAR_HEIGHT = 64
_MIC_BUTTON_SIZE = 64
_DEFAULT_PLACEHOLDER = "Type or press the mic to talk…"
_AWAITING_PLACEHOLDER = "One moment…"
_LISTENING_PLACEHOLDER = "Listening…"
_DIDNT_CATCH_TEXT = "I didn't catch that — try again?"
_NAV_ICONS: tuple[tuple[str, str], ...] = (
    ("house", "Home"),
    ("history", "History"),
    ("brain", "Memory"),
    ("settings", "Settings"),
)
_HOME_PAGE = 0
_SETTINGS_PAGE = 1
_MEMORY_PAGE = 2
_HISTORY_REPLAY_PAGE = 3
_SESSION_ID_ROLE = Qt.ItemDataRole.UserRole
_STATUS_COLOR_FOR_MODE = {
    "normal": Color.TEXT_SECONDARY,
    "fallback": Color.STATE_WARNING,
    "down": Color.STATE_ERROR,
}


class MainWindow(QMainWindow):
    """The whole app in one window (docs/05 §6.1): header / chat+pipeline split / input bar."""

    submit_requested = Signal(object)  # UserInput
    cancel_requested = Signal()
    confirmation_answered = Signal(str, bool)  # call_id, approved (FR-20)
    mic_pressed = Signal(object)  # device: int | None — start listening (M4)
    mic_repressed = Signal()  # re-press while listening: stop capturing, transcribe buffered
    listening_cancelled = Signal()  # Esc while listening: discard, no STT (docs/08 §2)
    stop_speaking_requested = Signal()  # speaker glyph / mic press / new input (FR-13)
    delete_fact_requested = Signal(str)  # fact id (FR-33, M5)
    clear_facts_requested = Signal()  # M5
    session_selected = Signal(str)  # session id (FR-5/6, M5)
    new_conversation_requested = Signal()  # M5

    def __init__(self, bus: EventBus, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._settings = settings
        self._awaiting_reply = False
        self._listening = False
        self._explicit_cancel = False
        self._mic_available = True
        self._pending_reply: AssistantReply | None = None
        self.setWindowTitle("NOVA")
        self.resize(*_WINDOW_SIZE)
        self.setMinimumSize(*_MIN_WINDOW_SIZE)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        self._chat_view = ChatView()
        self._chat_view.stop_speech_requested.connect(self.stop_speaking_requested)
        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.addWidget(self._chat_view)
        self._pipeline_view = PipelineView(bus, splitter)
        splitter.addWidget(self._pipeline_view)
        # persisted preference (docs/05 §6.1): presenter may want full-screen chat
        pipeline_width = int(_WINDOW_SIZE[0] * 0.4) if settings.ui.pipeline_visible else 0
        splitter.setSizes([_WINDOW_SIZE[0] - pipeline_width, pipeline_width])
        self._pipeline_view.setVisible(settings.ui.pipeline_visible)

        self._settings_view = SettingsView(settings)
        self._memory_view = MemoryView()
        self._memory_view.delete_requested.connect(self.delete_fact_requested)
        self._memory_view.clear_all_requested.connect(self.clear_facts_requested)

        self._stack = QStackedWidget(central)
        self._stack.addWidget(splitter)  # index _HOME_PAGE
        self._stack.addWidget(self._settings_view)  # index _SETTINGS_PAGE
        self._stack.addWidget(self._memory_view)  # index _MEMORY_PAGE
        self._stack.addWidget(self._build_history_replay_page())  # index _HISTORY_REPLAY_PAGE
        root.addWidget(self._stack, 1)

        self._input_bar = self._build_input_bar()
        root.addWidget(self._input_bar)

        self._build_history_dock()

        self._confirm_dialog: ConfirmDialog | None = None
        # EventBus delivers on the main thread (queued) — safe to open a modal from here.
        bus.event_published.connect(self._on_pipeline_event)

    # ── confirmation gate (docs/05 §6.6) ───────────────────────────────

    def _on_pipeline_event(self, event: PipelineEvent) -> None:
        if event.stage != PipelineStage.AWAITING_CONFIRMATION:
            return
        payload = event.payload or {}
        call_id = payload.get("call_id")
        if event.status == EventStatus.STARTED and call_id:
            self._ask_confirmation(call_id, payload)
        elif self._confirm_dialog is not None:
            # resolved elsewhere (decision timeout in the Executor) — close a stale dialog
            self._confirm_dialog.reject()

    def _ask_confirmation(self, call_id: str, payload: dict) -> None:
        detail = payload.get("detail") or "May I do that?"
        preview = list(payload.get("preview") or [])
        dialog = ConfirmDialog(detail, preview, self)
        self._confirm_dialog = dialog
        try:
            approved = dialog.exec() == ConfirmDialog.DialogCode.Accepted
        finally:
            self._confirm_dialog = None
        self.confirmation_answered.emit(call_id, approved)

    @property
    def settings_view(self) -> SettingsView:
        """`app.py`'s wiring surface for provider selection, key entry, and Test (T-209)."""
        return self._settings_view

    @property
    def pipeline_view(self) -> PipelineView:
        """`app.py`'s wiring surface for `SpeechInWorker.listening_level` (M4, T-401)."""
        return self._pipeline_view

    # ── header ───────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        header.setObjectName("surface")
        header.setFixedHeight(_HEADER_HEIGHT)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.MD, 0, Spacing.MD, 0)
        layout.setSpacing(Spacing.MD)

        logo = QLabel("●", header)
        logo.setStyleSheet(f"color: {theme.accent_hex('cyan')}; font-size: 18px;")
        layout.addWidget(logo)

        title = QLabel("NOVA", header)
        title_font = theme.font(theme.FontRole.LABEL)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # Honest placeholder until app.py's first `set_provider_status()` call lands.
        self._status_label = QLabel("offline · no provider set · mic unavailable", header)
        self._status_label.setFont(theme.font(theme.FontRole.CAPTION))
        self._status_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY};")
        layout.addWidget(self._status_label, 1)

        # docs/08 §4: "Voice: offline" status when pocket-tts fails and pyttsx3 is in use.
        self._voice_status_label = QLabel("· Voice: backup", header)
        self._voice_status_label.setFont(theme.font(theme.FontRole.CAPTION))
        self._voice_status_label.setStyleSheet(f"color: {Color.STATE_WARNING};")
        self._voice_status_label.setVisible(False)
        layout.addWidget(self._voice_status_label)

        self._debug_button = QPushButton("▶ Run demo pipeline", header)
        self._debug_button.setToolTip(
            "Dev only: plays a scripted pipeline sequence (see AGENTS.md's debug emitter)."
        )
        self._debug_button.clicked.connect(self._on_debug_button_clicked)
        layout.addWidget(self._debug_button)

        self._nav_buttons: dict[str, QPushButton] = {}
        for icon_name, _tooltip in _NAV_ICONS:
            button = QPushButton(header)
            button.setIcon(theme.load_icon(icon_name, Color.TEXT_SECONDARY))
            button.setFixedSize(32, 32)
            self._nav_buttons[icon_name] = button
            layout.addWidget(button)

        home_button = self._nav_buttons["house"]
        home_button.setToolTip("Home")
        home_button.clicked.connect(self._show_home_page)

        settings_button = self._nav_buttons["settings"]
        settings_button.setToolTip("Settings")
        settings_button.clicked.connect(self._show_settings_page)

        history_button = self._nav_buttons["history"]
        history_button.setToolTip("History")
        history_button.clicked.connect(self._toggle_history_dock)

        memory_button = self._nav_buttons["brain"]
        memory_button.setToolTip("Memory")
        memory_button.clicked.connect(self._show_memory_page)

        return header

    def _show_home_page(self) -> None:
        self._stack.setCurrentIndex(_HOME_PAGE)
        self._input_bar.setVisible(True)

    def _show_settings_page(self) -> None:
        self._stack.setCurrentIndex(_SETTINGS_PAGE)
        self._input_bar.setVisible(False)

    def _show_memory_page(self) -> None:
        self._stack.setCurrentIndex(_MEMORY_PAGE)
        self._input_bar.setVisible(False)

    # ── Memory View (docs/05 §6.4, FR-32/33, M5) ────────────────────────

    def set_memory_facts(self, facts: list[MemoryItem]) -> None:
        """Connect from `app.py` after any add/delete/clear (FR-32)."""
        self._memory_view.set_facts(facts)

    # ── History drawer (docs/05 §6.5, FR-5/6, M5) ───────────────────────

    def _build_history_dock(self) -> None:
        self._history_dock = QDockWidget("History", self)
        self._history_dock.setVisible(False)
        self._history_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )

        panel = QWidget(self._history_dock)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        panel_layout.setSpacing(Spacing.SM)

        new_conversation_button = QPushButton("New conversation", panel)
        new_conversation_button.clicked.connect(self._on_new_conversation_clicked)
        panel_layout.addWidget(new_conversation_button)

        self._session_list = QListWidget(panel)
        self._session_list.itemClicked.connect(self._on_session_item_clicked)
        panel_layout.addWidget(self._session_list, 1)

        self._history_dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._history_dock)

    def _toggle_history_dock(self) -> None:
        # `isHidden()` (the widget's own explicit flag) rather than `isVisible()` (which
        # also depends on the whole ancestor chain being shown) — see the pytest-qt gotcha
        # this codebase already documents: isVisible() is unreliable before the window's
        # first real `.show()`, so toggle logic shouldn't depend on it either.
        self._history_dock.setVisible(self._history_dock.isHidden())

    def _on_new_conversation_clicked(self) -> None:
        self._chat_view.clear()
        self._pending_reply = None
        self.new_conversation_requested.emit()

    def _on_session_item_clicked(self, item: QListWidgetItem) -> None:
        session_id = item.data(_SESSION_ID_ROLE)
        self.session_selected.emit(session_id)

    def set_sessions(self, sessions: list[SessionMeta]) -> None:
        """Connect from `app.py` whenever the drawer is opened / a turn is persisted."""
        self._session_list.clear()
        for session in sessions:
            label = f"{session.title} — {session.started_at:%Y-%m-%d}"
            item = QListWidgetItem(label)
            item.setData(_SESSION_ID_ROLE, session.session_id)
            self._session_list.addItem(item)

    def _build_history_replay_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        back_button = QPushButton("← Back to today", page)
        back_button.clicked.connect(self._show_home_page)
        layout.addWidget(back_button, 0)

        self._history_chat_view = ChatView(page)
        layout.addWidget(self._history_chat_view, 1)
        return page

    def show_session_replay(self, turns: list[TurnRecord]) -> None:
        """Connect from `app.py` after `MemoryService.load_session()` (read-only replay —
        the live `ChatView`/`ConversationState` are never touched)."""
        self._history_chat_view.clear()
        for turn in turns:
            self._history_chat_view.add_user_message(turn.user_text)
            self._history_chat_view.add_nova_message(turn.assistant_text)
        self._stack.setCurrentIndex(_HISTORY_REPLAY_PAGE)
        self._input_bar.setVisible(False)

    def set_provider_status(self, status: ProviderStatus) -> None:
        """Reflect the active provider's health in the header cluster (FR-43)."""
        self._status_label.setText(status.detail)
        color = _STATUS_COLOR_FOR_MODE[status.mode]
        self._status_label.setStyleSheet(f"color: {color};")

    def set_voice_mode(self, mode: str) -> None:
        """Connect to `SpeechOutWorker`'s tts-mode notifications (docs/08 §4) from `app.py`."""
        self._voice_status_label.setVisible(mode == "offline")

    def _on_debug_button_clicked(self) -> None:
        self._debug_button.setEnabled(False)
        self._debug_button.setText("▶ Running…")
        emit_fake_pipeline(self._bus, on_finished=self._on_debug_sequence_finished)

    def _on_debug_sequence_finished(self) -> None:
        self._debug_button.setEnabled(True)
        self._debug_button.setText("▶ Run demo pipeline")

    # ── input bar / chat wiring (T-208) ────────────────────────────────

    def _build_input_bar(self) -> QWidget:
        bar = QWidget(self)
        bar.setObjectName("surface")
        bar.setFixedHeight(_INPUT_BAR_HEIGHT)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.MD)

        self._mic_button = QPushButton(bar)
        self._mic_button.setFixedSize(_MIC_BUTTON_SIZE, _MIC_BUTTON_SIZE)
        self._mic_button.clicked.connect(self._on_mic_clicked)
        self._set_mic_visual(listening=False)
        layout.addWidget(self._mic_button)

        self._entry = QLineEdit(bar)
        self._entry.setPlaceholderText(_DEFAULT_PLACEHOLDER)
        self._entry.setFont(theme.font(theme.FontRole.BODY))
        self._entry.returnPressed.connect(self._on_send)
        layout.addWidget(self._entry, 1)

        self._send_button = QPushButton("Send", bar)
        self._send_button.clicked.connect(self._on_send)
        layout.addWidget(self._send_button)

        return bar

    def _on_send(self) -> None:
        text = self._entry.text().strip()
        if not text or self._awaiting_reply:
            return

        self.stop_speaking_requested.emit()  # FR-13: submitting new input stops speech
        self._chat_view.add_user_message(text)
        self._entry.clear()

        user_input = UserInput(
            request_id=new_request_id(), text=text, source="typed", ts=datetime.now(UTC)
        )
        self._set_awaiting_reply(True)
        self.submit_requested.emit(user_input)

    def on_reply_ready(self, reply: AssistantReply) -> None:
        """Connect to `AgentWorker.reply_ready` (queued, cross-thread) from `app.py`. Input
        re-enables immediately, but the bubble itself waits for `on_speech_started` (docs/05
        §9: "text reveals with the TTS start") — held here rather than shown right away."""
        self._pending_reply = reply
        self._set_awaiting_reply(False)

    def on_speech_started(self, request_id: str) -> None:
        """Connect to `SpeechOutWorker.speech_started` (queued, cross-thread) from `app.py`.
        Reveals the reply text held by `on_reply_ready` once audio has actually started (or
        `SpeechService` has determined none will play — voice off, nothing to say, or both
        engines failed all still call this, just immediately)."""
        if self._pending_reply is not None and self._pending_reply.request_id == request_id:
            self._chat_view.add_nova_message(self._pending_reply.text)
            self._pending_reply = None

    # ── voice (M4) ───────────────────────────────────────────────────

    def _on_mic_clicked(self) -> None:
        if self._listening:
            self.mic_repressed.emit()
            return
        if self._awaiting_reply:
            return
        self.stop_speaking_requested.emit()  # FR-13: pressing mic also stops any speech
        self._set_listening(True)
        self.mic_pressed.emit(self._settings.voice.input_device)

    def on_transcript_ready(self, transcript: Transcript) -> None:
        """Connect to `SpeechInWorker.transcript_ready` (queued, cross-thread) from `app.py`."""
        self._set_listening(False)
        explicit_cancel, self._explicit_cancel = self._explicit_cancel, False

        text = transcript.text.strip()
        if not text:
            if not explicit_cancel:  # Esc is a silent discard; anything else gets a nudge
                self._chat_view.add_nova_message(_DIDNT_CATCH_TEXT)
            return

        # FR-8: the transcript is shown before the agent acts, so a mistranscription is
        # visible, not silent.
        self._chat_view.add_user_message(text)
        user_input = UserInput(
            request_id=transcript.request_id, text=text, source="voice", ts=datetime.now(UTC)
        )
        self._set_awaiting_reply(True)
        self.submit_requested.emit(user_input)

    def on_listen_failed(self, friendly_message: str) -> None:
        """Connect to `SpeechInWorker.failed` (queued, cross-thread) from `app.py` — last-
        resort safety net; `SpeechService` itself handles every documented failure without
        raising."""
        self._set_listening(False)
        self._chat_view.add_nova_message(friendly_message)

    def set_mic_available(self, available: bool) -> None:
        """Called once at startup from `app.py` after enumerating input devices (FR-12)."""
        self._mic_available = available
        self._mic_button.setEnabled(available and not self._awaiting_reply)
        if not available:
            self._mic_button.setToolTip("I can't hear right now — you can type to me!")
        else:
            self._set_mic_visual(self._listening)

    def _set_listening(self, listening: bool) -> None:
        self._listening = listening
        self._entry.setEnabled(not listening and not self._awaiting_reply)
        self._send_button.setEnabled(not listening and not self._awaiting_reply)
        if listening:
            self._entry.setPlaceholderText(_LISTENING_PLACEHOLDER)
        else:
            self._entry.setPlaceholderText(
                _AWAITING_PLACEHOLDER if self._awaiting_reply else _DEFAULT_PLACEHOLDER
            )
        self._set_mic_visual(listening)

    def _set_mic_visual(self, listening: bool) -> None:
        if listening:
            self._mic_button.setIcon(theme.load_icon("mic", theme.accent_hex("cyan"), size=24))
            self._mic_button.setToolTip("Listening… (click to stop)")
        else:
            self._mic_button.setIcon(theme.load_icon("mic", Color.TEXT_SECONDARY, size=24))
            self._mic_button.setToolTip("Press to talk")

    def on_request_failed(self, request_id: str, friendly_message: str) -> None:
        """Connect to `AgentWorker.failed` (queued, cross-thread) from `app.py`."""
        del request_id  # no per-request UI state to key off in M2
        self._chat_view.add_nova_message(friendly_message)
        self._set_awaiting_reply(False)

    def on_request_cancelled(self, request_id: str) -> None:
        """Connect to `AgentWorker.request_cancelled` (queued, cross-thread) from `app.py`."""
        del request_id
        self._set_awaiting_reply(False)

    def on_request_rejected(self, request_id: str) -> None:
        """Connect to `AgentWorker.request_rejected` (queued, cross-thread) from `app.py`.

        Defensive only: `MainWindow` already disables Send the instant a request goes out,
        so the worker's own busy-guard should never actually fire from this app's own UI.
        """
        del request_id
        self._set_awaiting_reply(False)

    def _set_awaiting_reply(self, awaiting: bool) -> None:
        self._awaiting_reply = awaiting
        self._entry.setEnabled(not awaiting)
        self._send_button.setEnabled(not awaiting)
        self._entry.setPlaceholderText(_AWAITING_PLACEHOLDER if awaiting else _DEFAULT_PLACEHOLDER)
        self._mic_button.setEnabled(self._mic_available and not awaiting)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            if self._listening:
                self._explicit_cancel = True
                self.listening_cancelled.emit()
                return
            if self._awaiting_reply:
                self.cancel_requested.emit()
                return
        super().keyPressEvent(event)
