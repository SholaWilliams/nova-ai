# NOVA — Technology Decisions

| | |
|---|---|
| **Document** | Phase 4 — Technology Decisions |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | [03-system-architecture.md](03-system-architecture.md) (constraints A-1…A-6), Vision constraints (§10.4) |
| **Feeds into** | Phase 8 (speech engines), Phase 10 (providers), Phase 14 (packaging), Phase 20 (setup tasks) |

Each decision is a mini-ADR: **Decision → Why → Rejected alternatives**. Anything marked ⚠️ must be re-verified against current versions/pricing at implementation time (M1).

---

## Stack Summary

| Concern | Choice |
|---------|--------|
| Runtime | Python 3.12 (min 3.11) |
| UI | PySide6 (Qt 6) |
| Concurrency | QThread workers + signals (no asyncio) |
| LLM providers | Google Gemini (`google-genai` SDK) + Groq (`groq` SDK) |
| STT | Groq Whisper API (`whisper-large-v3-turbo`) ⚠️ |
| TTS | `edge-tts` (neural) with `pyttsx3` (SAPI5) offline fallback |
| VAD | `webrtcvad-wheels` |
| Audio I/O | `sounddevice` |
| Weather | Open-Meteo (no API key) |
| Safe math | `simpleeval` |
| Models/validation | Pydantic v2 (+ frozen dataclasses for events) |
| Config | `pydantic-settings` + `python-dotenv` |
| HTTP (non-SDK) | `httpx` |
| Logging | stdlib `logging` + `RotatingFileHandler` (+ `rich` dev console) |
| Testing | `pytest`, `pytest-qt`, `pytest-cov`, `import-linter` |
| Lint/format/types | `ruff` (lint+format), `mypy` (strict on `core`, `agent`) |
| Packaging | PyInstaller (one-folder) |
| Icons / fonts | Lucide (ISC) / Inter + JetBrains Mono (OFL) |

---

## TD-1 · Python 3.12

**Why:** Team skill; richest AI SDK ecosystem; PySide6 first-class. 3.12 gives measurable CPU perf gains (relevant on a 2 GHz machine); 3.11 floor keeps wheel availability safe.
**Rejected:** **Node/Electron** — RAM cost of Chromium alone threatens NFR-4 (≤1.5 GB); **C#/WinUI** — great for Windows but cuts against Python learning goals and AI ecosystem; **Python 3.13** — too new for guaranteed binary wheels across our audio deps.

## TD-2 · PySide6

**Why:** Native performance without a browser engine; QPropertyAnimation + QPainter cover the pulse ring and pipeline animations on CPU; LGPL license fits open source (Vision G-9); official Qt-for-Python support.
**Rejected:** **PyQt6** — functionally equivalent but GPL/commercial licensing complicates open-source contributions; **Tkinter** — cannot achieve the Phase 5 visual bar; **Kivy** — mobile-first idioms, weaker desktop polish; **Flet/Tauri hybrids** — webview RAM + a second language.

## TD-3 · QThread workers, not asyncio

**Why:** Qt's signal/slot system already provides thread-safe eventing (A-2, A-5); a single AgentWorker with blocking SDK calls is dramatically simpler to reason about — and to *teach* — than an asyncio bridge (`qasync`) mixing two event loops. Our concurrency need is small (3 workers).
**Rejected:** **asyncio + qasync** — adds a foreign event loop inside Qt, subtle re-entrancy bugs, and most provider SDKs remain sync-first; **multiprocessing** — IPC overhead and serialization complexity unjustified at our scale.

## TD-4 · LLM providers: Gemini + Groq

