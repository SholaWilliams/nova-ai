"""ClapDetector: pure DSP state machine for the clap-to-wake trigger (docs/08 §7a).

A clap is a broadband transient: RMS jumps far above the ambient noise floor in a single
frame and decays back down within ~150ms, unlike speech which sustains. Two such transients
150-600ms apart count as a double clap and fire WAKE_DETECTED. No model, no ML, no new
dependency — just an exponential-moving-average floor plus a rise/decay check on the same
30ms/16kHz frames AudioCapture already produces (docs/08 §2). Requiring a *double* clap
(rather than one) is what keeps a chair scrape or a dropped book from firing wake — a single
transient doesn't repeat on rhythm.
"""

from __future__ import annotations

import array
from enum import Enum, auto

from nova.speech.vad import FRAME_MS

_FLOOR_ALPHA = 0.95  # EMA weight retained per non-transient frame
_MIN_THRESHOLD = 0.02  # floor*sensitivity floor -- a near-silent floor can't 0 the threshold
_DECAY_RATIO = 1.5  # frame must fall back under floor*this to confirm a transient, not speech
_CONFIRM_MS = 150  # time budget for the decay check after a transient's rising edge
_MIN_GAP_MS = 150  # minimum spacing between the two claps of a double clap
_MAX_GAP_MS = 600  # maximum spacing between the two claps of a double clap
_COOLDOWN_MS = 2000  # ignore new transients this long after a wake fires -- avoids self-retrigger


def _rms(frame: bytes) -> float:
    """0..1 loudness estimate -- same shape as `SpeechService._rms_level`, kept local so this
    module stays a dependency-free pure state machine like `vad.py`."""
    samples = array.array("h")
    samples.frombytes(frame)
    if not samples:
        return 0.0
    mean_square = sum(s * s for s in samples) / len(samples)
    return min(1.0, (mean_square**0.5) / 32768.0)


class WakeEvent(Enum):
    """Outcome of feeding one frame to a `ClapDetector`."""

    CONTINUE = auto()
    WAKE_DETECTED = auto()


class ClapDetector:
    """One long-lived instance per wake-listening session -- fresh per `WakeWorker` start."""

    def __init__(self, sensitivity: float = 3.0) -> None:
        self._sensitivity = sensitivity
        self._floor = 0.0
        self._above_threshold = False  # previous frame's state, for rising-edge detection
        self._pending_onset_ms: float | None = None  # ms since onset, awaiting decay confirm
        self._first_clap_ms: float | None = None  # ms since the most recent confirmed clap
        self._cooldown_ms_left = 0.0

    def process_frame(self, frame: bytes) -> WakeEvent:
        """Feed one `FRAME_MS` frame. Pure function of the frame plus internal state."""
        rms = _rms(frame)

        if self._cooldown_ms_left > 0:
            self._cooldown_ms_left -= FRAME_MS
            self._floor = _FLOOR_ALPHA * self._floor + (1 - _FLOOR_ALPHA) * rms
            return WakeEvent.CONTINUE

        if self._pending_onset_ms is not None:
            return self._resolve_pending(rms)

        threshold = max(self._floor * self._sensitivity, _MIN_THRESHOLD)
        rising = rms > threshold and not self._above_threshold
        self._above_threshold = rms > threshold
        if rising:
            self._pending_onset_ms = 0.0
        else:
            self._floor = _FLOOR_ALPHA * self._floor + (1 - _FLOOR_ALPHA) * rms

        self._expire_stale_first_clap()
        return WakeEvent.CONTINUE

    def _resolve_pending(self, rms: float) -> WakeEvent:
        assert self._pending_onset_ms is not None
        self._pending_onset_ms += FRAME_MS
        if rms <= self._floor * _DECAY_RATIO:
            self._pending_onset_ms = None
            self._above_threshold = False
            return self._register_clap()
        if self._pending_onset_ms >= _CONFIRM_MS:
            # never decayed back down -- a sustained loud sound (e.g. speech), not a clap
            self._pending_onset_ms = None
        return WakeEvent.CONTINUE

    def _register_clap(self) -> WakeEvent:
        if self._first_clap_ms is None:
            self._first_clap_ms = 0.0
            return WakeEvent.CONTINUE
        gap = self._first_clap_ms
        if _MIN_GAP_MS <= gap <= _MAX_GAP_MS:
            self._first_clap_ms = None
            self._cooldown_ms_left = _COOLDOWN_MS
            return WakeEvent.WAKE_DETECTED
        # too fast or too slow to pair with the pending clap -- start a fresh pair from this one
        self._first_clap_ms = 0.0
        return WakeEvent.CONTINUE

    def _expire_stale_first_clap(self) -> None:
        if self._first_clap_ms is not None:
            self._first_clap_ms += FRAME_MS
            if self._first_clap_ms > _MAX_GAP_MS:
                self._first_clap_ms = None
