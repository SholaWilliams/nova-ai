"""Tests for SpeechService (docs/08 §1-§4, docs/11 §4 amendments) — fully mocked at the
constructor-injection boundary (fake engines/capture, fake VAD), real EventBus to assert the
actual published event sequence/payloads — same style as tests/unit/agent/test_agent.py.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from nova.core.config import VadSettings, VoiceSettings
from nova.core.errors import SpeechError
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import AssistantReply
from nova.speech import service as service_module
from nova.speech.service import SpeechService, _strip_for_speech
from nova.speech.vad import VadEvent


class _FakeCapture:
    def __init__(self, frames: list[bytes] | None = None, raise_on_start: Exception | None = None):
        self._frames = list(frames or [])
        self._raise_on_start = raise_on_start
        self.started = False
        self.stopped = False

    def start(self, device: int | None) -> None:
        if self._raise_on_start is not None:
            raise self._raise_on_start
        self.started = True

    def read_frame(self, timeout: float) -> bytes | None:
        del timeout
        if self._frames:
            return self._frames.pop(0)
        return None

    def stop(self) -> None:
        self.stopped = True


class _FakeVad:
    def __init__(self, events: list[VadEvent]) -> None:
        self._events = list(events)

    def process_frame(self, frame: bytes) -> VadEvent:
        del frame
        if self._events:
            return self._events.pop(0)
        return VadEvent.CONTINUE


class _FakeSTT:
    def __init__(self, text: str = "hello nova", raise_error: SpeechError | None = None) -> None:
        self._text = text
        self._raise_error = raise_error
        self.calls = 0

    def transcribe(self, request_id: str, pcm: bytes, sample_rate: int) -> object:
        from nova.core.models import Transcript

        del pcm, sample_rate
        self.calls += 1
        if self._raise_error is not None:
            raise self._raise_error
        return Transcript(request_id=request_id, text=self._text, confidence=0.9)


class _FakeTTS:
    def __init__(self, raise_error: SpeechError | None = None) -> None:
        self._raise_error = raise_error
        self.spoken: list[str] = []
        self.abort_called = False

    def speak(
        self, text: str, voice: str, device: int | None, should_stop: Callable[[], bool]
    ) -> None:
        del voice, device, should_stop
        if self._raise_error is not None:
            raise self._raise_error
        self.spoken.append(text)

    def abort(self) -> None:
        self.abort_called = True


def _service(
    *,
    stt: object | None = None,
    primary_tts: object | None = None,
    fallback_tts: object | None = None,
    capture_factory: Callable[[], object] | None = None,
    voice_settings: VoiceSettings | None = None,
) -> tuple[SpeechService, list[PipelineEvent]]:
    """Build a `SpeechService` with fakes wired in. Callers that exercise `listen()` must
    still monkeypatch `service_module.VadEndpointer` themselves — VAD scripting varies too
    much per test to usefully default here."""
    bus = EventBus()
    events: list[PipelineEvent] = []
    bus.subscribe(events.append)
    service = SpeechService(
        stt_engine=stt or _FakeSTT(),
        primary_tts=primary_tts or _FakeTTS(),
        fallback_tts=fallback_tts or _FakeTTS(),
        audio_capture_factory=capture_factory or (lambda: _FakeCapture()),
        bus=bus,
        vad_settings=VadSettings(),
        voice_settings=voice_settings or VoiceSettings(),
    )
    return service, events


class TestListenHappyPath:
    def test_speech_detected_and_transcribed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        frames = [b"\x00" * 960 for _ in range(3)]
        monkeypatch.setattr(
            service_module,
            "VadEndpointer",
            lambda *_a, **_kw: _FakeVad(
                [VadEvent.CONTINUE, VadEvent.SPEECH_STARTED, VadEvent.SPEECH_ENDED]
            ),
        )
        stt = _FakeSTT(text="what's the weather")
        service, events = _service(stt=stt, capture_factory=lambda: _FakeCapture(frames))

        transcript = service.listen(device=None)

        assert transcript.text == "what's the weather"
        assert stt.calls == 1
        stages = [(e.stage, e.status) for e in events]
        assert stages == [
            (PipelineStage.LISTENING, EventStatus.STARTED),
            (PipelineStage.LISTENING, EventStatus.COMPLETED),
            (PipelineStage.TRANSCRIBING, EventStatus.STARTED),
            (PipelineStage.TRANSCRIBING, EventStatus.COMPLETED),
        ]
        transcribing_completed = events[-1]
        assert transcribing_completed.payload == {
            "text": "what's the weather",
            "confidence": 0.9,
        }

    def test_listening_level_callback_fires_per_frame(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        frames = [b"\x00" * 960, b"\x00" * 960]
        monkeypatch.setattr(
            service_module,
            "VadEndpointer",
            lambda *_a, **_kw: _FakeVad([VadEvent.CONTINUE, VadEvent.SPEECH_ENDED]),
        )
        levels: list[float] = []
        bus = EventBus()
        service = SpeechService(
            stt_engine=_FakeSTT(),
            primary_tts=_FakeTTS(),
            fallback_tts=_FakeTTS(),
            audio_capture_factory=lambda: _FakeCapture(frames),
            bus=bus,
            vad_settings=VadSettings(),
            voice_settings=VoiceSettings(),
            on_listening_level=levels.append,
        )

        service.listen(device=None)

        assert len(levels) == 2


class TestListenFailureModes:
    def test_no_microphone_skips_transcribing_and_emits_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service_module, "VadEndpointer", lambda *_a, **_kw: _FakeVad([]))
        no_mic = SpeechError("no device", friendly_message="I can't hear right now")
        service, events = _service(capture_factory=lambda: _FakeCapture(raise_on_start=no_mic))

        transcript = service.listen(device=None)

        assert transcript.text == ""
        stages = [(e.stage, e.status) for e in events]
        assert stages == [
            (PipelineStage.LISTENING, EventStatus.STARTED),
            (PipelineStage.LISTENING, EventStatus.FAILED),
            (PipelineStage.TRANSCRIBING, EventStatus.SKIPPED),
            (PipelineStage.ERROR, EventStatus.COMPLETED),
        ]

    def test_no_speech_detected_skips_transcribing_without_calling_stt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        frames = [b"\x00" * 960]
        monkeypatch.setattr(
            service_module,
            "VadEndpointer",
            lambda *_a, **_kw: _FakeVad([VadEvent.CONTINUE]),
        )
        stt = _FakeSTT()
        service, events = _service(stt=stt, capture_factory=lambda: _FakeCapture(frames))

        # force the loop to end quickly via cancel rather than waiting on the real 30s cap
        service.cancel_listening()
        transcript = service.listen(device=None)

        assert transcript.text == ""
        assert stt.calls == 0
        assert (PipelineStage.TRANSCRIBING, EventStatus.SKIPPED) in [
            (e.stage, e.status) for e in events
        ]

    def test_stt_failure_emits_failed_and_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            service_module,
            "VadEndpointer",
            lambda *_a, **_kw: _FakeVad([VadEvent.SPEECH_STARTED, VadEvent.SPEECH_ENDED]),
        )
        stt = _FakeSTT(raise_error=SpeechError("boom", friendly_message="ears broken"))
        service, events = _service(
            stt=stt, capture_factory=lambda: _FakeCapture([b"\x00" * 960, b"\x00" * 960])
        )

        transcript = service.listen(device=None)

        assert transcript.text == ""
        stages = [(e.stage, e.status) for e in events]
        assert (PipelineStage.TRANSCRIBING, EventStatus.FAILED) in stages
        assert (PipelineStage.ERROR, EventStatus.COMPLETED) in stages

    def test_cancel_listening_discards_even_if_speech_was_detected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `listen()` resets its cancel/end flags at the top of every call (so a stale flag
        # from a *previous* request can't leak in) — so cancellation has to arrive mid-loop,
        # exactly as it would for real (Esc pressed on the main thread while `listen()` is
        # still running on SpeechIn). Wrapping `read_frame` to fire the cancel right after
        # the first frame is the simplest way to simulate that ordering.
        monkeypatch.setattr(
            service_module, "VadEndpointer", lambda *_a, **_kw: _FakeVad([VadEvent.SPEECH_STARTED])
        )
        stt = _FakeSTT()
        capture = _FakeCapture([b"\x00" * 960] * 5)
        service, _events = _service(stt=stt, capture_factory=lambda: capture)
        original_read = capture.read_frame

        def read_then_cancel(timeout: float) -> bytes | None:
            frame = original_read(timeout)
            service.cancel_listening()
            return frame

        capture.read_frame = read_then_cancel  # type: ignore[method-assign]

        transcript = service.listen(device=None)

        assert transcript.text == ""
        assert stt.calls == 0

    def test_end_listening_after_speech_started_still_transcribes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same mid-loop-trigger reasoning as the cancel test above, but re-press (`end_listening`)
        must still transcribe whatever was captured — the whole reason it's a separate verb
        from `cancel_listening` (docs/11 §4 amendment)."""
        monkeypatch.setattr(
            service_module, "VadEndpointer", lambda *_a, **_kw: _FakeVad([VadEvent.SPEECH_STARTED])
        )
        stt = _FakeSTT(text="partial")
        capture = _FakeCapture([b"\x00" * 960] * 5)
        service, _events = _service(stt=stt, capture_factory=lambda: capture)
        original_read = capture.read_frame

        def read_then_end(timeout: float) -> bytes | None:
            frame = original_read(timeout)
            service.end_listening()
            return frame

        capture.read_frame = read_then_end  # type: ignore[method-assign]

        transcript = service.listen(device=None)

        assert transcript.text == "partial"
        assert stt.calls == 1

    def test_hard_cap_ends_listening_even_without_vad_signal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service_module, "VadEndpointer", lambda *_a, **_kw: _FakeVad([]))
        clock = iter([0.0, 0.0, 31.0])  # started, first check, second check exceeds cap
        monkeypatch.setattr(service_module.time, "monotonic", lambda: next(clock, 31.0))
        stt = _FakeSTT()
        service, _events = _service(
            stt=stt, capture_factory=lambda: _FakeCapture([b"\x00" * 960] * 5)
        )

        transcript = service.listen(device=None)

        assert transcript.text == ""  # no VAD speech-start -> nothing to transcribe
        assert stt.calls == 0


