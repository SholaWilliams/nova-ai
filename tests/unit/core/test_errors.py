"""Unit tests for nova.core.errors — the NovaError hierarchy and the top-level exception hook."""

import logging
import sys

import pytest
from PySide6.QtWidgets import QMessageBox

from nova.core.errors import (
    ConfigError,
    MemoryError,  # shadows the builtin intentionally, matches docs/03 §14 - see core/errors.py
    NovaError,
    ProviderError,
    SpeechError,
    ToolDenied,
    ToolError,
    ToolInvalidArgs,
    ToolTimeout,
    install_excepthook,
)

# ── hierarchy ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "error_cls",
    [ConfigError, ProviderError, SpeechError, ToolError, MemoryError],
)
def test_direct_subclasses_are_nova_errors(error_cls: type[NovaError]) -> None:
    assert issubclass(error_cls, NovaError)
    assert issubclass(error_cls, Exception)


@pytest.mark.parametrize("error_cls", [ToolTimeout, ToolDenied, ToolInvalidArgs])
def test_tool_error_subclasses_are_tool_errors(error_cls: type[ToolError]) -> None:
    assert issubclass(error_cls, ToolError)
    assert issubclass(error_cls, NovaError)


def test_nova_error_uses_default_friendly_message_when_none_given() -> None:
    error = ConfigError("GEMINI key missing from environment")
    assert error.friendly_message
    assert "GEMINI" not in error.friendly_message  # technical detail stays out of child copy


def test_nova_error_preserves_custom_friendly_message() -> None:
    error = ToolTimeout(
        "weather tool exceeded 15s watchdog",
        friendly_message="That took too long — let's try again.",
    )
    assert error.friendly_message == "That took too long — let's try again."


def test_str_of_error_is_the_technical_message() -> None:
    error = ProviderError(
        "HTTP 401 from Gemini API", friendly_message="I can't reach my brain right now."
    )
    assert str(error) == "HTTP 401 from Gemini API"
    assert str(error) != error.friendly_message


# ── install_excepthook ────────────────────────────────────────────────


def test_install_excepthook_replaces_sys_excepthook(monkeypatch: pytest.MonkeyPatch) -> None:
    original = sys.excepthook
    monkeypatch.setattr(sys, "excepthook", original)  # ensure restoration after the test

    install_excepthook()

    assert sys.excepthook is not original


def test_hook_logs_and_does_not_raise_without_qapplication(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from nova.core.errors import _handle_uncaught_exception

    monkeypatch.setattr("PySide6.QtWidgets.QApplication.instance", lambda: None)

    try:
        raise ConfigError("missing key")
    except ConfigError:
        exc_type, exc_value, exc_tb = sys.exc_info()

    with caplog.at_level(logging.ERROR, logger="nova.core.errors"):
        _handle_uncaught_exception(exc_type, exc_value, exc_tb)  # type: ignore[arg-type]

    assert any("Uncaught exception" in r.message for r in caplog.records)


def test_hook_shows_friendly_dialog_when_qapplication_exists(
    monkeypatch: pytest.MonkeyPatch, qtbot: object
) -> None:
    from nova.core.errors import _handle_uncaught_exception

    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: calls.append(args)))

    try:
        raise ToolTimeout("timed out", friendly_message="That took too long.")
    except ToolTimeout:
        exc_type, exc_value, exc_tb = sys.exc_info()

    _handle_uncaught_exception(exc_type, exc_value, exc_tb)  # type: ignore[arg-type]

    assert len(calls) == 1
    assert calls[0][2] == "That took too long."


def test_hook_passes_keyboard_interrupt_to_default_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    from nova.core.errors import _handle_uncaught_exception

    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *args: calls.append(args))

    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        exc_type, exc_value, exc_tb = sys.exc_info()

    _handle_uncaught_exception(exc_type, exc_value, exc_tb)  # type: ignore[arg-type]

    assert len(calls) == 1
