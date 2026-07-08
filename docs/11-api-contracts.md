# NOVA — API Contracts

| | |
|---|---|
| **Document** | Phase 11 — API Contracts |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | Phases 3, 6, 7, 9, 10 (this document freezes their interfaces) |
| **Feeds into** | Implementation (all modules), Phase 13 (contract tests), API docs (Phase 17) |

These are the **internal contracts** between NOVA's layers. A contract change requires a version bump here and a matching doc amendment — code and this document may not drift (enforced by contract tests, §7).

---

## 1. Core Data Types (`nova/core/models.py`)

Frozen dataclasses (events/transfer) and Pydantic models (validated boundaries) per TD-10.

```python
# ── transfer artifacts (frozen dataclasses) ─────────────────────────
@dataclass(frozen=True)
class UserInput:
    request_id: str            # "req_" + 8 hex
    text: str
    source: Literal["voice", "typed"]
    ts: datetime

@dataclass(frozen=True)
class Transcript:
    request_id: str
    text: str
    confidence: float | None   # None if engine doesn't report

@dataclass(frozen=True)
class ToolCall:
    call_id: str               # "call_" + 8 hex (provider id if given)
    tool_name: str
    arguments: dict[str, Any]  # raw; validated by Executor

@dataclass(frozen=True)
class ToolResult:
    call_id: str
    status: Literal["ok", "error", "timeout", "denied"]
    data: dict[str, Any] | None      # tool output incl. "summary"
    error_code: str | None           # from the tool's declared error set
    error_message: str | None        # LLM-readable
    duration_ms: int

@dataclass(frozen=True)
class AssistantReply:
    request_id: str
    text: str                  # displayed
    spoken_text: str           # synthesized (may be shorter)

@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
```

## 2. Pipeline Events (`nova/core/events.py`)

```python
class PipelineStage(StrEnum):
    IDLE; LISTENING; TRANSCRIBING; THINKING; SELECTING_TOOL
    AWAITING_CONFIRMATION; EXECUTING; OBSERVING; REMEMBERING
    RESPONDING; SPEAKING; ERROR

class EventStatus(StrEnum):
    STARTED; COMPLETED; SKIPPED; FAILED

@dataclass(frozen=True)
class PipelineEvent:
    request_id: str
    stage: PipelineStage
    status: EventStatus
    detail: str                # child-readable, Phase 5 §9 rules
    payload: dict | None       # stage-specific (§2.1)
    ts: datetime
```

**§2.1 payload conventions:** `SELECTING_TOOL` → `{tool_name, tool_title, icon}` · `EXECUTING` → `{tool_name}` · `TRANSCRIBING completed` → `{text, confidence}` · `ERROR` → `{error_code}` · `*_COMPLETED` → `{duration_ms}`.

**EventBus:** `publish(event)` (any thread) · `subscribe(fn)` / Qt signal `event_published(PipelineEvent)` (delivered on main thread via queued connection). Ordering guarantee: per `request_id`, events arrive in publish order.

**Serialized form (logs, session `stages` records):**
```json
{"request_id":"req_5f1b","stage":"EXECUTING","status":"completed",
 "detail":"Checking the weather in Lagos","payload":{"duration_ms":642},
 "ts":"2026-07-08T14:32:10.412Z"}
```

## 3. Tool Contract (`nova/tools/base.py`)

```python
class ToolSpec(BaseModel):
    name: str                  # ^[a-z][a-z0-9_]{2,30}$, unique
    title: str
    description: str           # written for the LLM (Phase 7 §1)
    parameters: type[BaseModel]
    sensitive: bool = False
    icon: str                  # lucide name
    detail_template: str       # "Opening {app} on your PC"

class Tool(ABC):
    spec: ToolSpec
    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput: ...

class ToolOutput(BaseModel):
    data: dict[str, Any]       # MUST include "summary": str
    # errors are raised as ToolError(code, llm_message) — Executor normalizes

class ToolContext(BaseModel, frozen=True):
    settings: Settings
    memory: MemoryFacade | None = None   # injected only for memory_tool (D-3)
```

**Registry:** `register(tool)` (raises on duplicate) · `get(name) -> Tool | None` · `schemas() -> list[ToolSchema]` (cached).

