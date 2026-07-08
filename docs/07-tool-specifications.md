# NOVA — Tool Specifications

| | |
|---|---|
| **Document** | Phase 7 — Tool Specifications |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | Phase 3 (§13 tool flow), Phase 6 (Executor), Phase 4 (TD-8, TD-9) |
| **Feeds into** | Phase 11 (schemas), Phase 12 (per-tool tasks), Phase 13 (tool tests) |

---

## 1. The Tool Contract

Every tool subclasses `Tool` (`tools/base.py`) and provides a `ToolSpec`:

| Field | Purpose |
|-------|---------|
| `name` | snake_case unique ID used in tool calls (`"calculator"`) |
| `title` | Human name shown in pipeline ("Calculator") |
| `description` | **Written for the LLM** — when to pick this tool, with 1–2 example phrasings |
| `parameters` | Pydantic model → JSON Schema (FR-16, TD-10) |
| `sensitive` | `True` ⇒ Executor confirmation gate (FR-20) |
| `icon` | Lucide name (Phase 5 §5) |
| `detail_template` | Child-readable EXECUTING string, e.g. `"Opening {app} on your PC"` (FR-37) |

`execute(args: ParamsModel, ctx: ToolContext) → ToolResult` — synchronous, ≤ 15 s (FR-49), never raises to caller (Executor normalizes). `ToolContext` carries `settings` and, only where declared, narrow service interfaces (memory for the Memory Tool). Tools never import agent/providers/ui (D-3).

**Design rules:** read-only wherever possible; *move, never delete*; user-scoped paths only (NFR-6); every output includes a `summary` string the LLM can speak directly.

---

## 2. calculator

| | |
|---|---|
| **Purpose** | Arithmetic & basic math so children see "AI asked the calculator" (EO-3) |
| **Sensitive** | No |
| **Inputs** | `expression: str` — math expression, e.g. `"12 * 9"`, `"sqrt(144)"` |
| **Execution** | `simpleeval` (TD-9): whitelisted ops `+ - * / // % **`, funcs `sqrt round abs min max`, constants `pi e`. Hard caps: expression ≤ 200 chars, exponent ≤ 1000, result magnitude ≤ 1e100 |
| **Outputs** | `{result: number, expression_pretty: str, summary: "12 × 9 = 108"}` |
| **Errors** | `invalid_expression` (unparseable), `math_error` (div/0, domain), `too_large` |
| **Future** | Unit conversion; step-by-step explanation mode for teaching |

## 3. weather

| | |
|---|---|
| **Purpose** | Live weather via Open-Meteo (TD-8) — demonstrates a tool reaching the internet |
| **Sensitive** | No |
| **Inputs** | `city: str \| null` (null ⇒ default city from settings), `days: int 1–3 = 1` |
| **Execution** | Geocode city (Open-Meteo geocoding, first match) → forecast API (current + daily). 10 s HTTP timeout. 10-min in-memory cache per city (R-3) |
| **Outputs** | `{city, country, temp_c, condition: str, condition_emoji, high_c, low_c, days: […], summary: "It's 31° and sunny in Lagos"}` |
| **Errors** | `city_not_found`, `network_error`, `service_error` |
| **Future** | Severe-weather awareness; hourly detail; unit preference (°F) via memory |

## 4. app_launcher

| | |
|---|---|
| **Purpose** | Launch installed apps by common name — the flagship "AI caused a real action" moment (EO-4, US-7) |
| **Sensitive** | No (launching is benign & visible; **no** kill/close capability — that would be sensitive and is out of v1.0) |
| **Inputs** | `app_name: str` — e.g. `"notepad"`, `"calculator"`, `"paint"` |
| **Execution** | Resolution order: (1) curated alias map (~25 common apps → UWP/exe targets), (2) Start Menu `.lnk` index (both ProgramData & user, scanned at startup, fuzzy-matched ≥ 0.75), (3) `shutil.which`. Launch via `os.startfile`. Never a shell string — no injection surface (A-1) |
| **Outputs** | `{launched: bool, app_title: str, matched_via: alias\|startmenu\|path, summary: "Opening Notepad"}` |
| **Errors** | `app_not_found` (includes 3 closest matches so the LLM can offer them), `launch_failed` |
| **Future** | "Close X" (sensitive); focus-existing-window; recently-used ranking |

## 5. browser

| | |
|---|---|
| **Purpose** | Open websites / web searches in the default browser |
| **Sensitive** | No |
| **Inputs** | `action: "open_url" \| "search"`, `target: str` (URL or query) |
| **Execution** | stdlib `webbrowser`. URLs: scheme forced to `https`, syntactic validation; search: DuckDuckGo (`https://duckduckgo.com/?q=…&kp=1` — safe-search on, no account, kid-safer default). Domain blocklist hook (empty by default, presenter-extendable in settings file) |
| **Outputs** | `{opened: str, kind: url\|search, summary: "Searching the web for 'how do volcanoes work'"}` |
| **Errors** | `invalid_url`, `blocked_domain`, `browser_error` |
| **Future** | Tab control via browser extension; reading page summaries back (big scope — own phase if pursued) |

