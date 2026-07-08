# PROJECT_RULES.md — Process & Safety Invariants

Applies to every contributor, human or AI. Where a rule is mechanically enforced, the enforcer is named — the doc explains *why*, the tool says *no*.

## Safety invariants (never waivable)

| # | Invariant | Enforced by |
|---|---|---|
| S-1 | No code path deletes user files. Tools move/create/read only. | code review + grep gate in CI (`rm`, `unlink`, `rmtree`, `send2trash` outside tests) |
| S-2 | Anything modifying files/system state is a `sensitive=True` tool → Executor confirmation gate. No tool implements its own gate. | Executor design + review |
| S-3 | No `eval`/`exec` on any input; no shell-string command interpolation. | ruff custom rule + review |
| S-4 | File operations stay inside user-scoped folders (Desktop/Documents/Downloads/Pictures + `%APPDATA%\NOVA`). | `ToolContext` path helpers + tests |
| S-5 | No audio capture without a visible indicator; no network calls except LLM/STT/weather APIs; no telemetry. | review + integration tests |
| S-6 | Secrets: env/.env only; never in settings.json, logs, fixtures, or git. | `.gitignore`, log scrubber, fixture-scrub script |
| S-7 | Child-facing output: strictest provider safety settings; system-prompt tone rules; no dark patterns in UI. | provider adapters + copy review |
| S-8 | Pipeline events reflect reality — no simulated stages. | integration event-order suite (Phase 13 §3) |

## Process rules

| # | Rule |
|---|---|
| P-1 | Spec before code: new tools/features get their doc section first (same PR acceptable). |
| P-2 | Docs sync in the same PR as behavior changes (PR checklist item). |
| P-3 | Contract changes (Phase 11 types, wire formats, persisted schemas) = version bump + migration + golden-test update — never silent edits. |
| P-4 | All work flows through the quality gates: ruff, mypy (core/agent), import-linter, pytest. Red = not done. |
| P-5 | Scope guard: a feature must serve a persona (P-1…P-4) and a pillar (Vision §5). "It would be cool" is not a pillar (NG-1, R-9). |
| P-6 | Dependency additions require a TD entry in [docs/04](../04-technology-decisions.md) (decision + rejected alternatives). |
| P-7 | ⚠️-marked facts (model IDs, package viability) are verified at first implementation contact; findings update the doc. |
| P-8 | Milestone DoD (Phase 12 §1) includes demoability, green CI, and synced docs — all three. |
