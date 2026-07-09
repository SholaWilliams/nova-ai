"""MainWindow: header, chat pane, pipeline panel, input bar (docs/05 §6.1).

M1 scope: static layout only. Chat and input-bar wiring are M2 (T-208); nav buttons are
inert stubs. The one exception is the dev-only "Run demo pipeline" button (T-109's debug
emitter) — see `nova.ui.debug_emitter` for why that doesn't violate the no-fake-events rule.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from nova.core.config import Settings
from nova.core.events import EventBus
from nova.ui import theme
from nova.ui.debug_emitter import emit_fake_pipeline
from nova.ui.theme import Color, Spacing
from nova.ui.views.pipeline_view import PipelineView

_WINDOW_SIZE = (1200, 760)
_MIN_WINDOW_SIZE = (980, 640)
_HEADER_HEIGHT = 56
_INPUT_BAR_HEIGHT = 64
_MIC_BUTTON_SIZE = 64
_NAV_ICONS: tuple[tuple[str, str], ...] = (
    ("house", "Home"),
    ("history", "History"),
    ("brain", "Memory"),
    ("settings", "Settings"),
)


class MainWindow(QMainWindow):
    """The whole app in one window (docs/05 §6.1): header / chat+pipeline split / input bar."""

    def __init__(self, bus: EventBus, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self.setWindowTitle("NOVA")
        self.resize(*_WINDOW_SIZE)
        self.setMinimumSize(*_MIN_WINDOW_SIZE)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.addWidget(self._build_chat_pane())
        self._pipeline_view = PipelineView(bus, splitter)
        splitter.addWidget(self._pipeline_view)
        # persisted preference (docs/05 §6.1): presenter may want full-screen chat
        pipeline_width = int(_WINDOW_SIZE[0] * 0.4) if settings.ui.pipeline_visible else 0
        splitter.setSizes([_WINDOW_SIZE[0] - pipeline_width, pipeline_width])
        self._pipeline_view.setVisible(settings.ui.pipeline_visible)
        root.addWidget(splitter, 1)

        root.addWidget(self._build_input_bar())

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

        # Honest placeholder — no provider/network/mic exist yet (M2/M4); TEXT_SECONDARY
        # signals "not active" rather than claiming a connection that isn't there.
        status = QLabel("offline · no provider set · mic unavailable", header)
        status.setFont(theme.font(theme.FontRole.CAPTION))
        status.setStyleSheet(f"color: {Color.TEXT_SECONDARY};")
        layout.addWidget(status, 1)

        self._debug_button = QPushButton("▶ Run demo pipeline", header)
        self._debug_button.setToolTip(
            "Dev only: plays a scripted pipeline sequence (see AGENTS.md's debug emitter)."
        )
        self._debug_button.clicked.connect(self._on_debug_button_clicked)
        layout.addWidget(self._debug_button)

        for icon_name, tooltip in _NAV_ICONS:
            button = QPushButton(header)
            button.setIcon(theme.load_icon(icon_name, Color.TEXT_SECONDARY))
            button.setToolTip(f"{tooltip} (coming soon)")
            button.setFixedSize(32, 32)
            button.setEnabled(False)  # nav views land in later milestones
            layout.addWidget(button)

        return header

    def _on_debug_button_clicked(self) -> None:
        self._debug_button.setEnabled(False)
        self._debug_button.setText("▶ Running…")
        emit_fake_pipeline(self._bus, on_finished=self._on_debug_sequence_finished)

    def _on_debug_sequence_finished(self) -> None:
        self._debug_button.setEnabled(True)
        self._debug_button.setText("▶ Run demo pipeline")

    # ── chat pane (static — real chat is M2 T-208) ─────────────────────

    def _build_chat_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        placeholder = QLabel("Chat will appear here once NOVA can talk.", pane)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setWordWrap(True)
        placeholder.setFont(theme.font(theme.FontRole.BODY))
        placeholder.setStyleSheet(f"color: {Color.TEXT_SECONDARY};")
        layout.addWidget(placeholder)

        return pane

    # ── input bar (static — real wiring is M2 T-208) ───────────────────

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

        entry = QLineEdit(bar)
        entry.setPlaceholderText("Type or press the mic to talk…")
        entry.setFont(theme.font(theme.FontRole.BODY))
        layout.addWidget(entry, 1)

        send_button = QPushButton("Send", bar)
        send_button.setEnabled(False)  # typed chat lands in M2
        send_button.setToolTip("Typed conversation (coming soon)")
        layout.addWidget(send_button)

        return bar