## 6. file_search

| | |
|---|---|
| **Purpose** | Find files by name/pattern — read-only (US-9) |
| **Sensitive** | No (read-only by construction) |
| **Inputs** | `query: str`, `file_type: str \| null` (ext or `image/doc/video` alias), `location: "documents"\|"desktop"\|"downloads"\|"pictures"\|"all" = "all"` |
| **Execution** | `pathlib.rglob` across the named user folders only (NFR-6), depth ≤ 6, case-insensitive substring + fuzzy match, hard stop at 200 entries scanned-matches or 8 s. Returns top 10 by (match score, mtime) |
| **Outputs** | `{matches: [{name, folder, size_kb, modified}], count, truncated: bool, summary: "I found 3 files named like 'dragon drawing'"}` |
| **Errors** | `no_matches` (with hint), `location_unavailable` |
| **Future** | Content search (Windows Search index); open-found-file follow-up action |

## 7. desktop_organizer

| | |
|---|---|
| **Purpose** | Tidy the Desktop into category folders — the highest-drama demo, and the reason the confirmation stage exists (US-8) |
| **Sensitive** | **Yes** — full gate: plan → preview → confirm → act (FR-20, FR-26) |
| **Inputs** | `mode: "preview" \| "organize" \| "undo"` (LLM starts with `organize`; Executor internally runs preview→confirm first) |
| **Execution** | **Plan:** scan Desktop top-level *files* (never folders, never hidden/system files, never `.lnk` shortcuts) → categorize by extension: `Pictures / Documents / Videos / Music / Archives / Other` → build move list. **Preview:** move list rendered in the confirm dialog (Phase 5 §6.6). **Act:** create category folders on Desktop, `shutil.move` each file (collision ⇒ ` (2)` suffix), write `undo_manifest.json` (timestamped, in `%APPDATA%/NOVA/`). **Undo:** replay last manifest in reverse; report any files that moved since. *Move, never delete — no destructive branch exists.* |
| **Outputs** | `{moved: int, categories: {Pictures: 4, …}, undo_available: bool, summary: "I tidied 12 files into 4 folders on your Desktop"}` |
| **Errors** | `nothing_to_do`, `denied` (user said no), `partial_failure` (per-file report; successfully moved files stay in manifest so undo still works), `no_undo_available` |
| **Future** | Custom rules ("put school stuff in School"); organize Downloads; scheduled tidy (would violate NG-4 — only ever on-request) |

## 8. memory_tool

| | |
|---|---|
| **Purpose** | Explicit store/recall of facts & preferences — makes memory a *visible tool choice* (EO-5, US-10) |
| **Sensitive** | No (writes are additive; deletion only via Memory View UI — FR-33 — deliberately *not* LLM-invocable in v1.0) |
| **Inputs** | `action: "store" \| "recall"`, `content: str \| null` (store: the fact, third person: "Favorite color is blue"), `query: str \| null` (recall) |
| **Execution** | `store` → `MemoryService.addFact(content, kind=fact\|preference)` (kind heuristic: "likes/favorite/prefers" ⇒ preference) — emits REMEMBERING. `recall` → keyword retrieval top 3 (Phase 9 §5) |
| **Outputs** | store: `{stored: true, summary: "I'll remember that!"}` · recall: `{memories: [str], summary}` |
| **Errors** | `nothing_found` (recall miss — LLM says it honestly, rule 3), `storage_error` |
| **Future** | LLM-invocable forget with confirmation gate; auto-capture suggestions ("want me to remember that?") |

---

## 9. Future Tools (registry-ready, post-1.0)

| Tool | Sketch | Sensitive |
|------|--------|-----------|
| `timer` | "Remind me in 10 minutes" — local timers with TTS announcement | No |
| `joke` | Curated kid-safe joke list — the easiest community PR (SC-9 onramp; candidate for the CONTRIBUTING tutorial) | No |
| `screenshot` | Capture screen to Pictures | No |
| `music` | Play/pause local media via media keys | No |
| `system_info` | Battery, disk space, time/date | No |
| `email_draft` | Draft (never send) an email in default client | Yes |

Each future tool gets this same spec template before implementation (PROJECT_RULES.md, Phase 19).

## 10. Tool Authoring Checklist (feeds SC-9)

1. Spec written using the §1 template (this doc gains a section).
2. Params as a Pydantic model with field descriptions (the LLM reads them).
3. `description` says *when to choose it*, with example user phrasings.
4. `detail_template` in child language (Phase 5 §9).
5. Outputs include `summary`; errors from the tool's declared error set.
6. Unit tests: happy path, each error, timeout behavior (Phase 13).
7. Register in `app.py`; icon added to `assets/icons/`.

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 7 review. |

**Exit check:** all seven v1.0 tools fully specified (purpose/inputs/outputs/errors/future); sensitivity flags agreed (only desktop_organizer gated); no tool can delete anything.
