"""Tests for SpeechInWorker / SpeechOutWorker / WakeWorker — thread-boundary signal wiring
(docs/03 §5, docs/08 §7a).

Stubs stand in for a real SpeechService (its own behavior is covered by test_service.py) —
same style and division of responsibility as tests/unit/agent/test_worker.py. WakeWorker
tests fake `AudioCapture` and monkeypatch `ClapDetector`'s underlying `_rms` (same trick as
test_wake.py) rather than touching real hardware.
"""

from __future__ import annotations

import pytest

from nova.core.errors import SpeechError
from nova.core.models import AssistantReply, Transcript
from nova.speech import wake as wake_module
from nova.speech.worker import SpeechInWorker, SpeechOutWorker, WakeWorker


class _StubSpeechService:
    def __init__(self) -> None:
        self.cancel_called = False
        self.end_called = False
        self.stop_called = False
        self.warm_up_called = False
        self._listen_outcome: Transcript | Exception | None = None
        self._speak_outcome: None | Exception = None

    def script_listen(self, outcome: Transcript | Exception) -> None:
        self._listen_outcome = outcome

    def script_speak(self, outcome: Exception | None) -> None:
        self._speak_outcome = outcome

    def listen(self, device: int | None) -> Transcript:
        del device
        if isinstance(self._listen_outcome, Exception):
            raise self._listen_outcome
        assert isinstance(self._listen_outcome, Transcript)
        return self._listen_outcome

    def speak(self, reply: AssistantReply) -> None:
        del reply
        if self._speak_outcome is not None:
            raise self._speak_outcome

    def cancel_listening(self) -> None:
        self.cancel_called = True

    def end_listening(self) -> None:
        self.end_called = True

    def stop_speaking(self) -> None:
        self.stop_called = True

    def warm_up_tts(self) -> None:
        self.warm_up_called = True


def _transcript(text: str = "hi", request_id: str = "req_1") -> Transcript:
    return Transcript(request_id=request_id, text=text, confidence=None)


class TestSpeechInWorker:
    def test_successful_listen_emits_transcript_ready(self, qtbot) -> None:  # noqa: ANN001
        service = _StubSpeechService()
        transcript = _transcript()
        service.script_listen(transcript)
        worker = SpeechInWorker(service)  # type: ignore[arg-type]

        with qtbot.waitSignal(worker.transcript_ready, timeout=1000) as blocker:
            worker.listen_request(device=None)

        assert blocker.args == [transcript]

    def test_unexpected_exception_emits_failed(self, qtbot) -> None:  # noqa: ANN001
        service = _StubSpeechService()
        service.script_listen(RuntimeError("boom"))
        worker = SpeechInWorker(service)  # type: ignore[arg-type]

        with qtbot.waitSignal(worker.failed, timeout=1000) as blocker:
            worker.listen_request(device=None)

        assert blocker.args[0]

    def test_cancel_listening_forwards_to_service(self) -> None:
        service = _StubSpeechService()
        worker = SpeechInWorker(service)  # type: ignore[arg-type]

        worker.cancel_listening()

        assert service.cancel_called is True

    def test_end_listening_forwards_to_service(self) -> None:
        service = _StubSpeechService()
        worker = SpeechInWorker(service)  # type: ignore[arg-type]

        worker.end_listening()

        assert service.end_called is True


class TestSpeechOutWorker:
    def test_successful_speak_emits_speech_done(self, qtbot) -> None:  # noqa: ANN001
        service = _StubSpeechService()
        service.script_speak(None)
        worker = SpeechOutWorker(service)  # type: ignore[arg-type]
        reply = AssistantReply(request_id="req_9", text="hi", spoken_text="hi")

        with qtbot.waitSignal(worker.speech_done, timeout=1000) as blocker:
            worker.speak_request(reply)

        assert blocker.args == ["req_9"]

    def test_unexpected_exception_emits_failed(self, qtbot) -> None:  # noqa: ANN001
        service = _StubSpeechService()
        service.script_speak(RuntimeError("boom"))
        worker = SpeechOutWorker(service)  # type: ignore[arg-type]
        reply = AssistantReply(request_id="req_9", text="hi", spoken_text="hi")

        with qtbot.waitSignal(worker.failed, timeout=1000) as blocker:
            worker.speak_request(reply)

        assert blocker.args[0]

    def test_stop_speaking_forwards_to_service(self) -> None:
        service = _StubSpeechService()
        worker = SpeechOutWorker(service)  # type: ignore[arg-type]

        worker.stop_speaking()

        assert service.stop_called is True

    def test_warm_up_forwards_to_service(self) -> None:
        service = _StubSpeechService()
        worker = SpeechOutWorker(service)  # type: ignore[arg-type]

        worker.warm_up()

        assert service.warm_up_called is True


