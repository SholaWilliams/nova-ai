# NOVA — Product Requirements Document (PRD)

| | |
|---|---|
| **Document** | Phase 2 — Product Requirements Document |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Owner** | Project Lead |
| **Last updated** | 2026-07-08 |
| **Depends on** | [01-project-vision.md](01-project-vision.md) (goals G-x, success criteria SC-x, non-goals NG-x, educational objectives EO-x) |
| **Feeds into** | Phase 3 (Architecture), Phase 5 (UI/UX), Phase 12 (Roadmap), Phase 13 (Testing) |

---

## 1. Purpose

This PRD translates the Phase 1 vision into concrete, testable requirements. Every functional requirement (FR) traces to at least one goal (G-x) or educational objective (EO-x). Every acceptance criterion is written so that Phase 13 can turn it into a test.

**Priority scheme (MoSCoW):**
- **M** — Must have for v1.0. Release blocks without it.
- **S** — Should have for v1.0. Cut only under schedule pressure.
- **C** — Could have. Nice-to-have if time allows.
- **W** — Won't have in v1.0 (documented for later; see Vision §10.2).

---

## 2. User Personas

### P-1 · Zara — The Learner (primary audience)
- **Age 9**, curious, short attention span, no technical vocabulary.
- Watches a live demo; may be invited to speak a request to NOVA.
- **Needs:** big readable visuals, instant feedback, friendly language, a voice that talks back, nothing scary when things fail.
- **Success looks like:** after the demo she says *"it picked the calculator tool because I asked a math question."* (EO-3)

### P-2 · The Presenter — Educator / Parent (primary operator)
- Runs NOVA live in front of children; technically competent but not the developer.
- **Needs:** reliability during demos, a rehearsable flow, quick recovery from mic/internet failure, settings he can adjust without editing code, confidence nothing destructive can happen on stage (NG-5).
- **Success looks like:** a 15-minute demo with zero unrecoverable failures (SC-13).

### P-3 · Ada — The Teen Self-Learner (secondary)
- **Age 15**, learning Python, discovers NOVA on GitHub.
- **Needs:** readable code, a documented path to add her own Tool, docs that explain *why*, not just *what*.
- **Success looks like:** she adds a "tell me a joke" Tool in under an hour using only the docs (SC-9).

### P-4 · Dev — The Open-Source Contributor (secondary)
- Professional developer evaluating NOVA as a reference agent architecture.
- **Needs:** clean module boundaries, typed internal APIs, tests, contribution guidelines, honest docs.
- **Success looks like:** he can explain the full request lifecycle after one reading of the architecture doc.

---

## 3. Functional Requirements

### 3.1 Conversation (traces: G-1, SC-5)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | The user can submit a request by typing into a text input field. | M |
| FR-2 | The user can submit a request by voice via a push-to-talk / click-to-talk control. | M |
| FR-3 | Every capability available by voice is identically available by typing. | M |
| FR-4 | The conversation (user and assistant turns) is displayed in a scrollable chat view with clear speaker distinction. | M |
| FR-5 | Chat history persists across application restarts and is browsable per session. | M |
| FR-6 | The user can start a new conversation session without deleting past sessions. | S |
| FR-7 | If a request cannot be served by any tool, NOVA answers conversationally from the LLM (labeled as a direct answer, no tool stage shown). | M |

### 3.2 Speech (traces: G-6, EO-6)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-8 | Speech-to-text converts the user's spoken request to text; the transcript is shown live/on completion in the UI before the agent acts on it. | M |
| FR-9 | Text-to-speech speaks every assistant response aloud; the spoken text is always simultaneously visible as text (accessibility + EO-6). | M |
| FR-10 | The user can mute TTS and use NOVA silently. | M |
| FR-11 | Listening start/stop is explicitly indicated (visual + audio cue). NOVA never listens without indication. | M |
| FR-12 | The user can select input/output audio devices in Settings. | S |
| FR-13 | The user can interrupt (stop) NOVA's speech playback. | S |
| FR-14 | Wake-word activation ("Hey NOVA"). | W (post-1.0, spec in Phase 8) |

