# NOVA — Speech System

| | |
|---|---|
| **Document** | Phase 8 — Speech System |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | Phase 3 (§10 speech flow), Phase 4 (TD-5/6/7) |
| **Feeds into** | Phase 11 (SpeechService contract), Phase 12 (M4 tasks) |

---

## 1. Overview

`nova/speech/` provides two facades on two worker threads (Phase 3 §5): **listen** (capture → VAD → STT → `Transcript`) and **speak** (`AssistantReply.spoken_text` → TTS → playback). Engines sit behind `STTEngine`/`TTSEngine` ABCs (A-4); the service emits `LISTENING`/`TRANSCRIBING`/`SPEAKING` pipeline events — the same stream the UI renders (A-2).

## 2. Speech-to-Text

**Engine (v1.0):** Groq Whisper API, model `whisper-large-v3-turbo` ⚠️ (TD-5).

**Capture format:** 16 kHz, mono, 16-bit PCM (Whisper-native; smallest useful payload). `sounddevice.InputStream` with 30 ms frames (VAD-aligned).

**Flow (push-to-talk, FR-2/FR-11):**

1. User presses mic → chime + `LISTENING started` → stream opens on the configured device.
2. Frames buffer in memory; RMS level streams to the UI (pulse ring tracks voice — Phase 5 §7.1).
3. **End of speech** when: (a) VAD detects ≥ 800 ms silence *after* ≥ 300 ms of speech, (b) user re-presses mic, or (c) 30 s hard cap. Esc = cancel (no STT call).
4. Buffer → WAV in memory → Groq STT (10 s timeout) → `TRANSCRIBING` events → `Transcript(text, confidence)`.
5. Transcript rendered in the UI **before** the agent acts (FR-8; R-2 — mistranscription is visible, not silent).
6. Empty/whitespace transcript ⇒ friendly "I didn't catch that — try again?" (no agent call, no cost).

**Latency budget (SC-7/NFR-1):** endpoint detection ≤ 0.85 s + upload/STT ≈ 0.5–1.2 s → transcript typically < 2 s after user stops; `LISTENING`→`TRANSCRIBING` transition is immediate, so *visible* pipeline activity is instant.

## 3. Voice Activity Detection

`webrtcvad` (TD-7), aggressiveness **2** (1 = too permissive in classrooms, 3 clips soft child voices — R-2), 30 ms frames. Ring buffer of 25 frames; speech-start = 60 % voiced, speech-end = ≥ 800 ms unvoiced. Pure gate — VAD never touches STT; it only decides *when to stop recording*. Parameters live in settings (tunable without code).

## 4. Text-to-Speech

