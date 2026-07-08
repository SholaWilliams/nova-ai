# Contributing to NOVA

Thanks for helping build a friendlier way to teach AI. This guide covers setup, workflow, and the rules that keep NOVA teachable.

## Ground rules

1. **Read the vision first:** [docs/01-project-vision.md](docs/01-project-vision.md). Features must serve a product pillar; NOVA is not a general chatbot (NG-1).
2. **Architecture is enforced:** import contracts (D-1…D-7) fail CI if violated. Read [docs/03-system-architecture.md](docs/03-system-architecture.md) §6 and [docs/ai/ARCHITECTURE_RULES.md](docs/ai/ARCHITECTURE_RULES.md).
3. **Docs sync in the same PR** as behavior changes ([docs/17-documentation-suite.md](docs/17-documentation-suite.md)).
4. **Child-facing copy** follows [docs/05-ui-ux-specification.md](docs/05-ui-ux-specification.md) §9.
5. Safety invariants are non-negotiable: no destructive actions without confirmation, no deletion code paths, no covert listening, no telemetry.

## Development setup

```powershell
git clone https://github.com/<org>/nova-ai && cd nova-ai
uv venv && uv sync          # or: python -m venv .venv; pip install -e .[dev]
copy .env.example .env      # add your Gemini + Groq keys
python -m nova              # run the app
```

Quality gates (all must pass locally before a PR):

```powershell
ruff check . ; ruff format --check .
mypy src/nova/core src/nova/agent
lint-imports
pytest
```

## Workflow

- Branch from `main`: `feat/<area>-<short>`, `fix/…`, `docs/…` ([branching strategy](docs/20-implementation-plan.md)).
- Conventional Commits (`feat(tools): add joke tool`).
- Open a PR using the template; link the issue; all CI checks green; docs synced.
- Live-API tests (`-m live`) are never required for PRs and never run in CI.

## Adding a Tool (the best first contribution)

Follow the tutorial in the [developer guide](docs/guides/developer-guide.md) and the authoring checklist in [docs/07-tool-specifications.md](docs/07-tool-specifications.md) §10. Summary: write the spec (PR #1, doc-only) → implement `Tool` subclass + tests → register in `app.py` → icon + child-friendly `detail_template`. Target: under an hour.

## Reporting bugs / proposing features

Use the issue templates. For features, state which persona (P-1…P-4) and pillar (P-1…P-5) it serves — proposals that serve neither will be declined kindly.

## Code style

Single source: [docs/ai/CODING_STANDARDS.md](docs/ai/CODING_STANDARDS.md) — it applies to humans and AI coding agents alike.
