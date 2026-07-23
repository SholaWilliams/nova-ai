"""Tests for AudioCapture / AudioPlayback (docs/08 §2, §5) — `sounddevice` fully mocked at
the module boundary (`nova.speech.audio.sd`); never touches real PortAudio devices.
"""

from __future__ import annotations

import queue

import numpy as np
import pytest

from nova.core.errors import SpeechError
from nova.speech import audio as audio_module
from nova.speech.audio import AudioCapture, AudioPlayback


class _FakeInputStream:
    instances: list[_FakeInputStream] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.started = False
        self.closed = False
        _FakeInputStream.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class _RaisingInputStream:
    def __init__(self, **_kwargs: object) -> None:
        raise audio_module.sd.PortAudioError("no device")


class _FakeOutputStream:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.started = False
        self.aborted = False
        self.closed = False
        self.written: list[bytes] = []

    def start(self) -> None:
        self.started = True

    def write(self, pcm: bytes) -> None:
        self.written.append(pcm)

    def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _clear_fake_instances() -> None:
    _FakeInputStream.instances.clear()


class TestAudioCapture:
    def test_start_opens_stream_at_vad_aligned_blocksize(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(audio_module.sd, "InputStream", _FakeInputStream)
        capture = AudioCapture()

        capture.start(device=3)

        stream = _FakeInputStream.instances[0]
        assert stream.started is True
        assert stream.kwargs["samplerate"] == audio_module.SAMPLE_RATE
        assert stream.kwargs["blocksize"] == audio_module.FRAME_SAMPLES
        assert stream.kwargs["device"] == 3

    def test_portaudio_error_becomes_speech_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audio_module.sd, "InputStream", _RaisingInputStream)
        capture = AudioCapture()

        with pytest.raises(SpeechError):
            capture.start(device=None)

    def test_callback_pushes_frame_bytes_onto_queue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audio_module.sd, "InputStream", _FakeInputStream)
        capture = AudioCapture()
        capture.start(device=None)
        stream = _FakeInputStream.instances[0]

        stream.callback(b"\x01\x02", 1, None, None)

        assert capture.read_frame(timeout=0.1) == b"\x01\x02"

    def test_read_frame_times_out_to_none_on_silence(self) -> None:
        capture = AudioCapture()

        assert capture.read_frame(timeout=0.05) is None

    def test_callback_drops_frames_when_queue_is_full(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(audio_module.sd, "InputStream", _FakeInputStream)
        capture = AudioCapture()
        capture.start(device=None)
        stream = _FakeInputStream.instances[0]
        capture._queue = queue.Queue(maxsize=1)  # shrink for a fast, deterministic test

        stream.callback(b"\x01", 1, None, None)
        stream.callback(b"\x02", 1, None, None)  # dropped, must not raise

        assert capture.read_frame(timeout=0.1) == b"\x01"

    def test_stop_closes_the_stream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audio_module.sd, "InputStream", _FakeInputStream)
        capture = AudioCapture()
        capture.start(device=None)
        stream = _FakeInputStream.instances[0]

        capture.stop()

        assert stream.closed is True


class TestAudioPlayback:
    def test_open_starts_the_stream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audio_module.sd, "OutputStream", _FakeOutputStream)
        playback = AudioPlayback()

        playback.open(samplerate=24000, channels=1, device=None)

        assert playback._stream.started is True  # type: ignore[union-attr]

    def test_write_forwards_to_the_stream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audio_module.sd, "OutputStream", _FakeOutputStream)
        playback = AudioPlayback()
        playback.open(samplerate=24000, channels=1, device=None)

        playback.write(b"\x00\x01")

        written = playback._stream.written  # type: ignore[union-attr]
        assert len(written) == 1
        np.testing.assert_array_equal(written[0], np.frombuffer(b"\x00\x01", dtype="int16"))

    def test_abort_is_callable_without_a_prior_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audio_module.sd, "OutputStream", _FakeOutputStream)
        playback = AudioPlayback()
        playback.open(samplerate=24000, channels=1, device=None)

        playback.abort()

        assert playback._stream.aborted is True  # type: ignore[union-attr]

    def test_abort_before_open_is_a_no_op(self) -> None:
        playback = AudioPlayback()

        playback.abort()  # must not raise
