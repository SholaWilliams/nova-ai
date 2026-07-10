"""Tests for GroqSTTEngine (docs/08 §2, §6) — golden-fixture round-trips + retry/error mapping.

Fixtures are synthetic, hand-built from the real `groq.types.audio.Transcription` shape (a
single `text: str` field) — no live key was available at authoring time, same provenance note
as `test_groq.py`'s chat-completion fixtures.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest
from groq import _exceptions as groq_errors
from groq.types.audio.transcription import Transcription

from nova.core.errors import SpeechError
from nova.speech.stt.groq_whisper import GroqSTTEngine, _pcm_to_wav

_FIXTURES = Path(__file__).parents[3] / "fixtures" / "speech" / "groq_whisper"


def _load(name: str) -> Transcription:
    data = json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return Transcription.model_validate(data)


@pytest.fixture
def engine() -> GroqSTTEngine:
    return GroqSTTEngine(api_key="test-key")


def test_wav_packing_round_trips_pcm_at_the_given_rate() -> None:
    pcm = b"\x01\x00" * 480  # one 30ms frame of constant int16 samples

    wav_bytes = _pcm_to_wav(pcm, sample_rate=16000)

    import io

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() == 480
        assert wav_file.readframes(480) == pcm


def test_successful_transcription_has_no_confidence(
    engine: GroqSTTEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        engine._client.audio.transcriptions, "create", lambda **_kw: _load("simple")
    )

    result = engine.transcribe("req_1", b"\x00" * 960, sample_rate=16000)

    assert result.request_id == "req_1"
    assert result.text == "What's the weather in Lagos?"
    assert result.confidence is None


def test_empty_transcription_returns_empty_text_not_an_error(
    engine: GroqSTTEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine._client.audio.transcriptions, "create", lambda **_kw: _load("empty"))

    result = engine.transcribe("req_2", b"\x00" * 960, sample_rate=16000)

    assert result.text == ""


def test_auth_error_raises_immediately_without_retry(
    engine: GroqSTTEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def raise_auth(**_kw: object) -> None:
        nonlocal calls
        calls += 1
        raise groq_errors.AuthenticationError("bad key", response=_fake_response(401), body=None)

    monkeypatch.setattr(engine._client.audio.transcriptions, "create", raise_auth)

    with pytest.raises(SpeechError):
        engine.transcribe("req_3", b"\x00" * 960, sample_rate=16000)
    assert calls == 1


def test_transient_error_retries_once_then_succeeds(
    engine: GroqSTTEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def flaky(**_kw: object) -> Transcription:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("network blip")
        return _load("simple")

    monkeypatch.setattr(engine._client.audio.transcriptions, "create", flaky)

    result = engine.transcribe("req_4", b"\x00" * 960, sample_rate=16000)

    assert calls == 2
    assert result.text == "What's the weather in Lagos?"


def test_transient_error_exhausts_retries_and_raises_speech_error(
    engine: GroqSTTEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def always_fails(**_kw: object) -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError("network gone")

    monkeypatch.setattr(engine._client.audio.transcriptions, "create", always_fails)

    with pytest.raises(SpeechError):
        engine.transcribe("req_5", b"\x00" * 960, sample_rate=16000)
    assert calls == 2


def _fake_response(status_code: int) -> object:
    import httpx

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions")
    return httpx.Response(status_code=status_code, request=request)
