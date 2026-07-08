# AGENTS.md — Briefing for AI Coding Agents

You are working on **NOVA**: an educational Windows 11 desktop AI assistant (Python + PySide6 + cloud LLMs) that visualizes every stage of its agent pipeline for children. It is documentation-first: **every subsystem has an approved spec — read it before coding.**

## Read in this order

1. This file, then [docs/ai/MEMORY.md](docs/ai/MEMORY.md) — current state & decisions log.
2. The phase doc for your subsystem: [docs/00-documentation-map.md](docs/00-documentation-map.md) is the index (architecture = 03, agent = 06, tools = 07, speech = 08, memory = 09, providers = 10, contracts = 11, UI = 05).
3. [docs/ai/ARCHITECTURE_RULES.md](docs/ai/ARCHITECTURE_RULES.md) + [docs/ai/CODING_STANDARDS.md](docs/ai/CODING_STANDARDS.md) + [docs/ai/PROJECT_RULES.md](docs/ai/PROJECT_RULES.md).

## The five rules you will be tempted to break

1. **The LLM never touches Windows.** Provider output → Router → schema validation → Executor → Tool. Never shortcut this chain, even "temporarily".
2. **UI imports `core` only.** The UI learns everything from `PipelineEvent`s. If a widget needs data, the answer is an event or view model — never importing a service.
3. **Pipeline events are never faked.** Emit events only from code that is actually doing the thing. No cosmetic/simulated stages — the honesty of the visualization is the product.
4. **No deletion code paths.** Tools move/create/read; nothing deletes user files. Sensitive tools go through the Executor confirmation gate (set `sensitive=True` — never build your own gate).
5. **Spec before code.** New tool/feature without a doc section → write the doc section first (same PR is fine).

## Verify your work

```powershell
ruff check . ; ruff format --check . ; mypy src/nova/core src/nova/agent ; lint-imports ; pytest
```

All green = mergeable. `pytest -m live` needs real keys — never required, never in CI. UI work: run `python -m nova` and use the debug pipeline emitter rather than burning API calls.

## Conventions in 30 seconds

Conventional Commits · branches `feat|fix|docs/<area>-<short>` · frozen dataclasses across threads · Pydantic at every external boundary · child-facing strings follow [docs/05 §9](docs/05-ui-ux-specification.md) (never "API"/"executing" in child copy) · secrets only via env/.env (never logged, never committed) · docs synced in the same PR as behavior changes.

## When you finish significant work

Append to [docs/ai/MEMORY.md](docs/ai/MEMORY.md): what changed, decisions made (with *why*), gotchas discovered. Keep it under 300 lines by pruning superseded entries.
