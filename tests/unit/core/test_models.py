"""Unit tests for nova.core.models — construction and immutability (docs/11 §1)."""

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from nova.core.models import (
    AssistantReply,
    ChatMessage,
    ToolCall,
    ToolResult,
    Transcript,
    UserInput,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_user_input_holds_fields() -> None:
    ts = _now()
    ui = UserInput(request_id="req_abc12345", text="hello", source="typed", ts=ts)
    assert ui.request_id == "req_abc12345"
    assert ui.text == "hello"
    assert ui.source == "typed"
    assert ui.ts is ts


def test_transcript_confidence_is_optional() -> None:
    known = Transcript(request_id="req_1", text="what's the weather", confidence=0.92)
    unknown = Transcript(request_id="req_2", text="what's the weather", confidence=None)
    assert known.confidence == pytest.approx(0.92)
    assert unknown.confidence is None


def test_tool_call_holds_raw_arguments() -> None:
    call = ToolCall(call_id="call_1", tool_name="weather", arguments={"city": "Lagos"})
    assert call.tool_name == "weather"
    assert call.arguments == {"city": "Lagos"}


def test_tool_result_ok_status() -> None:
    result = ToolResult(
        call_id="call_1",
        status="ok",
        data={"summary": "It's 31C and sunny in Lagos"},
        error_code=None,
        error_message=None,
        duration_ms=642,
    )
    assert result.status == "ok"
    assert result.data is not None
    assert result.error_code is None


def test_tool_result_error_status_carries_llm_readable_message() -> None:
    result = ToolResult(
        call_id="call_1",
        status="error",
        data=None,
        error_code="city_not_found",
        error_message="No city named 'Lagoss' was found.",
        duration_ms=12,
    )
    assert result.status == "error"
    assert result.error_code == "city_not_found"
    assert result.error_message is not None


def test_assistant_reply_spoken_text_may_differ_from_displayed_text() -> None:
    reply = AssistantReply(
        request_id="req_1",
        text="It's 31 degrees and sunny in Lagos right now!",
        spoken_text="31 and sunny in Lagos.",
    )
    assert reply.text != reply.spoken_text


def test_chat_message_defaults_have_no_tool_calls() -> None:
    message = ChatMessage(role="user", content="hi")
    assert message.tool_calls == ()
    assert message.tool_call_id is None


def test_chat_message_can_carry_tool_calls() -> None:
    call = ToolCall(call_id="call_1", tool_name="calculator", arguments={"expression": "2+2"})
    message = ChatMessage(role="assistant", content=None, tool_calls=(call,))
    assert message.tool_calls == (call,)


@pytest.mark.parametrize(
    "instance",
    [
        UserInput(request_id="req_1", text="hi", source="typed", ts=_now()),
        Transcript(request_id="req_1", text="hi", confidence=None),
        ToolCall(call_id="call_1", tool_name="calculator", arguments={}),
        ToolResult(
            call_id="call_1",
            status="ok",
            data=None,
            error_code=None,
            error_message=None,
            duration_ms=1,
        ),
        AssistantReply(request_id="req_1", text="hi", spoken_text="hi"),
        ChatMessage(role="user", content="hi"),
    ],
)
def test_models_are_frozen(instance: object) -> None:
    first_field = fields(instance)[0].name
    with pytest.raises(FrozenInstanceError):
        setattr(instance, first_field, "mutated")