class _FakeAudioCapture:
    """Scripted `read_frame` sequence; calls `on_exhausted` once frames run out (tests use
    this to stop `WakeWorker`'s loop deterministically instead of hanging on real hardware)."""

    def __init__(self, frames: list[bytes], on_exhausted: object = None) -> None:
        self._frames = list(frames)
        self._on_exhausted = on_exhausted
        self.started_device: object = "not started"
        self.stop_called = False
        self.raise_on_start: Exception | None = None

    def start(self, device: int | None) -> None:
        if self.raise_on_start is not None:
            raise self.raise_on_start
        self.started_device = device

    def read_frame(self, timeout: float) -> bytes | None:
        del timeout
        if self._frames:
            return self._frames.pop(0)
        if self._on_exhausted is not None:
            self._on_exhausted()  # type: ignore[operator]
        return None

    def stop(self) -> None:
        self.stop_called = True


_DUMMY_FRAME = b"\x00" * 960
# Same shape as test_wake.py's valid double-clap fixture: loud/quiet pair, a 300ms gap, then
# a second loud/quiet pair -- the last frame is the one that resolves WAKE_DETECTED.
_DOUBLE_CLAP_RMS = [0.9, 0.0] + [0.0] * 10 + [0.9, 0.0]


class TestWakeWorker:
    def test_should_capture_requires_enabled_and_not_busy(self) -> None:
        worker = WakeWorker(audio_capture_factory=lambda: _FakeAudioCapture([]))

        assert worker._should_capture() is False

        worker.set_enabled(True)
        assert worker._should_capture() is True

        worker.pause_for_active_listen()
        assert worker._should_capture() is False

        worker.resume_after_active_listen()
        assert worker._should_capture() is True

    def test_run_returns_immediately_when_already_stopped(self) -> None:
        worker = WakeWorker(audio_capture_factory=lambda: _FakeAudioCapture([]))
        worker.stop_loop()

        worker.run()  # must not hang -- this is QThread's real entry point (see class docstring)

    def test_capture_until_interrupted_emits_wake_detected_on_double_clap(
        self, monkeypatch: pytest.MonkeyPatch, qtbot: object
    ) -> None:
        frames = [_DUMMY_FRAME] * len(_DOUBLE_CLAP_RMS)
        capture = _FakeAudioCapture(frames)
        worker = WakeWorker(audio_capture_factory=lambda: capture)
        worker.set_enabled(True)
        capture._on_exhausted = worker.stop_loop

        it = iter(_DOUBLE_CLAP_RMS)
        monkeypatch.setattr(wake_module, "_rms", lambda _frame: next(it))

        with qtbot.waitSignal(worker.wake_detected, timeout=1000):  # type: ignore[attr-defined]
            worker._capture_until_interrupted()

        assert capture.stop_called is True
        assert capture.started_device is None

    def test_capture_until_interrupted_handles_mic_open_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        capture = _FakeAudioCapture([])
        capture.raise_on_start = SpeechError("boom", friendly_message="no mic")
        worker = WakeWorker(audio_capture_factory=lambda: capture)
        worker.set_enabled(True)
        monkeypatch.setattr("nova.speech.worker.time.sleep", lambda _s: None)

        worker._capture_until_interrupted()  # must not raise

        assert capture.stop_called is False  # stream never opened, nothing to stop
