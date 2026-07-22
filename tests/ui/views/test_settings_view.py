"""Unit tests for nova.ui.views.settings_view — Brain/Voice section wiring (T-209/T-407)."""

import pytest
from PySide6.QtWidgets import QLineEdit

from nova.core.config import Settings
from nova.core.models import AudioDeviceInfo
from nova.ui.views.settings_view import SettingsView


@pytest.fixture
def view(qtbot: object) -> SettingsView:
    widget = SettingsView(Settings())
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    return widget


# ── provider radios ───────────────────────────────────────────────────


def test_gemini_radio_checked_by_default(view: SettingsView) -> None:
    checked = [b.text() for b in view._radio_group.buttons() if b.isChecked()]
    assert checked == ["Gemini"]


def test_groq_radio_checked_when_settings_says_so(qtbot: object) -> None:
    settings = Settings()
    settings.provider.active = "groq"
    widget = SettingsView(settings)
    qtbot.addWidget(widget)  # type: ignore[attr-defined]

    checked = [b.text() for b in widget._radio_group.buttons() if b.isChecked()]
    assert checked == ["Groq"]


def test_selecting_a_radio_emits_provider_selected(view: SettingsView, qtbot: object) -> None:
    groq_radio = next(b for b in view._radio_group.buttons() if b.text() == "Groq")

    with qtbot.waitSignal(view.provider_selected, timeout=1000) as blocker:  # type: ignore[attr-defined]
        groq_radio.click()

    assert blocker.args == ["groq"]


# ── key rows ──────────────────────────────────────────────────────────


def test_each_provider_gets_a_key_row(view: SettingsView) -> None:
    assert set(view._key_rows) == {"gemini", "groq", "openrouter"}


def test_key_entry_defaults_to_password_echo_mode(view: SettingsView) -> None:
    row = view._key_rows["gemini"]
    assert row.entry.echoMode() == QLineEdit.EchoMode.Password


def test_toggle_button_reveals_key_text(view: SettingsView) -> None:
    row = view._key_rows["gemini"]
    row._toggle_button.click()
    assert row.entry.echoMode() == QLineEdit.EchoMode.Normal
    assert row._toggle_button.text() == "Hide"


def test_toggle_button_hides_again_on_second_click(view: SettingsView) -> None:
    row = view._key_rows["gemini"]
    row._toggle_button.click()
    row._toggle_button.click()
    assert row.entry.echoMode() == QLineEdit.EchoMode.Password
    assert row._toggle_button.text() == "Show"


def test_editing_finished_emits_key_changed_and_clears_entry(
    view: SettingsView, qtbot: object
) -> None:
    row = view._key_rows["groq"]
    row.entry.setText("gsk_new_key")

    with qtbot.waitSignal(view.key_changed, timeout=1000) as blocker:  # type: ignore[attr-defined]
        row._on_editing_finished()

    assert blocker.args == ["groq", "gsk_new_key"]
    assert row.entry.text() == ""


def test_editing_finished_masks_placeholder_after_handoff(view: SettingsView) -> None:
    row = view._key_rows["groq"]
    row.entry.setText("gsk_new_key")
    row._on_editing_finished()
    assert "already set" in row.entry.placeholderText()


def test_editing_finished_with_blank_text_does_not_emit(view: SettingsView) -> None:
    row = view._key_rows["gemini"]
    row.entry.setText("   ")
    received: list[tuple[str, str]] = []
    view.key_changed.connect(lambda name, value: received.append((name, value)))

    row._on_editing_finished()

    assert received == []


def test_test_button_emits_test_requested(view: SettingsView, qtbot: object) -> None:
    row = view._key_rows["gemini"]
    with qtbot.waitSignal(view.test_requested, timeout=1000) as blocker:  # type: ignore[attr-defined]
        row._test_button.click()
    assert blocker.args == ["gemini"]


def test_set_testing_disables_button_and_changes_text(view: SettingsView) -> None:
    view.set_testing("gemini", True)
    row = view._key_rows["gemini"]
    assert row._test_button.isEnabled() is False
    assert row._test_button.text() == "Testing…"

    view.set_testing("gemini", False)
    assert row._test_button.isEnabled() is True
    assert row._test_button.text() == "Test"


