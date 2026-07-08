# NOVA — Testing Strategy

| | |
|---|---|
| **Document** | Phase 13 — Testing Strategy |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | Phase 2 (US acceptance criteria, NFRs), Phase 11 (contracts), Phase 12 (task gates) |
| **Feeds into** | CI configuration, Phase 20 (PR gates) |

---

## 1. Test Pyramid & Policy

| Level | Location | Runs | Network | Qt |
|---|---|---|---|---|
| Unit | `tests/unit/` | every push (CI) | never | never |
| Integration | `tests/integration/` | every push (CI) | never (fakes/fixtures) | never |
| UI (widget) | `tests/ui/` | every push (CI, offscreen) | never | pytest-qt |
| System (live) | `tests/system/` | manual, marker `live` | real APIs, real OS | real app |
| Acceptance | checklist + scripted runs | per milestone / release | real | real |

**Iron rule: CI never calls paid/keyed APIs.** Provider and STT behavior in CI comes from golden fixtures recorded once via a `record` marker and committed (scrubbed of keys).

## 2. Unit Tests

- **Fakes over mocks**: `FakeProvider` (scripted `LLMResponse` sequences), `FakeClock`, `RecordingEventBus`, in-memory `MemoryService`, `tmp_path` file roots. Patch-style mocking only at true edges (e.g., `os.startfile`).
- Focus areas & examples: calculator caps (`9**9**9` → `too_large`); VAD endpointing on synthesized frame patterns; retrieval scoring; config migration & corrupt-file quarantine; Planner token budget; Router shapes incl. malformed JSON; Executor watchdog with a deliberately slow stub tool.
- **Coverage gate: ≥ 70 % on `core`, `agent`, `tools`, `memory`** (NFR-11); `ui` exempt from the numeric gate (covered by widget tests).

## 3. Integration Tests (the agent on a bench)

The full agent loop with FakeProvider + real Registry (stub or real tools with `tmp_path`) + real MemoryService (temp dir) + RecordingEventBus:

- **Pipeline-order assertions**: for each scenario, assert the exact event sequence (e.g., typed weather request ⇒ `THINKING → SELECTING_TOOL → EXECUTING → OBSERVING → RESPONDING`, with `LISTENING/TRANSCRIBING skipped`). *This test is the mechanical guarantee of NG-9 — if the UI stream lies, this suite fails.*
- Scenario matrix: direct answer; single tool; multi-step (2 tools); repair round-trip; unknown tool; tool timeout; tool error fed back; denial; iteration cap; provider fallback (primary scripted to fail); cancellation between iterations.
- Contract tests (Phase 11 §7): golden wire formats, schema-drift regeneration diff, adapter round-trips, import-linter D-1…D-7.

## 4. UI (Widget) Tests

pytest-qt, `QT_QPA_PLATFORM=offscreen` in CI:

- Stage rail renders a synthetic event stream correctly (states, skips, durations, error tint).
- PulseRing state transitions on events (assert internal state + no per-frame allocation regression via paint counter).
- Confirmation dialog: Yes/No/Esc/timeout paths emit correct signals.
- Settings: key masking, invalid-key banner, hot-swap signal.
- Memory View: list/delete/clear flows against in-memory service.
- Keyboard map (NFR-10): Tab order, Ctrl+M, Esc.

## 5. System Tests (live, manual trigger)

Marker `live`, run on the dev machine and before releases: one real Gemini call, one real Groq call + fallback drill (invalid primary key), one real STT round-trip (recorded WAV), edge-tts + pyttsx3 switch drill, app_launcher opens Notepad, desktop_organizer full preview→confirm→act→undo cycle on a scratch Desktop directory (never the real one: `NOVA_DESKTOP_OVERRIDE` env for tests).

## 6. Acceptance & Manual Testing

- **Acceptance map:** every US-x Given/When/Then from the PRD becomes a checklist item tagged to its milestone (US-1/3/13 → M4; US-4/5/7/8/9 → M3; US-10/11 → M5; …). Release requires all M-priority items green on the packaged build (PRD §6).
- **Manual checklist (M6, clean Win 11 VM):** install-run with no Python; first-run key setup; SC-1…SC-10 walkthrough; failure drills (pull network mid-request, yank mic, kill speaker device); RAM/latency spot-check (SC-7/8: Task Manager steady-state ≤ 1.5 GB, stopwatch first-activity < 1 s).
- **Demo test (pre-M7, feeds SC-13):** run the Phase 16 script 3× consecutively on demo hardware, including the rehearsed offline-fallback path; zero unrecoverable failures required.

## 7. CI Pipeline (GitHub Actions, `windows-latest`)

```
on: push + PR →
  1. ruff check + format --check
  2. mypy (strict: core, agent)
  3. import-linter contracts
  4. pytest unit+integration+ui (offscreen) with coverage gate
  5. (release tags) PyInstaller build + artifact upload + smoke launch (--self-check flag: boots headless, verifies wiring, exits 0)
```

PR merge gate = all five green (Phase 20 §5). The `--self-check` startup flag is a deliberate design item: `app.py` wires everything, emits one synthetic pipeline event through the real bus, and exits — catching packaging/wiring breaks without a display.

## 8. Non-Functional Verification

| NFR | How verified |
|---|---|
| NFR-1/2 latency | timing asserts in integration (fake latencies) + stopwatch protocol in manual checklist |
| NFR-3 UI thread | debug `FreezeDetector` (main-thread heartbeat; logs stalls > 100 ms) active in dev builds; soak test 30 min |
| NFR-4 RAM | manual checklist measurement + `tracemalloc` snapshot test for leak trends across 50 fake requests |
| NFR-11 architecture | import-linter + coverage gates in CI |

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 13 review. |

**Exit check:** every PRD acceptance criterion has a home; NG-9 is enforced by a failing test, not a promise; CI is key-free; release gates are unambiguous.
