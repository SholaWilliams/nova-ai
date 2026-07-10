"""VadEndpointer: pure end-of-speech detection state machine (docs/08 §3).

`webrtcvad` is a pure *gate* — it never touches STT, it only decides when to stop recording
(docs/08 §3). Two independent triggers, each a plain function of frames + internal state:
speech-start (a 25-frame ring buffer crosses 60% voiced) and speech-end (>= `silence_ms` of
consecutive unvoiced frames once speech has started). No I/O in this module at all.
"""

from __future__ import annotations

from collections import deque
from enum import Enum, auto

import webrtcvad

from nova.core.config import VadSettings

FRAME_MS = 30  # VAD-required frame size at 16kHz: 480 samples (docs/08 §2)
_RING_SIZE = 25
_VOICED_RATIO_THRESHOLD = 0.6


class VadEvent(Enum):
    """Outcome of feeding one frame to a `VadEndpointer`."""

    CONTINUE = auto()
    SPEECH_STARTED = auto()
    SPEECH_ENDED = auto()


class VadEndpointer:
    """One utterance's worth of endpointing state — construct a fresh instance per `listen()`."""

    def __init__(self, settings: VadSettings, sample_rate: int = 16000) -> None:
        self._vad = webrtcvad.Vad(settings.aggressiveness)
        self._sample_rate = sample_rate
        self._silence_ms = settings.silence_ms
        self._ring: deque[bool] = deque(maxlen=_RING_SIZE)
        self._in_speech = False
        self._unvoiced_ms = 0

    def process_frame(self, frame: bytes) -> VadEvent:
        """Feed one `FRAME_MS` frame. Pure function of the frame plus internal state."""
        voiced = self._vad.is_speech(frame, self._sample_rate)

        if not self._in_speech:
            self._ring.append(voiced)
            if (
                len(self._ring) == _RING_SIZE
                and (sum(self._ring) / _RING_SIZE) >= _VOICED_RATIO_THRESHOLD
            ):
                self._in_speech = True
                self._unvoiced_ms = 0
                return VadEvent.SPEECH_STARTED
            return VadEvent.CONTINUE

        if voiced:
            self._unvoiced_ms = 0
            return VadEvent.CONTINUE

        self._unvoiced_ms += FRAME_MS
        if self._unvoiced_ms >= self._silence_ms:
            return VadEvent.SPEECH_ENDED
        return VadEvent.CONTINUE
