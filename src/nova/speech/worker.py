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
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from nova.core.errors import SpeechError
from nova.core.models import AssistantReply
from nova.speech.audio import AudioCapture
from nova.speech.service import SpeechService
from nova.speech.wake import ClapDetector, WakeEvent

logger = logging.getLogger(__name__)

_LISTEN_FAILED_MESSAGE = "Something went wrong while I was listening."
_SPEAK_FAILED_MESSAGE = "Something went wrong while I was speaking."
_IDLE_POLL_S = 0.1  # how often a paused/disabled WakeWorker rechecks whether to resume
_MIC_RETRY_S = 1.0  # backoff before retrying microphone open after a failure


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


class WakeWorker(QObject):
    """Owns a dedicated `AudioCapture` + `ClapDetector` loop (docs/08 §7a). Lives on its own
    `QThread`, independent of `SpeechInWorker` — never opens its microphone stream at the same
    time push-to-talk has one open (the WDM-KS lesson, docs/08 §5: two simultaneous
    `sd.InputStream`s on one device is a real Windows failure mode, not a hypothetical one).
    `set_enabled`/`set_device`/`pause_for_active_listen`/`resume_after_active_listen` are all
    direct calls from any thread, same idiom as `SpeechInWorker.cancel_listening` — they only
    flip plain booleans the loop polls, nothing queued.
    """

    wake_detected = Signal()

    def __init__(
        self,
        sensitivity: float = 3.0,
        audio_capture_factory: Callable[[], AudioCapture] = AudioCapture,
    ) -> None:
        super().__init__()
        self._sensitivity = sensitivity
        self._audio_capture_factory = audio_capture_factory
        self._device: int | None = None
        self._user_enabled = False
        self._busy = False
        self._stop_requested = False

    def start_loop(self, device: int | None) -> None:
        """Slot — connect to `QThread.started`. Blocks until `stop_loop()`, polling whether
        it should actually be capturing right now rather than opening/closing the stream on
        every flip (Settings toggle, an active listen cycle) — cheaper and simpler than
        tearing the stream down and rebuilding it on each transition."""
        self._device = device
        while not self._stop_requested:
            if not self._should_capture():
                time.sleep(_IDLE_POLL_S)
                continue
            self._capture_until_interrupted()

    def stop_loop(self) -> None:
        """Direct call, any thread — breaks the loop so the thread can quit at app shutdown."""
        self._stop_requested = True

    def set_enabled(self, enabled: bool) -> None:
        """Direct call, any thread — mirrors the `WakeSettings.enabled` Settings toggle."""
        self._user_enabled = enabled

    def set_device(self, device: int | None) -> None:
        """Direct call, any thread — mirrors the Settings input-device selection."""
        self._device = device

    def pause_for_active_listen(self) -> None:
        """Direct call, any thread — a real listen/transcribe cycle is running."""
        self._busy = True

    def resume_after_active_listen(self) -> None:
        """Direct call, any thread — that cycle ended."""
        self._busy = False

    def _should_capture(self) -> bool:
        return self._user_enabled and not self._busy and not self._stop_requested

    def _capture_until_interrupted(self) -> None:
        capture = self._audio_capture_factory()
        detector = ClapDetector(self._sensitivity)
        try:
            capture.start(self._device)
        except SpeechError:
            logger.warning("Wake listener couldn't open the microphone; retrying shortly")
            time.sleep(_MIC_RETRY_S)
            return
        try:
            while self._should_capture():
                frame = capture.read_frame(timeout=_IDLE_POLL_S)
                if frame is None:
                    continue
                if detector.process_frame(frame) is WakeEvent.WAKE_DETECTED:
                    self.wake_detected.emit()
        finally:
            capture.stop()
