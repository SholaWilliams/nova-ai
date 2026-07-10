"""LLMProvider ABC and the provider-facing types — docs/10 §1.

`agent` is explicitly allowed to import this module (D-4: "the ABCs of providers"); `ui` and
`tools` never should (D-5, D-3) — these types carry provider-specific vocabulary
(`finish_reason`, token usage) that only the agent layer needs. Adapters normalize every
provider SDK's dialect into these shapes and raise only `core.errors.ProviderError` subtypes
(`AuthError`, `RateLimited`, `Transient`, `SafetyBlocked`) — the agent and manager never see a
raw SDK exception (A-4, A-6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from nova.core.models import ChatMessage, ToolCall, ToolSchema


@dataclass(frozen=True)
class GenerateOptions:
    """Per-request generation budget (docs/10 §3.3)."""

    max_tokens: int = 300
    temperature: float = 0.6
    timeout_s: float = 20.0


@dataclass(frozen=True)
class TokenUsage:
    """Token accounting for one `generate()` call (R-3 monitoring)."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    """A provider's reply, normalized to NOVA's internal vocabulary (docs/10 §1)."""

    text: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: Literal["stop", "tool_calls", "length", "safety", "error"]
    usage: TokenUsage


@dataclass(frozen=True)
class ProviderHealth:
    """Whether a provider is currently usable — drives startup key validation (FR-47)."""

    available: bool
    detail: str


@dataclass(frozen=True)
class ProviderCaps:
    """Static capability info a caller can branch on without a live request."""

    tool_calling: bool
    max_context: int
    safety_settings: bool


class LLMProvider(ABC):
    """A cloud LLM backend, normalized to one dialect-free interface (docs/10 §1)."""

    name: str

    @abstractmethod
    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema],
        opts: GenerateOptions,
    ) -> LLMResponse:
        """Call the provider and return a normalized response.

        Raises only `core.errors.ProviderError` subtypes — never a raw SDK exception.
        Implementations must omit the tools parameter entirely from the underlying SDK call
        when `tools` is empty rather than passing an empty list — some SDKs treat an empty
        tool list as "tool mode requested with zero options."
        """
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Cheaply verify the configured key is valid and the provider is reachable."""
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCaps:
        """Static capability info for this provider."""
        raise NotImplementedError
