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

**Primary:** `edge-tts` neural voices (TD-6). Default **`en-US-AnaNeural`** (child-friendly timbre) ⚠️, alternates selectable in Settings (Aria, Guy, plus locale voices). Synthesis streams MP3 chunks → decode → `sounddevice.OutputStream`; playback begins on first chunk (NFR-2: < 2 s to first audio).

**Fallback:** `pyttsx3` (SAPI5, offline). Automatic switch when edge-tts errors or network is down; status cluster shows "Voice: offline" (warning tint, Phase 5 §7.4). This is also the demo backup voice (R-1).

**Behavior:**
- Every reply is spoken (TTS on) *and* displayed (FR-9); mute in Settings/status toggle (FR-10).
- `spoken_text` may be shorter than displayed text (agent may trim lists for speech — Phase 6 §5).
- **Interruption (FR-13):** clicking the speaker glyph, pressing mic, or submitting new input stops playback within 100 ms (stream abort, no fade). `SPEAKING failed→interrupted` recorded honestly.
- Emoji and markdown are stripped for synthesis; numbers ≤ 4 digits spoken naturally by the engine.

## 5. Audio Cues & Device Management

- **Cues** (`assets/sounds/`): listen-start (rising two-tone, 200 ms), listen-end (falling, 150 ms), error (soft thud). Cues ≤ -12 dBFS; disabled with reduced-motion? No — separate "sound effects" toggle.
- **Devices (FR-12):** enumerate via `sounddevice.query_devices()`; Settings dropdowns for input/output; "mic test" level meter. Device loss mid-session ⇒ `SpeechError` → conversational fallback to typed mode (SC-6) + status mic icon struck through.

## 6. Error Matrix

| Failure | Behavior | User sees |
|---|---|---|
| No microphone / access denied | typed mode remains; mic disabled | struck-through mic + tooltip; "I can't hear right now — you can type to me!" once |
| STT network/API failure | 1 retry; then abort listen | "My ears aren't working — is the internet on?" + typed fallback |
| STT empty result | no agent call | "I didn't catch that — try again?" |
| edge-tts failure | silent auto-switch to pyttsx3 | response still spoken (robotic); "Voice: offline" status |
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

**Exit check:** listen/speak flows fully deterministic with timeouts everywhere; every failure lands conversationally; nothing listens without a visible indicator (now or in the wake-word future).
