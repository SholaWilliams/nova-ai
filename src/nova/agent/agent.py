"""Agent: the bounded reason-act loop (docs/06 §1). `handle(UserInput) -> AssistantReply`
runs synchronously on the AgentWorker thread; `cancel()` is safe to call directly from any
thread (see `AgentCancelled` below).

M3: real tool iterations. `ProviderManager.generate()` receives the registry's schemas;
a `ToolRoute` dispatches sequentially through the `Executor` (validate -> confirm -> run ->
normalize), results are fed back as `tool`-role messages, and the loop continues until a
`DirectAnswer` or the iteration cap (FR-17).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from nova.agent.executor import Executor
from nova.agent.planner import Planner, thinking_summary
from nova.agent.router import DirectAnswer, RepairRoute, Router, ToolRoute
from nova.agent.state import ConversationState
from nova.core.errors import ProviderError, SafetyBlocked
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import AssistantReply, ChatMessage, ToolResult, UserInput
from nova.providers.base import GenerateOptions
from nova.providers.manager import ProviderManager
from nova.tools.registry import ToolRegistry

_MAX_TOOL_RESULT_CHARS = 1024  # docs/06 §5: larger results are summarized before appending


def _result_envelope(result: ToolResult) -> str:
    """The uniform error envelope / ok payload fed back to the LLM (docs/11 §3.1, §6)."""
    if result.status == "ok":
        data = result.data or {}
        text = json.dumps({"status": "ok", "data": data})
        if len(text) > _MAX_TOOL_RESULT_CHARS:
            text = json.dumps({"status": "ok", "data": {"summary": data.get("summary", "")}})
        return text
    return json.dumps(
        {
            "status": result.status,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }
    )


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
        registry: ToolRegistry | None = None,
        executor: Executor | None = None,
        opts: GenerateOptions | None = None,
    ) -> None:
        self._provider_manager = provider_manager
        self._planner = planner
        self._router = router
        self._state = state
        self._bus = bus
        self._registry = registry or ToolRegistry()
        self._executor = executor
        self._opts = opts or GenerateOptions()
        self._cancel_requested = False

    def confirm(self, call_id: str, approved: bool) -> None:
        """Answer a pending sensitive-tool confirmation (docs/11 §4).

        Like `cancel()`, must arrive as a direct call from the main thread — the worker
        thread is blocked inside the Executor's gate waiting for it.
        """
        if self._executor is not None:
            self._executor.resolve_confirmation(call_id, approved)

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

        final_text, used_tools = self._run_loop(request_id, messages)

        thinking_ms = int((time.monotonic() - thinking_started) * 1000)
        self._emit(
            request_id,
            PipelineStage.THINKING,
            EventStatus.COMPLETED,
            "Figured out what to say",
            {"duration_ms": thinking_ms},
        )

        if not used_tools:
            # Direct answer: the tool trio didn't run — say so honestly (skipped, not faked).
            self._emit(
                request_id, PipelineStage.SELECTING_TOOL, EventStatus.SKIPPED, "Choosing a tool"
            )
            self._emit(
                request_id, PipelineStage.EXECUTING, EventStatus.SKIPPED, "Doing it on your PC"
            )
            self._emit(
                request_id, PipelineStage.OBSERVING, EventStatus.SKIPPED, "Checking the result"
            )

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

    def _run_loop(self, request_id: str, messages: list[ChatMessage]) -> tuple[str, bool]:
        """Returns (final_text, used_tools)."""
        used_tools = False
        schemas = self._registry.schemas()

        for _iteration in range(1, self._state.max_iterations + 1):
            self._raise_if_cancelled()

            try:
                response = self._provider_manager.generate(messages, schemas, self._opts)
            except SafetyBlocked:
                return _SAFETY_REFUSAL_TEXT, used_tools
            except ProviderError:
                self._emit(
                    request_id,
                    PipelineStage.ERROR,
                    EventStatus.COMPLETED,
                    _CANT_REACH_BRAIN_TEXT,
                    {"error_code": "provider_unavailable"},
                )
                return _CANT_REACH_BRAIN_TEXT, used_tools

            if response.finish_reason == "safety" and not response.text:
                return _SAFETY_REFUSAL_TEXT, used_tools

            route = self._router.route(response)

            if isinstance(route, DirectAnswer):
                return route.text, used_tools

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
                if self._executor is None:  # defensive: registry without executor is a bug
                    raise AssertionError("ToolRoute reached without an Executor wired in")
                used_tools = True
                self._dispatch_tools(request_id, messages, response.text, route)

        self._emit(
            request_id,
            PipelineStage.ERROR,
            EventStatus.COMPLETED,
            _TOO_COMPLICATED_TEXT,
            {"error_code": "iteration_cap"},
        )
        return _TOO_COMPLICATED_TEXT, used_tools

    def _dispatch_tools(
        self,
        request_id: str,
        messages: list[ChatMessage],
        prose: str | None,
        route: ToolRoute,
    ) -> None:
        """One tool iteration: SELECTING_TOOL -> Executor per call (sequential) -> OBSERVING."""
        assert self._executor is not None
        first = self._registry.get(route.calls[0].tool_name)
        assert first is not None  # Router only routes known names
        summary = thinking_summary(prose, first.spec.title)
        selecting_payload = {
            "tool_name": first.spec.name,
            "tool_title": first.spec.title,
            "icon": first.spec.icon,
        }
        self._emit(
            request_id,
            PipelineStage.SELECTING_TOOL,
            EventStatus.STARTED,
            summary,
            selecting_payload,
        )
        self._emit(
            request_id,
            PipelineStage.SELECTING_TOOL,
            EventStatus.COMPLETED,
            summary,
            selecting_payload,
        )

        messages.append(ChatMessage(role="assistant", content=prose, tool_calls=route.calls))

        results: list[ToolResult] = []
        for call in route.calls:
            self._raise_if_cancelled()
            results.append(self._executor.execute(call, request_id))

        self._emit(request_id, PipelineStage.OBSERVING, EventStatus.STARTED, "Checking the result")
        observing_started = time.monotonic()
        for call, result in zip(route.calls, results, strict=True):
            messages.append(
                ChatMessage(
                    role="tool", content=_result_envelope(result), tool_call_id=call.call_id
                )
            )
        ok = sum(1 for result in results if result.status == "ok")
        self._emit(
            request_id,
            PipelineStage.OBSERVING,
            EventStatus.COMPLETED,
            "Got the result!" if ok == len(results) else "Something didn't work — telling you",
            {"duration_ms": int((time.monotonic() - observing_started) * 1000)},
        )

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
