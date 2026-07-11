"""MemoryView: "What NOVA remembers" (docs/05 §6.4, FR-32/FR-33).

Card list of stored facts/preferences; per-card delete + header "Forget everything", both
confirmed via the existing generic `ConfirmDialog` (no new dialog needed). `ui` imports core
only (D-5) — this view only knows `core.models.MemoryItem`; `app.py` wires it to the real
`MemoryService` via plain method calls + signals, the same pattern `SettingsView` already
uses for provider wiring.

Per-card delete uses a text "Forget" button rather than a trash icon — no trash icon is
bundled in `assets/icons/` (same reasoning `settings_view.py`'s show/hide toggle already
documents: icon-fetching tooling wasn't available when this was built).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nova.core.models import MemoryItem
from nova.ui import theme
from nova.ui.theme import Color, Radius, Spacing
from nova.ui.widgets.confirm_dialog import ConfirmDialog

_EMPTY_STATE_TEXT = "I don't remember anything yet. Tell me something to remember!"


class _FactCard(QWidget):
    delete_requested = Signal(str)  # fact id

    def __init__(self, item: MemoryItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._id = item.id
        self._content = item.content
        self.setObjectName("surface")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.MD)

        text_col = QVBoxLayout()
        text_col.setSpacing(Spacing.XS)
        content_label = QLabel(item.content, self)
        content_label.setWordWrap(True)
        content_label.setFont(theme.font(theme.FontRole.BODY))
        text_col.addWidget(content_label)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(Spacing.SM)
        kind_badge = QLabel(item.kind, self)
        kind_badge.setFont(theme.font(theme.FontRole.CAPTION))
        kind_badge.setStyleSheet(
            f"color: {Color.TEXT_INVERSE}; background-color: {theme.accent_hex('cyan')}; "
            f"border-radius: {Radius.CHIP}px; padding: 0px {Spacing.SM}px;"
        )
        meta_row.addWidget(kind_badge)
        date_label = QLabel(item.created_at.strftime("%Y-%m-%d"), self)
        date_label.setFont(theme.font(theme.FontRole.CAPTION))
        date_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY};")
        meta_row.addWidget(date_label)
        meta_row.addStretch(1)
        text_col.addLayout(meta_row)

        layout.addLayout(text_col, 1)

        self._delete_button = QPushButton("Forget", self)
        self._delete_button.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self._delete_button)

    def _on_delete_clicked(self) -> None:
        dialog = ConfirmDialog(f'Forget this: "{self._content}"?', [], self)
        if dialog.exec() == ConfirmDialog.DialogCode.Accepted:
            self.delete_requested.emit(self._id)


class MemoryView(QWidget):
    """ "What NOVA remembers" screen. Populated by `app.py` calling `set_facts()`."""

    delete_requested = Signal(str)  # fact id
    clear_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        header = QHBoxLayout()
        title = QLabel("What NOVA remembers", self)
        title.setFont(theme.font(theme.FontRole.DISPLAY))
        header.addWidget(title, 1)
        self._clear_all_button = QPushButton("Forget everything", self)
        self._clear_all_button.setStyleSheet(f"color: {Color.STATE_ERROR};")
        self._clear_all_button.clicked.connect(self._on_clear_all_clicked)
        header.addWidget(self._clear_all_button)
        layout.addLayout(header)

        self._empty_label = QLabel(_EMPTY_STATE_TEXT, self)
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY};")
        layout.addWidget(self._empty_label)

        self._column = QWidget()
        self._column_layout = QVBoxLayout(self._column)
        self._column_layout.setContentsMargins(0, 0, 0, 0)
        self._column_layout.setSpacing(Spacing.SM)
        self._column_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._column)
        layout.addWidget(scroll, 1)

        self.set_facts([])

    def set_facts(self, facts: list[MemoryItem]) -> None:
        while self._column_layout.count() > 1:
            item = self._column_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        for fact in facts:
            card = _FactCard(fact, self._column)
            card.delete_requested.connect(self.delete_requested)
            self._column_layout.insertWidget(self._column_layout.count() - 1, card)

        self._empty_label.setVisible(not facts)
        self._clear_all_button.setEnabled(bool(facts))

    def card_count(self) -> int:
        """Test/debug convenience."""
        return self._column_layout.count() - 1

    def _on_clear_all_clicked(self) -> None:
        dialog = ConfirmDialog("Forget everything you've told me?", [], self)
        if dialog.exec() == ConfirmDialog.DialogCode.Accepted:
            self.clear_all_requested.emit()