### 3.3 Agent Core (traces: G-2, EO-2, EO-3, EO-4)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-15 | The agent sends the user request plus tool schemas to a cloud LLM and receives either a tool call or a direct answer. | M |
| FR-16 | Tool calls are validated against the tool's JSON schema before execution; invalid calls are rejected and retried or reported. | M |
| FR-17 | The agent supports multi-step tool use: a tool result can be fed back to the LLM for further tool calls, up to a hard iteration cap (default 5). | M |
| FR-18 | The agent produces a child-readable one-line "thinking summary" for every request, displayed in the pipeline view. | M |
| FR-19 | The LLM never executes anything: it only returns structured decisions. All execution happens in validated Python code (Vision §11.3). | M |
| FR-20 | Tools flagged as *sensitive* (anything that modifies files or system state) require explicit user confirmation before execution (NG-5). | M |

### 3.4 Tools (traces: G-4, SC-3)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-21 | **Calculator** — evaluate arithmetic/math expressions safely (no `eval` of raw input). | M |
| FR-22 | **Weather** — current conditions + short forecast for a named or default location, via a public weather API. | M |
| FR-23 | **Application Launcher** — launch installed applications by common name (e.g., "open Notepad"). | M |
| FR-24 | **Browser Control** — open URLs and perform web searches in the default browser. | M |
| FR-25 | **File Search** — find files by name/pattern within user-scoped folders (Documents, Desktop, Downloads); read-only. | M |
| FR-26 | **Desktop Organization** — tidy the Desktop by moving files into categorized folders; dry-run preview + confirmation required (FR-20); undo of the last organization run. | M |
| FR-27 | **Memory Tool** — store and recall user facts/preferences on request ("remember that…", "what's my…"). | M |
| FR-28 | Tools are registered in a Tool Registry; the registry, not the agent, owns tool metadata, schemas, and lookup. | M |
| FR-29 | Adding a new tool requires only: implementing the tool interface + registering it. Zero changes to agent/UI core (G-8, SC-9). | M |

### 3.5 Memory (traces: G-5, SC-4, EO-5)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-30 | Long-term facts and preferences persist to local JSON storage and survive restarts. | M |
| FR-31 | Relevant memories are retrieved and injected into the LLM context for new requests (strategy detailed in Phase 9). | M |
| FR-32 | A "What NOVA remembers" panel lists all stored memories in plain language. | M |
| FR-33 | The user can delete any individual memory, or all memories, from the UI. | M |
| FR-34 | Conversation history is stored separately from long-term memory (different lifecycle, Phase 9). | M |

### 3.6 Pipeline Visualization (traces: G-3, EO-1…EO-7, NG-9)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-35 | The UI displays the pipeline stages for the current request: Listening → Understanding → Thinking → Choosing a Tool → Doing It → Remembering → Speaking. | M |
| FR-36 | Each stage activates in real time, driven by actual pipeline events — never simulated or pre-scripted (NG-9). | M |
| FR-37 | The tool-selection stage displays the chosen tool's name and icon; the execution stage shows a plain-language action description (e.g., "Opening Notepad on your PC"). | M |
| FR-38 | Stages that don't occur for a request (e.g., no tool needed) are visibly skipped, teaching that the pipeline adapts (EO-1). | M |
| FR-39 | Errors surface as a distinct pipeline state with a friendly explanation (EO-7). | M |
| FR-40 | Completed pipelines remain inspectable for the last request (the presenter can walk back through what happened). | S |

### 3.7 UI Shell (traces: G-7)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-41 | Dark futuristic theme as specified in Phase 5; consistent across all screens. | M |
| FR-42 | Animated pulse ring / assistant avatar reflecting state: idle, listening, thinking, speaking, error. | M |
| FR-43 | Persistent status indicators: network, microphone, active LLM provider. | M |
| FR-44 | Settings screen: API keys, provider selection, voice on/off, audio devices, default weather location, theme accent. | M |
| FR-45 | All animations run smoothly (target 60 fps, floor 30 fps) on the reference hardware. | S |

