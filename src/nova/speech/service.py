"""SpeechService: listen (capture -> VAD -> STT -> Transcript) and speak (AssistantReply ->
TTS -> playback) facades (docs/08 §1, docs/11 §4). A plain Python class, no `QObject` base —
mirrors the `Agent`/`AgentWorker` split (business logic here, Qt-thread wrapper in
`worker.py`), matching TD-3's one cross-thread idiom rather than inventing a second.

Two additive amendments to the frozen docs/11 §4 contract (see docs/ai/MEMORY.md decisions
log): `end_listening()` (re-press-mic: stop capturing now, transcribe whatever's buffered)
alongside `cancel_listening()` (Esc: discard, no STT) — one boolean flag can't honestly serve
both outcomes. And `warm_up_tts()`, called once at startup (not part of the frozen contract,
purely an optimization) — a real hands-on timing check found `TTSModel.load_model()` takes
30-100s even with cached weights, so lazy-loading on the first `speak()` call would make a
user's first spoken reply arrive a minute late. Loading in the background as soon as the app
starts means it's ready well before any request naturally reaches SPEAKING.
"""

from __future__ import annotations

import array
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

from nova.core.config import VadSettings, VoiceSettings
from nova.core.errors import SpeechError
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.ids import new_request_id
from nova.core.models import AssistantReply, Transcript
from nova.speech.audio import SAMPLE_RATE, AudioCapture
from nova.speech.stt.base import STTEngine
from nova.speech.tts.base import TTSEngine
from nova.speech.vad import VadEndpointer, VadEvent

logger = logging.getLogger(__name__)

_HARD_CAP_S = 30.0  # docs/08 §2: "30s hard cap"
_FRAME_TIMEOUT_S = 0.1
_EMPTY_TEXT = ""
_NO_MIC_ERROR_CODE = "no_microphone"
_STT_FAILED_ERROR_CODE = "stt_failed"
_TTS_FAILED_ERROR_CODE = "tts_failed"


def _rms_level(frame: bytes) -> float:
    """0..1 loudness estimate for the pulse ring (docs/05 §7.1) — deliberately not a
    PipelineEvent (docs/11 §4: `listening_level` is a separate high-frequency signal)."""
    samples = array.array("h")
    samples.frombytes(frame)
    if not samples:
        return 0.0
    mean_square = sum(s * s for s in samples) / len(samples)
    return min(1.0, (mean_square**0.5) / 32768.0)