**Primary (revised M9, owner direction):** `takada-tts-service` (TD-6) — a local FastAPI microservice, run separately (Docker or `uvicorn`) by the owner, that wraps pocket-tts behind `POST /v1/synthesize` and streams back a progressively-framed WAV response (`audio/wav`: a 44-byte RIFF header up front, then raw PCM16LE frames as they're generated — no fixed total length, an unbounded/unseekable stream). `RemoteTTSEngine` (`src/nova/speech/tts/remote_tts.py`) calls it over `httpx`, parses the 44-byte header once to read the sample rate, then writes every following byte chunk straight to `sounddevice.OutputStream` — no tensor/dtype conversion on Nova's side, since the bytes already arrive as PCM16. Default voice **`alba`** (matches `takada-tts-service`'s PocketTTSProvider default — the service loads exactly one voice per instance, so Nova's default must match or the service returns 400) ⚠️ unauditioned in this dev environment (no speakers) — owner should confirm/replace once heard for real; alternates selectable in Settings from the same catalog (`cosette`, `marius`, `jean`, …), sent as the `voice` field on each request. Playback begins on first streamed chunk (NFR-2: < 2 s to first audio — ⚠️ pending re-measurement over HTTP, was ~0.85 s in-process on the dev machine). `SpeechService.warm_up_tts()` now does a best-effort `GET /health` check at startup instead of loading a local model — the service owns its own model warm-up.

**Fallback:** `pyttsx3` (SAPI5, offline, zero model/network dependency). Automatic switch when `takada-tts-service` is unreachable, times out, or returns an error; status cluster shows a backup-voice indicator (warning tint, Phase 5 §7.4). This is also the demo backup voice (R-1). Voice cloning (arbitrary audio-prompt URLs) is out of scope for v1.0 — the fixed catalog only.

**Behavior:**
- Every reply is spoken (TTS on) *and* displayed (FR-9); mute in Settings/status toggle (FR-10).
- `spoken_text` may be shorter than displayed text (agent may trim lists for speech — Phase 6 §5).
- **Interruption (FR-13):** clicking the speaker glyph, pressing mic, or submitting new input stops playback within 100 ms. Two mechanisms: `AudioPlayback.abort()` (PortAudio's `Pa_AbortStream`, the actual bound-delivering hard stop, safe cross-thread) plus a cooperative `should_stop` flag polled between chunks/iterations (stops further wasted generation/decode work, doesn't itself deliver the 100 ms bound). `SPEAKING failed→interrupted` recorded honestly.
- Emoji and markdown are stripped for synthesis; numbers ≤ 4 digits spoken naturally by the engine.

**Contract additions (docs/11 §4, M4, additive):** `SpeechService.end_listening()` — re-press-mic (stop capturing now, transcribe whatever's buffered) alongside the existing `cancel_listening()` (Esc: discard, no STT) — one boolean flag can't honestly serve both outcomes, since Esc must *always* discard regardless of how much speech was captured. A `tts_mode_changed(str)` notification ("primary" | "offline") drives the status-cluster indicator above.

## 5. Audio Cues & Device Management

- **Cues** (`assets/sounds/`): listen-start (rising two-tone, 200 ms), listen-end (falling, 150 ms), error (soft thud). Cues ≤ -12 dBFS; disabled with reduced-motion? No — separate "sound effects" toggle.
- **Devices (FR-12):** enumerate via `sounddevice.query_devices()`, excluding the **Windows WDM-KS** host API ⚠️ confirmed by hands-on testing: WDM-KS doesn't support the blocking read/write this app uses and always fails stream-open with `PaErrorCode -9999` — Windows commonly exposes the same physical device (esp. Bluetooth headsets) redundantly under MME/DirectSound/WASAPI *and* WDM-KS, so filtering WDM-KS still leaves a working entry; Settings dropdowns for input/output; "mic test" level meter. Device loss mid-session ⇒ `SpeechError` → conversational fallback to typed mode (SC-6) + status mic icon struck through.

## 6. Error Matrix

| Failure | Behavior | User sees |
|---|---|---|
| No microphone / access denied | typed mode remains; mic disabled | struck-through mic + tooltip; "I can't hear right now — you can type to me!" once |
| STT network/API failure | 1 retry; then abort listen | "My ears aren't working — is the internet on?" + typed fallback |
| STT empty result | no agent call | "I didn't catch that — try again?" |
| pocket-tts failure (load or generate) | silent auto-switch to pyttsx3 | response still spoken (robotic); backup-voice status |
| Both TTS fail | text-only | reply displayed; speaker icon disabled with tooltip |
| Playback device vanished | stop, re-enumerate | toast "Speaker changed — check Settings" |

## 7. Wake Word (post-1.0 spec — FR-14 W)

**Engine:** openWakeWord (Apache-2.0, ONNX on CPU — fits no-GPU constraint). Custom "Hey NOVA" model trained from TTS-generated samples. **Design constraints when built:** always-listening loop must show a *persistent* visible indicator (extends FR-11 — never covert listening); wake-word detection runs fully locally (no audio leaves the machine until wake fires); toggle default **off**. Architecture is ready: it's a new front-edge producer that triggers the same `startListening()` path.

## 8. Future Offline STT

`faster-whisper` (CTranslate2) `base.en` int8: ~140 MB, ~2–4× realtime on the reference CPU — usable, not snappy. Slots in as an `STTEngine` implementation selected by a settings dropdown; auto-fallback when offline is post-1.0. Storage budget fine (46 GB free).

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 8 review. |
| 1.1.0 | 2026-07-10 | M4, owner direction: primary TTS swapped `edge-tts` → `pocket-tts` (docs/04 TD-6); default voice, warm-up-at-startup rationale, and revised interruption/error-matrix wording updated to match; `end_listening()`/`tts_mode_changed` contract additions recorded (docs/11 §4). |
| 1.2.0 | 2026-07-23 | M9 (Stream A), owner direction: primary TTS moved from in-process `pocket-tts` to `takada-tts-service` over HTTP (docs/04 TD-6) — `RemoteTTSEngine` parses a streamed WAV response instead of consuming `generate_audio_stream()` tensors directly; `warm_up_tts()` now health-checks the remote service instead of loading a local model. `pyttsx3` fallback and voice catalog unchanged. |

**Exit check:** listen/speak flows fully deterministic with timeouts everywhere; every failure lands conversationally; nothing listens without a visible indicator (now or in the wake-word future).
