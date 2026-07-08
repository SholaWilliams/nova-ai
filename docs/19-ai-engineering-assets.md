# NOVA — AI Engineering Assets (Phase 19)

| | |
|---|---|
| **Document** | Phase 19 — AI Engineering Assets index |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |

NOVA is built *with* AI coding agents as first-class contributors. These assets give any agent (Claude Code or otherwise) the context, rules, and guardrails to produce code that passes review on the first try.

| Asset | Location | Role |
|---|---|---|
| AGENTS.md | `/AGENTS.md` | **Canonical agent briefing** — read first, links to everything |
| CLAUDE.md | `/CLAUDE.md` | Thin Claude Code entry → AGENTS.md + Claude-specific notes |
| PROJECT_RULES.md | `docs/ai/PROJECT_RULES.md` | Process rules + non-negotiable safety invariants |
| CODING_STANDARDS.md | `docs/ai/CODING_STANDARDS.md` | Style/idiom (single source for humans too — Phase 17) |
| ARCHITECTURE_RULES.md | `docs/ai/ARCHITECTURE_RULES.md` | Machine-checkable design rules + decision tree |
| PROMPT_LIBRARY.md | `docs/ai/PROMPT_LIBRARY.md` | NOVA's own runtime prompts + reusable dev prompts |
| MEMORY.md | `docs/ai/MEMORY.md` | Durable cross-session agent memory: decisions, state, gotchas |

**Design principles:** (1) rules that matter are *also* enforced mechanically (CI) — docs tell agents *why*, linters tell them *no*; (2) one source per topic — agent docs link to phase docs, never restate them; (3) MEMORY.md is append-curated: agents update it when finishing significant work, humans prune it.

**Exit check:** an agent given only the repo can answer: what is this, what may I not do, where does X go, what's the current state, how do I verify my work.
