"""SettingsView: the Settings screen, Brain section only (docs/05 §6.3, T-209).

Voice/Weather/Look/About sections have nothing to populate until M4/M5 — building an empty
icon-rail scaffold for them now would be speculative unexercised surface. `SettingsView` is
still composed as a `QVBoxLayout` of section-widgets from day one so a rail can wrap around
it later without a rewrite.

`ui` imports core only (D-5) — this view never imports `nova.providers`. Provider selection,
key entry, and key testing are all signals the composition root (`app.py`) wires to the real
`ProviderManager`; `SettingsView` only knows `core.config.Settings` and plain strings/bools.

The show/hide key toggle uses text ("Show"/"Hide") rather than eye/eye-off icons — Lucide
icon-fetching tooling was unavailable when this was built; swapping in real icons later is a
one-line change (see the flagged follow-up task), not a design constraint.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from nova.core.config import Settings
from nova.ui import theme
from nova.ui.theme import Color, Radius, Spacing

_PROVIDER_LABELS = {"gemini": "Gemini", "groq": "Groq"}


class _KeyRow(QWidget):
    """One provider's masked key entry + show/hide + Test + inline feedback."""

    key_changed = Signal(str, str)  # provider_name, new_value
    test_requested = Signal(str)  # provider_name

    def __init__(self, provider_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.provider_name = provider_name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.XS)

        label = QLabel(f"{_PROVIDER_LABELS.get(provider_name, provider_name)} API key", self)
        label.setFont(theme.font(theme.FontRole.LABEL))
        layout.addWidget(label)

        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)

        self.entry = QLineEdit(self)
        self.entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.entry.setPlaceholderText("Paste your API key…")
        self.entry.editingFinished.connect(self._on_editing_finished)
        row.addWidget(self.entry, 1)

        self._toggle_button = QPushButton("Show", self)
        self._toggle_button.setCheckable(True)
        self._toggle_button.setFixedWidth(64)
        self._toggle_button.clicked.connect(self._on_toggle_visibility)
        row.addWidget(self._toggle_button)

        self._test_button = QPushButton("Test", self)
        self._test_button.clicked.connect(lambda: self.test_requested.emit(self.provider_name))
        row.addWidget(self._test_button)

        layout.addLayout(row)

        self._feedback_label = QLabel(self)
        self._feedback_label.setFont(theme.font(theme.FontRole.CAPTION))
        self._feedback_label.setVisible(False)
        layout.addWidget(self._feedback_label)

    def set_key_masked_placeholder(self, has_key: bool) -> None:
        """Reflect an already-configured key via placeholder text — never display it."""
        placeholder = "•••••••••••••••• (already set)" if has_key else "Paste your API key…"
        self.entry.setPlaceholderText(placeholder)

    def set_testing(self, in_progress: bool) -> None:
        self._test_button.setEnabled(not in_progress)
        self._test_button.setText("Testing…" if in_progress else "Test")

    def show_test_result(self, available: bool, detail: str) -> None:
        self._feedback_label.setVisible(True)
        if available:
            self._feedback_label.setText(f"✓ {detail}")
            self._feedback_label.setStyleSheet(f"color: {Color.STATE_SUCCESS};")
        else:
            self._feedback_label.setText(f"⚠ {detail}")
            self._feedback_label.setStyleSheet(f"color: {Color.STATE_ERROR};")

    def _on_toggle_visibility(self) -> None:
        if self._toggle_button.isChecked():
            self.entry.setEchoMode(QLineEdit.EchoMode.Normal)
            self._toggle_button.setText("Hide")
        else:
            self.entry.setEchoMode(QLineEdit.EchoMode.Password)
            self._toggle_button.setText("Show")

    def _on_editing_finished(self) -> None:
        value = self.entry.text().strip()
        if value:
            self.key_changed.emit(self.provider_name, value)
            self.entry.clear()  # never linger in the widget once handed off (S-6 spirit)
            self.entry.setPlaceholderText("•••••••••••••••• (already set)")


class SettingsView(QWidget):
    """The Settings screen. M2: Brain section only (provider pick, keys, hot-swap)."""

    provider_selected = Signal(str)  # "gemini" | "groq"
    key_changed = Signal(str, str)  # provider_name, new_value
    test_requested = Signal(str)  # provider_name

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.LG)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._banner = QLabel(self)
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(
            f"background-color: {Color.STATE_ERROR}; color: {Color.TEXT_INVERSE}; "
            f"border-radius: {Radius.CHIP}px; padding: {Spacing.SM}px {Spacing.MD}px;"
        )
        self._banner.setVisible(False)
        layout.addWidget(self._banner)

        layout.addWidget(self._build_brain_section(settings))
        layout.addStretch(1)

    def _build_brain_section(self, settings: Settings) -> QWidget:
        section = QWidget(self)
        section.setObjectName("surface")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        section_layout.setSpacing(Spacing.MD)

        title = QLabel("Brain", section)
        title.setFont(theme.font(theme.FontRole.DISPLAY))
        section_layout.addWidget(title)

        self._radio_group = QButtonGroup(self)
        for name in ("gemini", "groq"):
            radio = QRadioButton(_PROVIDER_LABELS[name], section)
            radio.setChecked(settings.provider.active == name)
            radio.toggled.connect(
                lambda checked, provider_name=name: (
                    checked and self.provider_selected.emit(provider_name)
                )
            )
            self._radio_group.addButton(radio)
            section_layout.addWidget(radio)

        self._key_rows: dict[str, _KeyRow] = {}
        for name in ("gemini", "groq"):
            row = _KeyRow(name, section)
            row.key_changed.connect(self.key_changed)
            row.test_requested.connect(self.test_requested)
            self._key_rows[name] = row
            section_layout.addWidget(row)

        return section

    def show_missing_key_banner(self, message: str) -> None:
        self._banner.setText(message)
        self._banner.setVisible(True)

    def hide_missing_key_banner(self) -> None:
        self._banner.setVisible(False)

    def focus_first_key_field(self) -> None:
        """The banner's "Fix now" affordance target (FR-47)."""
        first_row = self._key_rows.get("gemini")
        if first_row is not None:
            first_row.entry.setFocus()

    def set_testing(self, provider_name: str, in_progress: bool) -> None:
        row = self._key_rows.get(provider_name)
        if row is not None:
            row.set_testing(in_progress)

    def set_key_test_result(self, provider_name: str, available: bool, detail: str) -> None:
        row = self._key_rows.get(provider_name)
        if row is not None:
            row.show_test_result(available, detail)

    def set_key_configured(self, provider_name: str, has_key: bool) -> None:
        row = self._key_rows.get(provider_name)
        if row is not None:
            row.set_key_masked_placeholder(has_key)
