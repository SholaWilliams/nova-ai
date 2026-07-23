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
    name: str                    # "omniroute" (sole backend, M9)
    def generate(self, messages: list[ChatMessage],
                 tools: list[ToolSchema],
                 opts: GenerateOptions) -> LLMResponse: ...
    def health_check(self) -> ProviderHealth: ...      # key valid? reachable?
    @property
    def capabilities(self) -> ProviderCaps: ...        # tool_calling, max_context, safety_settings
```

`LLMResponse` (normalized): `text: str | None`, `tool_calls: list[ToolCall]`, `finish_reason: stop|tool_calls|length|safety|error`, `usage: {in, out}`. Adapters raise only `ProviderError` subtypes (`AuthError`, `RateLimited(retry_after)`, `Transient`, `SafetyBlocked`) — the manager and agent never see SDK exceptions (A-4, A-6).

## 2. Provider Implementation

### 2.1 OmniRoute (`omniroute.py`) — sole backend, revised M9

- Plain `httpx` (TD-11: owned HTTP calls), not a vendor SDK — [OmniRoute](https://github.com/diegosouzapw/OmniRoute)
  is a locally-run AI gateway the owner runs separately, exposing an OpenAI-Chat-Completions-
  compatible REST endpoint (`http://127.0.0.1:20128/v1`) across 278+ upstream providers with
  its own routing/circuit-breaking/quota-lending. Request/response mapping reuses
  `_openai_compat.py`, the exact adapter shape `OpenRouterProvider` established at M8 — same
  dialect, this module is close to a rename-and-repoint of that one.
- Default model **`auto/chat`** — verified against a live local OmniRoute instance's
  `GET /v1/models` (2026-07-23): every `auto/*` combo, including `auto/chat`, reports
  `tool_calling: true` (see Phase 4 TD-4). Settings exposes an editable model field, same
  pattern OpenRouter used — changing it rebuilds the live `OmniRouteProvider` instance via
  `ProviderManager.set_provider()`.
- No hard-safety-block concept documented in OmniRoute's API surface (like OpenRouter/Groq,
  unlike Gemini) — this adapter never raises `SafetyBlocked`.
- The OpenRouter-specific `provider.quantizations` free-tier mitigation (M8) does **not**
  carry over — that was steering around OpenRouter's own backend load-balancing, a concern
  specific to that gateway. The provider-agnostic degenerate-output detect-and-retry-once in
  `agent.py` (`_looks_degenerate()`) is kept as a general safeguard, since OmniRoute's own
  278-provider routing could in principle land on a similarly degenerate backend.