### 3.8 Reliability & Errors (traces: SC-6)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-46 | Loss of network yields a conversational, child-friendly error and a UI network indicator; the app remains fully navigable. | M |
| FR-47 | Missing/invalid API keys are detected at startup and produce actionable guidance in the UI (not a crash or a stack trace). | M |
| FR-48 | If the primary LLM provider fails, the agent falls back to the secondary provider automatically (strategy in Phase 10). | S |
| FR-49 | Tool execution is time-boxed (default 15 s); timeouts are reported as tool errors, not hangs. | M |
| FR-50 | All errors are logged to a local rotating log file with enough context to diagnose (Phase 14). | M |

---

## 4. Non-Functional Requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | Performance | First visible pipeline activity < 1 s after end of user input (SC-7). |
| NFR-2 | Performance | TTS playback begins < 2 s after response text is ready. |
| NFR-3 | Performance | UI thread never blocks: all network, speech, and tool work executes off the UI thread. No frozen frames > 100 ms. |
| NFR-4 | Resources | Steady-state RAM ≤ 1.5 GB; no assumption of GPU; acceptable on ~2 GHz CPU (SC-8). |
| NFR-5 | Reliability | A 15-minute scripted demo completes without crash or unrecoverable state (SC-13). |
| NFR-6 | Safety | No destructive or irreversible action without explicit confirmation (NG-5). File operations restricted to user-scoped folders; system folders are off-limits. |
| NFR-7 | Safety | System prompts instruct child-appropriate language; provider safety settings set to strictest available tier. |
| NFR-8 | Privacy | No telemetry. No data leaves the machine except calls to LLM/STT/weather APIs (NG-6). API keys stored locally, never committed (Phase 14). |
| NFR-9 | Usability | All UI copy readable by the target age group where child-facing; presenter/developer-facing copy may be technical. Minimum contrast WCAG AA; minimum body font 14 px equivalent. |
| NFR-10 | Accessibility | Full keyboard operability for typed mode; everything spoken is also displayed as text (FR-9). |
| NFR-11 | Maintainability | One module, one responsibility (Vision §11.1). Public internal APIs type-hinted and docstringed. Core logic unit-test coverage ≥ 70% (Phase 13). |
| NFR-12 | Extensibility | New Tool in < 1 h by an intermediate dev (SC-9); provider swap via settings only (SC-10). |
| NFR-13 | Compatibility | Windows 11; Python 3.11+; PySide6 (versions pinned in Phase 4). |
| NFR-14 | Observability | Structured logging with levels; pipeline events are the single source of truth for both UI and logs (one instrumentation stream, two consumers). |

---

## 5. User Stories & Acceptance Criteria

Stories are grouped by epic. Acceptance criteria are Given/When/Then and become Phase 13 test cases.

### Epic A — Talking to NOVA

**US-1** · As Zara, I want to ask NOVA a question with my voice, so that I can use it without typing.
- **Given** the app is idle, **when** I press the talk button and speak "what is 12 times 9", **then** my words appear as text on screen, the pipeline animates through its stages, and NOVA speaks and displays "108".
- **Given** I am speaking, **when** I stop, **then** listening ends within ~1 s and the transcript is shown before the thinking stage begins (FR-8, FR-11).

**US-2** · As the Presenter, I want typed input with feature parity, so that a demo survives a broken microphone.
- **Given** the mic is unavailable, **when** I type any request that works by voice, **then** the behavior is identical except the Listening/Understanding stages are skipped-marked (FR-3, FR-38).

**US-3** · As Zara, I want NOVA to talk back, so that it feels alive.
- **Given** any completed response, **when** TTS is enabled, **then** the response is spoken and simultaneously shown as text (FR-9). **When** TTS is muted, **then** only text appears (FR-10).

### Epic B — Watching NOVA think

**US-4** · As Zara, I want to see what NOVA is doing at each moment, so that I understand it isn't magic.
- **Given** any request, **when** processing occurs, **then** each pipeline stage lights in the true order of events, with child-readable labels (FR-35, FR-36).
- **Given** a request needing no tool, **when** it completes, **then** the tool stages show as skipped (FR-38).

**US-5** · As Zara, I want to see which tool NOVA picked, so that I learn that abilities are tools.
- **Given** "what's the weather in Lagos", **when** the agent selects the Weather tool, **then** the pipeline shows the Weather tool's name and icon before execution begins (FR-37, EO-3).

