"""Agent: the bounded reason-act loop (docs/06 §1). `handle(UserInput) -> AssistantReply`
runs synchronously on the AgentWorker thread; `cancel()` is safe to call directly from any
thread (see `AgentCancelled` below).

M2 has no tools: `ProviderManager.generate()` is always called with `tools=[]`, so `Router`
(constructed with an empty known-tool-name set) can only ever return `DirectAnswer` or
`RepairRoute` — never `ToolRoute`. Every `RepairRoute` consumes one loop iteration and
appends a corrective tool-error message, exactly like a real repair round-trip would
(docs/06 §6) — exhausting `max_iterations` without ever reaching a `DirectAnswer` is
uniformly "iteration cap hit" (ERROR event + apology). docs/06 §6 also describes a softer
"repair also fails, no ERROR" outcome as if distinct from cap-hit; with M2's permanently-
empty tool registry there's no way to reach that outcome differently from cap-hit, so this
collapses the two into one mechanism (a judgment call — see docs/ai/MEMORY.md) — revisit
once M3's real multi-step tool loop makes a meaningful distinction possible.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from nova.agent.planner import Planner
from nova.agent.router import DirectAnswer, RepairRoute, Router, ToolRoute
from nova.agent.state import ConversationState
from nova.core.errors import ProviderError, SafetyBlocked
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import AssistantReply, ChatMessage, UserInput
from nova.providers.base import GenerateOptions
from nova.providers.manager import ProviderManager

_SAFETY_REFUSAL_TEXT = "I don't think I should talk about that — let's chat about something else!"
_CANT_REACH_BRAIN_TEXT = "I can't reach my brain right now — is the internet on?"
_TOO_COMPLICATED_TEXT = "That got too complicated for me — try asking a simpler way?"


class AgentCancelled(Exception):  # noqa: N818 - deliberately not "*Error"; see docstring
    """Raised internally when `Agent.handle()` observes a cancellation at a loop boundary.

    Deliberately not a `NovaError` — `NovaError`s become conversational replies (A-6); a
    cancellation is the opposite (the user explicitly doesn't want a reply). This keeps
    `handle()`'s `-> AssistantReply` signature honest on every *completing* path.
    """


class Agent:
    """The perceive-reason-act loop (docs/06 §1). Everything pluggable arrives via
    constructor injection from `app.py` (D-6)."""

    def __init__(
        self,
        provider_manager: ProviderManager,
        planner: Planner,
        router: Router,
        state: ConversationState,
        bus: EventBus,
        opts: GenerateOptions | None = None,
    ) -> None:
        self._provider_manager = provider_manager
        self._planner = planner
        self._router = router
        self._state = state
        self._bus = bus
        self._opts = opts or GenerateOptions()
        self._cancel_requested = False

    def cancel(self) -> None:
        """Request cancellation of whichever request is currently in `handle()`.

        Safe to call directly from any thread: it's a single attribute write, polled (never
        pushed) by `handle()` at its loop boundaries — the sanctioned exception to "workers
        communicate only via signals" (ARCHITECTURE_RULES.md's threading law explicitly
        calls for flag-based cancellation, never thread termination). Routing this through a
        queued Qt connection instead would leave it undelivered until the current blocking
        call returns, defeating the point.
        """
        self._cancel_requested = True

    def handle(self, user_input: UserInput) -> AssistantReply:
        """Handle one user request end-to-end, emitting real pipeline events throughout."""
        self._cancel_requested = False
        request_id = user_input.request_id

        if user_input.source == "typed":
            # docs/03 §8 line 367: typed input gets these emitted as skipped, not silently
            # omitted — SpeechService (voice, M4) will already have emitted the real ones
            # before handle() is even called for voice-sourced input (hence the guard).
            self._emit(request_id, PipelineStage.LISTENING, EventStatus.SKIPPED, "Listening…")
            self._emit(
                request_id,
                PipelineStage.TRANSCRIBING,
                EventStatus.SKIPPED,
                "Understanding your words",
            )

        self._raise_if_cancelled()
        self._emit(request_id, PipelineStage.THINKING, EventStatus.STARTED, "Thinking…")
        thinking_started = time.monotonic()

        history = self._state.snapshot()
        messages = self._planner.build(user_input, history)

        final_text = self._run_loop(request_id, messages)

        thinking_ms = int((time.monotonic() - thinking_started) * 1000)
        self._emit(
            request_id,
            PipelineStage.THINKING,
            EventStatus.COMPLETED,
            "Figured out what to say",
            {"duration_ms": thinking_ms},
        )

        # No tools exist until M3 -> this trio never actually runs in M2's loop.
        self._emit(request_id, PipelineStage.SELECTING_TOOL, EventStatus.SKIPPED, "Choosing a tool")
        self._emit(request_id, PipelineStage.EXECUTING, EventStatus.SKIPPED, "Doing it on your PC")
        self._emit(request_id, PipelineStage.OBSERVING, EventStatus.SKIPPED, "Checking the result")

        # No MemoryService yet (M5) -> Agent itself is a valid emitter for this stage
        # (docs/03 §7.1, docs/06 §1) and there's never anything to actually store.
        self._emit(
            request_id, PipelineStage.REMEMBERING, EventStatus.SKIPPED, "Nothing new to remember"
        )

        self._emit(
            request_id, PipelineStage.RESPONDING, EventStatus.STARTED, "Getting my answer ready"
        )
        responding_started = time.monotonic()
        reply = AssistantReply(request_id=request_id, text=final_text, spoken_text=final_text)
        responding_ms = int((time.monotonic() - responding_started) * 1000)
        self._emit(
            request_id,
            PipelineStage.RESPONDING,
            EventStatus.COMPLETED,
            final_text,
            {"duration_ms": responding_ms},
        )

        self._state.append(ChatMessage(role="user", content=user_input.text))
        self._state.append(ChatMessage(role="assistant", content=final_text))

        return reply

    def _run_loop(self, request_id: str, messages: list[ChatMessage]) -> str:
        for _iteration in range(1, self._state.max_iterations + 1):
            self._raise_if_cancelled()

            try:
                response = self._provider_manager.generate(messages, [], self._opts)
            except SafetyBlocked:
                return _SAFETY_REFUSAL_TEXT
            except ProviderError:
                self._emit(
                    request_id,
                    PipelineStage.ERROR,
                    EventStatus.COMPLETED,
                    _CANT_REACH_BRAIN_TEXT,
                    {"error_code": "provider_unavailable"},
                )
                return _CANT_REACH_BRAIN_TEXT

            if response.finish_reason == "safety" and not response.text:
                return _SAFETY_REFUSAL_TEXT

            route = self._router.route(response)

            if isinstance(route, DirectAnswer):
                return route.text

            if isinstance(route, RepairRoute):
                messages.append(
                    ChatMessage(
                        role="assistant", content=response.text, tool_calls=response.tool_calls
                    )
                )
                for call in response.tool_calls:
                    messages.append(
                        ChatMessage(role="tool", content=route.reason, tool_call_id=call.call_id)
                    )
                continue

            if isinstance(route, ToolRoute):
                # Unreachable in M2: Router is always constructed with known_tool_names=
                # frozenset(), so route() can never classify a call as "known". M3 replaces
                # this branch with real Executor dispatch once tools exist.
                raise AssertionError("ToolRoute is unreachable before M3's Executor exists")

        self._emit(
            request_id,
            PipelineStage.ERROR,
            EventStatus.COMPLETED,
            _TOO_COMPLICATED_TEXT,
            {"error_code": "iteration_cap"},
        )
        return _TOO_COMPLICATED_TEXT

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested:
            raise AgentCancelled

    def _emit(
        self,
        request_id: str,
        stage: PipelineStage,
        status: EventStatus,
        detail: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._bus.publish(
            PipelineEvent(
                request_id=request_id,
                stage=stage,
                status=status,
                detail=detail,
                payload=payload,
                ts=datetime.now(UTC),
            )
        )