**Why (Gemini):** strong native function-calling, generous free tier, first-party `google-genai` SDK, adjustable safety settings (NFR-7). Default model **`gemini-3.5-flash`** — fast + cheap tier. (Verified at M2/T-202: `gemini-2.5-flash`, the model originally named here, shuts down 2026-10-16; `gemini-3.5-flash` has been GA since 2026-05-19 with no announced shutdown.)
**Why (Groq):** extremely low latency (great for a kids' demo — waiting kills attention), free tier, OpenAI-compatible tool calling, hosts **`openai/gpt-oss-120b`** with agentic tool use — and doubles as our STT vendor (TD-5), one key covering two needs. (Verified at M2/T-203: `llama-3.3-70b-versatile`, the model originally named here, was deprecated for Groq's free/developer tier on 2026-06-17; `openai/gpt-oss-120b` is Groq's own recommended replacement, matching the old model's tier and purpose-trained for agentic tool-calling — the exact reason Groq was chosen at all.)
**Rejected:** **OpenAI/Anthropic** — excellent tool calling but no meaningful free tier for a classroom/education budget (R-3); designed for as *future providers* in Phase 10; **local models** — excluded by NG-2.

## TD-5 · STT: Groq-hosted Whisper

**Why:** `whisper-large-v3-turbo` on Groq is fast (typically < 1 s for short utterances), accurate on non-adult voices (R-2 mitigation), free tier, and reuses the Groq API key. Push-to-talk clips are short, so payloads are small.
**Rejected:** **Windows SAPI recognition** — accuracy too poor for children; **Vosk (local)** — accuracy gap vs Whisper; **local faster-whisper** — viable on CPU but adds seconds of latency on 2 GHz; retained as the *future offline* path (Phase 8 §8); **Azure/Google Cloud STT** — setup ceremony + billing complexity unfit for classroom operators.

## TD-6 · TTS: edge-tts primary, pyttsx3 fallback

**Why:** `edge-tts` gives Microsoft neural voices (natural, child-friendly) free with no API key — the single biggest "it feels alive" lever (R-11). `pyttsx3` (SAPI5) is fully offline and keyless: it is both the network-failure fallback (SC-6, R-1) and the demo backup voice.
**Risk ⚠️:** `edge-tts` is an unofficial client of a Microsoft endpoint and can break; the fallback is therefore *architecturally mandatory* (`TTSEngine` ABC, A-4), not optional.
**Rejected:** **ElevenLabs/OpenAI TTS** — quality, but paid (R-3); **gTTS** — high latency, robotic prosody; **SAPI5-only** — robotic voice undermines P-4.

## TD-7 · VAD: webrtcvad · Audio: sounddevice

**Why:** WebRTC VAD is a few hundred KB, pure CPU, industry-proven for end-of-speech detection (30 ms frames); `webrtcvad-wheels` provides maintained binary wheels for Python 3.12. `sounddevice` (PortAudio) has clean device enumeration/selection (FR-12) and NumPy-friendly capture.
**Rejected:** **silero-vad** — better accuracy but drags in ONNX/torch weight for marginal gain at push-to-talk (we have an explicit start signal); **PyAudio** — stale wheel maintenance.

## TD-8 · Weather: Open-Meteo

**Why:** Completely free, **no API key** — one less secret for a presenter to configure (FR-47 surface shrinks), includes geocoding, generous limits, no account.
**Rejected:** **OpenWeatherMap** — key + account for no added value at our needs.

## TD-9 · Safe math: simpleeval

**Why:** Tiny AST-based evaluator; whitelisted operators/functions; no `eval` ever touches user or LLM output (FR-21, A-1).
**Rejected:** **`eval`/`exec`** — banned outright; **sympy** — tens of MB and import latency for elementary arithmetic.

## TD-10 · Pydantic v2 (+ dataclasses for events)

