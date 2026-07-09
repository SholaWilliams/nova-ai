"""Logging setup: rotating file handler, secret scrubbing, event->log bridge (docs/14 §3).

Runtime logging never hard-depends on `rich` (TD-11) — it's imported defensively and used
only when present, so a packaged build that omits it still logs correctly to file.
"""

from __future__ import annotations

import logging
import logging.handlers
import threading
from pathlib import Path

from nova.core.events import EventBus, PipelineEvent

try:
    from rich.logging import RichHandler
except ImportError:  # pragma: no cover - exercised via monkeypatched absence in tests
    RichHandler = None  # type: ignore[assignment, misc]

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
_BACKUP_COUNT = 5
_REDACTED = "***REDACTED***"


class _RequestIdFilter(logging.Filter):
    """Defaults `record.request_id` to "-" so the format string never KeyErrors.

    Most log calls (warnings from deep inside a module) have no request in flight; only
    calls made through `EventLogBridge` pass a real one via `extra={"request_id": ...}`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


class _SecretScrubberFilter(logging.Filter):
    """Redacts known secret values from every log record (S-6: keys are never logged).

    Values are registered after the fact (`register_secrets`) since secrets are typically
    loaded slightly after logging is set up — the filter starts empty and is safe either way.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._secrets: list[str] = []

    def add(self, value: str) -> None:
        with self._lock:
            if value and value not in self._secrets:
                self._secrets.append(value)

    def filter(self, record: logging.LogRecord) -> bool:
        with self._lock:
            secrets = list(self._secrets)
        if not secrets:
            return True
        record.msg = self._redact(str(record.msg), secrets)
        if record.args:
            record.args = tuple(
                self._redact(arg, secrets) if isinstance(arg, str) else arg for arg in record.args
            )
        return True

    @staticmethod
    def _redact(text: str, secrets: list[str]) -> str:
        for secret in secrets:
            text = text.replace(secret, _REDACTED)
        return text


_scrubber = _SecretScrubberFilter()


def register_secrets(*values: str | None) -> None:
    """Redact these values from all future log output (S-6). Falsy values are skipped."""
    for value in values:
        if value:
            _scrubber.add(value)


def setup_logging(data_dir: Path, level: str = "INFO", console: bool = True) -> logging.Logger:
    """Configure the `nova` logger: rotating file handler + optional dev console.

    Safe to call once at startup (`app.py`). Child loggers created elsewhere via
    `logging.getLogger(__name__)` propagate up to these handlers automatically.
    """
    logs_dir = data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("nova")
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "nova.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    _install_filters(file_handler)
    logger.addHandler(file_handler)

    if console:
        logger.addHandler(_build_console_handler())

    return logger


def _build_console_handler() -> logging.Handler:
    if RichHandler is not None:
        handler: logging.Handler = RichHandler(show_path=False, rich_tracebacks=True)
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    _install_filters(handler)
    return handler


def _install_filters(handler: logging.Handler) -> None:
    handler.addFilter(_RequestIdFilter())
    handler.addFilter(_scrubber)


class EventLogBridge:
    """Subscribes to an EventBus and writes every PipelineEvent to the log at INFO (A-2).

    A normal `logging` consumer, not a Qt object — works regardless of which thread
    `EventBus.publish()` was called from.
    """

    def __init__(self, bus: EventBus, logger: logging.Logger | None = None) -> None:
        self._bus = bus
        self._logger = logger or logging.getLogger("nova.events")
        bus.subscribe(self._on_event)

    def close(self) -> None:
        """Unsubscribe from the bus. Call if a bridge instance is ever torn down early."""
        self._bus.unsubscribe(self._on_event)

    def _on_event(self, event: PipelineEvent) -> None:
        self._logger.info(
            "%s %s: %s",
            event.stage.value,
            event.status.value,
            event.detail,
            extra={"request_id": event.request_id},
        )
