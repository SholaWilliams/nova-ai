"""Tests for PocketTTSEngine (docs/04 TD-6 revision) — `pocket_tts.TTSModel` and
`AudioPlayback` both fully faked; never triggers a real model load/download.

`torch` is an actual installed dependency by this point (pocket-tts pulls it in), so fake
audio chunks are real small tensors rather than a further mock — no need to fake the tensor
type itself, only `TTSModel`.
"""

from __future__ import annotations

import pytest
import torch

from nova.core.errors import SpeechError
from nova.speech.tts import pocket_tts as pocket_tts_module
from nova.speech.tts.pocket_tts import PocketTTSEngine, _tensor_to_pcm16


class _FakePlayback:
    instances: list[_FakePlayback] = []

    def __init__(self) -> None:
        self.opened: tuple[int, int, int | None] | None = None
        self.written: list[bytes] = []
        self.aborted = False
        self.closed = False
        _FakePlayback.instances.append(self)

    def open(self, samplerate: int, channels: int, device: int | None) -> None:
        self.opened = (samplerate, channels, device)

    def write(self, pcm: bytes) -> None:
        self.written.append(pcm)

    def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
        self.closed = True


class _FakeTTSModel:
    load_calls = 0

    def __init__(self, sample_rate: int = 24000, chunks: int = 3) -> None:
        self.sample_rate = sample_rate
        self._chunks = chunks
        self.voice_states_built: list[str] = []

    @classmethod
    def load_model(cls, quantize: bool = False) -> _FakeTTSModel:
        assert quantize is True  # PocketTTSEngine must request quantization (RAM budget)
        cls.load_calls += 1
        return cls()

    def get_state_for_audio_prompt(self, voice: str) -> dict[str, object]:
        self.voice_states_built.append(voice)
        return {"voice": voice}

    def generate_audio_stream(self, voice_state: dict[str, object], text: str):
        del voice_state, text
        for _ in range(self._chunks):
            yield torch.zeros(1920)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakePlayback.instances.clear()
    _FakeTTSModel.load_calls = 0
    monkeypatch.setattr(pocket_tts_module, "TTSModel", _FakeTTSModel)


def test_tensor_to_pcm16_clamps_and_scales() -> None:
    chunk = torch.tensor([-2.0, -1.0, 0.0, 1.0, 2.0])

    pcm = _tensor_to_pcm16(chunk)

    ints = torch.frombuffer(bytearray(pcm), dtype=torch.int16)
    assert ints.tolist() == [-32767, -32767, 0, 32767, 32767]


def test_speak_loads_model_once_and_writes_every_chunk() -> None:
    engine = PocketTTSEngine(audio_playback_factory=_FakePlayback)

    engine.speak("hello", voice="cosette", device=None, should_stop=lambda: False)
    engine.speak("again", voice="cosette", device=None, should_stop=lambda: False)

    assert _FakeTTSModel.load_calls == 1  # lazy-loaded once, reused across calls
    assert len(_FakePlayback.instances) == 2
    for playback in _FakePlayback.instances:
        assert playback.opened == (24000, 1, None)
        assert len(playback.written) == 3
        assert playback.closed is True


def test_voice_state_is_cached_per_voice_name() -> None:
    engine = PocketTTSEngine(audio_playback_factory=_FakePlayback)

    engine.speak("a", voice="cosette", device=None, should_stop=lambda: False)
    engine.speak("b", voice="cosette", device=None, should_stop=lambda: False)
    engine.speak("c", voice="alba", device=None, should_stop=lambda: False)

    assert engine._model.voice_states_built == ["cosette", "alba"]  # type: ignore[union-attr]


def test_should_stop_halts_chunk_writes_partway_through() -> None:
    engine = PocketTTSEngine(audio_playback_factory=_FakePlayback)
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    engine.speak("hello", voice="cosette", device=None, should_stop=should_stop)

    assert len(_FakePlayback.instances[0].written) == 1


def test_warm_up_loads_model_and_voice_state_ahead_of_time() -> None:
    engine = PocketTTSEngine(audio_playback_factory=_FakePlayback)

    engine.warm_up("cosette")

    assert _FakeTTSModel.load_calls == 1
    assert "cosette" in engine._voice_states


def test_generation_failure_raises_speech_error_and_still_closes_playback() -> None:
    class _RaisingModel(_FakeTTSModel):
        def generate_audio_stream(self, voice_state, text):  # type: ignore[override]
            del voice_state, text
            raise RuntimeError("inference exploded")
            yield  # pragma: no cover - unreachable, keeps this a generator

    engine = PocketTTSEngine(audio_playback_factory=_FakePlayback)
    engine._model = _RaisingModel()

    with pytest.raises(SpeechError):
        engine.speak("hello", voice="cosette", device=None, should_stop=lambda: False)

    assert _FakePlayback.instances[0].closed is True


def test_abort_forwards_to_the_active_playback_instance() -> None:
    """`stop_speaking()`'s hard-stop half (see TTSEngine.abort's docstring): calling
    `abort()` on the engine *while* `speak()` is still running must reach the same
    `AudioPlayback` instance currently in use — this is the whole reason `abort()`
    exists on the engine rather than relying on `should_stop` polling alone."""
    engine = PocketTTSEngine(audio_playback_factory=_FakePlayback)
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            engine.abort()  # simulates SpeechService.stop_speaking() firing mid-flight
        return False

    engine.speak("hello", voice="cosette", device=None, should_stop=should_stop)

    assert _FakePlayback.instances[0].aborted is True


def test_abort_after_speak_returns_is_a_no_op() -> None:
    engine = PocketTTSEngine(audio_playback_factory=_FakePlayback)
    engine.speak("hello", voice="cosette", device=None, should_stop=lambda: False)

    engine.abort()  # _playback already cleared to None — must not raise

    assert _FakePlayback.instances[0].aborted is False
