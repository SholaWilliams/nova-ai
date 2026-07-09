# MEMORY.md — Durable Agent Memory

Cross-session working memory for AI agents on this repo. **Append-curated:** add entries when finishing significant work; prune superseded ones; keep under 300 lines. Newest first within each section. This file records *state and decisions-in-flight* — settled design lives in the phase docs.

## Current state

- **2026-07-09** — M1 (Skeleton & Shell, T-101…T-110) implemented and verified locally: `core` (models/events/config/logging/errors, 100% test coverage) + themed UI shell (theme, PulseRing, StageChip, PipelineView, MainWindow) + `app.py` composition root + CI workflow. `python -m nova` boots to a dark themed window with an idling pulse ring; the header's "Run demo pipeline" button drives a full 9-stage rail via the debug emitter (visually confirmed via offscreen screenshots). All 5 quality gates green locally: ruff, ruff format, mypy(core), lint-imports, pytest (174 tests). **Nothing committed** — working tree only, awaiting owner review. Next step: M2 (Talking Brain) starting at T-201, per [docs/12](../12-development-roadmap.md) §2.
- **2026-07-08** — Documentation phase complete through Phase 20 (Build Track). Phases 15–16 (Education Track) deferred until after the build; Phase 18 (Obsidian) paused indefinitely.

## Decisions log (with why)

- **2026-07-09** — Lockfile tool: **uv** (resolves the ⚠️ item below). Already available locally (0.11.21+) and provisions pinned Python versions on demand (`uv python install 3.12`) independent of whatever the system's default `python` resolves to.
- **2026-07-09** — Runtime deps added incrementally, not the full docs/04 budget upfront: M1's `pyproject.toml` lists only PySide6/pydantic/pydantic-settings/python-dotenv as packaged deps, plus a `dev` group (ruff/mypy/pytest/pytest-qt/pytest-cov/import-linter/rich). `rich` is dev-console-only per docs/04's own dependency budget table (absent from its "packaged" list) — `core.logging` import-guards it so file logging works with or without it installed. google-genai/groq/edge-tts/pyttsx3/sounddevice/webrtcvad-wheels/httpx/simpleeval land in the M2–M4 PRs that first import them.
- **2026-07-09** — `core.models` implements exactly docs/11 §1's six frozen dataclasses (UserInput, Transcript, ToolCall, ToolResult, AssistantReply, ChatMessage). docs/03 §7.2 additionally lists `AgentThought`/`MemoryItem`; deferred to the agent/memory milestones that actually produce them (docs/11 is the later, drift-checked authority and omits them).
- **2026-07-09** — import-linter (T-110) currently has one `layers` contract — `nova.app > nova.ui > nova.core` — covering D-1, D-5, D-6, D-7. D-2/D-3/D-4 (providers/speech/memory/tools/agent) get added as new layers in the PRs that create those packages; the `layers` contract type requires every listed module to actually exist and be importable.
- **2026-07-09** — Stage rail composition (docs/05 §6.2 prose vs the §6.1 ASCII mockup disagree on which stages get their own chip): implemented with **9 rows** — every PipelineStage except IDLE (its child label is "—") and AWAITING_CONFIRMATION (docs/05 §6.6 gives it a modal dialog; §11's state map says its pulse-ring state is "Executing (held)", so the Executing chip just stays active while the modal is open). The §6.1 mockup only shows 7 of these 9 (omits Observing/Responding) — read as illustrative shorthand, not a deliberate exclusion, since a literal reading would also have dropped Remembering, which the same mockup explicitly includes (as "skipped"). Cheap to revisit: one line in `nova/ui/views/pipeline_view.py::RAIL_STAGES`.
- **2026-07-09** — `Color.ACCENT_SECONDARY` (violet, thinking/reasoning) is a **fixed** token, not swapped when the user picks a different `ui.accent`; only `accent.primary` (default cyan) follows FR-44's 4-option picker. The docs don't resolve what happens if a user picks "violet" as their primary accent (collides visually with the fixed secondary) — not exercised yet since the Settings view doesn't exist until M2.
- **2026-07-08** — Batched doc delivery approved by owner; review gates remain per-phase in spirit (owner reviews the set).
- **2026-07-08** — AGENTS.md is canonical, CLAUDE.md is a thin wrapper (single-source rule).
- **2026-07-08** — CODING_STANDARDS.md serves humans *and* agents (no separate style doc — drift prevention).
- **2026-07-08** — Pydantic v2 at validated boundaries + frozen dataclasses for transfer/events (TD-10 amends Phase 3 §7.2).

## Verify-at-implementation (⚠️ items)

- Model IDs: `gemini-2.5-flash`, `llama-3.3-70b-versatile`, `whisper-large-v3-turbo` — confirm current at T-202/T-203/T-403.
- `edge-tts` package viability + `en-US-AnaNeural` voice availability — confirm at T-404; pyttsx3 fallback is mandatory regardless.
- Default primary provider (Gemini assumed for free-tier tool-calling strength) — re-verify at T-204.
- MIT license marked "proposed" in README — owner to confirm before first release.

## Gotchas discovered

- pytest-qt 4.5.0's `waitSignal` context manager throws (`AttributeError: 'MultiSignalBlocker' object has no attribute 'check_params_callback'`) if the watched signal fires more than once inside the `with` block — use `qtbot.wait_until(predicate)` instead for signals that may emit rapidly/repeatedly (e.g. EventBus bursts from a worker thread).
- `QWidget.isVisible()` reflects the *whole ancestor chain*, not just the widget's own flag — a widget tree that's never been `.show()`n reports `isVisible() == False` even right after `setVisible(True)`. Cost time in a PulseRing repaint-count test and a StageChip expand/collapse test; fix is `.show()` (+ `qapp.processEvents()`) before asserting visibility/paint counts, or use `.grab()` which forces a synchronous render regardless of shown state.
- `Qt.WidgetAttribute.WA_TransparentForMouseEvents`, applied recursively to a composite row's children, reliably forwards clicks to one outer handler — used so `StageChip`'s whole row (icon/text/status labels) click-through to the outer widget's single `mousePressEvent`. Confirmed via a real `qtbot.mouseClick` dispatch, not just a direct method-call test.
- Variable fonts (`Inter[opsz,wght].ttf`, `JetBrainsMono[wght].ttf` from the google/fonts repo) load fine via `QFontDatabase.addApplicationFont`, and `QFont.setWeight()` correctly selects the right instance — no need to source separate static per-weight files.
- Lucide renamed `alert-triangle` → `triangle-alert` and `shield-question` → `shield-question-mark` upstream at some point (old names 404 on raw.githubusercontent.com). Fetched under the new names; saved locally as `assets/icons/alert-triangle.svg` / `shield-question.svg` to match the names docs/05 §5 actually specifies.
- Qt's SVG renderer does not resolve Lucide's `stroke="currentColor"` — icons are tinted by rendering to a transparent QPixmap then filling with `CompositionMode_SourceIn` (`nova.ui.theme.load_icon`), not by editing the SVG source.
