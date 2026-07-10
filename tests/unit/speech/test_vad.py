"""Tests for VadEndpointer (docs/08 §3) — pure state machine, no hardware.

`webrtcvad.Vad.is_speech` is monkeypatched to a scripted sequence so these tests never touch
real audio content; frame *bytes* are irrelevant once `is_speech` is faked, only their count/
timing matters.
"""

from __future__ import annotations

import pytest

from nova.core.config import VadSettings
from nova.speech.vad import FRAME_MS, VadEndpointer, VadEvent

_DUMMY_FRAME = b"\x00" * 960  # 480 samples * 2 bytes — real shape, content irrelevant (faked)


def _endpointer(**overrides: object) -> VadEndpointer:
    settings = VadSettings(**overrides)  # type: ignore[arg-type]
    return VadEndpointer(settings)


def _feed(
    endpointer: VadEndpointer, monkeypatch: pytest.MonkeyPatch, voiced_sequence: list[bool]
) -> list[VadEvent]:
    results = []
    it = iter(voiced_sequence)

    def fake_is_speech(_frame: bytes, _rate: int) -> bool:
        return next(it)

    monkeypatch.setattr(endpointer._vad, "is_speech", fake_is_speech)
    for _ in voiced_sequence:
        results.append(endpointer.process_frame(_DUMMY_FRAME))
    return results


def test_continues_while_ring_buffer_not_yet_full(monkeypatch: pytest.MonkeyPatch) -> None:
    endpointer = _endpointer()

    events = _feed(endpointer, monkeypatch, [True] * 24)

    assert all(event is VadEvent.CONTINUE for event in events)


def test_speech_started_when_ring_buffer_crosses_60_percent_voiced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpointer = _endpointer()
    # 25 frames, 15 voiced (60%) -> crosses the threshold on the 25th frame.
    sequence = [True] * 15 + [False] * 10

    events = _feed(endpointer, monkeypatch, sequence)

    assert events[-1] is VadEvent.SPEECH_STARTED
    assert all(event is VadEvent.CONTINUE for event in events[:-1])


def test_speech_not_started_below_60_percent_voiced(monkeypatch: pytest.MonkeyPatch) -> None:
    endpointer = _endpointer()
    sequence = [True] * 14 + [False] * 11  # 56% voiced — below threshold

    events = _feed(endpointer, monkeypatch, sequence)

    assert all(event is VadEvent.CONTINUE for event in events)


def test_speech_ended_after_silence_ms_of_consecutive_unvoiced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpointer = _endpointer(silence_ms=90)  # 3 frames @ 30ms
    start_sequence = [True] * 25  # trigger SPEECH_STARTED
    silence_sequence = [False, False, False]

    _feed(endpointer, monkeypatch, start_sequence)
    events = _feed(endpointer, monkeypatch, silence_sequence)

    assert events == [VadEvent.CONTINUE, VadEvent.CONTINUE, VadEvent.SPEECH_ENDED]


def test_voiced_frame_resets_the_unvoiced_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    endpointer = _endpointer(silence_ms=90)
    _feed(endpointer, monkeypatch, [True] * 25)

    # two unvoiced frames, then a voiced one resets the counter, then two more unvoiced —
    # never reaches 3 consecutive, so speech never ends within this window.
    events = _feed(endpointer, monkeypatch, [False, False, True, False, False])

    assert VadEvent.SPEECH_ENDED not in events


def test_frame_ms_matches_30ms_at_16khz() -> None:
    assert FRAME_MS == 30
