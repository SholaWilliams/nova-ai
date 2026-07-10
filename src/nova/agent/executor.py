"""Executor: validate -> confirm (if sensitive) -> run -> normalize (docs/06 §2.3).

The chokepoint between the LLM's *choice* and anything actually happening on Windows
(rule 1): every `ToolCall` passes Pydantic validation against the tool's declared params
model (FR-16), sensitive tools block on the user's explicit Yes (FR-20, 120 s decision
timeout), and the tool body runs under a watchdog (FR-49). Every outcome — value, ToolError,
timeout, denial, crash — is normalized into a `ToolResult`; nothing raises past `execute()`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from nova.core.errors import ToolError
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import ToolCall, ToolResult
from nova.tools.base import Tool, ToolContext
from nova.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_CONFIRM_TIMEOUT_S = 120.0  # docs/06 §2.3 decision timeout


def _flatten_validation_error(exc: ValidationError) -> str:
    """Pydantic's error list flattened into one LLM-readable string (docs/11 §6)."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(loc) for loc in error["loc"]) or "arguments"
        parts.append(f"{location}: {error['msg']}")
    return "Invalid arguments — " + "; ".join(parts)


class _PendingConfirmation:
    """One in-flight confirmation: the Executor blocks on `answered`; the UI thread
    resolves it via `Executor.resolve_confirmation()` (a plain attribute write + event
    set — safe from any thread)."""

    def __init__(self) -> None:
        self.answered = threading.Event()
        self.approved = False


