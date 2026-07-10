"""STTEngine ABC (docs/08 §1: "engines sit behind STTEngine/TTSEngine ABCs", A-4)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from nova.core.models import Transcript


class STTEngine(ABC):
    """Converts captured PCM audio into a `Transcript`.

    Raises only `core.errors.SpeechError` at the boundary (mirrors `providers/*.py`'s
    "adapters raise only `core.errors` subtypes" rule, applied to a different subsystem).
    """

    @abstractmethod
    def transcribe(self, request_id: str, pcm: bytes, sample_rate: int) -> Transcript:
        raise NotImplementedError
