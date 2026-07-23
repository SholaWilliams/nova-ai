"""Tests for AudioCapture / AudioPlayback (docs/08 §2, §5) — `sounddevice` fully mocked at
the module boundary (`nova.speech.audio.sd`); never touches real PortAudio devices.
"""

from __future__ import annotations

import queue

import numpy as np
import pytest

from nova.core.errors import SpeechError
from nova.speech import audio as audio_module
from nova.speech.audio import AudioCapture, AudioPlayback, list_output_devices


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


_FAKE_HOSTAPIS = [{"name": "MME"}, {"name": "Windows WDM-KS"}]
_FAKE_DEVICES = [
    {"name": "Mic (MME)", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 0},
    {"name": "Speaker (MME)", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
    {"name": "Headset (WDM-KS)", "max_input_channels": 1, "max_output_channels": 1, "hostapi": 1},
    {"name": "Device 3 (MME)", "max_input_channels": 1, "max_output_channels": 2, "hostapi": 0},
]


@pytest.fixture(autouse=True)
def _clear_fake_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeInputStream.instances.clear()
    # deterministic device list — real `sd.query_devices()` would make `_resolve_device()`
    # (called by every `start()`/`open()`) depend on whatever hardware runs the test
    monkeypatch.setattr(audio_module.sd, "query_hostapis", lambda: _FAKE_HOSTAPIS)
    monkeypatch.setattr(audio_module.sd, "query_devices", lambda: _FAKE_DEVICES)


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

    def test_start_falls_back_to_default_for_a_stale_wdm_ks_device(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A device index persisted before WDM-KS exclusion existed (or one that got
        unplugged) must degrade to the system default, not crash stream-open."""
        monkeypatch.setattr(audio_module.sd, "InputStream", _FakeInputStream)
        capture = AudioCapture()

        capture.start(device=2)  # index 2 in _FAKE_DEVICES is the WDM-KS headset

        stream = _FakeInputStream.instances[0]
        assert stream.kwargs["device"] is None

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

    def test_open_falls_back_to_default_for_a_stale_wdm_ks_device(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reproduces the real bug: `output_device` persisted in settings.json pointed at a
        WDM-KS entry, and PortAudio's blocking API can't open one — `PaErrorCode -9999`
        'Blocking API not supported yet'. Must degrade to the default device, not crash."""
        monkeypatch.setattr(audio_module.sd, "OutputStream", _FakeOutputStream)
        playback = AudioPlayback()

        playback.open(samplerate=24000, channels=1, device=2)  # index 2 = WDM-KS headset

        assert playback._stream.kwargs["device"] is None  # type: ignore[union-attr]

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


def test_list_output_devices_excludes_wdm_ks(monkeypatch: pytest.MonkeyPatch) -> None:
    """WDM-KS devices (e.g. Bluetooth headsets) can't open a blocking OutputStream — see
    audio.py's `_usable_devices` comment — so Settings must never offer them."""
    monkeypatch.setattr(
        audio_module.sd,
        "query_hostapis",
        lambda: [{"name": "MME"}, {"name": "Windows WDM-KS"}],
    )
    monkeypatch.setattr(
        audio_module.sd,
        "query_devices",
        lambda: [
            {"name": "Speakers (MME)", "max_output_channels": 2, "hostapi": 0},
            {"name": "Headset (WDM-KS)", "max_output_channels": 1, "hostapi": 1},
        ],
    )

    devices = list_output_devices()

    assert [d.name for d in devices] == ["Speakers (MME)"]
