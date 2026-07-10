"""ConfirmDialog: the sensitive-tool confirmation modal (docs/05 §6.6, FR-20/FR-26).

"May I?" + plain-language action preview + Yes/No. Esc = No. Never constructed by the
Executor (that's the worker thread) — MainWindow opens it when it sees an
AWAITING_CONFIRMATION started event and answers back via its `confirmation_answered` signal.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nova.ui import theme
from nova.ui.theme import Color, Spacing

_MAX_PREVIEW_HEIGHT = 220


class ConfirmDialog(QDialog):
    """Modal question: body text + optional scrollable move-preview list."""

    def __init__(
        self,
        detail: str,
        preview: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("May I?")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        header = QHBoxLayout()
        icon_label = QLabel(self)
        icon_label.setPixmap(
            theme.load_icon("shield-question", theme.accent_hex("cyan")).pixmap(28, 28)
        )
        header.addWidget(icon_label)
        title = QLabel("May I?", self)
        title_font = theme.font(theme.FontRole.DISPLAY)
        title.setFont(title_font)
        header.addWidget(title, 1)
        layout.addLayout(header)

        body = QLabel(detail, self)
        body.setFont(theme.font(theme.FontRole.BODY))
        body.setWordWrap(True)
        layout.addWidget(body)

        if preview:
            preview_list = QListWidget(self)
            preview_list.addItems(preview)
            preview_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
            preview_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            preview_list.setMaximumHeight(_MAX_PREVIEW_HEIGHT)
            layout.addWidget(preview_list)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._no_button = QPushButton("No, stop", self)
        self._no_button.clicked.connect(self.reject)  # Esc also routes here (QDialog default)
        buttons.addWidget(self._no_button)
        self._yes_button = QPushButton("Yes, do it", self)
        self._yes_button.setDefault(True)
        self._yes_button.setStyleSheet(
            f"background-color: {theme.accent_hex('cyan')}; color: {Color.BG_BASE};"
        )
        self._yes_button.clicked.connect(self.accept)
        buttons.addWidget(self._yes_button)
        layout.addLayout(buttons)
