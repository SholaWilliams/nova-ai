# NOVA — LLM Provider Architecture

| | |
|---|---|
| **Document** | Phase 10 — LLM Provider Architecture |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | Phase 4 (TD-4), Phase 6 (§4 normalization, §6 recovery) |
| **Feeds into** | Phase 11 (LLMProvider contract), Phase 12 (M2 tasks) |

---

## 1. Provider Interface

`providers/base.py` (full signatures in Phase 11):

```python
class LLMProvider(ABC):
    name: str                    # "gemini" | "groq" | …
    def generate(self, messages: list[ChatMessage],
                 tools: list[ToolSchema],
                 opts: GenerateOptions) -> LLMResponse: ...
    def health_check(self) -> ProviderHealth: ...      # key valid? reachable?
    @property
    def capabilities(self) -> ProviderCaps: ...        # tool_calling, max_context, safety_settings
```

`LLMResponse` (normalized): `text: str | None`, `tool_calls: list[ToolCall]`, `finish_reason: stop|tool_calls|length|safety|error`, `usage: {in, out}`. Adapters raise only `ProviderError` subtypes (`AuthError`, `RateLimited(retry_after)`, `Transient`, `SafetyBlocked`) — the manager and agent never see SDK exceptions (A-4, A-6).

## 2. Provider Implementations

### 2.1 Gemini (`gemini.py`)
- SDK `google-genai`; default model **`gemini-3.5-flash`** (model id in settings, not code; verified at M2/T-202 — see Phase 4 TD-4).
- Mapping: system prompt → `system_instruction`; `ChatMessage` history → `contents` (role `user`/`model`, tool results as `functionResponse` parts); `ToolSchema` → `function_declarations`.
- Safety settings pinned to the strictest available tier for all harm categories (NFR-7). Two distinct outcomes, not one: a *hard* block (no candidate generated at all) raises `SafetyBlocked`; a *soft* per-candidate filter comes back as a normal `LLMResponse(finish_reason="safety")`. Both become the same gentle refusal via the agent (Phase 6 §6) — never an error dialog.

### 2.2 Groq (`groq.py`)
- SDK `groq`; default model **`openai/gpt-oss-120b`** (verified at M2/T-203 — see Phase 4 TD-4); OpenAI-style `messages`/`tools`/`tool_calls` — near-1:1 with our internal form.
- Also hosts STT (TD-5): the *speech* layer holds its own thin Groq client — no dependency from `speech/` to `providers/` (D-2); they share only the API key via config.
- Groq's API surface has no hard-block concept equivalent to Gemini's `prompt_feedback.block_reason` — this adapter never raises `SafetyBlocked`.

### 2.3 Normalization Table

| Internal | Gemini | Groq (OpenAI-style) |
|---|---|---|
| system prompt | `system_instruction` | `messages[role=system]` |
| assistant tool call | `functionCall` part | `tool_calls[]` |
| tool result msg | `functionResponse` part | `messages[role=tool]` |
| tool schema | `function_declarations[]` | `tools[{type:function}]` |
| max_tokens | `max_output_tokens` | `max_tokens` |

Adapter unit tests assert round-trips on golden fixtures (Phase 13) — dialect drift is caught in CI, not in class.

## 3. Provider Manager (`manager.py`)

Owns: the provider registry, the **active** provider (from settings, hot-swappable — US-12), fallback execution, and status reporting to the UI (FR-43).

### 3.1 Selection strategy
- User picks the primary in Settings (default: Gemini — strongest free-tier tool calling, confirmed at M2).
- The other configured provider is automatically the fallback. With one key configured, that provider is simply primary-with-no-fallback (FR-48 is S-priority — degraded is acceptable).

### 3.2 Fallback strategy (state machine)

```
generate(request):
  try primary      ──ok──────────────→ return
    │ Transient/RateLimited: retry once (backoff 1s, honor retry_after)
    │ AuthError: skip retry (retrying a bad key is noise)
    ▼ still failing
  mark primary COOLING (60 s circuit-breaker)
  try fallback     ──ok──────────────→ return + status "Groq (fallback)" (warning tint)
    ▼ failing too
  raise ProviderError → agent's "can't reach my brain" path (Phase 6 §6)
```

- While COOLING, requests go straight to fallback; after 60 s the next request probes the primary again.
- `SafetyBlocked` never falls back (the block is the correct outcome, not an outage).
- All transitions emit log events + a status-cluster update — provider trouble is visible, never silent (A-2 spirit).

### 3.3 Budgets
`GenerateOptions` defaults: `max_tokens=300`, `temperature=0.6`, request timeout 20 s. Per-session token counter logged (R-3 monitoring); no hard cutoff in v1.0.

## 4. API Key Management

- Keys via env (`NOVA_GEMINI_API_KEY`, `NOVA_GROQ_API_KEY`) loaded from `.env` (Phase 3 §15, Phase 14); Settings writes to the user-level `.env`, never `settings.json` (NFR-8), via `core.config.write_secret_to_env()`.
- Startup (M2 implementation): `app.py` checks which providers have a key *configured* (network-free) to populate the Settings key rows and decide whether to show the missing-key banner (FR-47); zero configured providers ⇒ app opens in typed-mode-with-banner, still navigable (SC-6). A real `health_check()` network round-trip happens on-demand — via the Settings "Test" button, or automatically right after a hot-swap/new-key entry — rather than unconditionally for every configured provider on every launch, to keep startup network-free by default.

## 5. Adding a Provider (SC-10 discipline)

1. New module `providers/<name>.py` implementing `LLMProvider` (+ error mapping).
2. Golden-fixture adapter tests.
3. Constructed in `app.py` and passed into `ProviderManager`'s constructor (D-6: composition lives in `app.py`, never inside `manager.py` itself) + settings enum + `.env.example` key line.
4. No agent, tool, or UI changes — if any are needed, the abstraction failed; fix the abstraction.

**Future providers (design-verified against the interface):** OpenAI (`gpt-4o-mini`) and Anthropic (`claude-haiku`) — both OpenAI/Groq-shaped or trivially mappable; Mistral; OpenRouter (meta-provider giving many models behind one key — attractive for classrooms, evaluate post-1.0).

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 10 review. |
| 1.1.0 | 2026-07-09 | M2: default models resolved (`gemini-3.5-flash`, `openai/gpt-oss-120b`; Phase 4 TD-4); §2 clarifies the hard-block/soft-filter safety split and that Groq never raises `SafetyBlocked`; §4/§5 updated to match the actual constructor-injection pattern (`app.py` builds providers and passes them into `ProviderManager`, no static `PROVIDERS` dict) and the lighter network-free startup check M2 actually implements. |

**Exit check:** agent is 100 % dialect-free; every provider failure mode maps to a defined behavior; fallback is observable in the UI; adding provider #3 touches two files + config.
