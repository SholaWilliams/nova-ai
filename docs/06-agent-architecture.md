# NOVA — Agent Architecture

| | |
|---|---|
| **Document** | Phase 6 — Agent Architecture |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | Phase 3 (§9 agent flow, A-1…A-6), Phase 4 (TD-4, TD-10) |
| **Feeds into** | Phase 7 (tools), Phase 10 (providers), Phase 11 (contracts) |

---

## 1. Overview

The agent is a **bounded reason–act loop** living in `nova/agent/`, running on the AgentWorker thread. It is deliberately small: four collaborating classes (`Planner`, `Router`, `Executor`, `ConversationState`) orchestrated by `Agent.handle(user_input) → AssistantReply`. Everything pluggable (provider, tools, memory) arrives via constructor injection from `app.py` (D-6).

```
handle(UserInput):
  context  = Planner.build(input, memory, state)          # THINKING started
  for i in 1..MAX_ITERATIONS(5):                          # FR-17
      resp   = ProviderManager.generate(context, tools)    # provider call
      route  = Router.route(resp)                          # decision parse
      if route is DirectAnswer:  break                     # → compose reply
      emit SELECTING_TOOL(tool, detail)                     # FR-37
      result = Executor.execute(route.tool_calls)           # validate·confirm·run
      context.append(tool results); emit OBSERVING
  reply = compose(resp.text)                                # RESPONDING
  MemoryService.persist(turn); emit REMEMBERING (if wrote)
  return AssistantReply
```

## 2. Component Responsibilities

### 2.1 Planner (`planner.py`)
Assembles the provider-ready message list:
1. **System prompt** (§3) — identity, rules, tone, tool guidance.
2. **Memory context** — `MemoryService.getContext(input)`: preferences + top-k facts + recent turns (Phase 9 §5).
3. **Trimmed history** — from `ConversationState` (§5).
4. **User input.**

Also owns **thinking-summary extraction** (FR-18): providers can return prose *alongside* tool calls; the Planner takes the first sentence of that prose as the child-readable summary. If the model returned none, it synthesizes one from the tool spec: *"I'll use the {tool.title} to {tool.short_action}."* Honest either way — it describes the actual chosen action (NG-9).

### 2.2 Router (`router.py`)
Classifies each normalized `LLMResponse`:

| Response shape | Route |
|---|---|
| text only | `DirectAnswer(text)` |
| ≥1 tool call, args parse OK | `ToolRoute(calls)` |
| tool call, malformed/unknown | `RepairRoute` — one corrective round-trip (§6), then error |

Router validates *structure* (name exists in registry, args are a JSON object); *semantic* validation is Executor's job (FR-16).

### 2.3 Executor (`executor.py`)
Per `ToolCall`: registry lookup → Pydantic-validate args against the tool's schema → **sensitive gate** (emit `AWAITING_CONFIRMATION`, block on UI signal with a 120 s decision timeout → `ToolDenied` on timeout/No) → run `tool.execute(args, ctx)` under a 15 s watchdog (FR-49) → normalize any outcome (value, `ToolError`, timeout, denial) into a `ToolResult`. Emits `EXECUTING` with the tool's human `detail` string. Multiple calls in one response execute **sequentially** in order (deterministic, teachable).

### 2.4 ConversationState (`state.py`)
Holds the current session's turns as normalized `ChatMessage`s; enforces the iteration cap; trims context (§5); exposes `snapshot()` for the Planner. Not persistent — persistence is MemoryService's job (Phase 9).

## 3. Prompt Strategy

One system prompt, versioned in `agent/prompts/system.md` (reviewable in git, referenced by PROMPT_LIBRARY.md — Phase 19). Structure:

```
## Identity
You are NOVA, a friendly AI assistant living on a Windows 11 computer,
often talking with children. You are a computer program and say so if asked.

## How you work  (mirrors the real pipeline — the prompt teaches the model
its own architecture so its explanations match the UI)
You cannot do anything on the computer yourself. To act, you must choose
one of your tools. The computer runs the tool and tells you what happened.

## Rules
1. Prefer a tool whenever one matches the request; answer directly otherwise.
2. Before calling a tool, state in ONE short sentence what you're about to do
   and why — simple words a 9-year-old understands.        ← feeds FR-18
3. Never invent tool results. If a tool failed, say so simply and kindly.
4. Keep spoken answers to 1–3 sentences. Warm, playful, never sarcastic.
5. Safety: kid-appropriate language always; refuse adult/violent/scary
   content gently; never ask for personal information beyond first name.
6. When the user asks you to remember something, use the memory tool —
   do not just say you will.

## Response style
{examples: 3 few-shot pairs — tool case, direct case, error case}
```