**US-6** · As the Presenter, I want to review the last pipeline after it finishes, so that I can walk children back through what happened.
- **Given** a completed request, **when** I open the pipeline detail, **then** every stage shows its label, duration, and plain-language description (FR-40).

### Epic C — NOVA acts on the computer

**US-7** · As Zara, I want to say "open the calculator app" and watch it open, so that I see the AI causing a real action.
- **Given** the request, **when** the Application tool executes, **then** the app launches, and the execution stage displays "Opening Calculator on your PC" (FR-23, FR-37, EO-4).

**US-8** · As the Presenter, I want desktop organization to preview before acting, so that nothing embarrassing happens live.
- **Given** "tidy my desktop", **when** the Desktop tool runs, **then** NOVA shows a preview of planned moves and requires my confirmation before touching any file (FR-26, FR-20).
- **Given** an organization run just completed, **when** I ask to undo it, **then** files return to their previous locations (FR-26).

**US-9** · As Zara, I want NOVA to find my file, so that I see AI being useful.
- **Given** "find my file called dragon drawing", **when** the File tool runs, **then** matching files from user folders are listed with locations; nothing is modified (FR-25).

### Epic D — NOVA remembers

**US-10** · As Zara, I want NOVA to remember my favorite color, so that I see AI memory in action.
- **Given** "remember my favorite color is blue", **when** stored, **then** the Remembering stage lights, and after a full app restart, "what's my favorite color?" answers "blue" (FR-27, FR-30, SC-4).

**US-11** · As the Presenter, I want to show and clear NOVA's memories, so that I can teach that memory is stored data — and reset between classes.
- **Given** stored memories, **when** I open "What NOVA remembers", **then** all memories are listed in plain language and each can be deleted; a clear-all exists (FR-32, FR-33, EO-5).

### Epic E — Configuration & resilience

**US-12** · As the Presenter, I want to configure keys and providers in Settings, so that setup requires no code editing.
- **Given** the Settings screen, **when** I enter API keys and pick a provider, **then** changes apply without restart, and the active provider shows in the status bar (FR-43, FR-44, SC-10).

**US-13** · As the Presenter, I want NOVA to fail kindly when the internet dies, so that a demo survives it.
- **Given** no network, **when** any request is made, **then** NOVA responds conversationally that it can't reach its brain right now, the network indicator shows offline, and the app remains responsive (FR-46, SC-6, EO-7).

**US-14** · As Dev, I want the agent to fall back to a second provider, so that one API outage doesn't kill the product.
- **Given** the primary provider errors, **when** a request is in flight, **then** the agent retries on the fallback provider and the status bar reflects the switch (FR-48).

### Epic F — Developer experience

**US-15** · As Ada, I want to add my own tool in under an hour, so that I can make NOVA mine.
- **Given** only the repo docs, **when** Ada implements the documented tool interface and registers it, **then** the tool is selectable by the LLM and visualized in the pipeline with no core changes (FR-29, SC-9).

---

## 6. Release-Level Acceptance

v1.0 ships when:

1. All **M** requirements pass their acceptance tests (Phase 13).
2. Vision success criteria SC-1 … SC-10 are demonstrated on the reference hardware.
3. The full documentation suite (Phase 17) and AI-engineering assets (Phase 19) are current with the shipped behavior.
4. The packaged build (Phase 14) installs and runs on a clean Windows 11 machine with no Python preinstalled.

(SC-11…SC-13 are Education Track criteria and gate the *demo*, not the software release.)

---

