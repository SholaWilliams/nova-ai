"""NFR-1/2 latency check (docs/13 §8, SC-7 "first visible pipeline activity < 1s after end
of user input"): a timing assert against a deliberately slow `FakeProvider`, proving
THINKING/STARTED fires immediately at the start of `Agent.handle()` rather than waiting on
the network round-trip — the structural guarantee behind SC-7, locked in as a regression.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from nova.agent.agent import Agent
from nova.agent.planner import Planner
from nova.agent.router import Router
from nova.agent.state import ConversationState
from nova.core.events import EventBus, EventStatus, PipelineEvent, PipelineStage
from nova.core.models import UserInput
from nova.providers.base import GenerateOptions, LLMResponse, TokenUsage
from nova.providers.fake import FakeProvider
from nova.providers.manager import ProviderManager

_SIMULATED_NETWORK_DELAY_S = 0.3
_VISIBLE_ACTIVITY_BUDGET_S = 0.05  # generous vs. the 1s SC-7 target; this is in-process, no I/O


class _SlowProvider(FakeProvider):
    """A `FakeProvider` that simulates real network latency before replying."""

    def generate(self, messages, tools, opts):  # noqa: ANN001
        time.sleep(_SIMULATED_NETWORK_DELAY_S)
        return super().generate(messages, tools, opts)


def test_thinking_started_fires_before_the_slow_provider_call_returns() -> None:
    bus = EventBus()
    thinking_started_at: list[float] = []

    def _on_event(event: PipelineEvent) -> None:
        if event.stage == PipelineStage.THINKING and event.status == EventStatus.STARTED:
            thinking_started_at.append(time.monotonic())

    bus.subscribe(_on_event)

    reply = LLMResponse(text="hi!", tool_calls=(), finish_reason="stop", usage=TokenUsage(10, 5))
    provider = _SlowProvider("gemini", [reply])
    manager = ProviderManager({"gemini": provider}, active="gemini")
    agent = Agent(
        manager,
        Planner(system_prompt="you are NOVA, a friendly assistant"),
        Router(),
        ConversationState(max_iterations=5),
        bus,
        opts=GenerateOptions(),
    )

    user_input = UserInput(request_id="req_1", text="hello", source="typed", ts=datetime.now(UTC))
    call_started_at = time.monotonic()
    agent.handle(user_input)
    total_elapsed = time.monotonic() - call_started_at

    assert len(thinking_started_at) == 1
    visible_activity_latency = thinking_started_at[0] - call_started_at

    assert visible_activity_latency < _VISIBLE_ACTIVITY_BUDGET_S
    # sanity: the provider's simulated delay really did dominate the call, otherwise this
    # test would pass trivially without proving anything about ordering. 10% slack absorbs
    # OS timer/scheduler jitter around time.sleep()'s lower bound (observed ~1% short on
    # this machine) without weakening what the check actually proves.
    assert total_elapsed >= _SIMULATED_NETWORK_DELAY_S * 0.9
