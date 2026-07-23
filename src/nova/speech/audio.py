"""AudioCapture / AudioPlayback: thin `sounddevice` (PortAudio) wrappers (docs/08 §2, §5).

The PortAudio callback thread does exactly one thing — push raw frame bytes onto a bounded
queue — so all VAD/business logic runs on the `SpeechIn` worker thread pulling from that
queue, never on PortAudio's own real-time thread (the standard safe pattern for audio +
Python). `AudioPlayback.abort()` is the mechanism that actually delivers the <100ms
interruption bound (FR-13): PortAudio's `Pa_AbortStream` discards buffered-but-unplayed audio
immediately rather than draining it, and is documented safe to call from a different thread
than the one doing `write()`.
"""

from __future__ import annotations

import contextlib
import logging
import queue

import numpy as np
import sounddevice as sd

from nova.core.errors import SpeechError
from nova.core.models import AudioDeviceInfo

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # Whisper-native (docs/08 §2)
FRAME_SAMPLES = 480  # 30ms @ 16kHz, VAD-aligned
_QUEUE_MAXSIZE = 50  # ~1.5s of frames — bounds memory if a consumer stalls

_NO_MIC_TEXT = "I can't hear right now — you can type to me!"


# PortAudio's WDM-KS host API doesn't support the blocking read/write this app uses
# (raises PaErrorCode -9999 "Blocking API not supported yet" on stream open) — exclude it
# so Settings can never offer a device that's guaranteed to fail (e.g. Bluetooth headsets
# that Windows exposes only via WDM-KS alongside a working MME/WASAPI entry).
_WDM_KS_HOSTAPI_NAME = "Windows WDM-KS"


def _usable_devices(min_channels_key: str) -> list[AudioDeviceInfo]:
    hostapis = sd.query_hostapis()
    return [
        AudioDeviceInfo(index=index, name=device["name"])
        for index, device in enumerate(sd.query_devices())
        if device[min_channels_key] > 0
        and hostapis[device["hostapi"]]["name"] != _WDM_KS_HOSTAPI_NAME
    ]


def list_input_devices() -> list[AudioDeviceInfo]:
    return _usable_devices("max_input_channels")


def list_output_devices() -> list[AudioDeviceInfo]:
    return _usable_devices("max_output_channels")


def _resolve_device(device: int | None, min_channels_key: str) -> int | None:
    """Falls back to the system default (`None`) if `device` doesn't resolve to a currently
    usable entry — e.g. a device index persisted to `settings.json` before WDM-KS exclusion
    existed, or a device that's since been unplugged/renamed. Without this, a stale index
    crashes stream-open outright instead of degrading to the default device."""
    if device is None:
        return None
    if device in {d.index for d in _usable_devices(min_channels_key)}:
        return device
    logger.warning("audio device %d is no longer usable, falling back to system default", device)
    return None


class AudioCapture:
    """One `listen()` call's worth of microphone capture."""

    def __init__(self) -> None:
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._stream: sd.InputStream | None = None

    def start(self, device: int | None) -> None:
        device = _resolve_device(device, "max_input_channels")
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=FRAME_SAMPLES,
                device=device,
                callback=self._on_frame,
            )
            self._stream.start()
        except sd.PortAudioError as exc:
            raise SpeechError(str(exc), friendly_message=_NO_MIC_TEXT) from exc

    def _on_frame(self, indata: object, frames: int, time_info: object, status: object) -> None:
        del frames, time_info, status  # unused — see module docstring: callback does one thing
        # a stalled consumer drops frames rather than growing memory unboundedly
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(bytes(indata))  # type: ignore[arg-type]

    def read_frame(self, timeout: float) -> bytes | None:
        """Blocks up to `timeout` seconds; `None` lets the caller re-check its own exit
        conditions (cancel/end/hard-cap) even during silence."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class AudioPlayback:
    """One `speak()` call's worth of output playback."""

    def __init__(self) -> None:
        self._stream: sd.OutputStream | None = None

    def open(self, samplerate: int, channels: int, device: int | None) -> None:
        device = _resolve_device(device, "max_output_channels")
        try:
            self._stream = sd.OutputStream(
                samplerate=samplerate, channels=channels, dtype="int16", device=device
            )
            self._stream.start()
        except sd.PortAudioError as exc:
            raise SpeechError(
                str(exc), friendly_message="Speaker changed — check Settings"
            ) from exc

    def write(self, pcm: bytes) -> None:
        if self._stream is None:
            return
        try:
            # sd.OutputStream.write needs a numpy array matching its dtype ("int16") —
            # passing raw bytes makes numpy build a 0-d dtype='S<len>' array instead of
            # reinterpreting the buffer as samples, which raises a dtype mismatch.
            self._stream.write(np.frombuffer(pcm, dtype="int16"))
        except sd.PortAudioError as exc:
            raise SpeechError(
                str(exc), friendly_message="Speaker changed — check Settings"
            ) from exc

    def abort(self) -> None:
        """Safe to call from a different thread than the one doing `write()` (Pa_AbortStream);
        this is the real <100ms interruption mechanism (FR-13), not the polled `should_stop`
        flag `TTSEngine.speak()` implementations also check."""
        if self._stream is not None:
            self._stream.abort()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
