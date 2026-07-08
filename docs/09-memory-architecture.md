# NOVA — Memory Architecture

| | |
|---|---|
| **Document** | Phase 9 — Memory Architecture |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | Phase 3 (§11 memory flow), Phase 6 (§2.1 planner, §5 trimming), Phase 7 (§8 memory_tool) |
| **Feeds into** | Phase 11 (file schemas), Memory View (Phase 5 §6.4) |

---

## 1. Principles

- **All local, all inspectable.** Plain JSON/JSONL under `%APPDATA%/NOVA/` — a curious teen can open NOVA's "brain" in Notepad, which is itself the lesson (EO-5, NFR-8).
- **Three stores, three lifecycles** (Phase 3 §11): conversations (append-only archive), facts (until user deletes), preferences (until changed).
- **Explicit writes are visible.** Fact writes happen only through the memory tool → REMEMBERING stage lights. Conversation persistence is automatic and silent (archival, not "memory" in the child-facing sense).

## 2. Storage Layout

```
%APPDATA%/NOVA/
├── memory/
│   ├── facts.json          # long-term facts & preferences
│   └── undo_manifest.json  # desktop organizer undo state (Phase 7 §7)
├── conversations/
│   ├── index.json          # session list for History drawer
│   └── 2026-07-08_a3f2.jsonl
└── settings.json / .env / logs/   (Phase 14)
```

Writes are atomic (write temp → `os.replace`); a corrupt file is renamed `.corrupt-<ts>` and recreated empty with a logged warning — memory loss is graceful, never a crash (SC-6 spirit).

## 3. JSON Structures

**facts.json**
```json
{
  "version": 1,
  "facts": [
    {
      "id": "f_9c2e1a",
      "kind": "preference",
      "content": "Favorite color is blue",
      "keywords": ["favorite", "color", "blue"],
      "created_at": "2026-07-08T14:32:11Z",
      "source_request": "req_5f1b"
    }
  ]
}
```
- `content` is third-person plain language (what the Memory View displays verbatim).
- `keywords`: lowercased salient tokens extracted at write time (stopwords removed) — the v1 retrieval index.
- Soft cap 200 facts; at cap, the memory tool returns `storage_error` asking the user to tidy (deliberate: forgetting is a *user* decision, FR-33).

**Conversation session (`.jsonl`, one object per line)**
```json
{"t":"turn","request_id":"req_5f1b","ts":"2026-07-08T14:32:09Z",
 "user":{"text":"remember my favorite color is blue","source":"voice"},
 "assistant":{"text":"I'll remember that your favorite color is blue!"},
 "tools":[{"name":"memory_tool","args":{"action":"store","content":"Favorite color is blue"},"status":"ok","duration_ms":18}],
 "stages":[["LISTENING",842],["TRANSCRIBING",510],["THINKING",1150],
            ["SELECTING_TOOL",5],["EXECUTING",18],["REMEMBERING",4],["SPEAKING",2100]]}
```
The `stages` record makes every past pipeline replayable — History can show *how* NOVA handled any old request (FR-40 extension, presenter gold).

**index.json:** `[{session_id, started_at, title (first user message, 60 chars), turns}]`.

**preferences.json:** flat typed map (`{"default_city": "Lagos", "spoken_name": "Zara"}`) — settings-adjacent user facts the Planner always injects.

## 4. MemoryService API (contract detail in Phase 11)

```
getContext(input: UserInput) → MemoryContext      # read path, called by Planner
addFact(content, kind) → MemoryItem                # write path, memory_tool only
listFacts() / deleteFact(id) / clearFacts()        # Memory View (FR-32/33)
persistTurn(turn: TurnRecord)                      # agent, at RESPONDING
listSessions() / loadSession(id)                   # History drawer
```

Thread-safety: MemoryService is called from AgentWorker (read/persist) and main thread (view ops) — internal lock around file I/O; reads served from an in-memory cache invalidated on write.

## 5. Retrieval Strategy (v1.0)

`getContext` assembles, in priority order, within the ~300-token memory budget (Phase 6 §3):

1. **Preferences** — always included (small, high value: name, city).
2. **Facts** — keyword scoring: tokenize input (lowercase, stopwords out) → score = |input ∩ fact.keywords| with recency tiebreak → top 5 with score ≥ 1.
3. **Recent turns** — handled by ConversationState (last 12, Phase 6 §5), not duplicated here.

Injected as a labeled system block: `"Things you remember about this user: …"`. No hits ⇒ block omitted (prompt stays lean).

**Why keyword-first:** transparent (a child can be shown *why* a memory matched — EO-5), zero dependencies, adequate at ≤ 200 facts. The seam for upgrading is `memory/retrieval.py` behind `Retriever.retrieve(query, k)` (Phase 3 §16).

## 6. Future: Vector Retrieval

When fact volume or fuzziness outgrows keywords: embed facts (provider embedding API — stays cloud, NG-2) into **SQLite + sqlite-vec** (single file, no server, fits the local-and-inspectable principle better than Chroma/FAISS). `KeywordRetriever` → `HybridRetriever` (keyword ∪ vector, rank-fused). No agent or planner changes — `getContext` signature holds. Also future: rolling conversation summaries (Phase 6 §5) stored per session.

## 7. Privacy & Lifecycle

- Nothing leaves the machine except what enters LLM prompts (facts the user asked NOVA to hold — same trust boundary as the conversation itself, NFR-8).
- Memory View (Phase 5 §6.4) is the complete truth: everything injectable is listed there; delete/clear-all are immediate and physical (file rewrite).
- "Forget everything" also offers to clear conversation history (separate checkbox — different lifecycles, same reset-between-classes need, US-11).

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 9 review. |

**Exit check:** every store has a schema, a lifecycle, and an owner; retrieval is explainable to a child; the vector future requires zero agent changes.
