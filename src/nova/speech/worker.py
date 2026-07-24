"""SpeechInWorker / SpeechOutWorker: run `SpeechService` off the main thread (docs/03 §5).

Two plain `QObject`s, each `.moveToThread()`'d onto its own `QThread` in `app.py` — the exact
`AgentWorker` idiom (docs/03 §5 names these as "SpeechInWorker (QThread)"/"SpeechOutWorker
(QThread)"), not a new one. `cancel_listening`/`end_listening`/`stop_speaking` must be
connected with a **direct** (non-queued) Qt connection from `app.py`: the target thread is
blocked inside `SpeechService.listen()`/`speak()` when these need to land — a queued
connection would sit undelivered in the worker's own event queue until the blocking call
returns, defeating the point (see `Agent.cancel()`'s docstring for the identical reasoning).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from nova.core.models import AssistantReply
from nova.speech.service import SpeechService

logger = logging.getLogger(__name__)

_LISTEN_FAILED_MESSAGE = "Something went wrong while I was listening."
_SPEAK_FAILED_MESSAGE = "Something went wrong while I was speaking."


class SpeechInWorker(QObject):
    """Owns the one in-flight `SpeechService.listen()` call. Lives on its own `QThread`."""

    transcript_ready = Signal(object)  # Transcript
    listening_level = Signal(float)
    failed = Signal(str)  # friendly_message — last-resort safety net

    def __init__(self, service: SpeechService) -> None:
        super().__init__()
        self._service = service

    def listen_request(self, device: int | None) -> None:
        """Slot — connect with a queued (cross-thread) connection from the main thread."""
        try:
            transcript = self._service.listen(device)
        except Exception:
            logger.exception("Unhandled error in SpeechService.listen")
            self.failed.emit(_LISTEN_FAILED_MESSAGE)
            return
        self.transcript_ready.emit(transcript)

    def cancel_listening(self) -> None:
        """Direct call only, any thread — see module docstring."""
        self._service.cancel_listening()

    def end_listening(self) -> None:
        """Direct call only, any thread — see module docstring."""
        self._service.end_listening()


class SpeechOutWorker(QObject):
    """Owns the one in-flight `SpeechService.speak()` call. Lives on its own `QThread`."""

    speech_done = Signal(str)  # request_id
    failed = Signal(str)  # friendly_message — last-resort safety net
    tts_mode_changed = Signal(str)  # "primary" | "offline" (docs/08 §4) — `app.py` wires
    # `SpeechService.set_tts_mode_callback(speech_out_worker.tts_mode_changed.emit)` so the
    # callback (invoked from this worker's own thread) crosses to the main thread via Qt's
    # normal queued-connection delivery rather than touching a widget directly off-thread.
    speech_started = Signal(str)  # request_id — audio has actually started (docs/05 §9:
    # "text reveals with the TTS start"); wired the same way as `tts_mode_changed` above via
    # `SpeechService.set_speech_started_callback(speech_out_worker.speech_started.emit)`.

    def __init__(self, service: SpeechService) -> None:
        super().__init__()
        self._service = service

    def warm_up(self) -> None:
        """Connect to `QThread.started` — runs once, as soon as this worker's thread begins,
        well ahead of the first real request (see `SpeechService.warm_up_tts`'s docstring)."""
        self._service.warm_up_tts()

    def speak_request(self, reply: AssistantReply) -> None:
        """Slot — connect with a queued (cross-thread) connection from the main thread."""
        try:
            self._service.speak(reply)
        except Exception:
            logger.exception("Unhandled error in SpeechService.speak")
            self.failed.emit(_SPEAK_FAILED_MESSAGE)
            return
        self.speech_done.emit(reply.request_id)

    def stop_speaking(self) -> None:
        """Direct call only, any thread — see module docstring."""
        self._service.stop_speaking()