class SpeechService:
    """`listen()`/`speak()` — blocking, intended to run on dedicated SpeechIn/SpeechOut
    worker threads (see `worker.py`)."""

    def __init__(
        self,
        stt_engine: STTEngine,
        primary_tts: TTSEngine,
        fallback_tts: TTSEngine,
        audio_capture_factory: Callable[[], AudioCapture],
        bus: EventBus,
        vad_settings: VadSettings,
        voice_settings: VoiceSettings,
        on_listening_level: Callable[[float], None] | None = None,
        on_tts_mode_changed: Callable[[str], None] | None = None,
        on_speech_started: Callable[[str], None] | None = None,
    ) -> None:
        self._stt_engine = stt_engine
        self._primary_tts = primary_tts
        self._fallback_tts = fallback_tts
        self._audio_capture_factory = audio_capture_factory
        self._bus = bus
        self._vad_settings = vad_settings
        self._voice_settings = voice_settings
        self._on_listening_level = on_listening_level
        self._on_tts_mode_changed = on_tts_mode_changed
        self._on_speech_started = on_speech_started

        self._cancel_requested = False
        self._end_requested = False
        self._stop_requested = False
        self._active_engine: TTSEngine | None = None

    # ── post-construction wiring ─────────────────────────────────────────────
    # `app.py` must build the `SpeechInWorker`/`SpeechOutWorker` *after* this service (their
    # constructors take the service), so the level/mode callbacks — which need to point back
    # at those workers' signals — can't be supplied at `__init__` time without a circular
    # construction order. Same "construct now, wire callback later" shape as
    # `ProviderManager.set_provider()` elsewhere in this codebase.

    def set_listening_level_callback(self, callback: Callable[[float], None] | None) -> None:
        self._on_listening_level = callback

    def set_tts_mode_callback(self, callback: Callable[[str], None] | None) -> None:
        self._on_tts_mode_changed = callback

    def set_speech_started_callback(self, callback: Callable[[str], None] | None) -> None:
        self._on_speech_started = callback

    # ── warm-up (not part of the frozen contract — see module docstring) ───

    def warm_up_tts(self) -> None:
        """Best-effort: load the primary engine's model/voice ahead of the first real
        request. Failure here is silent — the first `speak()` call will hit the same
        failure and fall back to `pyttsx3` through the normal path."""
        try:
            self._primary_tts.warm_up(self._voice_settings.voice)
        except SpeechError:
            logger.warning("pocket-tts warm-up failed; will retry on first speak()", exc_info=True)

    # ── listening (docs/08 §2, §3) ──────────────────────────────────────────

    def cancel_listening(self) -> None:
        """Esc: discard, no STT call. Direct call only, any thread — the SpeechIn thread is
        blocked inside `listen()`'s loop when this needs to land (same reasoning as
        `Agent.cancel()`; see ARCHITECTURE_RULES.md's threading law)."""
        self._cancel_requested = True

    def end_listening(self) -> None:
        """Re-press mic: stop capturing now, transcribe whatever's buffered. Direct call
        only, any thread — same reasoning as `cancel_listening()`."""
        self._end_requested = True

    def listen(self, device: int | None) -> Transcript:
        request_id = new_request_id()
        self._cancel_requested = False
        self._end_requested = False

        self._emit(request_id, PipelineStage.LISTENING, EventStatus.STARTED, "Listening…")
        capture = self._audio_capture_factory()
        try:
            capture.start(device)
        except SpeechError as exc:
            self._fail_listen(request_id, exc, _NO_MIC_ERROR_CODE)
            return Transcript(request_id=request_id, text=_EMPTY_TEXT, confidence=None)

        vad = VadEndpointer(self._vad_settings)
        frames: list[bytes] = []
        speech_detected = False
        started = time.monotonic()
        try:
            while True:
                if self._cancel_requested or self._end_requested:
                    break
                if time.monotonic() - started > _HARD_CAP_S:
                    break
                frame = capture.read_frame(timeout=_FRAME_TIMEOUT_S)
                if frame is None:
                    continue
                frames.append(frame)
                if self._on_listening_level is not None:
                    self._on_listening_level(_rms_level(frame))
                outcome = vad.process_frame(frame)
                if outcome is VadEvent.SPEECH_STARTED:
                    speech_detected = True
                elif outcome is VadEvent.SPEECH_ENDED:
                    break
        finally:
            capture.stop()

        self._emit(request_id, PipelineStage.LISTENING, EventStatus.COMPLETED, "Heard you!")

        if self._cancel_requested or not speech_detected:
            self._emit(
                request_id, PipelineStage.TRANSCRIBING, EventStatus.SKIPPED, "Nothing to transcribe"
            )
            return Transcript(request_id=request_id, text=_EMPTY_TEXT, confidence=None)

        self._emit(
            request_id, PipelineStage.TRANSCRIBING, EventStatus.STARTED, "Understanding your words"
        )
        pcm = b"".join(frames)
        try:
            transcript = self._stt_engine.transcribe(request_id, pcm, sample_rate=SAMPLE_RATE)
        except SpeechError as exc:
            self._fail_transcribe(request_id, exc)
            return Transcript(request_id=request_id, text=_EMPTY_TEXT, confidence=None)

        # Empty-but-successful is `completed`, not `failed` — the call worked, the result
        # is just empty; "no agent call" is a decision made one layer up (MainWindow).
        self._emit(
            request_id,
            PipelineStage.TRANSCRIBING,
            EventStatus.COMPLETED,
            transcript.text or "Heard nothing",
            {"text": transcript.text, "confidence": transcript.confidence},
        )
        return transcript

    def _fail_listen(self, request_id: str, exc: SpeechError, error_code: str) -> None:
        self._emit(
            request_id,
            PipelineStage.LISTENING,
            EventStatus.FAILED,
            exc.friendly_message,
            {"error_code": error_code},
        )
        self._emit(
            request_id, PipelineStage.TRANSCRIBING, EventStatus.SKIPPED, "Nothing to transcribe"
        )
        self._emit(
            request_id,
            PipelineStage.ERROR,
            EventStatus.COMPLETED,
            exc.friendly_message,
            {"error_code": error_code},
        )

    def _fail_transcribe(self, request_id: str, exc: SpeechError) -> None:
        self._emit(
            request_id,
            PipelineStage.TRANSCRIBING,
            EventStatus.FAILED,
            exc.friendly_message,
            {"error_code": _STT_FAILED_ERROR_CODE},
        )
        self._emit(
            request_id,
            PipelineStage.ERROR,
            EventStatus.COMPLETED,
            exc.friendly_message,
            {"error_code": _STT_FAILED_ERROR_CODE},
        )

    # ── speaking (docs/08 §4) ────────────────────────────────────────────────

    def stop_speaking(self) -> None:
        """Direct call only, any thread — the SpeechOut thread is blocked inside `speak()`
        when this needs to land. Two mechanisms (see `TTSEngine.abort()`'s docstring for
        why): the cooperative `should_stop` flag, and a hard `abort()` on whichever engine
        is currently active — the latter is what actually delivers the <100ms bound."""
        self._stop_requested = True
        if self._active_engine is not None:
            self._active_engine.abort()

    def speak(self, reply: AssistantReply) -> None:
        request_id = reply.request_id
        revealed = False

        def reveal() -> None:
            """Fires the chat bubble's text reveal exactly once — on real audio start where
            possible, or as a fallback at whichever point `speak()` ends up returning from,
            so an interrupted/skipped/failed reply's text is never permanently swallowed
            (FR-9: spoken text is always simultaneously visible)."""
            nonlocal revealed
            if revealed:
                return
            revealed = True
            if self._on_speech_started is not None:
                self._on_speech_started(request_id)

        if not self._voice_settings.tts_enabled:
            self._emit(request_id, PipelineStage.SPEAKING, EventStatus.SKIPPED, "Voice is off")
            reveal()
            return

        text = _strip_for_speech(reply.spoken_text)
        if not text:
            self._emit(request_id, PipelineStage.SPEAKING, EventStatus.SKIPPED, "Nothing to say")
            reveal()
            return

        self._stop_requested = False
        self._emit(request_id, PipelineStage.SPEAKING, EventStatus.STARTED, "Speaking")

        try:
            self._speak_with(self._primary_tts, text, reveal)
        except SpeechError:
            logger.warning("primary TTS failed, falling back to pyttsx3", exc_info=True)
            if self._on_tts_mode_changed is not None:
                self._on_tts_mode_changed("offline")
            try:
                self._speak_with(self._fallback_tts, text, reveal)
            except SpeechError:
                self._emit(
                    request_id,
                    PipelineStage.SPEAKING,
                    EventStatus.FAILED,
                    "I can't speak right now, but here's my answer.",
                    {"error_code": _TTS_FAILED_ERROR_CODE},
                )
                reveal()
                return

        reveal()
        self._emit(request_id, PipelineStage.SPEAKING, EventStatus.COMPLETED, "Finished speaking")

    def _speak_with(self, engine: TTSEngine, text: str, on_start: Callable[[], None]) -> None:
        self._active_engine = engine
        try:
            engine.speak(
                text,
                self._voice_settings.voice,
                self._voice_settings.output_device,
                should_stop=lambda: self._stop_requested,
                on_start=on_start,
            )
        finally:
            self._active_engine = None

    # ── shared ───────────────────────────────────────────────────────────────

    def _emit(
        self,
        request_id: str,
        stage: PipelineStage,
        status: EventStatus,
        detail: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._bus.publish(
            PipelineEvent(
                request_id=request_id,
                stage=stage,
                status=status,
                detail=detail,
                payload=payload,
                ts=datetime.now(UTC),
            )
        )


_MARKDOWN_CHARS = re.compile(r"[*_`#>~]")
# Emoji blocks + regional indicators + variation selectors (0xFE00-0xFE0F — the invisible
# "render as emoji" modifier that trails many symbols, e.g. sun-symbol + variation-16 for a
# sun emoji). Built from int code points via chr(), not embedded literals, to keep this
# source file plain ASCII.
_EMOJI_CODE_RANGES = [
    (0x1F000, 0x1FFFF),
    (0x2600, 0x27BF),
    (0x1F1E6, 0x1F1FF),
    (0xFE00, 0xFE0F),
]
_EMOJI_CHARS = "".join(chr(c) for lo, hi in _EMOJI_CODE_RANGES for c in range(lo, hi + 1))
_EMOJI_RANGES = re.compile(f"[{re.escape(_EMOJI_CHARS)}]")


def _strip_for_speech(text: str) -> str:
    """Strip emoji and markdown before synthesis (docs/08 §4) — one small pure function,
    called once before dispatch, so neither TTS engine needs its own copy."""
    without_markdown = _MARKDOWN_CHARS.sub("", text)
    without_emoji = _EMOJI_RANGES.sub("", without_markdown)
    return " ".join(without_emoji.split())
