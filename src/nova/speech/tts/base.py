"""TTSEngine ABC (docs/08 §1, A-4).

Deliberately one method that owns *both* synthesis and playback, rather than "synthesize,
return chunks, something else plays them." pocket-tts and pyttsx3 have fundamentally
different playback ownership models (pocket-tts hands back a PCM tensor we play ourselves;
pyttsx3 drives SAPI5's own COM-based audio output and never gives us PCM at all) — forcing
them through one "yield chunks" shape would mean inventing a fake chunk stream for pyttsx3
that corresponds to nothing real. Still a thin, two-method-total ABC (A-4's "everything
pluggable is behind an interface," nothing more).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class TTSEngine(ABC):
    """Synthesizes `text` and plays it. Raises only `core.errors.SpeechError` on failure."""

    @abstractmethod
    def speak(
        self,
        text: str,
        voice: str,
        device: int | None,
        should_stop: Callable[[], bool],
        on_start: Callable[[], None] | None = None,
    ) -> None:
        """`should_stop` is polled between chunks/iterations so playback can be interrupted
        (FR-13, cooperative half) — see `abort()` below for the hard-stop half.

        `on_start`, if given, fires once audio has actually begun playing (not merely
        requested) — `SpeechService` uses it to gate the chat bubble's text reveal on real
        audio (docs/05 §9: "text reveals with the TTS start"), not on the reply merely
        arriving from the agent.
        """
        raise NotImplementedError

    def abort(self) -> None:
        """Hard-stop whatever playback is currently in flight, if any (FR-13, <100ms bound).

        Safe to call from a different thread than the one inside `speak()` — the whole
        reason it exists as a separate method rather than relying on `should_stop` alone.
        Default no-op: engines that don't own a `sounddevice` stream themselves (pyttsx3
        drives SAPI5's own COM-based output) have nothing to abort here; `should_stop`
        polling is their only interruption path, best-effort rather than bounded.
        """
        return None