- **No cloud fallback** (owner decision, M9): if the local OmniRoute process is down, Nova has
  no LLM access — typed-mode-with-banner (FR-47's existing zero-configured-providers path),
  not a second cloud adapter. Accepted because this is a local dev/classroom app the owner
  controls directly, not a hosted service with independent uptime requirements.

### 2.2 Normalization Table

| Internal | OmniRoute (OpenAI-style) |
|---|---|
| system prompt | `messages[role=system]` |
| assistant tool call | `tool_calls[]` |
| tool result msg | `messages[role=tool]` |
| tool schema | `tools[{type:function}]` |
| max_tokens | `max_tokens` |

Adapter unit tests assert round-trips on golden fixtures (Phase 13) — dialect drift is caught in CI, not in class.

## 3. Provider Manager (`manager.py`) — simplified M9

Owns: the single configured `OmniRouteProvider` instance, retry-once-on-transient-failure,
and status reporting to the UI (FR-43). The multi-provider primary/fallback/cooldown state
machine (§3.1/§3.2 below, M2–M8) is **removed**, not merely unused — with exactly one provider
there is nothing left to fall back to or hot-swap between; keeping dead branches for providers
that no longer exist was rejected as speculative flexibility (see Phase 4 TD-4's "Rejected"
line).

### 3.1 Retry strategy

```
generate(request):
  try provider     ──ok──────────────→ return, status "normal"
    │ Transient/RateLimited: retry once (backoff 1s, honor retry_after)
    │ AuthError: skip retry (retrying a bad key is noise)
    ▼ still failing
  raise ProviderError → agent's "can't reach my brain" path (Phase 6 §6), status "down"
```

- No cooldown/circuit-breaker state on Nova's side — OmniRoute's own gateway already does
  per-model health scoring and circuit-breaking upstream of this call; duplicating that logic
  here for a single local endpoint would be redundant.
- `SafetyBlocked` never retries (the block is the correct outcome, not an outage).
- All transitions emit log events + a status-cluster update — provider trouble is visible, never silent (A-2 spirit).

### 3.2 Budgets
`GenerateOptions` defaults: `max_tokens=300`, `temperature=0.6`, request timeout 20 s. Per-session token counter logged (R-3 monitoring); no hard cutoff in v1.0.

## 4. API Key Management

- One key via env (`NOVA_OMNIROUTE_API_KEY`, from the owner's OmniRoute dashboard →
  Endpoints), loaded from `.env` (Phase 3 §15, Phase 14); Settings writes to the user-level
  `.env`, never `settings.json` (NFR-8), via `core.config.write_secret_to_env()`. `NOVA_GROQ_API_KEY`
  remains, unrelated to this section now — it only serves STT (TD-5).
- Startup: `app.py` checks whether the OmniRoute key is *configured* (network-free) to decide
  whether to show the missing-key banner (FR-47); no key ⇒ app opens in typed-mode-with-banner,
  still navigable (SC-6). A real `health_check()` network round-trip happens on-demand — via
  the Settings "Test" button, or automatically right after a hot-swap/new-key entry — rather
  than unconditionally on every launch, to keep startup network-free by default.

## 5. Adding a Provider (SC-10 discipline)

1. New module `providers/<name>.py` implementing `LLMProvider` (+ error mapping).
2. Golden-fixture adapter tests.
3. Constructed in `app.py` and passed into `ProviderManager`'s constructor (D-6: composition lives in `app.py`, never inside `manager.py` itself) + settings field + `.env.example` key line.
4. No agent, tool, or UI changes — if any are needed, the abstraction failed; fix the abstraction.

M9 collapsed three providers down to one (OmniRoute) rather than adding a fourth — this section's discipline still applies if a second backend is ever reintroduced (e.g. a cloud fallback for OmniRoute-down scenarios), at which point §3's single-provider simplification would need revisiting too.

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 10 review. |
| 1.1.0 | 2026-07-09 | M2: default models resolved (`gemini-3.5-flash`, `openai/gpt-oss-120b`; Phase 4 TD-4); §2 clarifies the hard-block/soft-filter safety split and that Groq never raises `SafetyBlocked`; §4/§5 updated to match the actual constructor-injection pattern (`app.py` builds providers and passes them into `ProviderManager`, no static `PROVIDERS` dict) and the lighter network-free startup check M2 actually implements. |
| 1.2.0 | 2026-07-23 | M8: §2.3 OpenRouter section added (was previously undocumented despite the code citing it); §5 moves OpenRouter from "future" to shipped; documents the free-tier quantization-routing pin and the provider-agnostic degenerate-output retry in `agent.py`. |
| 1.3.0 | 2026-07-23 | M9 (Stream B), owner direction: Gemini/Groq(-chat)/OpenRouter superseded by OmniRoute as the sole LLM backend (§2.1 rewritten); §3 ProviderManager simplified to single-provider retry-only (fallback/cooldown state machine removed, not just unused); §4 API key management collapsed to one key. Default model `auto/coding` flagged ⚠️ unverified. |
| 1.4.0 | 2026-07-23 | M9 follow-up: default model verified against a live OmniRoute instance and swapped `auto/coding` → `auto/chat` (§2.1) — better fit for a general assistant, no longer a placeholder. |

**Exit check:** agent is 100 % dialect-free; every provider failure mode maps to a defined behavior; fallback is observable in the UI; adding provider #3 touches two files + config.
