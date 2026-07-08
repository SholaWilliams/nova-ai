# NOVA — Documentation Map

> **Document status:** Living document — updated at the end of every phase.
> **Last updated:** 2026-07-08 (Build Track complete: Phases 1–14, 17, 19, 20 delivered; 1–3 approved)

This is the master index for all NOVA planning and engineering documentation. Every phase produces one or more repository-ready documents. No implementation code is written until all **Build Track** phases are approved (gate: [Phase 20 §7](20-implementation-plan.md)).

---

## Documentation Tracks

Per project direction (2026-07-08):

1. **Build Track (priority)** — everything required to design, document, and implement the application. ✅ **All documents delivered.**
2. **Education Track (deferred)** — teaching guide and presentation script, produced **after** the application is built (target: milestone M7).
3. **Phase 18 (Obsidian vault)** — paused indefinitely.

---

## Build Track

| # | Phase | Document(s) | Status |
|---|-------|-------------|--------|
| 1 | Project Vision | [01-project-vision.md](01-project-vision.md) | ✅ Approved |
| 2 | Product Requirements (PRD) | [02-product-requirements.md](02-product-requirements.md) | ✅ Approved |
| 3 | System Architecture | [03-system-architecture.md](03-system-architecture.md) | ✅ Approved |
| 4 | Technology Decisions | [04-technology-decisions.md](04-technology-decisions.md) | 🔍 Ready for review |
| 5 | UI/UX Design Specification | [05-ui-ux-specification.md](05-ui-ux-specification.md) | 🔍 Ready for review |
| 6 | Agent Architecture | [06-agent-architecture.md](06-agent-architecture.md) | 🔍 Ready for review |
| 7 | Tool Specifications | [07-tool-specifications.md](07-tool-specifications.md) | 🔍 Ready for review |
| 8 | Speech System | [08-speech-system.md](08-speech-system.md) | 🔍 Ready for review |
| 9 | Memory Architecture | [09-memory-architecture.md](09-memory-architecture.md) | 🔍 Ready for review |
| 10 | LLM Provider Architecture | [10-llm-provider-architecture.md](10-llm-provider-architecture.md) | 🔍 Ready for review |
| 11 | API Contracts | [11-api-contracts.md](11-api-contracts.md) | 🔍 Ready for review |
| 12 | Development Roadmap | [12-development-roadmap.md](12-development-roadmap.md) | 🔍 Ready for review |
| 13 | Testing Strategy | [13-testing-strategy.md](13-testing-strategy.md) | 🔍 Ready for review |
| 14 | Deployment Strategy | [14-deployment-strategy.md](14-deployment-strategy.md) | 🔍 Ready for review |
| 17 | Documentation Suite | [17-documentation-suite.md](17-documentation-suite.md) → [README](../README.md), [CONTRIBUTING](../CONTRIBUTING.md), [CHANGELOG](../CHANGELOG.md), [developer guide](guides/developer-guide.md), [troubleshooting](guides/troubleshooting.md) | 🔍 Ready for review |
| 19 | AI Engineering Assets | [19-ai-engineering-assets.md](19-ai-engineering-assets.md) → [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md), [PROJECT_RULES](ai/PROJECT_RULES.md), [CODING_STANDARDS](ai/CODING_STANDARDS.md), [ARCHITECTURE_RULES](ai/ARCHITECTURE_RULES.md), [PROMPT_LIBRARY](ai/PROMPT_LIBRARY.md), [MEMORY](ai/MEMORY.md) | 🔍 Ready for review |
| 20 | Implementation Planning | [20-implementation-plan.md](20-implementation-plan.md) + [.github templates](../.github/) | 🔍 Ready for review |

## Education Track (deferred — target milestone M7)

| # | Phase | Document(s) | Status |
|---|-------|-------------|--------|
| 15 | Teaching Guide | `15-teaching-guide.md` | ⏸ Deferred |
| 16 | Presentation Script | `16-presentation-script.md` | ⏸ Deferred |

## Paused

| # | Phase | Document(s) | Status |
|---|-------|-------------|--------|
| 18 | Obsidian Second Brain Vault | `18-obsidian-vault.md` | ⏸ Paused indefinitely |

---

## Reading Paths

- **"What is NOVA?"** → [README](../README.md) → [01 Vision](01-project-vision.md)
- **"How does it work?"** → [03 Architecture](03-system-architecture.md) → 06/07/08/09/10 subsystem docs → [11 Contracts](11-api-contracts.md)
- **"What do I build first?"** → [12 Roadmap](12-development-roadmap.md) → [20 Implementation Plan](20-implementation-plan.md)
- **"I'm an AI coding agent"** → [AGENTS.md](../AGENTS.md) → [docs/ai/MEMORY.md](ai/MEMORY.md)

## Review Process

1. Each phase is one or more complete markdown documents, submitted for review.
2. Outcomes: **Approve** or **Revise** (amend + re-review). Approved docs may be amended later via the revision-history table.
3. Cross-references use stable IDs (`G-x`, `SC-x`, `FR-x`, `NFR-x`, `US-x`, `R-x`, `NG-x`, `EO-x`, `A-x`, `D-x`, `TD-x`, `S-x`, `P-x`, `T-xxx`).
4. Items marked ⚠️ are verify-at-implementation facts, tracked in [docs/ai/MEMORY.md](ai/MEMORY.md).

## Document Conventions

- Metadata block (status, version, owner, dates) at the top of every document.
- Diagrams in Mermaid or ASCII — GitHub-renderable and diffable.
- Single-source rule: one owning document per topic ([17-documentation-suite.md](17-documentation-suite.md)); everything else links.
