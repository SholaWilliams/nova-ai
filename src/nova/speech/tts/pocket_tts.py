"""PocketTTSEngine: Kyutai Labs' local CPU neural voice (docs/04 TD-6, revised M4).

Three findings from hands-on testing against the real installed package, worth recording
here rather than trusting the upstream README's numbers blindly:

1. `TTSModel.load_model()` took 30-100s in this environment even with cached weights —
   nothing like a sub-second cost. `SpeechService.warm_up_tts()` calls `warm_up()` once at
   app startup so this lands before any request naturally reaches SPEAKING, not on a user's
   first spoken reply.
2. `quantize=True` (dynamic int8 quantization of attention/FFN) is used unconditionally —
   the project's own docs claim ~48% less runtime memory with "no measurable impact on
   speech quality," a direct, free win against this app's RAM ceiling (NFR-4).
3. Voice selection uses pocket-tts's built-in, non-gated voice catalog (plain names like
   `"cosette"`, `"alba"`, ...) via `get_state_for_audio_prompt()` — NOT an `hf://` voice-
   cloning URL: those require accepting gated terms on Hugging Face and being logged in
   locally (confirmed by a real failed call during testing), and voice cloning is
   speculative surface nobody asked for anyway (v1.0 ships fixed catalog voices only).
"""

from __future__ import annotations

from collections.abc import Callable

import torch
from pocket_tts import TTSModel

from nova.core.errors import SpeechError
from nova.speech.audio import AudioPlayback
from nova.speech.tts.base import TTSEngine

_CANT_SPEAK_TEXT = "I can't speak right now, but here's my answer."


def _tensor_to_pcm16(chunk: torch.Tensor) -> bytes:
    """1D float32 tensor in [-1, 1] (docs/08 §4: "decode -> playback") -> 16-bit PCM bytes."""
    clamped = chunk.clamp(-1.0, 1.0)
    ints = (clamped * 32767.0).to(dtype=torch.int16)
    return ints.numpy().tobytes()


class PocketTTSEngine(TTSEngine):
    """Primary TTS engine. Lazily (or via `warm_up()`) loads one shared `TTSModel` instance —
    generation is documented as "NOT thread-safe" across concurrent calls, which is fine here
    since only one `SpeechOut` thread ever calls `speak()` (one request in flight at a time,
    same rule the agent loop follows)."""

    def __init__(self, audio_playback_factory: Callable[[], AudioPlayback] = AudioPlayback) -> None:
        self._audio_playback_factory = audio_playback_factory
        self._model: TTSModel | None = None
        self._voice_states: dict[str, dict[str, object]] = {}
        self._playback: AudioPlayback | None = None

    def warm_up(self, voice: str) -> None:
        """Best-effort — failures surface identically on the next real `speak()` call."""
        try:
            self._get_voice_state(self._load_model(), voice)
        except Exception as exc:
            raise SpeechError(f"pocket-tts warm-up failed: {exc}") from exc

    def speak(
        self, text: str, voice: str, device: int | None, should_stop: Callable[[], bool]
    ) -> None:
        try:
            model = self._load_model()
            voice_state = self._get_voice_state(model, voice)
        except Exception as exc:
            raise SpeechError(
                f"pocket-tts setup failed: {exc}", friendly_message=_CANT_SPEAK_TEXT
            ) from exc

        playback = self._audio_playback_factory()
        self._playback = playback
        try:
            playback.open(model.sample_rate, 1, device)
            for chunk in model.generate_audio_stream(voice_state, text):
                if should_stop():
                    break
                playback.write(_tensor_to_pcm16(chunk))
        except Exception as exc:
            raise SpeechError(
                f"pocket-tts generation failed: {exc}", friendly_message=_CANT_SPEAK_TEXT
            ) from exc
        finally:
            playback.close()
            self._playback = None

    def abort(self) -> None:
        if self._playback is not None:
            self._playback.abort()

    def _load_model(self) -> TTSModel:
        if self._model is None:
            self._model = TTSModel.load_model(quantize=True)
        return self._model

    def _get_voice_state(self, model: TTSModel, voice: str) -> dict[str, object]:
        state = self._voice_states.get(voice)
        if state is None:
            # `copy_state=True` (generate_audio_stream's default) preserves this cached
            # state across calls — never pass `copy_state=False` here or reuse breaks.
            state = model.get_state_for_audio_prompt(voice)
            self._voice_states[voice] = state
        return state
