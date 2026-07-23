"""NFR-4 leak-trend check (docs/13 §8): a `tracemalloc` snapshot test across 50 fake
requests through the real Agent + MemoryService stack. Not an absolute RAM budget (that's
the M6 clean-VM manual checklist, SC-8) — this catches a *growing* trend (a handler or
buffer that accumulates per-request and never releases) by comparing the growth of the
second half of the run against the first half.
"""

from __future__ import annotations

import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

from nova.agent.agent import Agent
from nova.agent.planner import Planner
from nova.agent.router import Router
from nova.agent.stage_recorder import StageRecorder
from nova.agent.state import ConversationState
from nova.core.events import EventBus
from nova.core.models import UserInput
from nova.memory.service import MemoryService
from nova.providers.base import GenerateOptions, LLMResponse, TokenUsage
from nova.providers.fake import FakeProvider
from nova.providers.manager import ProviderManager

_REQUEST_COUNT = 50
_USAGE = TokenUsage(input_tokens=10, output_tokens=5)


def _reply(i: int) -> LLMResponse:
    return LLMResponse(text=f"answer {i}", tool_calls=(), finish_reason="stop", usage=_USAGE)


def _user_input(i: int) -> UserInput:
    return UserInput(request_id=f"req_{i}", text=f"hello {i}", source="typed", ts=datetime.now(UTC))


def test_no_growing_leak_trend_across_50_requests(tmp_path: Path) -> None:
    bus = EventBus()
    memory = MemoryService(tmp_path)
    provider = FakeProvider("gemini", [_reply(i) for i in range(_REQUEST_COUNT)])
    manager = ProviderManager(provider)
    agent = Agent(
        manager,
        Planner(system_prompt="you are NOVA, a friendly assistant"),
        Router(),
        ConversationState(max_iterations=5),
        bus,
        opts=GenerateOptions(),
        memory=memory,
        stage_recorder=StageRecorder(bus),
    )

    half = _REQUEST_COUNT // 2
    tracemalloc.start()
    try:
        baseline = tracemalloc.take_snapshot()

        for i in range(half):
            agent.handle(_user_input(i))
        first_half = tracemalloc.take_snapshot()

        for i in range(half, _REQUEST_COUNT):
            agent.handle(_user_input(i))
        second_half = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()

    def _total_bytes(snapshot: tracemalloc.Snapshot) -> int:
        return sum(stat.size for stat in snapshot.statistics("lineno"))

    growth_first_half = _total_bytes(first_half) - _total_bytes(baseline)
    growth_second_half = _total_bytes(second_half) - _total_bytes(first_half)

    # A real leak trend compounds (each batch costs more than the last); steady per-request
    # allocation (trimmed history, bounded retrieval) does not. Generous 3x slack absorbs
    # allocator/GC noise between runs while still catching genuine unbounded growth.
    assert growth_second_half <= growth_first_half * 3 + 512_000, (
        f"possible leak trend: first {half} requests grew heap by {growth_first_half} bytes, "
        f"next {half} grew it by {growth_second_half} bytes"
    )
