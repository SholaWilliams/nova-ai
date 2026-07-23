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
| TTS | `pocket-tts` (local CPU neural, revised M4) with `pyttsx3` (SAPI5) fallback |
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

## TD-4 · LLM providers: OmniRoute (sole backend, revised M9)

**Revised at M9 (owner direction):** Gemini, Groq(-chat), and OpenRouter (M2–M8 picks, history below) are all superseded by **[OmniRoute](https://github.com/diegosouzapw/OmniRoute)**, a locally-run AI gateway the owner runs separately (`http://127.0.0.1:20128`) that routes across 278+ upstream providers behind one OpenAI-Chat-Completions-compatible endpoint (`/v1/chat/completions`), with its own circuit-breaking, quota-lending, and per-model health scoring. Nova's `OmniRouteProvider` reuses the exact `httpx` + `_openai_compat.py` adapter shape `OpenRouterProvider` already established (TD-4's M8 amendment) — same dialect, different base URL/key source, no vendor SDK.
**Why:** collapses three separately-keyed cloud adapters (and the reliability problems each one individually produced — see the M8 free-tier-garbling entry below) into one locally-controlled gateway that already does the routing/fallback/circuit-breaking work `ProviderManager`'s 3-provider state machine used to do by hand. **No cloud fallback kept** — explicit owner decision, single point of failure accepted since this is a local dev/classroom app the owner controls directly; if the local OmniRoute process is down, Nova has no LLM access at all (typed-only mode, per the existing no-provider-configured path). **Model selection: pinned, not `"auto"`** — same reasoning as the OpenRouter free-tier garbling incident below: an auto-routed model isn't guaranteed to support tool calling reliably, and the agent loop depends on it. Default **`auto/coding`** (OmniRoute's own "quality-first" combo name) ⚠️ placeholder — OmniRoute's public docs don't document a specific model id with confirmed tool-calling support (unlike OpenRouter's catalog, which did), so this is picked as the closest documented option, not a verified one; **owner must confirm/replace via their own OmniRoute dashboard/model catalog** once it's running, same as TD-6's unauditioned-voice ⚠️ pattern.
**Rejected:** **keeping one cloud provider as an emergency fallback** — considered and declined; would keep more of `ProviderManager`'s multi-provider machinery alive for a case (local gateway process down) the owner accepts as acceptable downtime, at the cost of two more configured keys and dead-branch complexity for providers that no longer exist in the primary path. **OpenAI/Anthropic direct** — still true, no meaningful free tier (R-3), and now moot: OmniRoute itself can route to either behind the same one gateway if ever wanted. **local models** — still excluded by NG-2 (OmniRoute is a router to cloud providers, not local inference).

**History (superseded, kept for context):**
- **Gemini (M2–M8):** strong native function-calling, generous free tier, first-party `google-genai` SDK, adjustable safety settings (NFR-7). Default model `gemini-3.5-flash`.
- **Groq-for-chat (M2–M8):** extremely low latency, free tier, OpenAI-compatible tool calling, hosted `openai/gpt-oss-120b`. Groq itself is **not** removed — it still serves STT (TD-5), only its chat-completions usage is gone.
- **OpenRouter (M8, added 2026-07-22):** added as a consistency lever against Groq's `gpt-oss-120b` reasoning-model chain-of-thought leaking into replies. Its `:free` tier's backend load-balancing produced observed degenerate output (`<unk>`-token spam) from a low-precision quantized backend (2026-07-23), mitigated via a `provider.quantizations` allow-list and a degenerate-output detect-and-retry-once in `agent.py` (the retry survives into M9 as a provider-agnostic safeguard; the quantization pin was OpenRouter-specific and does not carry over).

## TD-5 · STT: Groq-hosted Whisper

**Why:** `whisper-large-v3-turbo` on Groq is fast (typically < 1 s for short utterances), accurate on non-adult voices (R-2 mitigation), free tier, and reuses the Groq API key. Push-to-talk clips are short, so payloads are small.
**Rejected:** **Windows SAPI recognition** — accuracy too poor for children; **Vosk (local)** — accuracy gap vs Whisper; **local faster-whisper** — viable on CPU but adds seconds of latency on 2 GHz; retained as the *future offline* path (Phase 8 §8); **Azure/Google Cloud STT** — setup ceremony + billing complexity unfit for classroom operators.

## TD-6 · TTS: takada-tts-service primary, pyttsx3 fallback

**Revised at M9 (owner direction):** in-process **[pocket-tts](https://github.com/kyutai-labs/pocket-tts)** (Kyutai Labs) — this TD's M4 pick — is replaced by **`takada-tts-service`**, a local FastAPI microservice the owner runs separately (Docker or `uvicorn`) that wraps pocket-tts behind `POST /v1/synthesize` and streams back a progressively-framed WAV (RIFF header + PCM16LE frames, `audio/wav`). Nova talks to it over `httpx` — no vendor SDK, no local model. `pyttsx3` (SAPI5) stays as the fallback, unchanged: fully offline, keyless, used whenever the remote call fails or times out.
**Why:** moves pocket-tts's PyTorch runtime out of Nova's own process/dependency tree entirely, eliminating the M4 "real cost, accepted" paragraph below as a live concern for Nova (the service that owns it manages its own footprint separately) and removing a whole bug class this app hit in practice — a `torch.Tensor`→PCM16 dtype-mismatch crash chain compounded by stale Windows WDM-KS device indices (fixed on `fix/wdm-ks-device-validation`, 2026-07-23). Bytes now arrive from the service pre-formatted as PCM16LE inside a streamed WAV container — Nova parses a 44-byte header for sample rate and writes the rest straight to `AudioPlayback`, no tensor/dtype conversion on Nova's side at all. Voice selection, quantization, and model warm-up now live entirely in `takada-tts-service` — out of scope for Nova's own code and docs.
**Real cost, accepted:** none, on Nova's side — `httpx` already covers "plain HTTP calls we own" (TD-11), same reasoning `OpenRouterProvider` uses. The tradeoff moves elsewhere: Nova now depends on a second local process being up; if it isn't, `pyttsx3` fallback covers the gap the same way it already did for pocket-tts failures.
**Rejected:** **in-process pocket-tts** (M4–M8 pick) — works, but couples Nova's own packaged footprint (≈1.2–2 GB, docs/14 §5) and dependency surface to a heavy ML runtime it doesn't otherwise need, and was the direct cause of the dtype/device bug class above. **edge-tts** (original pick) — unofficial client of a Microsoft endpoint that can break, and needs network for every utterance. **ElevenLabs/OpenAI TTS** — quality, but paid (R-3). **gTTS** — high latency, robotic prosody. **SAPI5-only** — robotic voice undermines P-4 (kept only as the fallback, not the primary).

## TD-7 · VAD: webrtcvad · Audio: sounddevice

**Why:** WebRTC VAD is a few hundred KB, pure CPU, industry-proven for end-of-speech detection (30 ms frames); `webrtcvad-wheels` provides maintained binary wheels for Python 3.12. `sounddevice` (PortAudio) has clean device enumeration/selection (FR-12) and NumPy-friendly capture.
**Rejected:** **silero-vad** — better accuracy but drags in ONNX/torch weight for marginal gain at push-to-talk (we have an explicit start signal); **PyAudio** — stale wheel maintenance.
**Note (M4):** TD-6's revision above already brings PyTorch into the dependency tree for TTS, so the premise behind rejecting `silero-vad` here ("avoid adding torch") no longer fully holds — recorded for honesty, not acted on: `webrtcvad` is still lighter, still proven, and switching VAD to `silero-vad` now would buy nothing new, so VAD stays as originally decided.

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

Runtime deps (packaged): PySide6, google-genai, groq, pyttsx3, sounddevice, webrtcvad-wheels, httpx, pydantic, pydantic-settings, python-dotenv, simpleeval. **No TTS ML runtime** — `torch`/`pocket-tts` (added M4) removed at M9; synthesis now happens in the separately-run `takada-tts-service` process, outside Nova's own dependency tree.

**Revised at M9:** M4 had brought pocket-tts's PyTorch dependency into this budget (`torch` ≈ 477 MB on disk, whole dev venv ≈ 1.53 GB, packaged estimate ≈ 1.2–2 GB, all ⚠️ pending measurement). M9 moves TTS inference out of Nova's process entirely (TD-6) — Nova's own packaged footprint should return toward the pre-M4 ≈ 300–400 MB estimate, since `httpx` (already counted, TD-11) is the only addition. ⚠️ still pending: an actual M9-era PyInstaller artifact measurement to confirm. See docs/14 §5 for the matching support-matrix update.

**Pinning policy:** exact pins in a lockfile (`uv lock` or `pip-tools`) ⚠️ tool choice at M1; `pyproject.toml` carries compatible ranges. `torch` is pinned to PyPI's `cpu`-only wheel index (`download.pytorch.org/whl/cpu`) via `[tool.uv.sources]`/`[[tool.uv.index]]` in `pyproject.toml` — without this override, the default Windows wheel bundles CUDA runtime libraries that are dead weight on this GPU-less target (confirmed via `torch.cuda.is_available() == False` post-install).

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 4 review. |
| 1.1.0 | 2026-07-09 | M2/T-202-T-203: swapped stale default models — `gemini-2.5-flash` → `gemini-3.5-flash` (old model shuts down 2026-10-16), `llama-3.3-70b-versatile` → `openai/gpt-oss-120b` (deprecated for Groq's free/dev tier 2026-06-17). Both ⚠️s resolved. |
| 1.2.0 | 2026-07-10 | M4, owner direction: TD-6 primary TTS swapped `edge-tts` → `pocket-tts` (local CPU neural voice, Kyutai Labs); dependency budget and TD-7 amended for the resulting PyTorch footprint; both flagged ⚠️ pending the M6 packaged-artifact measurement. |
| 1.3.0 | 2026-07-23 | M8: TD-4 amended for OpenRouter as the third LLM provider — `httpx` accepted over the `openai` SDK (reuses `_openai_compat.py`); documents the free-tier quantization-routing pin and degenerate-output retry added to mitigate observed `<unk>`-spam from low-precision backend routing. |
| 1.4.0 | 2026-07-23 | M9 (Stream B), owner direction: TD-4 rewritten — Gemini, Groq(-chat), and OpenRouter superseded by OmniRoute (local gateway) as the sole LLM backend, no cloud fallback kept. Groq's STT usage (TD-5) is unaffected. Default model `auto/coding` flagged ⚠️ pending owner verification against their live OmniRoute dashboard. |
| 1.4.0 | 2026-07-23 | M9 (Stream A): TD-6 revised — primary TTS moved from in-process pocket-tts to `takada-tts-service` over HTTP; PyTorch dependency and its cost paragraph removed from TD-6 and the Dependency Budget, both flagged ⚠️ pending an actual M9-era packaged-artifact measurement. |

**Exit check:** every choice traces to a constraint (hardware, cost, license, pedagogy); all ⚠️ items are listed as M1 verification tasks in Phase 12.
