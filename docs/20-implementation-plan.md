# NOVA — Implementation Plan

| | |
|---|---|
| **Document** | Phase 20 — Implementation Planning |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | All Build Track phases (1–14, 17, 19) |
| **Gate** | Implementation starts only after this document is approved |

---

## 1. Implementation Order

The build follows Phase 12's milestones; within them, this is the strict start order (each row unblocks the next):

| Step | Work | Why this order |
|---|---|---|
| 1 | `git init` + first commit of docs + T-101 bootstrap (pyproject, gates, CI) | Everything after this is PR-driven with green gates |
| 2 | `core` package complete (T-102…T-105) | Every other package imports it; contracts frozen early |
| 3 | UI shell + theme + PulseRing + stage rail on the debug emitter (T-106…T-110) | Visual heartbeat early: motivation + UI iterates without API costs |
| 4 | Providers + agent loop, typed chat E2E (M2) | First real "it talks" moment; fallback proven before tools complicate things |
| 5 | Registry/Executor, then tools **in risk order**: calculator → browser → weather → file_search → app_launcher → memory_tool (stub) → desktop_organizer last (needs confirmation UI hardened) | Cheap wins first; the sensitive tool lands on a mature gate |
| 6 | Speech in, then speech out (M4) | Voice completes SC-1 |
| 7 | Memory system + views + polish (M5), then ship (M6) | Persistence lands when the loop it records is stable |

## 2. Git Strategy

- **Model:** trunk-based-lite. `main` is always green and releasable; short-lived branches (≤ 1 week of work) merge via PR. No develop branch, no gitflow — solo-dev overhead without benefit.
- **Branch naming:** `feat/<area>-<short>` · `fix/<area>-<short>` · `docs/<short>` · `chore/<short>` · `release/vX.Y.Z`. Area = package (`tools`, `agent`, `ui`, `speech`, `memory`, `providers`, `core`, `build`).
- **Planned feature branches (first waves):** `feat/core-events`, `feat/core-config`, `feat/ui-shell`, `feat/ui-pulse-ring`, `feat/providers-gemini`, `feat/providers-groq`, `feat/agent-loop`, `feat/tools-registry`, one `feat/tools-<name>` per tool, `feat/speech-stt`, `feat/speech-tts`, `feat/memory-service`, `feat/ui-memory-view`, `feat/build-pyinstaller`.
- **Merges:** squash-merge; PR title becomes the commit (must be Conventional). Even solo: self-review the diff in the PR UI against the checklist — the discipline catches real bugs.
- **Protection on `main`:** require CI green; no force-push; no direct pushes (except the initial bootstrap commits).

## 3. Commit Strategy

- **Conventional Commits** (`feat|fix|docs|test|refactor|chore|perf(scope): summary`); imperative, ≤ 72 chars; body = why, not what.
- Working commits on branches can be messy; the **squash title** is what must be clean — it feeds the changelog.
- One logical change per PR; a PR that needs "and" in its title is two PRs.

## 4. Release Strategy

Per Phase 14 §4: SemVer, milestone-driven tags, `release/vX.Y.Z` branch → version bump + CHANGELOG PR → tag → CI artifact → clean-VM smoke → GitHub Release. `v0.x` during M1–M5 (`v0.1.0` = M1 demo, `v0.2.0` = M2, …), `v1.0.0` at M6. Post-1.0 fixes: `v1.0.x` from `main` (cherry-pick model only if a hotfix must skip in-flight work).

## 5. PR Gates (mechanical)

CI (Phase 13 §7): ruff → mypy(core,agent) → import-linter → pytest+coverage. Human/agent checklist (template §7): spec/doc synced · tests included · child-facing copy follows Phase 5 §9 · no new deps without TD entry · safety invariants untouched (S-1…S-8).

## 6. Issue & PR Templates

Live templates created at `.github/` (this phase's deliverables):

- [`bug_report.md`](../.github/ISSUE_TEMPLATE/bug_report.md) — repro, expected/actual, log excerpt, environment.
- [`feature_request.md`](../.github/ISSUE_TEMPLATE/feature_request.md) — persona + pillar justification (enforces P-5 scope guard).
- [`tool_proposal.md`](../.github/ISSUE_TEMPLATE/tool_proposal.md) — pre-filled Phase 7 spec template (spec-before-code as a form).
- [`pull_request_template.md`](../.github/pull_request_template.md) — the gate checklist.

Milestone tasks (T-xxx) are seeded as issues labeled `milestone:M1…M6`, `area:<pkg>`, `type:task` at step 1.

## 7. Definition of "Implementation May Begin"

- [ ] This document approved by the owner
- [ ] Repo is a git repository with docs committed as the initial history
- [ ] GitHub repo created; branch protection + labels + templates active
- [ ] T-101 merged: gates runnable locally and in CI
- [ ] ⚠️ verification items assigned to their tasks (tracked in [docs/ai/MEMORY.md](ai/MEMORY.md))

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 20 review. |

**Exit check:** a contributor could start T-101 tomorrow with zero open process questions.
