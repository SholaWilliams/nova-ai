"""MemoryService: facts + conversation persistence + retrieval facade (docs/09 §4).

Satisfies `tools.base.MemoryFacade` structurally (`add_fact(content, kind) -> None`,
`recall(query) -> list[str]`) without either module importing the other (D-3) — the same
duck-typed pattern the M3 `InMemoryFacade` stub already established, just backed by real
files now (`app.py` swaps the stub for this wholesale). Internal `threading.Lock` around
file I/O is the one sanctioned lock in this codebase's threading law
(ARCHITECTURE_RULES.md) — called from both `AgentWorker` (read/persist) and the main thread
(Memory View / History drawer).
"""

from __future__ import annotations

import threading
from pathlib import Path

from nova.core.models import MemoryContext, MemoryItem, SessionMeta, TurnRecord, UserInput
from nova.memory.conversation_store import ConversationStore
from nova.memory.facts_store import FactsStore
from nova.memory.retrieval import KeywordRetriever

_PREFERENCE_KIND = "preference"
_FACT_KIND = "fact"
_CONTEXT_TOP_K = 5
_RECALL_TOP_K = 3


class MemoryService:
    def __init__(self, data_dir: Path) -> None:
        self._lock = threading.Lock()
        self._facts_store = FactsStore(data_dir / "memory" / "facts.json")
        self._conversation_store = ConversationStore(data_dir / "conversations")
        self._retriever = KeywordRetriever()
        self._current_request_id = ""

    # ── request tracking (source_request provenance, docs/09 §3) ─────────────

    def begin_request(self, request_id: str) -> None:
        """Called once per `Agent.handle()` so fact writes during this turn can record
        `source_request` — kept separate from `add_fact` since that signature is the
        already-shipped (M3) `MemoryFacade` Protocol and can't grow a parameter without
        breaking it; this sidesteps the need to, for what's otherwise inspectable-only
        metadata (docs/09 §1: "a curious teen can open NOVA's brain in Notepad")."""
        with self._lock:
            self._current_request_id = request_id

    # ── MemoryFacade protocol (tools/base.py) ─────────────────────────────────

    def add_fact(self, content: str, kind: str) -> None:
        with self._lock:
            self._facts_store.add_fact(content, kind, self._current_request_id)

    def recall(self, query: str) -> list[str]:
        with self._lock:
            facts = self._facts_store.list_facts()
        matches = self._retriever.retrieve(query, facts, k=_RECALL_TOP_K)
        return [item.content for item in matches]

    # ── docs/11 §4 MemoryService contract ─────────────────────────────────────

    def get_context(self, user_input: UserInput) -> MemoryContext:
        with self._lock:
            facts = self._facts_store.list_facts()
        preferences = tuple(item.content for item in facts if item.kind == _PREFERENCE_KIND)
        generic = [item for item in facts if item.kind == _FACT_KIND]
        top = self._retriever.retrieve(user_input.text, generic, k=_CONTEXT_TOP_K)
        return MemoryContext(preferences=preferences, facts=tuple(item.content for item in top))

    def list_facts(self) -> list[MemoryItem]:
        with self._lock:
            return self._facts_store.list_facts()

    def delete_fact(self, fact_id: str) -> None:
        with self._lock:
            self._facts_store.delete_fact(fact_id)

    def clear_facts(self) -> None:
        with self._lock:
            self._facts_store.clear_facts()

    def persist_turn(self, turn: TurnRecord) -> None:
        with self._lock:
            self._conversation_store.persist_turn(turn)

    def start_new_session(self) -> None:
        """ "New conversation" (docs/05 §6.5) — see `ConversationStore.start_new_session`."""
        with self._lock:
            self._conversation_store.start_new_session()

    def list_sessions(self) -> list[SessionMeta]:
        with self._lock:
            return self._conversation_store.list_sessions()

    def load_session(self, session_id: str) -> list[TurnRecord]:
        with self._lock:
            return self._conversation_store.load_session(session_id)
