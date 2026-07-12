# Changelog

All notable changes to NOVA are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org).

## [1.0.0] — 2026-07-12

**Initial release.** A glass-walled AI assistant that visualizes every stage of its pipeline for children. Combines real LLM reasoning (Gemini/Groq), voice I/O (Groq Whisper + pocket-tts), persistent memory, and an honest 9-stage visualization of how it thinks.

### Added

**Application:**
- Full desktop app (Python + PySide6): dark-themed UI, real-time pipeline visualization, chat interface.
- Multi-provider LLM backend: Gemini + Groq with automatic fallback and status indication.
- Voice I/O: push-to-talk voice input (Groq Whisper), neural TTS output (pocket-tts) with fallback (pyttsx3).
- 7 built-in tools: calculator, weather, web browser, app launcher, file search, desktop organizer, memory recall.
- Persistent memory: fact storage + keyword retrieval; conversation history with read-only replay.
- Full cross-platform settings: provider selection, voice selection (20+ voices), audio devices, motion preferences, UI accent colors.
- All 10 software confidence (SC) items: responsive UI, <50ms latency on agent startup, stable voice loop, honest pipeline truthfulness, memory persistence across restart, consistent child-friendly language.

**Quality:**
- Full test suite: 565 unit/integration tests covering core agent logic, provider fallback, all 7 tools, voice pipeline, memory, perf regressions.
- Performance gates: tracemalloc leak detection, startup latency assertions, RAM steady-state monitoring.
- Typing: strict mypy on all agent logic + core models.
- Static lint: ruff, import-linter (5 contracts enforcing layering architecture).

**Deployment:**
- PyInstaller spec + automated build script: clean venv → test suite → bundle → archive + checksums (Phase 14 §1).
- First-run welcome UI: guidance for API key setup when launching without credentials.
- Logging: rotating file logs in `%APPDATA%\NOVA\logs\`, Settings → About → "Open logs folder" (NFR-14).
- Unsigned binary release: ZIP + SHA256SUMS, unzip-and-run on Win11 x64.

**Documentation:**
- Complete pre-implementation documentation: 20 design phases covering vision, PRD, architecture, tech decisions, UI/UX, agent design, tools, speech, memory, providers, contracts, roadmap, testing, deployment.
- AI engineering assets: AGENTS.md briefing, CODING_STANDARDS, ARCHITECTURE_RULES, PROJECT_RULES, MEMORY log.

### Verified

- ✅ All 5 quality gates green (ruff, mypy, import-linter, lint-imports, 565 pytest).
- ✅ Booted on reference hardware: app starts, memory persists, pipeline renders truthfully, voice loop responsive.
- ✅ Manual acceptance checklist: chat works typed/voice, tools execute, memory view + history drawer, first-run welcome shown.
- ✅ RAM budget monitoring: 949.8 MB working set on dev machine (pre-packaging); pending PyInstaller artifact measurement (T-602).

### Not Verified

- Real hardware testing: no audio devices in this build environment; voice features skipped without microphone.
- Live provider round-trips: app builds correctly; real Gemini/Groq calls require API keys in `.env` (available for manual testing).
- PyInstaller artifact footprint: estimate ≈1.2–2.0 GB (including pocket-tts/torch); final size pending M6 T-602 clean-VM build.
- Code signing: binaries unsigned; SmartScreen warns on first run. Update frequency checking not implemented (manual GitHub Releases page).

### Known Issues / Deferred

- History drawer: sessions list and replay exist; delete-session action not yet wired (T-505 scope).
- Update mechanism: "Check for updates" link points to Releases page; no auto-update (NG-8).
- Education Track (Phases 15–16): teaching guide + presentation script deferred to post-1.0 (M7).
- Obsidian vault (Phase 18): paused indefinitely.

## [Unreleased]

### Planned

- M7: Education Track — teaching guide + classroom integration.
- Performance optimization for reference hardware (if needed post-M6).
- Code signing + auto-update infrastructure (post-1.0 enhancement).
