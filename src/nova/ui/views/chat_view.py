"""ChatView: the chat pane (docs/05 §6.1, §7.3) — bubbles in a scrolling column.

Does not subscribe to EventBus itself: `MainWindow` calls `add_user_message()`/
`add_nova_message()` directly in response to submit/reply signals, so this widget has no
subscription lifecycle to manage (CODING_STANDARDS.md: long-lived EventBus subscribers must
unsubscribe).
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from nova.ui.theme import Spacing
from nova.ui.widgets.message_bubble import MessageBubble

_AT_BOTTOM_EPSILON_PX = 24


class ChatView(QWidget):
    """A scrolling column of `MessageBubble`s.

    Auto-scrolls to the newest message unless the user has manually scrolled up to read
    history — courtesy behavior implied by T-208's own "history scroll" scope, not
    explicitly spec'd elsewhere.
    """

    stop_speech_requested = Signal()  # any NOVA bubble's speaker glyph was clicked (FR-13)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._column = QWidget()
        self._column_layout = QVBoxLayout(self._column)
        self._column_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        self._column_layout.setSpacing(Spacing.SM)
        self._column_layout.addStretch(1)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll_area.setWidget(self._column)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll_area)

    def add_user_message(self, text: str) -> None:
        self._add_bubble(text, role="user")

    def add_nova_message(self, text: str) -> None:
        self._add_bubble(text, role="nova")

    def bubble_count(self) -> int:
        """Number of message bubbles currently shown (test/debug convenience)."""
        return self._column_layout.count() - 1  # exclude the trailing stretch

    def clear(self) -> None:
        """ "New conversation" (docs/05 §6.5) — removes every bubble."""
        while self._column_layout.count() > 1:
            item = self._column_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_bubble(self, text: str, *, role: Literal["user", "nova"]) -> None:
        was_at_bottom = self._is_scrolled_to_bottom()

        bubble = MessageBubble(text, role=role, parent=self._column)
        bubble.set_max_bubble_width(self.width())
        bubble.stop_speech_requested.connect(self.stop_speech_requested)
        self._column_layout.insertWidget(self._column_layout.count() - 1, bubble)

        if was_at_bottom:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _is_scrolled_to_bottom(self) -> bool:
        bar = self._scroll_area.verticalScrollBar()
        return bar.value() >= bar.maximum() - _AT_BOTTOM_EPSILON_PX

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
