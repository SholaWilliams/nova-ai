"""GroqSTTEngine: Groq-hosted Whisper (docs/08 §2, TD-5).

Named `groq_whisper.py` rather than `groq.py` to avoid two same-named files with different
responsibilities (chat completions in `providers/groq.py` vs. audio transcription here) —
naming clarity only, not a technical requirement. Shares the same `NOVA_GROQ_API_KEY` as
`GroqProvider` (TD-5: "one key covering two needs").
"""

from __future__ import annotations

import io
import wave

from groq import Groq
from groq import _exceptions as groq_errors

from nova.core.errors import SpeechError
from nova.core.models import Transcript
from nova.speech.stt.base import STTEngine

MODEL = "whisper-large-v3-turbo"  # ⚠️ verify-at-implementation (docs/08 §2, TD-5)
_TIMEOUT_S = 10
_MAX_ATTEMPTS = 2  # docs/08 §6: "1 retry; then abort"
_CANT_HEAR_TEXT = "My ears aren't working — is the internet on?"


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Pack raw 16-bit mono PCM into an in-memory WAV container (docs/08 §2 step 4)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


class GroqSTTEngine(STTEngine):
    """Whisper transcription via the `groq` SDK's audio-transcriptions endpoint."""

    def __init__(self, api_key: str, model: str = MODEL) -> None:
        self._client = Groq(api_key=api_key)
        self._model = model

    def transcribe(self, request_id: str, pcm: bytes, sample_rate: int) -> Transcript:
        wav_bytes = _pcm_to_wav(pcm, sample_rate)
        last_exc: Exception | None = None

        for _attempt in range(_MAX_ATTEMPTS):
            try:
                response = self._client.audio.transcriptions.create(
                    model=self._model,
                    file=(f"{request_id}.wav", wav_bytes),
                    timeout=_TIMEOUT_S,
                )
            except (groq_errors.AuthenticationError, groq_errors.PermissionDeniedError) as exc:
                # never retried — a bad key won't fix itself (mirrors GroqProvider).
                raise SpeechError(str(exc), friendly_message=_CANT_HEAR_TEXT) from exc
            except Exception as exc:  # transient: connection, 5xx, timeout — one retry
                last_exc = exc
                continue
            else:
                # Whisper's plain JSON response carries only `text` — no confidence score
                # (docs/11 §1: "None if engine doesn't report", honored literally).
                return Transcript(
                    request_id=request_id, text=response.text.strip(), confidence=None
                )

        raise SpeechError(
            f"groq STT failed after {_MAX_ATTEMPTS} attempts: {last_exc}",
            friendly_message=_CANT_HEAR_TEXT,
        ) from last_exc