**Why:** Tool parameter schemas must be *generated* as JSON Schema for the LLM and *validated* on the way back (FR-16) — Pydantic v2 does both from one class definition, closing the loop with zero drift. `pydantic-settings` handles `.env` + `settings.json` with typed access (Phase 3 §15). Pipeline events remain frozen stdlib dataclasses: created thousands of times, no validation needed, cheapest possible.
**Amendment to Phase 3 §7.2:** tool arguments/results and settings are Pydantic models; `PipelineEvent` and pure transfer artifacts stay frozen dataclasses.
**Rejected:** **jsonschema + hand-written dicts** — schema/validator drift risk; **attrs/cattrs** — fine, but Pydantic's JSON-Schema emission is the killer feature here.

## TD-11 · httpx · stdlib logging · rich

**Why:** `httpx` for the two plain-HTTP calls we own (Open-Meteo; provider health checks) — sane timeouts by default. Logging stays stdlib (`logging` + `RotatingFileHandler`) so consumers need zero knowledge of a bespoke framework; the EventBus→log bridge (A-2) is a normal `Handler`. `rich` prettifies the *dev* console only — never a runtime dependency of packaged builds' logic.
**Rejected:** **requests** — no default timeouts (a real hang source, FR-49 spirit); **loguru** — pleasant, but nonstandard for contributors and adds nothing we need.

## TD-12 · Testing & quality toolchain

**Why:** `pytest` (+`pytest-qt` for widget tests driven by synthetic pipeline events, `pytest-cov` for the ≥70 % core gate — NFR-11). **`import-linter`** turns Phase 3 rules D-1…D-7 into CI-failing contracts — architecture that isn't enforced decays. `ruff` covers lint *and* formatting in one fast tool; `mypy --strict` on `core` + `agent` (the layers where type drift is most dangerous), permissive elsewhere.
**Rejected:** **black+flake8+isort trio** — three tools where ruff is one; **mypy strict everywhere** — Qt stubs make strict UI typing a time sink with low payoff.

## TD-13 · Packaging: PyInstaller one-folder

**Why:** Mature PySide6 support via official hooks; one-folder mode starts faster and debugs easier than one-file (which unpacks to temp on every launch — slow on target CPU). Ships as a zipped folder on GitHub Releases (Phase 14).
**Rejected:** **Nuitka** — best runtime perf but long build times and harder CI; **Briefcase** — MSI polish, but less battle-tested with our audio stack; revisit post-1.0 if an installer is wanted; **cx_Freeze** — weaker hook ecosystem.

## TD-14 · Assets: Lucide icons, Inter + JetBrains Mono

**Why:** Lucide — consistent stroke style, ISC licensed, has every icon Phase 5 needs (tools, status, stages). Inter — screen-optimized, excellent legibility for children at distance; JetBrains Mono for transcripts/expressions. Both OFL — bundleable (Phase 14).
**Rejected:** **Font Awesome** — license tiering; **system fonts** — inconsistent metrics break the Phase 5 spacing system.

---

## Dependency Budget

Runtime deps (packaged): PySide6, google-genai, groq, edge-tts, pyttsx3, sounddevice, webrtcvad-wheels, httpx, pydantic, pydantic-settings, python-dotenv, simpleeval, numpy (sounddevice transitive). Estimated packaged footprint ≈ 300–400 MB on disk, well within storage constraint; steady-state RAM dominated by Qt (~250–400 MB) — comfortable under the 1.5 GB ceiling (NFR-4).

**Pinning policy:** exact pins in a lockfile (`uv lock` or `pip-tools`) ⚠️ tool choice at M1; `pyproject.toml` carries compatible ranges.

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 4 review. |
| 1.1.0 | 2026-07-09 | M2/T-202-T-203: swapped stale default models — `gemini-2.5-flash` → `gemini-3.5-flash` (old model shuts down 2026-10-16), `llama-3.3-70b-versatile` → `openai/gpt-oss-120b` (deprecated for Groq's free/dev tier 2026-06-17). Both ⚠️s resolved. |

**Exit check:** every choice traces to a constraint (hardware, cost, license, pedagogy); all ⚠️ items are listed as M1 verification tasks in Phase 12.
