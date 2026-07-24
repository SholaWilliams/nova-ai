"""Pyttsx3Engine: SAPI5 offline fallback (docs/08 §4, TD-6).

Used whenever the primary engine (pocket-tts) fails to load or generate — always available,
zero network, zero model download. `voice` is accepted for `TTSEngine` compliance but not
applied: SAPI5's voice catalog has no relationship to pocket-tts's named voices, and this is
already the accepted degraded path (docs/08 §4: "robotic," "Voice: offline"/backup voice).

Uses pyttsx3's documented external-loop pattern (`startLoop(False)` + manual `iterate()`)
rather than the simpler `runAndWait()` so `should_stop` can interrupt mid-utterance —
`runAndWait()` blocks until the whole utterance finishes with no interruption point.
"""

from __future__ import annotations

from collections.abc import Callable

import pyttsx3

from nova.core.errors import SpeechError
from nova.speech.tts.base import TTSEngine

_CANT_SPEAK_TEXT = "I can't speak right now, but here's my answer."


class Pyttsx3Engine(TTSEngine):
    def speak(
        self,
        text: str,
        voice: str,
        device: int | None,
        should_stop: Callable[[], bool],
        on_start: Callable[[], None] | None = None,
    ) -> None:
        del voice, device  # not applicable to SAPI5 (see module docstring)
        try:
            engine = pyttsx3.init()
        except Exception as exc:
            raise SpeechError(
                f"pyttsx3 init failed: {exc}", friendly_message=_CANT_SPEAK_TEXT
            ) from exc

        try:
            engine.say(text)
            engine.startLoop(False)
            if on_start is not None:
                on_start()
            try:
                while engine.isBusy():
                    if should_stop():
                        engine.stop()
                        break
                    engine.iterate()
            finally:
                engine.endLoop()
        except Exception as exc:
            raise SpeechError(
                f"pyttsx3 speak failed: {exc}", friendly_message=_CANT_SPEAK_TEXT
            ) from exc
