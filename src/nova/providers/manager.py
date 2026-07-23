"""ProviderManager: single-provider retry + status reporting (docs/10 §3, simplified M9).

Owns the one configured OmniRoute provider instance and reports its status. A `QObject` with
a `status_changed` Signal — same cross-thread pattern `core.events.EventBus` already
establishes (TD-3: Qt signals are the app's one cross-thread eventing mechanism): `generate()`
typically runs on the AgentWorker thread, but `status_changed` still safely reaches a
main-thread listener via Qt's automatic queued connection, regardless of which thread emits.

M9 removed the M2-M8 primary/fallback/cooldown state machine across multiple providers —
with OmniRoute as the sole backend (docs/04 TD-4, owner decision: no cloud fallback), there is
nothing left to fall back to or hot-swap between. Retry-once-on-transient-failure is kept: a
local gateway process can still hiccup (mid-restart, upstream momentarily exhausted).
"""

from __future__ import annotations

import time
from typing import Literal

from PySide6.QtCore import QObject, Signal

from nova.core.errors import ProviderError, RateLimited, SafetyBlocked, Transient
from nova.core.models import ChatMessage, ProviderStatus, ToolSchema
from nova.providers.base import GenerateOptions, LLMProvider, LLMResponse

_RETRY_BACKOFF_S = 1.0
_NAME = "omniroute"
_LABEL = "OmniRoute"


class ProviderManager(QObject):
    """Routes `generate()` calls to the configured OmniRoute provider, retrying once on a
    transient failure.

    ```
    try provider  --ok--> return, status "normal"
      Transient/RateLimited: retry once (backoff 1s, honor retry_after)
      AuthError: no retry (retrying a bad key is noise)
      still failing -> raise, status "down"
    ```
    `SafetyBlocked` never retries (docs/10 §3.1) — it's a correct outcome, not an outage, and
    propagates straight to the caller.

    The provider is injected as an already-constructed instance, or `None` if no key is
    configured yet (D-6: composition lives in `app.py` — this class never constructs a
    provider from a name/key itself).
    """

    status_changed = Signal(object)  # ProviderStatus

    def __init__(self, provider: LLMProvider | None) -> None:
        super().__init__()
        self._provider = provider

    @property
    def configured(self) -> bool:
        """Whether a real provider instance is currently registered (i.e. a key is set)."""
        return self._provider is not None

    def set_provider(self, provider: LLMProvider | None) -> None:
        """Register, replace, or clear the OmniRoute provider instance (US-12: a key was just
        entered/rotated). Takes effect on the next `generate()`/`check_health()` call."""
        self._provider = provider

    def check_health(self) -> tuple[bool, str]:
        """Used by Settings' per-key "Test" button and startup validation (FR-47)."""
        if self._provider is None:
            return False, "No key configured"
        health = self._provider.health_check()
        return health.available, health.detail

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema],
        opts: GenerateOptions,
    ) -> LLMResponse:
        """Call the configured provider, retrying once on a transient failure.

        Raises `core.errors.ProviderError` (or a subtype) if no provider is configured or the
        retry also fails — the agent's "can't reach my brain" path (docs/06 §6) is the only
        caller that should ever see this propagate.
        """
        if self._provider is None:
            self._emit_status("down", "I can't reach my brain right now")
            raise ProviderError(
                "no provider configured",
                friendly_message="I can't reach my brain right now — is the internet on?",
            )

        try:
            result = self._attempt_with_retry(messages, tools, opts)
        except SafetyBlocked:
            raise
        except ProviderError:
            self._emit_status("down", "I can't reach my brain right now")
            raise

        self._emit_status("normal", _LABEL)
        return result

    def _attempt_with_retry(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema],
        opts: GenerateOptions,
    ) -> LLMResponse:
        assert self._provider is not None
        provider = self._provider
        try:
            return provider.generate(messages, tools, opts)
        except (Transient, RateLimited) as exc:
            delay = (
                exc.retry_after
                if isinstance(exc, RateLimited) and exc.retry_after
                else (_RETRY_BACKOFF_S)
            )
            time.sleep(delay)
            return provider.generate(messages, tools, opts)

    def _emit_status(self, mode: Literal["normal", "down"], detail: str) -> None:
        self.status_changed.emit(ProviderStatus(active=_NAME, mode=mode, detail=detail))
