"""SettingsView: the Settings screen (docs/05 §6.3, T-209/T-407).

Brain (M2), Voice (M4), Weather + Look (M5) sections are built; About lands in M6 (T-603).
`SettingsView` is composed as a `QVBoxLayout` of section-widgets rather than the icon-rail
docs/05 §6.3 pictures — a rail can still wrap around it later without a rewrite, and building
one now for 5 sections would be premature chrome.

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
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nova import __version__
from nova.core.config import Settings, get_data_dir
from nova.core.models import AudioDeviceInfo
from nova.ui import theme
from nova.ui.theme import Color, Radius, Spacing

_PROVIDER_LABELS = {"gemini": "Gemini", "groq": "Groq", "openrouter": "OpenRouter"}

# pocket-tts's built-in, non-gated voice catalog (docs/04 TD-6 revision, confirmed against
# the installed package — voice-cloning hf:// URLs need gated HF access, these plain names
# don't). Hardcoded here (not imported from `nova.speech`) because `ui` imports core only
# (D-5) — this is display data, not behavior, so a local copy is the honest answer, not a
# layering workaround.
_VOICE_CATALOG = (
    "cosette",
    "marius",
    "javert",
    "alba",
    "jean",
    "anna",
    "vera",
    "fantine",
    "charles",
    "paul",
    "eponine",
    "azelma",
    "george",
    "mary",
    "jane",
    "michael",
    "eve",
    "bill_boerst",
    "peter_yearsley",
    "stuart_bell",
    "caro_davy",
    "giovanni",
    "lola",
    "juergen",
    "rafael",
    "estelle",
)
_SYSTEM_DEFAULT_DEVICE = "System default"


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
        self._toggle_button.setFixedWidth(80)  # 64 clipped "Show"/"Hide" under the button padding
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
    tts_enabled_changed = Signal(bool)
    voice_changed = Signal(str)
    openrouter_model_changed = Signal(str)
    input_device_changed = Signal(object)  # int | None
    output_device_changed = Signal(object)  # int | None
    default_city_changed = Signal(str)
    accent_changed = Signal(str)  # "cyan" | "violet" | "emerald" | "amber"
    reduced_motion_changed = Signal(bool)

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # All five sections stacked here total ~1000px — taller than the window on most
        # screens. Without a scroll area the QStackedWidget just clips them (sections looked
        # empty / cut off); wrap the column in a QScrollArea so it scrolls instead.
        content = QWidget()
        layout = QVBoxLayout(content)
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
        layout.addWidget(self._build_voice_section(settings))
        layout.addWidget(self._build_weather_section(settings))
        layout.addWidget(self._build_look_section(settings))
        layout.addWidget(self._build_about_section())
        layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

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
        for name in ("gemini", "groq", "openrouter"):
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
        for name in ("gemini", "groq", "openrouter"):
            row = _KeyRow(name, section)
            row.key_changed.connect(self.key_changed)
            row.test_requested.connect(self.test_requested)
            self._key_rows[name] = row
            section_layout.addWidget(row)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("OpenRouter model", section))
        self._openrouter_model_combo = QComboBox(section)
        self._openrouter_model_combo.setEditable(True)
        self._openrouter_model_combo.addItem(settings.provider.openrouter_model)
        self._openrouter_model_combo.setCurrentText(settings.provider.openrouter_model)
        self._openrouter_model_combo.textActivated.connect(self.openrouter_model_changed)
        model_row.addWidget(self._openrouter_model_combo, 1)
        section_layout.addLayout(model_row)

        return section

    def _build_voice_section(self, settings: Settings) -> QWidget:
        section = QWidget(self)
        section.setObjectName("surface")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        section_layout.setSpacing(Spacing.MD)

        title = QLabel("Voice", section)
        title.setFont(theme.font(theme.FontRole.DISPLAY))
        section_layout.addWidget(title)

        self._tts_enabled_checkbox = QCheckBox("Speak replies out loud", section)
        self._tts_enabled_checkbox.setChecked(settings.voice.tts_enabled)
        self._tts_enabled_checkbox.toggled.connect(self.tts_enabled_changed)
        section_layout.addWidget(self._tts_enabled_checkbox)

        voice_row = QHBoxLayout()
        voice_row.addWidget(QLabel("Voice", section))
        self._voice_combo = QComboBox(section)
        self._voice_combo.addItems(_VOICE_CATALOG)
        if settings.voice.voice in _VOICE_CATALOG:
            self._voice_combo.setCurrentText(settings.voice.voice)
        self._voice_combo.currentTextChanged.connect(self.voice_changed)
        voice_row.addWidget(self._voice_combo, 1)
        section_layout.addLayout(voice_row)

        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("Microphone", section))
        self._input_device_combo = QComboBox(section)
        self._input_device_combo.currentIndexChanged.connect(
            lambda _i: self.input_device_changed.emit(self._input_device_combo.currentData())
        )
        input_row.addWidget(self._input_device_combo, 1)
        section_layout.addLayout(input_row)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Speaker", section))
        self._output_device_combo = QComboBox(section)
        self._output_device_combo.currentIndexChanged.connect(
            lambda _i: self.output_device_changed.emit(self._output_device_combo.currentData())
        )
        output_row.addWidget(self._output_device_combo, 1)
        section_layout.addLayout(output_row)

        return section

    def _build_weather_section(self, settings: Settings) -> QWidget:
        section = QWidget(self)
        section.setObjectName("surface")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        section_layout.setSpacing(Spacing.MD)

        title = QLabel("Weather", section)
        title.setFont(theme.font(theme.FontRole.DISPLAY))
        section_layout.addWidget(title)

        city_row = QHBoxLayout()
        city_row.addWidget(QLabel("Default city", section))
        self._default_city_entry = QLineEdit(settings.weather.default_city, section)
        self._default_city_entry.editingFinished.connect(self._on_default_city_editing_finished)
        city_row.addWidget(self._default_city_entry, 1)
        section_layout.addLayout(city_row)

        return section

    def _on_default_city_editing_finished(self) -> None:
        city = self._default_city_entry.text().strip()
        if city:
            self.default_city_changed.emit(city)

    def _build_look_section(self, settings: Settings) -> QWidget:
        section = QWidget(self)
        section.setObjectName("surface")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        section_layout.setSpacing(Spacing.MD)

        title = QLabel("Look", section)
        title.setFont(theme.font(theme.FontRole.DISPLAY))
        section_layout.addWidget(title)

        accent_row = QHBoxLayout()
        accent_row.addWidget(QLabel("Accent color", section))
        self._accent_group = QButtonGroup(self)
        for accent_name in ("cyan", "violet", "emerald", "amber"):
            radio = QRadioButton(accent_name.capitalize(), section)
            radio.setChecked(settings.ui.accent == accent_name)
            radio.toggled.connect(
                lambda checked, name=accent_name: checked and self.accent_changed.emit(name)
            )
            self._accent_group.addButton(radio)
            accent_row.addWidget(radio)
        accent_row.addStretch(1)
        section_layout.addLayout(accent_row)

        self._reduced_motion_checkbox = QCheckBox("Reduce motion", section)
        self._reduced_motion_checkbox.setChecked(settings.ui.reduced_motion)
        self._reduced_motion_checkbox.toggled.connect(self.reduced_motion_changed)
        section_layout.addWidget(self._reduced_motion_checkbox)

        return section

    def _build_about_section(self) -> QWidget:
        """About section: version + logging folder link (Phase 14 §3, T-603)."""
        section = QWidget(self)
        section.setObjectName("surface")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        section_layout.setSpacing(Spacing.MD)

        title = QLabel("About", section)
        title.setFont(theme.font(theme.FontRole.DISPLAY))
        section_layout.addWidget(title)

        version_label = QLabel(f"NOVA v{__version__}", section)
        version_label.setFont(theme.font(theme.FontRole.BODY))
        section_layout.addWidget(version_label)

        # Logging folder link (NFR-14)
        logs_btn = QPushButton("Open logs folder", section)
        logs_btn.clicked.connect(self._open_logs_folder)
        section_layout.addWidget(logs_btn)

        return section

    def _open_logs_folder(self) -> None:
        """Open the logs directory in the file explorer (NFR-14)."""
        from PySide6.QtGui import QDesktopServices

        logs_path = get_data_dir() / "logs"
        logs_path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(logs_path.as_uri())

    @property
    def welcome_banner_visible(self) -> bool:
        """Is the welcome banner shown? (M6 T-603)."""
        return self._banner.isVisible() and "welcome" in self._banner.text().lower()

    @welcome_banner_visible.setter
    def welcome_banner_visible(self, value: bool) -> None:
        """Show/hide the welcome banner on first run (M6 T-603)."""
        if value:
            self._banner.setText(
                "Welcome to NOVA! To get started, add your API keys below. "
                "You can still use the chat without keys (typed mode only)."
            )
            # Use a welcoming color (violet accent) instead of error red
            self._banner.setStyleSheet(
                f"background-color: {Color.ACCENT_SECONDARY}; color: {Color.TEXT_INVERSE}; "
                f"border-radius: {Radius.CHIP}px; padding: {Spacing.SM}px {Spacing.MD}px;"
            )
            self._banner.setVisible(True)
        else:
            self._banner.setVisible(False)

    def set_input_devices(self, devices: list[AudioDeviceInfo]) -> None:
        """Called once at startup from `app.py` (FR-12) — `ui` can't enumerate devices
        itself (D-5: no `nova.speech` import), so `app.py` hands the list over."""
        self._fill_device_combo(self._input_device_combo, devices)

    def set_output_devices(self, devices: list[AudioDeviceInfo]) -> None:
        self._fill_device_combo(self._output_device_combo, devices)

    @staticmethod
    def _fill_device_combo(combo: QComboBox, devices: list[AudioDeviceInfo]) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_SYSTEM_DEFAULT_DEVICE, None)
        for device in devices:
            combo.addItem(device.name, device.index)
        combo.blockSignals(False)

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
