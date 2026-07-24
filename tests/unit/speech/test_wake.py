"""Tests for ClapDetector (docs/08 §7a) -- pure state machine, no hardware.

`_rms` is monkeypatched to a scripted sequence, same pattern as `test_vad.py` faking
`is_speech`: frame *bytes* are irrelevant once `_rms` is faked, only the returned loudness
values and their timing matter. All gap/window constants below are frame counts derived from
`FRAME_MS = 30` matching the module's own ms constants (150/600/2000ms).
"""

from __future__ import annotations

import pytest

from nova.speech import wake
from nova.speech.wake import ClapDetector, WakeEvent

_DUMMY_FRAME = b"\x00" * 960  # 480 samples * 2 bytes -- real shape, content irrelevant (faked)
_LOUD = 0.9
_QUIET = 0.0


def _feed(
    detector: ClapDetector, monkeypatch: pytest.MonkeyPatch, rms_sequence: list[float]
) -> list[WakeEvent]:
    results = []
    it = iter(rms_sequence)

    def fake_rms(_frame: bytes) -> float:
        return next(it)

    monkeypatch.setattr(wake, "_rms", fake_rms)
    for _ in rms_sequence:
        results.append(detector.process_frame(_DUMMY_FRAME))
    return results


def _clap() -> list[float]:
    """One clap: a loud onset frame, then a quiet frame the very next tick (instant decay)."""
    return [_LOUD, _QUIET]


def test_silence_never_triggers(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = ClapDetector()

    events = _feed(detector, monkeypatch, [_QUIET] * 50)

    assert all(event is WakeEvent.CONTINUE for event in events)


def test_single_clap_does_not_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = ClapDetector()

    events = _feed(detector, monkeypatch, _clap() + [_QUIET] * 30)

    assert WakeEvent.WAKE_DETECTED not in events


def test_double_clap_with_valid_gap_wakes(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = ClapDetector()
    # 10 quiet frames between claps = 300ms gap -- inside the 150-600ms window.
    sequence = _clap() + [_QUIET] * 10 + _clap()

    events = _feed(detector, monkeypatch, sequence)

    assert events[-1] is WakeEvent.WAKE_DETECTED
    assert events.count(WakeEvent.WAKE_DETECTED) == 1


def test_claps_too_close_together_do_not_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = ClapDetector()
    # 2 quiet frames between claps = 60ms gap -- below the 150ms minimum.
    sequence = _clap() + [_QUIET] * 2 + _clap()

    events = _feed(detector, monkeypatch, sequence)

    assert WakeEvent.WAKE_DETECTED not in events


def test_claps_too_far_apart_do_not_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = ClapDetector()
    # 25 quiet frames between claps = 750ms gap -- above the 600ms maximum.
    sequence = _clap() + [_QUIET] * 25 + _clap()

    events = _feed(detector, monkeypatch, sequence)

    assert WakeEvent.WAKE_DETECTED not in events


def test_sustained_loud_sound_is_not_a_clap(monkeypatch: pytest.MonkeyPatch) -> None:
    """A door slam decays; speech sustains -- 20 loud frames (600ms) never decays back down."""
    detector = ClapDetector()
    sequence = [_LOUD] * 20 + [_QUIET] * 30

    events = _feed(detector, monkeypatch, sequence)

    assert WakeEvent.WAKE_DETECTED not in events


def test_cooldown_suppresses_retrigger_immediately_after_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = ClapDetector()
    first_pair = _clap() + [_QUIET] * 10 + _clap()  # fires WAKE_DETECTED
    # Would also qualify as a valid double clap, but arrives mid-cooldown.
    second_pair = [_QUIET] * 5 + _clap() + [_QUIET] * 10 + _clap()

    events = _feed(detector, monkeypatch, first_pair + second_pair)

    assert events.count(WakeEvent.WAKE_DETECTED) == 1


def test_wake_fires_again_after_cooldown_elapses(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = ClapDetector()
    first_pair = _clap() + [_QUIET] * 10 + _clap()
    cooldown_wait = [_QUIET] * 70  # 2100ms of quiet -- past the 2000ms cooldown
    second_pair = _clap() + [_QUIET] * 10 + _clap()

    events = _feed(detector, monkeypatch, first_pair + cooldown_wait + second_pair)

    assert events.count(WakeEvent.WAKE_DETECTED) == 2


def test_sensitivity_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A high sensitivity multiplier demands a louder-than-floor transient to register at all."""
    detector = ClapDetector(sensitivity=100.0)
    # Settle an ambient floor around 0.02 first (never crosses its own threshold while settling),
    # then floor*100 towers well above the "clap" -- it never reads as a rising edge at all.
    ambient = [0.02] * 60
    sequence = ambient + _clap() + [_QUIET] * 10 + _clap()

    events = _feed(detector, monkeypatch, sequence)

    assert WakeEvent.WAKE_DETECTED not in events
