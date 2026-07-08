# MEMORY.md — Durable Agent Memory

Cross-session working memory for AI agents on this repo. **Append-curated:** add entries when finishing significant work; prune superseded ones; keep under 300 lines. Newest first within each section. This file records *state and decisions-in-flight* — settled design lives in the phase docs.

## Current state

- **2026-07-08** — Documentation phase complete through Phase 20 (Build Track). **No application code exists yet.** Next engineering step: M1/T-101 (repo bootstrap) per [docs/12](../12-development-roadmap.md), following the [docs/20](../20-implementation-plan.md) order. Phases 15–16 (Education Track) deferred until after the build; Phase 18 (Obsidian) paused indefinitely.

## Decisions log (with why)

- **2026-07-08** — Batched doc delivery approved by owner; review gates remain per-phase in spirit (owner reviews the set).
- **2026-07-08** — AGENTS.md is canonical, CLAUDE.md is a thin wrapper (single-source rule).
- **2026-07-08** — CODING_STANDARDS.md serves humans *and* agents (no separate style doc — drift prevention).
- **2026-07-08** — Pydantic v2 at validated boundaries + frozen dataclasses for transfer/events (TD-10 amends Phase 3 §7.2).

## Verify-at-implementation (⚠️ items)

- Model IDs: `gemini-2.5-flash`, `llama-3.3-70b-versatile`, `whisper-large-v3-turbo` — confirm current at T-202/T-203/T-403.
- `edge-tts` package viability + `en-US-AnaNeural` voice availability — confirm at T-404; pyttsx3 fallback is mandatory regardless.
- Lockfile tool (`uv` vs `pip-tools`) — decide at T-101.
- Default primary provider (Gemini assumed for free-tier tool-calling strength) — re-verify at T-204.
- MIT license marked "proposed" in README — owner to confirm before first release.

## Gotchas discovered

- *(none yet — populate during implementation)*
