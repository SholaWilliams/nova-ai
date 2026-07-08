# CLAUDE.md

**Read [AGENTS.md](AGENTS.md) first** — it is the canonical agent briefing (reading order, the five unbreakable rules, verification commands). This file adds only Claude Code specifics.

## Claude Code notes

- **Shell:** Windows 11. Prefer PowerShell for scripts under `scripts/`; quality gates run identically in either shell.
- **Fast feedback:** `pytest tests/unit -x` first; the full suite needs no network or keys. Never run `pytest -m live` or `-m record` unless the user explicitly asks (they hit real APIs with the user's keys).
- **Plan mode:** for anything touching `agent/`, `providers/`, or a persisted file format (`settings.json`, `facts.json`, session JSONL), plan first — these carry contracts ([docs/11](docs/11-api-contracts.md)) with golden tests; changing them means versioning + migration, not editing in place.
- **Don't** add dependencies without checking [docs/04-technology-decisions.md](docs/04-technology-decisions.md) — most "missing" libraries were explicitly rejected with reasons.
- **Do** update [docs/ai/MEMORY.md](docs/ai/MEMORY.md) at the end of significant sessions (append-curated, prune superseded entries).
- Items marked ⚠️ in phase docs are verify-at-implementation facts (model IDs, package viability) — check them before relying on them; update the doc with findings.
