"""Tests for Router — response classification (docs/06 §2.2)."""

from __future__ import annotations

from nova.agent.router import DirectAnswer, RepairRoute, Router, ToolRoute
from nova.core.models import ToolCall
from nova.providers.base import LLMResponse, TokenUsage

_USAGE = TokenUsage(input_tokens=10, output_tokens=5)


def _response(text: str | None = None, tool_calls: tuple[ToolCall, ...] = ()) -> LLMResponse:
    finish = "tool_calls" if tool_calls else "stop"
    return LLMResponse(text=text, tool_calls=tool_calls, finish_reason=finish, usage=_USAGE)


def test_text_only_response_routes_to_direct_answer() -> None:
    router = Router()

    route = router.route(_response(text="hello there"))

    assert route == DirectAnswer(text="hello there")


def test_none_text_and_no_tool_calls_routes_to_empty_direct_answer() -> None:
    router = Router()

    route = router.route(_response(text=None))

    assert route == DirectAnswer(text="")


def test_known_tool_call_routes_to_tool_route() -> None:
    call = ToolCall(call_id="call_1", tool_name="weather", arguments={"city": "Lagos"})
    router = Router(known_tool_names=frozenset({"weather"}))

    route = router.route(_response(text="checking...", tool_calls=(call,)))

    assert route == ToolRoute(calls=(call,))


def test_default_router_has_no_known_tools_so_any_call_is_unknown() -> None:
    call = ToolCall(call_id="call_1", tool_name="weather", arguments={"city": "Lagos"})
    router = Router()  # M2: no tools registered anywhere

    route = router.route(_response(tool_calls=(call,)))

    assert isinstance(route, RepairRoute)
    assert "weather" in route.reason
    assert "no tools are available" in route.reason


def test_unknown_tool_name_routes_to_repair_with_known_list() -> None:
    call = ToolCall(call_id="call_1", tool_name="mystery_tool", arguments={})
    router = Router(known_tool_names=frozenset({"weather", "calculator"}))

    route = router.route(_response(tool_calls=(call,)))

    assert isinstance(route, RepairRoute)
    assert "mystery_tool" in route.reason
    assert "calculator" in route.reason
    assert "weather" in route.reason


def test_mixed_known_and_unknown_calls_routes_to_repair() -> None:
    known_call = ToolCall(call_id="call_1", tool_name="weather", arguments={})
    unknown_call = ToolCall(call_id="call_2", tool_name="bogus", arguments={})
    router = Router(known_tool_names=frozenset({"weather"}))

    route = router.route(_response(tool_calls=(known_call, unknown_call)))

    assert isinstance(route, RepairRoute)
    assert "bogus" in route.reason
