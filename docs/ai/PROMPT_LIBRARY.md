# PROMPT_LIBRARY.md — Runtime & Development Prompts

Two collections: prompts NOVA itself uses at runtime (versioned artifacts), and reusable prompts for developing NOVA with AI agents.

## A. Runtime prompts (product artifacts)

| Prompt | Source of truth | Notes |
|---|---|---|
| System prompt v1 | `src/nova/agent/prompts/system.md` (structure: [docs/06 §3](../06-agent-architecture.md)) | Identity · pipeline self-knowledge · 6 rules · style examples. Change = behavior change → PR + prompt-regression check (below) |
| Repair prompt | `agent/prompts/repair.md` | Injected on malformed tool calls: names the error, lists valid tools, demands one corrected call |
| Direct-answer fallback | `agent/prompts/no_tools.md` | Used at iteration cap / repair failure: answer honestly without tools, apologize simply |

**Prompt-regression check:** `tests/integration/test_prompts.py` runs the FakeProvider scenario matrix against prompt *assembly* (structure, token budget, memory-block inclusion). Live behavior spot-check protocol (5 canonical requests × 2 providers, `-m live`) documented in the test module — run before merging any system-prompt change.

**Prompt changelog:** table at the bottom of `system.md` (version, date, change, why) — prompts drift subtly; make drift visible.

## B. Development prompts (for AI coding agents)

Copy-paste starters that encode our process. Each assumes the agent read AGENTS.md.

**New tool (end-to-end):**
> Add a `<name>` tool to NOVA. Follow docs/07 §1 template + §10 checklist: write the spec section in docs/07 first, then params model, Tool subclass, unit tests (happy + each error + timeout), register in app.py, icon + child-friendly detail_template. Verify with the full gate suite. It must require zero changes outside `tools/`, `app.py`, `assets/`, and docs — if not, stop and report the friction instead of working around it.

**New provider:**
> Add a `<name>` provider per docs/10 §5: adapter implementing LLMProvider with error mapping to ProviderError subtypes, golden-fixture round-trip tests, manager + settings registration, .env.example line. No agent/tool/ui edits allowed.

**Bug fix:**
> Reproduce first: write the failing test that captures issue #<n>, then fix it, then run the full gates. If the fix touches a contract (docs/11), stop and propose the version/migration plan before editing.

**Docs sync sweep:**
> Diff behavior changes on this branch against docs/. List every doc section now stale, update them, and check PR-checklist item "docs synced". Do not restate content across docs — link to the owning doc (docs/17 single-source rule).

**Pipeline stage audit (pre-release):**
> Trace every emit site of PipelineEvents. For each stage: confirm started→completed|failed|skipped pairing, confirm the emitting code actually performs the described work (S-8), confirm detail strings pass Phase 5 §9. Report violations with file:line.
