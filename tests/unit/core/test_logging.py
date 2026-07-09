"""Unit tests for nova.core.logging — handler setup, scrubbing, and the event bridge."""

import logging
import logging.handlers
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

import nova.core.logging as nova_logging
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.logging import EventLogBridge, register_secrets, setup_logging


@pytest.fixture(autouse=True)
def _reset_secret_scrubber() -> Iterator[None]:
    """`_scrubber` is a process-wide singleton — don't let one test's secrets leak into another."""
    nova_logging._scrubber._secrets.clear()
    yield
    nova_logging._scrubber._secrets.clear()


def _read_log(data_dir: Path) -> str:
    for handler in logging.getLogger("nova").handlers:
        handler.flush()
    return (data_dir / "logs" / "nova.log").read_text(encoding="utf-8")


def test_setup_logging_creates_log_file(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    logging.getLogger("nova.test").info("hello")

    assert "hello" in _read_log(tmp_path)


def test_setup_logging_uses_rotating_file_handler_with_expected_limits(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path, console=False)

    file_handlers = [
        h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 2 * 1024 * 1024
    assert file_handlers[0].backupCount == 5


def test_setup_logging_sets_requested_level(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path, level="DEBUG", console=False)
    assert logger.getEffectiveLevel() == logging.DEBUG


def test_setup_logging_is_idempotent_about_handler_count(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    logger = setup_logging(tmp_path, console=False)
    assert len(logger.handlers) == 1  # file handler only; not duplicated


def test_log_call_without_request_id_does_not_raise(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    # No `extra={"request_id": ...}` — must not KeyError against the format string.
    logging.getLogger("nova.somewhere").warning("something odd happened")

    log_text = _read_log(tmp_path)
    assert "something odd happened" in log_text
    assert "nova.somewhere - something odd happened" in log_text  # request_id defaulted to "-"


def test_child_logger_propagates_to_nova_handlers(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    logging.getLogger("nova.core.config").warning("settings.json is corrupt")

    assert "settings.json is corrupt" in _read_log(tmp_path)


def test_console_handler_falls_back_when_rich_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nova_logging, "RichHandler", None)
    logger = setup_logging(tmp_path, console=True)

    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)


def test_console_handler_uses_rich_when_available(tmp_path: Path) -> None:
    if nova_logging.RichHandler is None:
        pytest.skip("rich is not installed in this environment")
    logger = setup_logging(tmp_path, console=True)

    assert any(isinstance(h, nova_logging.RichHandler) for h in logger.handlers)


# ── secret scrubbing (S-6) ───────────────────────────────────────────


def test_register_secrets_redacts_value_from_later_messages(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    register_secrets("super-secret-key")

    logging.getLogger("nova.providers.gemini").info("using key %s", "super-secret-key")

    log_text = _read_log(tmp_path)
    assert "super-secret-key" not in log_text
    assert "REDACTED" in log_text


def test_register_secrets_ignores_falsy_values(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    register_secrets(None, "")  # must not raise

    logging.getLogger("nova.test").info("no secrets here")
    assert "no secrets here" in _read_log(tmp_path)


# ── EventLogBridge ────────────────────────────────────────────────────


def test_event_log_bridge_logs_pipeline_events_at_info(tmp_path: Path) -> None:
    setup_logging(tmp_path, level="INFO", console=False)
    bus = EventBus()
    EventLogBridge(bus)

    bus.publish(
        PipelineEvent(
            request_id="req_deadbeef",
            stage=PipelineStage.EXECUTING,
            status=EventStatus.COMPLETED,
            detail="Checking the weather in Lagos",
            payload={"duration_ms": 642},
            ts=datetime.now(UTC),
        )
    )

    log_text = _read_log(tmp_path)
    assert "req_deadbeef" in log_text
    assert "Checking the weather in Lagos" in log_text
    assert "EXECUTING" in log_text


def test_event_log_bridge_close_stops_further_logging(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    bus = EventBus()
    bridge = EventLogBridge(bus)
    bridge.close()

    bus.publish(
        PipelineEvent(
            request_id="req_after_close",
            stage=PipelineStage.IDLE,
            status=EventStatus.STARTED,
            detail="should not be logged",
            payload=None,
            ts=datetime.now(UTC),
        )
    )

    assert "req_after_close" not in _read_log(tmp_path)