### 3.1 Tool-calling wire format (canonical, provider-normalized)

Schema sent to LLM (generated from the params model):
```json
{"name": "weather",
 "description": "Get current weather and forecast. Use when the user asks about weather, temperature, rain…",
 "parameters": {"type": "object",
   "properties": {"city": {"type": ["string","null"], "description": "City name; null = user's default city"},
                  "days": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1}},
   "required": ["city"]}}
```
Call received → `ToolCall{call_id, tool_name:"weather", arguments:{"city":"Lagos"}}`.
Result returned to LLM (role `tool`, JSON string content):
```json
{"status":"ok","data":{"city":"Lagos","temp_c":31,"condition":"sunny",
 "summary":"It's 31° and sunny in Lagos"}}
```
Error to LLM: `{"status":"error","error_code":"city_not_found","error_message":"No city named 'Lagoss' was found. Ask the user to check the spelling."}` — messages are written *to the LLM* so it can respond helpfully (Phase 6 rule 3).

## 4. Service Facades

```python
class LLMProvider(ABC):                                  # Phase 10 §1
    def generate(messages, tools, opts) -> LLMResponse
    def health_check() -> ProviderHealth

class SpeechService:                                     # Phase 8
    def listen(device: int | None) -> Transcript          # blocking, SpeechIn thread
    def cancel_listening() -> None
    def speak(reply: AssistantReply) -> None               # queued, SpeechOut thread
    def stop_speaking() -> None
    signals: listening_level(float), speech_done(str request_id)

class MemoryService:                                     # Phase 9 §4
    def get_context(input: UserInput) -> MemoryContext
    def add_fact(content: str, kind: FactKind) -> MemoryItem
    def list_facts() -> list[MemoryItem]
    def delete_fact(id: str) -> None
    def clear_facts() -> None
    def persist_turn(turn: TurnRecord) -> None
    def list_sessions() -> list[SessionMeta]
    def load_session(id: str) -> list[TurnRecord]

class Agent:                                             # Phase 6
    def handle(input: UserInput) -> AssistantReply         # AgentWorker thread
    def cancel() -> None
    # confirmation: agent emits AWAITING_CONFIRMATION; Orchestrator calls
    def confirm(call_id: str, approved: bool) -> None
```

## 5. Settings Schema (`settings.json`, Pydantic-validated)

```json
{"version": 1,
 "provider": {"active": "gemini", "gemini_model": "gemini-2.5-flash",
               "groq_model": "llama-3.3-70b-versatile"},
 "voice": {"tts_enabled": true, "voice": "en-US-AnaNeural",
            "input_device": null, "output_device": null, "sound_effects": true},
 "weather": {"default_city": "Lagos"},
 "ui": {"accent": "cyan", "reduced_motion": false, "pipeline_visible": true},
 "advanced": {"max_iterations": 5, "tool_timeout_s": 15,
               "vad": {"aggressiveness": 2, "silence_ms": 800}}}
```
Unknown fields are preserved on rewrite (forward compatibility); invalid fields revert to defaults with a logged warning (Phase 3 §15).

## 6. Validation & Error Envelope

- **Boundary rule:** every datum crossing a layer boundary is typed (dataclass/Pydantic); every datum arriving from *outside* (LLM output, API responses, user files) is validated before use (FR-16, A-1).
- Tool args: `params_model.model_validate(arguments)`; on `ValidationError` → `ToolInvalidArgs` with the Pydantic error list flattened into an LLM-readable string (drives the repair round-trip, Phase 6 §6).
- The **error envelope** is uniform everywhere an error is represented as data: `{status, error_code, error_message}` (§3.1) — same shape in tool results, logs, and session records.

## 7. Versioning & Enforcement

- Persisted files (`settings.json`, `facts.json`, session JSONL) carry `version: int`; loaders migrate forward or quarantine (Phase 9 §2).
- Contract tests (Phase 13): golden-file tests freeze §3.1 wire formats and §2 serialization; import-linter freezes the dependency shape; a schema-drift test regenerates tool JSON Schemas and diffs against committed goldens.

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 11 review. |

**Exit check:** every cross-layer arrow in Phase 3 §2 has a typed contract here; all external data is validated at entry; wire formats are golden-testable.
