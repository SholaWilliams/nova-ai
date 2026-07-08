# ARCHITECTURE_RULES.md — Design Rules for Code Changes

Operational form of [docs/03-system-architecture.md](../03-system-architecture.md). If this file and a phase doc disagree, the phase doc wins — then fix this file.

## Layer map & import law (CI-enforced: `lint-imports`)

```
core  ←  providers | speech | memory | tools   ←  agent | ui   ←  app.py
```

- `core` imports no `nova.*`. `ui` imports **core only**. `agent` imports core + the ABCs of providers/tools/memory. `app.py` imports everything; nothing imports `app.py`.
- Fighting these rules means the code is in the wrong place. Common correct answers: *UI needs data* → emit a PipelineEvent or extend a view model in core. *Tool needs a service* → inject via `ToolContext` in `app.py`. *Agent needs provider detail* → normalize it into `LLMResponse` in the adapter.

## "Where does my code go?" decision tree

| You are adding… | It goes in… | Register in |
|---|---|---|
| A capability the LLM can choose | `tools/<name>.py` (spec in docs/07 first) | `app.py` |
| An LLM backend | `providers/<name>.py` | `manager.py` + settings enum |
| A voice engine | `speech/stt|tts/<name>.py` | speech service config |
| A screen/panel | `ui/views/` (subscribe to EventBus) | `main_window.py` |
| A cross-layer data shape | `core/models.py` (+ docs/11 §1 update) | — |
| A pipeline stage *(rare — needs review)* | `core/events.py` + docs/03 §7.1 + Phase 5 child label + teaching impact | — |
| Everything-wiring | `app.py` only | — |

## Threading law

- Main thread: Qt only. AgentWorker: agent loop + provider calls + tool execution. SpeechIn/SpeechOut: audio.
- Cross-thread traffic: Qt signals + frozen dataclasses, queued connections. No locks in feature code (MemoryService's internal file lock is the sanctioned exception).
- One request at a time; cancellation via flag checks at loop boundaries — never thread termination.

## Event law

- Emit events only around code doing the actual work (S-8). `started` must be followed by exactly one of `completed|failed|skipped` for that stage/request.
- New `detail` strings are child-facing copy → Phase 5 §9 rules apply.

## Contract law

- `core/models.py`, wire formats, persisted schemas = contracts (docs/11). Changing one: bump version, write migration, update golden tests, amend docs/11 — in the same PR.
- Tool schemas are generated from Pydantic params models; never hand-edit a schema.

## Dependency law

- New runtime dependency → TD entry in docs/04 (with rejected alternatives) + lockfile update. Check the rejected list first: `requests`, `PyQt6`, `loguru`, `pyaudio`, local-LLM stacks were rejected deliberately.
