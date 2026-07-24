"""Tests for Pyttsx3Engine (docs/08 §4) — `pyttsx3` fully mocked at the module boundary."""

from __future__ import annotations

import pytest

from nova.core.errors import SpeechError
from nova.speech.tts import pyttsx3_engine as pyttsx3_engine_module
from nova.speech.tts.pyttsx3_engine import Pyttsx3Engine


class _FakeSapiEngine:
    def __init__(self, busy_iterations: int) -> None:
        self._remaining = busy_iterations
        self.said: str | None = None
        self.stopped = False
        self.loop_started = False
        self.loop_ended = False
        self.iterate_calls = 0

    def say(self, text: str) -> None:
        self.said = text

    def startLoop(self, refresh: bool) -> None:  # noqa: N802 - mirrors pyttsx3's API
        assert refresh is False
        self.loop_started = True

    def isBusy(self) -> bool:  # noqa: N802 - mirrors pyttsx3's API
        return self._remaining > 0

    def iterate(self) -> None:
        self.iterate_calls += 1
        self._remaining -= 1

    def endLoop(self) -> None:  # noqa: N802 - mirrors pyttsx3's API
        self.loop_ended = True

    def stop(self) -> None:
        self.stopped = True
        self._remaining = 0


def test_speaks_text_and_completes_the_external_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_engine = _FakeSapiEngine(busy_iterations=3)
    monkeypatch.setattr(pyttsx3_engine_module.pyttsx3, "init", lambda: fake_engine)
    engine = Pyttsx3Engine()

    engine.speak("hello there", voice="ignored", device=None, should_stop=lambda: False)

    assert fake_engine.said == "hello there"
    assert fake_engine.loop_started is True
    assert fake_engine.loop_ended is True
    assert fake_engine.iterate_calls == 3
    assert fake_engine.stopped is False


def test_on_start_fires_once_the_speech_loop_has_begun(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_engine = _FakeSapiEngine(busy_iterations=1)
    monkeypatch.setattr(pyttsx3_engine_module.pyttsx3, "init", lambda: fake_engine)
    engine = Pyttsx3Engine()
    calls: list[bool] = []

    engine.speak(
        "hello",
        voice="ignored",
        device=None,
        should_stop=lambda: False,
        on_start=lambda: calls.append(fake_engine.loop_started),
    )

    assert calls == [True]


def test_on_start_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_engine = _FakeSapiEngine(busy_iterations=0)
    monkeypatch.setattr(pyttsx3_engine_module.pyttsx3, "init", lambda: fake_engine)
    engine = Pyttsx3Engine()

    engine.speak("hello", voice="ignored", device=None, should_stop=lambda: False)  # no raise


def test_should_stop_interrupts_the_loop_and_calls_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_engine = _FakeSapiEngine(busy_iterations=100)
    monkeypatch.setattr(pyttsx3_engine_module.pyttsx3, "init", lambda: fake_engine)
    engine = Pyttsx3Engine()
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    engine.speak("long text", voice="ignored", device=None, should_stop=should_stop)

    assert fake_engine.stopped is True
    assert fake_engine.loop_ended is True
    assert fake_engine.iterate_calls == 2


def test_init_failure_raises_speech_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_init() -> None:
        raise RuntimeError("no SAPI5 driver")

    monkeypatch.setattr(pyttsx3_engine_module.pyttsx3, "init", raise_init)
    engine = Pyttsx3Engine()

    with pytest.raises(SpeechError):
        engine.speak("hi", voice="ignored", device=None, should_stop=lambda: False)


def test_abort_is_a_no_op_default(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = Pyttsx3Engine()

    engine.abort()  # must not raise — default no-op (see TTSEngine.abort docstring)