class TestSpeak:
    def test_muted_skips_without_calling_either_engine(self) -> None:
        primary = _FakeTTS()
        fallback = _FakeTTS()
        service, events = _service(
            primary_tts=primary,
            fallback_tts=fallback,
            voice_settings=VoiceSettings(tts_enabled=False),
        )

        service.speak(AssistantReply(request_id="req_1", text="hi", spoken_text="hi"))

        assert primary.spoken == []
        assert fallback.spoken == []
        assert [(e.stage, e.status) for e in events] == [
            (PipelineStage.SPEAKING, EventStatus.SKIPPED)
        ]

    def test_empty_spoken_text_skips(self) -> None:
        primary = _FakeTTS()
        service, events = _service(primary_tts=primary)

        service.speak(AssistantReply(request_id="req_1", text="hi", spoken_text="   "))

        assert primary.spoken == []
        assert [(e.stage, e.status) for e in events] == [
            (PipelineStage.SPEAKING, EventStatus.SKIPPED)
        ]

    def test_happy_path_uses_primary_engine(self) -> None:
        primary = _FakeTTS()
        fallback = _FakeTTS()
        service, events = _service(primary_tts=primary, fallback_tts=fallback)

        service.speak(AssistantReply(request_id="req_1", text="hi", spoken_text="Hello there!"))

        assert primary.spoken == ["Hello there!"]
        assert fallback.spoken == []
        assert [(e.stage, e.status) for e in events] == [
            (PipelineStage.SPEAKING, EventStatus.STARTED),
            (PipelineStage.SPEAKING, EventStatus.COMPLETED),
        ]

    def test_primary_failure_falls_back_and_notifies_mode_change(self) -> None:
        primary = _FakeTTS(raise_error=SpeechError("pocket-tts down"))
        fallback = _FakeTTS()
        modes: list[str] = []
        bus = EventBus()
        events: list[PipelineEvent] = []
        bus.subscribe(events.append)
        service = SpeechService(
            stt_engine=_FakeSTT(),
            primary_tts=primary,
            fallback_tts=fallback,
            audio_capture_factory=lambda: _FakeCapture(),
            bus=bus,
            vad_settings=VadSettings(),
            voice_settings=VoiceSettings(),
            on_tts_mode_changed=modes.append,
        )

        service.speak(AssistantReply(request_id="req_1", text="hi", spoken_text="hi there"))

        assert fallback.spoken == ["hi there"]
        assert modes == ["offline"]
        assert [(e.stage, e.status) for e in events] == [
            (PipelineStage.SPEAKING, EventStatus.STARTED),
            (PipelineStage.SPEAKING, EventStatus.COMPLETED),
        ]

    def test_both_engines_fail_emits_failed_but_never_raises(self) -> None:
        primary = _FakeTTS(raise_error=SpeechError("pocket-tts down"))
        fallback = _FakeTTS(raise_error=SpeechError("pyttsx3 down"))
        service, events = _service(primary_tts=primary, fallback_tts=fallback)

        service.speak(AssistantReply(request_id="req_1", text="hi", spoken_text="hi there"))

        assert [(e.stage, e.status) for e in events] == [
            (PipelineStage.SPEAKING, EventStatus.STARTED),
            (PipelineStage.SPEAKING, EventStatus.FAILED),
        ]

    def test_stop_speaking_calls_abort_on_the_active_engine(self) -> None:
        primary = _FakeTTS()

        def speak_and_stop(text, voice, device, should_stop):  # noqa: ANN001
            del text, voice, device, should_stop
            service.stop_speaking()

        primary.speak = speak_and_stop  # type: ignore[method-assign]
        service, _events = _service(primary_tts=primary)

        service.speak(AssistantReply(request_id="req_1", text="hi", spoken_text="hi"))

        assert primary.abort_called is True


class TestStripForSpeech:
    def test_strips_markdown_and_collapses_whitespace(self) -> None:
        assert _strip_for_speech("**Hello**  world") == "Hello world"

    def test_strips_emoji(self) -> None:
        assert _strip_for_speech("Sunny today! ☀️") == "Sunny today!"
