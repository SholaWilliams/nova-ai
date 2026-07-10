"""Tests for SpeechInWorker / SpeechOutWorker — thread-boundary signal wiring (docs/03 §5).

Stubs stand in for a real SpeechService (its own behavior is covered by test_service.py) —
same style and division of responsibility as tests/unit/agent/test_worker.py.
"""

from __future__ import annotations

from nova.core.models import AssistantReply, Transcript
from nova.speech.worker import SpeechInWorker, SpeechOutWorker


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
