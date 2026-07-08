# NOVA — Documentation Suite (Phase 17)

| | |
|---|---|
| **Document** | Phase 17 — Documentation Structure |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |

## Structure & Single-Source Rules

Every topic has exactly **one** owning document; everything else links. This prevents doc drift — the #1 killer of repo documentation.

| Doc | Location | Owns | Created |
|---|---|---|---|
| README | `/README.md` | First contact: what/why/quickstart/screenshot | ✅ this phase |
| Contributing | `/CONTRIBUTING.md` | How to set up, test, propose changes, add tools | ✅ this phase |
| Changelog | `/CHANGELOG.md` | Release history (Keep a Changelog) | ✅ this phase (stub) |
| Architecture | [docs/03-system-architecture.md](03-system-architecture.md) + Phases 6–11 | System design (Phase docs ARE the architecture docs) | Phase 3 |
| Roadmap | [docs/12-development-roadmap.md](12-development-roadmap.md) | Milestones/tasks | Phase 12 |
| Code style | [docs/ai/CODING_STANDARDS.md](ai/CODING_STANDARDS.md) | Style for humans AND AI agents (single source — Phase 19) | Phase 19 |
| Developer guide | [docs/guides/developer-guide.md](guides/developer-guide.md) | Orientation tour, dev workflow, add-a-tool tutorial | ✅ this phase |
| API documentation | [docs/11-api-contracts.md](11-api-contracts.md) + docstrings | Internal contracts; generated reference via `pdoc` from M2 (`scripts/gen_api_docs.ps1`, output `docs/api/` — git-ignored, published with releases) | Phase 11 |
| Troubleshooting | [docs/guides/troubleshooting.md](guides/troubleshooting.md) | User + developer FAQ/fixes | ✅ this phase |
| AI agent assets | `/CLAUDE.md`, `/AGENTS.md`, `docs/ai/*` | Rules for AI coding agents | Phase 19 |

**Sync rule (enforced in PR template, Phase 20):** a PR that changes behavior must update the owning doc in the same PR — "docs synced" is a merge checkbox, and milestone DoD includes it (Phase 12 §5).

**Exit check:** no topic has two owners; every audience (user, presenter, contributor, AI agent) has an entry point one click from README.