class Executor:
    """Runs validated tool calls sequentially, one at a time (deterministic, teachable)."""

    def __init__(
        self,
        registry: ToolRegistry,
        bus: EventBus,
        ctx: ToolContext,
        tool_timeout_s: float = 15.0,
        confirm_timeout_s: float = _CONFIRM_TIMEOUT_S,
    ) -> None:
        self._registry = registry
        self._bus = bus
        self._ctx = ctx
        self._tool_timeout_s = tool_timeout_s
        self._confirm_timeout_s = confirm_timeout_s
        self._pending: dict[str, _PendingConfirmation] = {}

    # ── confirmation (called from the main thread via app.py wiring) ──

    def resolve_confirmation(self, call_id: str, approved: bool) -> None:
        """Answer a pending confirmation. Must be invoked with a direct connection —
        the worker thread is blocked inside `execute()` waiting for this."""
        pending = self._pending.get(call_id)
        if pending is None:
            return
        pending.approved = approved
        pending.answered.set()

    # ── execution ─────────────────────────────────────────────────────

    def execute(self, call: ToolCall, request_id: str) -> ToolResult:
        started = time.monotonic()

        def elapsed_ms() -> int:
            return int((time.monotonic() - started) * 1000)

        tool = self._registry.get(call.tool_name)
        if tool is None:  # Router already screens unknown names; defensive only
            return ToolResult(
                call_id=call.call_id,
                status="error",
                data=None,
                error_code="unknown_tool",
                error_message=f"Unknown tool {call.tool_name!r}.",
                duration_ms=elapsed_ms(),
            )

        try:
            args = tool.spec.parameters.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult(
                call_id=call.call_id,
                status="error",
                data=None,
                error_code="invalid_args",
                error_message=_flatten_validation_error(exc),
                duration_ms=elapsed_ms(),
            )

        detail = self._render_detail(tool, args)

        if tool.spec.sensitive:
            approved = self._await_confirmation(tool, args, call, request_id, detail)
            if not approved:
                self._emit(
                    request_id,
                    PipelineStage.EXECUTING,
                    EventStatus.SKIPPED,
                    "Okay — not doing that",
                    {"tool_name": call.tool_name},
                )
                return ToolResult(
                    call_id=call.call_id,
                    status="denied",
                    data=None,
                    error_code="denied",
                    error_message=(
                        "The user said no. Acknowledge politely and don't try again "
                        "unless they ask."
                    ),
                    duration_ms=elapsed_ms(),
                )

        self._emit(
            request_id,
            PipelineStage.EXECUTING,
            EventStatus.STARTED,
            detail,
            {"tool_name": call.tool_name},
        )

        result = self._run_with_watchdog(tool, args, call, elapsed_ms)

        if result.status == "ok":
            self._emit(
                request_id,
                PipelineStage.EXECUTING,
                EventStatus.COMPLETED,
                detail,
                {"tool_name": call.tool_name, "duration_ms": result.duration_ms},
            )
        else:
            failure_detail = result.error_message or detail
            self._emit(
                request_id,
                PipelineStage.EXECUTING,
                EventStatus.FAILED,
                failure_detail,
                {"tool_name": call.tool_name, "error_code": result.error_code},
            )
        return result

    def _run_with_watchdog(
        self,
        tool: Tool,
        args: BaseModel,
        call: ToolCall,
        elapsed_ms: Any,
    ) -> ToolResult:
        # ponytail: a timed-out tool's thread can't be killed in Python — it's abandoned
        # (daemonized pool thread) and its eventual result discarded. Acceptable for v1.0's
        # bounded, read-mostly tools; a process-based executor is the upgrade path.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{tool.spec.name}")
        try:
            future = pool.submit(tool.execute, args, self._ctx)
            try:
                output = future.result(timeout=self._tool_timeout_s)
            except FutureTimeoutError:
                return ToolResult(
                    call_id=call.call_id,
                    status="timeout",
                    data=None,
                    error_code="timeout",
                    error_message=(
                        f"The {tool.spec.title} took longer than "
                        f"{int(self._tool_timeout_s)} seconds and was stopped."
                    ),
                    duration_ms=elapsed_ms(),
                )
            except ToolError as exc:
                return ToolResult(
                    call_id=call.call_id,
                    status="error",
                    data=None,
                    error_code=exc.code,
                    error_message=str(exc),
                    duration_ms=elapsed_ms(),
                )
            except Exception as exc:  # tool crashed — normalize, never propagate
                logger.exception("Tool %s crashed", tool.spec.name)
                return ToolResult(
                    call_id=call.call_id,
                    status="error",
                    data=None,
                    error_code="tool_error",
                    error_message=f"The {tool.spec.title} hit an unexpected problem: {exc}",
                    duration_ms=elapsed_ms(),
                )
            return ToolResult(
                call_id=call.call_id,
                status="ok",
                data=output.data,
                error_code=None,
                error_message=None,
                duration_ms=elapsed_ms(),
            )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _await_confirmation(
        self,
        tool: Tool,
        args: BaseModel,
        call: ToolCall,
        request_id: str,
        detail: str,
    ) -> bool:
        try:
            preview = tool.preview(args, self._ctx)
        except Exception:  # preview must never block the gate itself
            logger.exception("Tool %s preview failed", tool.spec.name)
            preview = []

        pending = _PendingConfirmation()
        self._pending[call.call_id] = pending
        try:
            self._emit(
                request_id,
                PipelineStage.AWAITING_CONFIRMATION,
                EventStatus.STARTED,
                "Asking your permission",
                {
                    "call_id": call.call_id,
                    "tool_name": tool.spec.name,
                    "tool_title": tool.spec.title,
                    "icon": tool.spec.icon,
                    "detail": detail,
                    "preview": preview,
                },
            )
            answered = pending.answered.wait(self._confirm_timeout_s)
            approved = answered and pending.approved
            self._emit(
                request_id,
                PipelineStage.AWAITING_CONFIRMATION,
                EventStatus.COMPLETED if approved else EventStatus.FAILED,
                "You said yes!"
                if approved
                else ("You said no" if answered else "No answer — so I won't do it"),
                {"call_id": call.call_id, "approved": approved},
            )
            return approved
        finally:
            self._pending.pop(call.call_id, None)

    def _render_detail(self, tool: Tool, args: BaseModel) -> str:
        values: defaultdict[str, Any] = defaultdict(str)
        for key, value in args.model_dump().items():
            if value is not None:
                values[key] = value
        # weather's template says {city} but city may be null -> default city
        if not values.get("city"):
            values["city"] = self._ctx.settings.weather.default_city
        return tool.spec.detail_template.format_map(values)

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
