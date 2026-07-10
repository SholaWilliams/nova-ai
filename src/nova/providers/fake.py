"""FakeProvider: scripted response sequences for tests (docs/06 §8, docs/13 §2).

A real collaborator, not test-only scaffolding — CODING_STANDARDS.md's "fakes over mocks"
rule and docs/06 §8 both frame it this way. Shipped in `nova.providers` (same reasoning as
`nova.ui.debug_emitter`: importable, but never reachable from a real request) rather than
under `tests/`, so `agent`'s own test suite can construct one without reaching across the
`tests/`/`src/` boundary.

Safety boundary: never add this to `manager.PROVIDERS` or to `ProviderSettings.active`'s
`Literal["gemini", "groq"]` — that's what keeps it importable-but-never-user-selectable.
"""

from __future__ import annotations

from collections.abc import Sequence

from nova.core.errors import ProviderError
from nova.core.models import ChatMessage, ToolSchema
from nova.providers.base import (
    GenerateOptions,
    LLMProvider,
    LLMResponse,
    ProviderCaps,
    ProviderHealth,
)

_DEFAULT_CAPS = ProviderCaps(tool_calling=True, max_context=32_000, safety_settings=True)
_DEFAULT_HEALTH = ProviderHealth(available=True, detail="ready")


class FakeProvider(LLMProvider):
    """Replays a scripted sequence of responses/errors, one per `generate()` call.

    Each script item is either an `LLMResponse` to return or a `ProviderError` instance to
    raise — mirroring the real adapter contract (docs/10 §1: adapters raise only
    `ProviderError` subtypes, never a raw SDK exception). Every call is recorded in `.calls`
    for assertions (e.g. "the manager retried the same provider once").
    """

    def __init__(
        self,
        name: str,
        script: Sequence[LLMResponse | ProviderError],
        *,
        caps: ProviderCaps = _DEFAULT_CAPS,
        health: ProviderHealth = _DEFAULT_HEALTH,
    ) -> None:
        self.name = name
        self._script = list(script)
        self._index = 0
        self._caps = caps
        self._health = health
        self.calls: list[tuple[list[ChatMessage], list[ToolSchema], GenerateOptions]] = []

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema],
        opts: GenerateOptions,
    ) -> LLMResponse:
        self.calls.append((messages, tools, opts))
        if self._index >= len(self._script):
            raise AssertionError(
                f"FakeProvider {self.name!r} script exhausted after {self._index} call(s)"
            )
        item = self._script[self._index]
        self._index += 1
        if isinstance(item, ProviderError):
            raise item
        return item

    def health_check(self) -> ProviderHealth:
        return self._health

    @property
    def capabilities(self) -> ProviderCaps:
        return self._caps
