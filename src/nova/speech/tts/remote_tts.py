"""RemoteTTSEngine: HTTP client for takada-tts-service (docs/04 TD-6, M9 revision).

Talks to a locally-run FastAPI microservice (`POST /v1/synthesize`) that wraps pocket-tts
and streams back a progressively-framed WAV response: a 44-byte RIFF/WAVE header (mono,
16-bit PCM) written up front, followed by raw PCM16LE frames as they're generated — an
unbounded/unseekable stream (the service patches `wave.Wave_write._patchheader` to a no-op
and sets an oversized `nframes`, the same trick pocket-tts's own StreamingWAVWriter uses).
Because of that, the client can't use stdlib `wave` to parse it (that expects a seekable,
correctly-sized file) — it reads the fixed 44-byte header directly to pull the sample rate
(bytes 24:28, little-endian uint32) and treats everything after as raw PCM16 to hand
straight to `AudioPlayback.write()`. No dtype/tensor conversion needed on this side, unlike
the in-process pocket-tts engine this replaces — the service already emits PCM16.
"""

from __future__ import annotations

import struct
from collections.abc import Callable

import httpx

from nova.core.errors import SpeechError
from nova.speech.audio import AudioPlayback
from nova.speech.tts.base import TTSEngine

_CANT_SPEAK_TEXT = "I can't speak right now, but here's my answer."
_WAV_HEADER_SIZE = 44
_SAMPLE_RATE_OFFSET = 24


class RemoteTTSEngine(TTSEngine):
    """Primary TTS engine (M9): calls takada-tts-service instead of running pocket-tts
    in-process. Only one `SpeechOut` thread ever calls `speak()` (same one-request-in-
    flight rule the previous in-process engine followed), so no internal locking here."""

    def __init__(
        self,
        base_url: str,
        tenant_id: str,
        provider: str = "pocket-tts",
        audio_playback_factory: Callable[[], AudioPlayback] = AudioPlayback,
        timeout_s: float = 30.0,
    ) -> None:
        self._tenant_id = tenant_id
        self._provider = provider
        self._audio_playback_factory = audio_playback_factory
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s)
        self._playback: AudioPlayback | None = None

    def warm_up(self, voice: str) -> None:
        """Best-effort — failures surface identically on the next real `speak()` call.
        Nothing to preload client-side anymore; the service owns its own model warm-up."""
        del voice
        try:
            response = self._client.get("/health")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpeechError(f"takada-tts-service health check failed: {exc}") from exc

    def speak(
        self, text: str, voice: str, device: int | None, should_stop: Callable[[], bool]
    ) -> None:
        payload = {
            "tenant_id": self._tenant_id,
            "provider": self._provider,
            "text": text,
            "voice": voice,
            "language": "en-US",
        }
        playback = self._audio_playback_factory()
        self._playback = playback
        try:
            with self._client.stream("POST", "/v1/synthesize", json=payload) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise SpeechError(
                        f"takada-tts-service returned {exc.response.status_code}",
                        friendly_message=_CANT_SPEAK_TEXT,
                    ) from exc

                header = bytearray()
                opened = False
                for chunk in response.iter_bytes():
                    if should_stop():
                        break
                    if not opened:
                        header += chunk
                        if len(header) < _WAV_HEADER_SIZE:
                            continue
                        sample_rate = struct.unpack_from("<I", header, _SAMPLE_RATE_OFFSET)[0]
                        playback.open(sample_rate, 1, device)
                        opened = True
                        pcm = bytes(header[_WAV_HEADER_SIZE:])
                        if pcm:
                            playback.write(pcm)
                        continue
                    playback.write(chunk)
        except httpx.HTTPError as exc:
            raise SpeechError(
                f"takada-tts-service request failed: {exc}", friendly_message=_CANT_SPEAK_TEXT
            ) from exc
        finally:
            playback.close()
            self._playback = None

    def abort(self) -> None:
        if self._playback is not None:
            self._playback.abort()
