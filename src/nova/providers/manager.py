"""ProviderManager: selection, retry, fallback, cooldown, status reporting (docs/10 §3).

Owns the configured-provider registry, the active/primary selection (hot-swappable, US-12),
and the fallback state machine. A `QObject` with a `status_changed` Signal — same cross-thread
pattern `core.events.EventBus` already establishes (TD-3: Qt signals are the app's one
cross-thread eventing mechanism): `generate()` typically runs on the AgentWorker thread, but
`status_changed` still safely reaches a main-thread listener via Qt's automatic queued
connection, regardless of which thread emits.
"""

from __future__ import annotations

import time
from typing import Literal

from PySide6.QtCore import QObject, Signal

from nova.core.errors import ProviderError, RateLimited, SafetyBlocked, Transient
from nova.core.models import ChatMessage, ProviderStatus, ToolSchema
from nova.providers.base import GenerateOptions, LLMProvider, LLMResponse

_COOLDOWN_S = 60.0
_RETRY_BACKOFF_S = 1.0
_DISPLAY_NAMES = {"gemini": "Gemini", "groq": "Groq", "openrouter": "OpenRouter"}


class ProviderManager(QObject):
    """Routes `generate()` calls through the active provider, falling back on failure.

    ```
    try primary  --ok--> return
      Transient/RateLimited: retry once (backoff 1s, honor retry_after)
      AuthError: no retry (retrying a bad key is noise)
      still failing -> mark primary COOLING (60s) -> try fallback (single attempt)
        --ok--> return, status "fallback" (warning tint)
        --failing too--> raise, status "down"
    ```
    `SafetyBlocked` never retries, never cools, never falls back (docs/10 §3.2) — it's a
    correct outcome, not an outage, and propagates straight to the caller.

    Providers are injected as already-constructed instances (D-6: composition lives in
    `app.py`) — this class never constructs a provider from a name/key itself.
    """

    status_changed = Signal(object)  # ProviderStatus

    def __init__(self, providers: dict[str, LLMProvider], active: str) -> None:
        super().__init__()
        self._providers = dict(providers)
        self._active_name = active
        self._cooling_until: dict[str, float] = {}

    @property
    def active_name(self) -> str:
        return self._active_name

    @property
    def configured_names(self) -> frozenset[str]:
        """Names of providers currently backed by a real instance (i.e. a key is set)."""
        return frozenset(self._providers)

    def set_active(self, name: str) -> None:
        """Hot-swap the primary provider (US-12) — takes effect on the next `generate()`."""
        self._active_name = name

    def set_provider(self, name: str, provider: LLMProvider) -> None:
        """Register or replace a provider instance (US-12: a key was just entered/rotated).

        Takes effect on the next `generate()`/`check_health()` call for `name`. Does not
        itself change `active_name` — pair with `set_active()` if the newly-keyed provider
        should also become primary.
        """
        self._providers[name] = provider

    def check_health(self, name: str) -> tuple[bool, str]:
        """Used by Settings' per-key "Test" button and startup validation (FR-47)."""
        provider = self._providers.get(name)
        if provider is None:
            return False, "No key configured"
        health = provider.health_check()
        return health.available, health.detail

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema],
        opts: GenerateOptions,
    ) -> LLMResponse:
        """Call the active provider, falling back per the state machine above.

        Raises `core.errors.ProviderError` (or a subtype) only once every configured
        provider has been tried and failed — the agent's "can't reach my brain" path
        (docs/06 §6) is the only caller that should ever see this propagate.
        """
        primary = self._active_name
        fallback = self._other_configured(primary)
        last_error: ProviderError | None = None

        if primary in self._providers and not self._is_cooling(primary):
            try:
                result = self._attempt_with_retry(primary, messages, tools, opts)
            except SafetyBlocked:
                raise
            except ProviderError as exc:
                last_error = exc
                self._start_cooling(primary)
            else:
                self._emit_status(primary, "normal", self._label(primary))
                return result

        if fallback is not None:
            try:
                result = self._providers[fallback].generate(messages, tools, opts)
            except SafetyBlocked:
                raise
            except ProviderError as exc:
                last_error = exc
            else:
                self._emit_status(fallback, "fallback", f"{self._label(fallback)} (fallback)")
                return result

        self._emit_status(primary, "down", "I can't reach my brain right now")
        if last_error is not None:
            raise last_error
        raise ProviderError(
            "no provider configured",
            friendly_message="I can't reach my brain right now — is the internet on?",
        )

    def _attempt_with_retry(
        self,
        name: str,
        messages: list[ChatMessage],
        tools: list[ToolSchema],
        opts: GenerateOptions,
    ) -> LLMResponse:
        provider = self._providers[name]
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

    def _other_configured(self, name: str) -> str | None:
        for candidate in self._providers:
            if candidate != name:
                return candidate
        return None

    def _is_cooling(self, name: str) -> bool:
        until = self._cooling_until.get(name)
        return until is not None and time.monotonic() < until

    def _start_cooling(self, name: str) -> None:
        self._cooling_until[name] = time.monotonic() + _COOLDOWN_S

    def _label(self, name: str) -> str:
        return _DISPLAY_NAMES.get(name, name)

    def _emit_status(
        self, active: str, mode: Literal["normal", "fallback", "down"], detail: str
    ) -> None:
        self.status_changed.emit(ProviderStatus(active=active, mode=mode, detail=detail))
