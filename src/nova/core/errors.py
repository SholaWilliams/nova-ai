"""NovaError hierarchy and the top-level exception hook (docs/03 §14, A-6).

"Fail conversationally": every error path ends in a pipeline ERROR event (producer's job)
and a child-friendly message — never a stack trace reaching the user. Exceptions here carry
that friendly copy alongside the technical `str(exc)` used in logs.
"""

from __future__ import annotations

import logging
import sys
from types import TracebackType

logger = logging.getLogger(__name__)

_DEFAULT_FRIENDLY_MESSAGE = "Something went wrong on my end — let's try that again."


class NovaError(Exception):
    """Base for every NOVA-raised error.

    `friendly_message` is blame-free, child-facing copy (docs/05 §9) suitable for display
    or speech. `str(exc)` remains the technical message, for logs and developers.
    """

    def __init__(self, message: str, *, friendly_message: str | None = None) -> None:
        super().__init__(message)
        self.friendly_message = friendly_message or _DEFAULT_FRIENDLY_MESSAGE


class ConfigError(NovaError):
    """Bad or missing settings / API keys (FR-47)."""


class ProviderError(NovaError):
    """An LLM API call failed — triggers fallback to the next provider (FR-48)."""


class AuthError(ProviderError):
    """An API key was rejected. Never retried — retrying a bad key is just noise."""


class RateLimited(ProviderError):  # noqa: N818 - name matches docs/10 §1's spec'd tree exactly
    """The provider throttled the request. `retry_after` (seconds) is honored if given."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        friendly_message: str | None = None,
    ) -> None:
        super().__init__(message, friendly_message=friendly_message)
        self.retry_after = retry_after


class Transient(ProviderError):  # noqa: N818 - name matches docs/10 §1's spec'd tree exactly
    """A timeout, 5xx, or other transient failure — worth one same-provider retry."""


class SafetyBlocked(ProviderError):  # noqa: N818 - name matches docs/10 §1's spec'd tree exactly
    """The provider refused to generate at all (blocked before any candidate existed).

    Distinct from a normal `LLMResponse(finish_reason="safety")` (a *soft* filter where a
    response did come back) — this is the *hard* case with nothing to normalize. Never
    triggers retry or fallback (docs/10 §3.2): the block is a correct outcome, not an outage.
    """


class SpeechError(NovaError):
    """A microphone, STT, or TTS operation failed (SC-6)."""


class ToolError(NovaError):
    """A tool failed to execute."""


class ToolTimeout(ToolError):  # noqa: N818 - name matches the approved docs/03 §14 tree exactly
    """The Executor's watchdog fired before the tool finished (FR-49)."""


class ToolDenied(ToolError):  # noqa: N818 - name matches the approved docs/03 §14 tree exactly
    """The user declined the confirmation gate for a sensitive tool (FR-20)."""


class ToolInvalidArgs(ToolError):  # noqa: N818 - matches the approved docs/03 §14 tree exactly
    """The LLM's tool-call arguments failed schema validation (FR-16)."""


# Name matches the approved docs/03 §14 tree exactly; intentionally shadows the builtin
# `MemoryError` within this module's namespace (nothing here needs the builtin).
class MemoryError(NovaError):
    """A memory persistence operation (facts, conversation, preferences) failed."""


def install_excepthook() -> None:
    """Install the top-level `sys.excepthook`: log, show a friendly dialog, keep the app alive.

    Headless-safe: if no `QApplication` instance exists (unit tests, `--self-check`), it only
    logs. `KeyboardInterrupt` is passed through to the default hook so Ctrl+C still works.
    """
    sys.excepthook = _handle_uncaught_exception


def _handle_uncaught_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

    friendly_message = getattr(exc_value, "friendly_message", _DEFAULT_FRIENDLY_MESSAGE)
    _show_friendly_dialog(friendly_message)


def _show_friendly_dialog(message: str) -> None:
    # Imported lazily so importing nova.core.errors never requires a Qt platform plugin
    # (e.g. constructing NovaError subclasses in a plain unit test).
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance()
    if app is None:
        return
    QMessageBox.critical(None, "NOVA", message)