## 7. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R-1 | **Cloud LLM outage/latency during a live demo** | Medium | High | Dual-provider fallback (FR-48); rehearsed offline script (Phase 16); cached demo answers clearly labeled as cached (NG-9 compliant). |
| R-2 | **STT accuracy with children's voices / noisy classrooms** | High | High | Push-to-talk (no open mic); show transcript before acting so mistakes are visible and teachable (FR-8); typed fallback (FR-3); mic selection (FR-12). |
| R-3 | **Free-tier API rate limits / cost creep** | Medium | Medium | Provider abstraction with per-provider limits awareness (Phase 10); conservative token budgets (Phase 6); local caching of weather. |
| R-4 | **PySide6 threading bugs (UI freezes, cross-thread crashes)** | Medium | High | Strict threading model defined in Phase 3; all cross-thread communication via Qt signals; threading rules in ARCHITECTURE_RULES.md (Phase 19). |
| R-5 | **Desktop organization damages user files** | Low | Very High | Dry-run + confirmation + undo (FR-26); user-scoped folders only (NFR-6); move-never-delete policy. |
| R-6 | **LLM returns malformed/unsafe tool calls** | Medium | Medium | Schema validation before execution (FR-16); sensitive-tool confirmation (FR-20); iteration cap (FR-17). |
| R-7 | **LLM produces child-inappropriate content** | Low | Very High | Strict provider safety settings + system prompt constraints (NFR-7); presenter-reviewed demo script; typed mode moderation identical to voice. |
| R-8 | **Performance misses targets on 2 GHz CPU** | Medium | Medium | RAM/CPU budgets are architecture constraints from day one (NFR-4); animation complexity budget in Phase 5; profiling milestone in Phase 12. |
| R-9 | **Scope creep (chatbot gravity)** | High | Medium | NG-1 enforced at review gates; MoSCoW discipline; new features must map to a pillar (Vision §5). |
| R-10 | **Windows API brittleness (app launch paths, shell quirks)** | Medium | Medium | Use stable Windows interfaces (shell associations, Start Menu index); per-tool integration tests on a clean VM (Phase 13). |
| R-11 | **TTS voice quality undermines the "alive" feel** | Medium | Low | Evaluate voices early (Phase 8 spike); voice selection in settings. |
| R-12 | **Solo-developer schedule risk** | High | Medium | Milestones sized small (Phase 12); Must-scope is minimal; Education Track explicitly deferred. |

---

## 8. Indicative Timeline

Detailed sprint planning happens in Phase 12; this establishes the shape. Assumes a solo developer working part-time.

| Milestone | Content | Indicative duration |
|-----------|---------|---------------------|
| M0 | Complete Build Track documentation (Phases 2–14, 17, 19, 20) | 2–3 weeks |
| M1 | Project skeleton, config, logging, event bus, UI shell (dark theme, layout, no logic) | 1–2 weeks |
| M2 | Agent core + provider abstraction + typed conversation end-to-end (no tools yet) | 2 weeks |
| M3 | Tool registry + all seven v1.0 tools, with pipeline events | 2–3 weeks |
| M4 | Speech: STT input, TTS output, audio device handling | 2 weeks |
| M5 | Memory system + pipeline visualization polish + animations | 2 weeks |
| M6 | Testing hardening, packaging, docs sync, v1.0 release | 1–2 weeks |
| M7 | Education Track: teaching guide + presentation script (Phases 15–16) | 1 week |

Total indicative: **13–17 weeks** part-time to v1.0 + education materials.

---

## 9. Traceability

| Vision goal | Covered by |
|-------------|-----------|
| G-1 Voice + typed | FR-1…FR-13 |
| G-2 Agent loop | FR-15…FR-20 |
| G-3 Pipeline viz | FR-35…FR-40 |
| G-4 Toolset | FR-21…FR-29 |
| G-5 Memory | FR-30…FR-34 |
| G-6 Speech | FR-8…FR-13 |
| G-7 UI polish | FR-41…FR-45 |
| G-8 Extensibility | FR-28, FR-29, NFR-12 |
| G-9 Docs quality | §6.3, Phases 17/19 |
| G-11 Readable codebase | NFR-11 |

---

## 10. Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 2 review. |

---

## 11. Phase 2 Exit — Review Checklist

- [ ] Personas match the real intended audiences
- [ ] All FR priorities (M/S/C/W) agreed — especially what is **not** Must
- [ ] NFR budgets (latency, RAM, coverage) agreed
- [ ] Risk register complete; mitigations acceptable (especially R-2, R-5, R-7)
- [ ] Indicative timeline realistic for available time

**On approval → Phase 3: System Architecture** (delivered alongside this document for joint review).