def test_set_key_test_result_success_shows_checkmark(view: SettingsView) -> None:
    view.set_key_test_result("gemini", True, "Looks good")
    row = view._key_rows["gemini"]
    assert not row._feedback_label.isHidden()
    assert "Looks good" in row._feedback_label.text()
    assert "✓" in row._feedback_label.text()


def test_set_key_test_result_failure_shows_warning(view: SettingsView) -> None:
    view.set_key_test_result("gemini", False, "Invalid key")
    row = view._key_rows["gemini"]
    assert "Invalid key" in row._feedback_label.text()
    assert "⚠" in row._feedback_label.text()


def test_set_key_configured_true_shows_already_set_placeholder(view: SettingsView) -> None:
    view.set_key_configured("groq", True)
    assert "already set" in view._key_rows["groq"].entry.placeholderText()


def test_set_key_configured_false_restores_default_placeholder(view: SettingsView) -> None:
    row = view._key_rows["groq"]
    view.set_key_configured("groq", True)
    view.set_key_configured("groq", False)
    assert row.entry.placeholderText() == "Paste your API key…"


# ── missing-key banner ────────────────────────────────────────────────


def test_missing_key_banner_hidden_by_default(view: SettingsView) -> None:
    assert not view._banner.isVisible()


def test_show_missing_key_banner_displays_message(view: SettingsView) -> None:
    view.show_missing_key_banner("Add a Gemini key to get started")
    assert not view._banner.isHidden()
    assert view._banner.text() == "Add a Gemini key to get started"


def test_hide_missing_key_banner(view: SettingsView) -> None:
    view.show_missing_key_banner("missing")
    view.hide_missing_key_banner()
    assert not view._banner.isVisible()


def test_focus_first_key_field_focuses_the_gemini_entry(
    view: SettingsView, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(view._key_rows["gemini"].entry, "setFocus", lambda: calls.append(True))

    view.focus_first_key_field()

    assert calls == [True]


# ── voice section (T-407) ──────────────────────────────────────────────


def test_tts_enabled_checkbox_reflects_settings_default(view: SettingsView) -> None:
    assert view._tts_enabled_checkbox.isChecked() is True


def test_toggling_tts_checkbox_emits_tts_enabled_changed(view: SettingsView, qtbot: object) -> None:
    with qtbot.waitSignal(view.tts_enabled_changed, timeout=1000) as blocker:  # type: ignore[attr-defined]
        view._tts_enabled_checkbox.click()

    assert blocker.args == [False]


def test_voice_combo_defaults_to_settings_voice(view: SettingsView) -> None:
    assert view._voice_combo.currentText() == "cosette"


def test_changing_voice_combo_emits_voice_changed(view: SettingsView, qtbot: object) -> None:
    with qtbot.waitSignal(view.voice_changed, timeout=1000) as blocker:  # type: ignore[attr-defined]
        view._voice_combo.setCurrentText("alba")

    assert blocker.args == ["alba"]


def test_set_input_devices_populates_combo_with_system_default_first(view: SettingsView) -> None:
    view.set_input_devices([AudioDeviceInfo(index=2, name="USB Mic")])

    assert view._input_device_combo.itemText(0) == "System default"
    assert view._input_device_combo.itemData(0) is None
    assert view._input_device_combo.itemText(1) == "USB Mic"
    assert view._input_device_combo.itemData(1) == 2


def test_selecting_an_input_device_emits_input_device_changed(
    view: SettingsView, qtbot: object
) -> None:
    view.set_input_devices([AudioDeviceInfo(index=5, name="Headset Mic")])

    with qtbot.waitSignal(view.input_device_changed, timeout=1000) as blocker:  # type: ignore[attr-defined]
        view._input_device_combo.setCurrentIndex(1)

    assert blocker.args == [5]


def test_selecting_an_output_device_emits_output_device_changed(
    view: SettingsView, qtbot: object
) -> None:
    view.set_output_devices([AudioDeviceInfo(index=7, name="Speakers")])

    with qtbot.waitSignal(view.output_device_changed, timeout=1000) as blocker:  # type: ignore[attr-defined]
        view._output_device_combo.setCurrentIndex(1)

    assert blocker.args == [7]
