"""Tests for RemoteTTSEngine (docs/04 TD-6 M9 revision) — `httpx.MockTransport` fakes the
`takada-tts-service` HTTP boundary, `AudioPlayback` is faked (same `_FakePlayback` shape
`test_pocket_tts.py` used before this replaced it), never touches a real network socket.

Response fixtures are built with stdlib `wave` (the same module `takada-tts-service`'s own
`app/wav.py` uses) so the 44-byte header this engine parses is byte-for-byte what the real
service produces, not a hand-rolled approximation.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Callable

import httpx
import pytest

from nova.core.errors import SpeechError
from nova.speech.tts.remote_tts import RemoteTTSEngine

_URL = "http://127.0.0.1:8020/v1/synthesize"
_HEALTH_URL = "http://127.0.0.1:8020/health"


class _FakePlayback:
    instances: list[_FakePlayback] = []

    def __init__(self) -> None:
        self.opened: tuple[int, int, int | None] | None = None
        self.written: list[bytes] = []
        self.aborted = False
        self.closed = False
        _FakePlayback.instances.append(self)

    def open(self, samplerate: int, channels: int, device: int | None) -> None:
        self.opened = (samplerate, channels, device)

    def write(self, pcm: bytes) -> None:
        self.written.append(pcm)

    def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset() -> None:
    _FakePlayback.instances.clear()


def _wav_header(sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
    header = buf.getvalue()
    assert len(header) == 44
    return header


def _engine(handler: Callable[[httpx.Request], httpx.Response]) -> RemoteTTSEngine:
    engine = RemoteTTSEngine(
        "http://127.0.0.1:8020", tenant_id="nova", audio_playback_factory=_FakePlayback
    )
    engine._client = httpx.Client(
        base_url="http://127.0.0.1:8020", transport=httpx.MockTransport(handler)
    )
    return engine


def _streaming_handler(
    chunks: list[bytes], status: int = 200
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, content=iter(chunks))

    return handler


def _raising_handler(exc: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise exc

    return handler


def test_speak_parses_header_and_streams_pcm_to_playback() -> None:
    header = _wav_header(24000)
    pcm1, pcm2 = b"\x01\x02\x03\x04", b"\x05\x06\x07\x08"
    engine = _engine(_streaming_handler([header + pcm1, pcm2]))

    engine.speak("hello", voice="alba", device=None, should_stop=lambda: False)

    playback = _FakePlayback.instances[0]
    assert playback.opened == (24000, 1, None)
    assert b"".join(playback.written) == pcm1 + pcm2
    assert playback.closed is True


def test_speak_raises_speech_error_on_http_status_error() -> None:
    engine = _engine(_streaming_handler([b"unavailable"], status=503))

    with pytest.raises(SpeechError):
        engine.speak("hello", voice="alba", device=None, should_stop=lambda: False)

    assert _FakePlayback.instances[0].closed is True


def test_speak_raises_speech_error_on_connection_failure() -> None:
    engine = _engine(_raising_handler(httpx.ConnectError("connection refused")))

    with pytest.raises(SpeechError):
        engine.speak("hello", voice="alba", device=None, should_stop=lambda: False)

    assert _FakePlayback.instances[0].closed is True


def test_on_start_fires_once_the_wav_header_is_parsed_and_playback_is_open() -> None:
    header = _wav_header(24000)
    engine = _engine(_streaming_handler([header + b"\x01\x02", b"\x03\x04"]))
    calls: list[tuple[int, int, int | None] | None] = []

    def on_start() -> None:
        calls.append(_FakePlayback.instances[0].opened)

    engine.speak("hello", voice="alba", device=None, should_stop=lambda: False, on_start=on_start)

    assert calls == [(24000, 1, None)]  # playback was already open when on_start fired


def test_on_start_is_optional() -> None:
    header = _wav_header(24000)
    engine = _engine(_streaming_handler([header + b"\x01\x02"]))

    engine.speak("hello", voice="alba", device=None, should_stop=lambda: False)  # must not raise


def test_should_stop_halts_streaming_partway_through() -> None:
    header = _wav_header(24000)
    pcm1, pcm2, pcm3 = b"\x01\x02", b"\x03\x04", b"\x05\x06"
    engine = _engine(_streaming_handler([header + pcm1, pcm2, pcm3]))
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    engine.speak("hello", voice="alba", device=None, should_stop=should_stop)

    assert _FakePlayback.instances[0].written == [pcm1]


def test_abort_forwards_to_the_active_playback_instance() -> None:
    header = _wav_header(24000)
    engine = _engine(_streaming_handler([header + b"\x01\x02", b"\x03\x04"]))
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            engine.abort()  # simulates SpeechService.stop_speaking() firing mid-flight
        return False

    engine.speak("hello", voice="alba", device=None, should_stop=should_stop)

    assert _FakePlayback.instances[0].aborted is True


def test_abort_after_speak_returns_is_a_no_op() -> None:
    header = _wav_header(24000)
    engine = _engine(_streaming_handler([header]))

    engine.speak("hello", voice="alba", device=None, should_stop=lambda: False)
    engine.abort()  # _playback already cleared to None — must not raise

    assert _FakePlayback.instances[0].aborted is False


def test_warm_up_checks_health_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    engine = _engine(handler)

    engine.warm_up("alba")  # must not raise


def test_warm_up_raises_speech_error_when_service_unavailable() -> None:
    engine = _engine(_raising_handler(httpx.ConnectError("connection refused")))

    with pytest.raises(SpeechError):
        engine.warm_up("alba")
