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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nova.core.config import Settings
from nova.core.events import EventBus
from nova.core.ids import new_request_id
from nova.core.models import AssistantReply, ProviderStatus, UserInput
from nova.ui import theme
from nova.ui.debug_emitter import emit_fake_pipeline
from nova.ui.theme import Color, Spacing
from nova.ui.views.chat_view import ChatView
from nova.ui.views.pipeline_view import PipelineView
from nova.ui.views.settings_view import SettingsView

_WINDOW_SIZE = (1200, 760)
_MIN_WINDOW_SIZE = (980, 640)
_HEADER_HEIGHT = 56
_INPUT_BAR_HEIGHT = 64
_MIC_BUTTON_SIZE = 64
_DEFAULT_PLACEHOLDER = "Type or press the mic to talk…"
_AWAITING_PLACEHOLDER = "One moment…"
_NAV_ICONS: tuple[tuple[str, str], ...] = (
    ("house", "Home"),
    ("history", "History"),
    ("brain", "Memory"),
    ("settings", "Settings"),
)
_HOME_PAGE = 0
_SETTINGS_PAGE = 1
_STATUS_COLOR_FOR_MODE = {
    "normal": Color.TEXT_SECONDARY,
    "fallback": Color.STATE_WARNING,
    "down": Color.STATE_ERROR,
}


class MainWindow(QMainWindow):
    """The whole app in one window (docs/05 §6.1): header / chat+pipeline split / input bar."""

    submit_requested = Signal(object)  # UserInput
    cancel_requested = Signal()

    def __init__(self, bus: EventBus, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._awaiting_reply = False
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
        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.addWidget(self._chat_view)
        self._pipeline_view = PipelineView(bus, splitter)
        splitter.addWidget(self._pipeline_view)
        # persisted preference (docs/05 §6.1): presenter may want full-screen chat
        pipeline_width = int(_WINDOW_SIZE[0] * 0.4) if settings.ui.pipeline_visible else 0
        splitter.setSizes([_WINDOW_SIZE[0] - pipeline_width, pipeline_width])
        self._pipeline_view.setVisible(settings.ui.pipeline_visible)

        self._settings_view = SettingsView(settings)

        self._stack = QStackedWidget(central)
        self._stack.addWidget(splitter)  # index _HOME_PAGE
        self._stack.addWidget(self._settings_view)  # index _SETTINGS_PAGE
        root.addWidget(self._stack, 1)

        self._input_bar = self._build_input_bar()
        root.addWidget(self._input_bar)

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

        for icon_name in ("history", "brain"):
            button = self._nav_buttons[icon_name]
            label = dict(_NAV_ICONS)[icon_name]
            button.setToolTip(f"{label} (coming soon)")
            button.setEnabled(False)  # nav views land in later milestones

        return header

    def _show_home_page(self) -> None:
        self._stack.setCurrentIndex(_HOME_PAGE)
        self._input_bar.setVisible(True)

    def _show_settings_page(self) -> None:
        self._stack.setCurrentIndex(_SETTINGS_PAGE)
        self._input_bar.setVisible(False)

    def set_provider_status(self, status: ProviderStatus) -> None:
        """Reflect the active provider's health in the header cluster (FR-43)."""
        self._status_label.setText(status.detail)
        color = _STATUS_COLOR_FOR_MODE[status.mode]
        self._status_label.setStyleSheet(f"color: {color};")

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

        mic_button = QPushButton(bar)
        mic_button.setIcon(theme.load_icon("mic", Color.TEXT_SECONDARY, size=24))
        mic_button.setFixedSize(_MIC_BUTTON_SIZE, _MIC_BUTTON_SIZE)
        mic_button.setEnabled(False)  # voice input lands in M4
        mic_button.setToolTip("Voice input (coming soon)")
        layout.addWidget(mic_button)

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

        self._chat_view.add_user_message(text)
        self._entry.clear()

        user_input = UserInput(
            request_id=new_request_id(), text=text, source="typed", ts=datetime.now(UTC)
        )
        self._set_awaiting_reply(True)
        self.submit_requested.emit(user_input)

    def on_reply_ready(self, reply: AssistantReply) -> None:
        """Connect to `AgentWorker.reply_ready` (queued, cross-thread) from `app.py`."""
        self._chat_view.add_nova_message(reply.text)
        self._set_awaiting_reply(False)

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

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape and self._awaiting_reply:
            self.cancel_requested.emit()
            return
        super().keyPressEvent(event)
