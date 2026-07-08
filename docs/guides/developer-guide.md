# NOVA — Developer Guide

Orientation for anyone (human or AI agent) writing NOVA code. Read time: ~10 minutes.

## 1. The system in five sentences

The **UI** (PySide6, main thread) renders pipeline events and captures input — it never computes results. The **agent** (worker thread) loops: build context → call a cloud **provider** → route the decision → validate & execute a **tool** → feed the result back, max 5 iterations. **Tools** are the only code that touches Windows; the LLM only ever *chooses* them. **Memory** persists facts/preferences/conversations as inspectable JSON. Every stage emits a **PipelineEvent** on one bus consumed by both the UI and the logs — so the visualization is provably honest.

Full design: [architecture](../03-system-architecture.md) · [agent](../06-agent-architecture.md) · [contracts](../11-api-contracts.md).

## 2. Repo tour

| Path | What lives there | Rules |
|---|---|---|
| `src/nova/core/` | models, events, config, errors, logging | imports nothing from `nova.*` |
| `src/nova/providers/` | Gemini/Groq adapters + manager | never import tools/agent/ui |
| `src/nova/tools/` | the seven tools + registry | never import agent/providers/ui |
| `src/nova/agent/` | planner, router, executor, state | imports ABCs only, never ui |
| `src/nova/speech/` | STT/TTS engines, VAD, audio | imports core only |
| `src/nova/memory/` | stores + retrieval | imports core only |
| `src/nova/ui/` | views, widgets, theme | imports **core only** — learns everything from events |
| `src/nova/app.py` | composition root | the only module that imports everything |

`lint-imports` enforces this; if your change fights the import rules, the design is wrong — ask before working around it.

## 3. Dev workflow

Setup: see [CONTRIBUTING](../../CONTRIBUTING.md). Daily loop:

```powershell
python -m nova                # run (NOVA_LOG_LEVEL=DEBUG for verbose)
pytest tests/unit -x          # fast feedback
pytest                        # full suite (no network needed)
pytest -m live                # real-API tests — your keys, your call
```

Debug affordances: `--self-check` (headless wiring check), the debug pipeline emitter (M1) for UI work without burning API calls, `FreezeDetector` logs any main-thread stall > 100 ms.

## 4. Tutorial: add a Tool in under an hour

Worked example — a `joke` tool (see [tool spec template](../07-tool-specifications.md) §1, checklist §10):

1. **Spec (10 min):** add a section to `docs/07-tool-specifications.md`: purpose, params, outputs, errors, `sensitive: false`, icon, detail template.
2. **Params model (5 min):** in `src/nova/tools/joke.py`, a Pydantic model (`category: Literal["animals","space","silly"] = "silly"`) with field descriptions — the LLM reads them.
3. **Tool class (15 min):** subclass `Tool`; `spec = ToolSpec(name="joke", title="Joke Teller", description="Tell a kid-friendly joke. Use when the user asks for a joke or to be cheered up.", …, detail_template="Finding a {category} joke")`; `execute()` returns `ToolOutput(data={"joke": …, "summary": …})`.
4. **Tests (15 min):** happy path per category, empty-category fallback; run `pytest tests/unit/tools/test_joke.py`.
5. **Register (5 min):** one line in `app.py`; drop `joke.svg` (Lucide `laugh`) into `assets/icons/`.
6. Run the app, type "tell me a joke", and watch your tool light up in the pipeline.

If any step required touching `agent/`, `ui/`, or `providers/` — stop; that's an architecture bug (SC-9).

## 5. Where things go wrong (read before your first PR)

- **Qt threading:** widgets only on the main thread; cross-thread = signals with frozen dataclasses. Never call a service directly from a widget.
- **Never `eval`**, never shell-string interpolation, never paths outside user scopes — see [PROJECT_RULES](../ai/PROJECT_RULES.md) safety invariants.
- **Child-facing strings** live in the places Phase 5 §9 defines — don't scatter copy.
- **New settings** go through the Pydantic schema ([contracts §5](../11-api-contracts.md)) with a default — never raw dict access.