**Token budget** per request (guards R-3): system ≈ 450 · tools schemas ≈ 700 · memory ≈ 300 · history ≈ 1200 · input ≈ 100 → ~2.8 k in, replies capped at 300 out (`max_tokens`). Well inside free tiers.

## 4. Message Normalization

Internal canonical form (Phase 11 fixes the exact types):

```python
ChatMessage(role: system|user|assistant|tool,
            content: str | None,
            tool_calls: list[ToolCall] | None,   # assistant only
            tool_call_id: str | None)             # tool role only
```

Provider adapters translate to/from native formats (Gemini `contents`/`functionCall`, Groq OpenAI-style) — the agent never sees provider dialects (A-4, Phase 10 §4).

## 5. Context Window Management

- Keep the **last 12 turns** verbatim (turn = user+assistant pair incl. tool exchanges).
- Older turns drop off; long-term facts live in memory, not history — "remember" survives trimming because it was *stored*, which is itself the lesson (EO-5).
- Tool results > 1 kB are summarized to their salient fields before appending (e.g., file search: first 10 hits + count).
- Post-1.0: rolling summary of dropped turns (noted in Phase 9 futures).

## 6. Error Recovery Matrix

| Failure | Recovery | User sees |
|---|---|---|
| Provider transient (timeout, 5xx, rate limit) | 1 retry same provider → fallback provider (Phase 10 §6) | status bar "Groq (fallback)" (warning tint) |
| Both providers down | abort loop | ERROR stage + "I can't reach my brain right now — is the internet on?" |
| Prompt hard-blocked (`SafetyBlocked` raised — no candidate generated at all) | short-circuit straight to a gentle refusal, bypassing `Router` entirely; never retried, never falls back (Phase 10 §3.2: the block is a correct outcome, not an outage) | gentle refusal, no ERROR stage |
| Response soft-filtered (`LLMResponse(finish_reason="safety")` — a candidate did come back, but got filtered) | same gentle-refusal reply as the hard-block case | gentle refusal, no ERROR stage |
| Malformed tool call | `RepairRoute`: one round-trip appending a corrective tool-error message ("unknown tool X / invalid args: {errors}. Choose from: …") | brief extra "Thinking…" |
| Repair also fails | give up on tools this turn | LLM asked to answer directly + apologize |
| Tool error / timeout | result fed back to LLM (rule 3: report honestly) | honest kid-friendly explanation + failed EXECUTING chip |
| User denies confirmation | `ToolResult(denied)` fed back | polite acknowledgment ("Okay, I won't touch anything!") |
| Iteration cap hit | stop, apologize | ERROR stage + "That got too complicated for me — try asking a simpler way?" |

Every row ends in a conversational reply (A-6) — errors are teachable moments (EO-7).

**M3 note (supersedes the M2 note):** with real tools registered, `RepairRoute` covers unknown tool names, while *invalid arguments* are handled one level down — the Executor returns a `ToolResult(status="error", error_code="invalid_args")` whose flattened Pydantic error list is fed back to the LLM as the corrective message. Both drive the same "one more iteration" recovery.

## 7. Concurrency & Cancellation

`Agent.handle` is synchronous within AgentWorker; one request at a time (Phase 3 §5). A `cancel_requested` flag is checked between loop steps (provider call boundaries and before each tool) — pressing Esc/new-input mid-run cancels at the next boundary; in-flight HTTP is abandoned (SDK timeout bounds the wait).

## 8. Testability

The agent is fully testable without network or Qt: inject `FakeProvider` (scripted `LLMResponse` sequences), in-memory registry with stub tools, memory fake, and a recording EventBus. Phase 13 builds its integration suite exactly this way — the event recording asserts the *pipeline order*, which is also asserting the UI truthfulness (A-2).

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 6 review. |
| 1.1.0 | 2026-07-09 | M2: §6 error matrix gains explicit hard-block (`SafetyBlocked`) vs soft-filter (`finish_reason="safety"`) rows, both resolving to the same gentle-refusal reply; noted the M2-only collapse of "repair also fails" into "iteration cap hit" while the tool registry is always empty. |

**Exit check:** loop bounded and cancellable; every LLM output shape has a defined route; every failure row lands conversationally; prompt encodes the educational rules (FR-18, NFR-7).
