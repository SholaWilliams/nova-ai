"""ConversationState: holds one session's turns, trims context (docs/06 §2.4, §5).

Not persistent — persistence is `MemoryService`'s job (M5). The trim is a simple last-N-
messages window in M2; docs/06 §5's "tool results > 1kB are summarized" refinement has
nothing to summarize until M3 adds tools.
"""

from __future__ import annotations

from nova.core.models import ChatMessage

_MAX_TURNS = 12  # docs/06 §5: last 12 turns verbatim (a turn = one user + one assistant msg)


class ConversationState:
    """Owns the iteration cap (FR-17) and the trimmed message history for one session."""

    def __init__(self, max_iterations: int = 5) -> None:
        self._max_iterations = max_iterations
        self._messages: list[ChatMessage] = []

    @property
    def max_iterations(self) -> int:
        return self._max_iterations

    def append(self, message: ChatMessage) -> None:
        self._messages.append(message)

    def snapshot(self) -> tuple[ChatMessage, ...]:
        """The trimmed history for the Planner: the last `_MAX_TURNS` turns, verbatim.

        Older messages drop off — long-term facts live in memory, not history; "remember"
        survives trimming because it was *stored*, which is itself the lesson (EO-5).
        """
        limit = _MAX_TURNS * 2
        return tuple(self._messages[-limit:])
