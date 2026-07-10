"""Tests for FakeProvider — the scripted test double (docs/06 §8)."""

from __future__ import annotations

import pytest

from nova.core.errors import AuthError, Transient
from nova.core.models import ChatMessage
from nova.providers.base import GenerateOptions, LLMResponse, TokenUsage
from nova.providers.fake import FakeProvider


def _reply(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=(),
        finish_reason="stop",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
    )


def test_replays_scripted_responses_in_order() -> None:
    fake = FakeProvider("fake", [_reply("first"), _reply("second")])
    opts = GenerateOptions()
    messages = [ChatMessage(role="user", content="hi")]

    first = fake.generate(messages, [], opts)
    second = fake.generate(messages, [], opts)

    assert first.text == "first"
    assert second.text == "second"


def test_raises_scripted_provider_errors() -> None:
    fake = FakeProvider("fake", [Transient("boom"), _reply("recovered")])
    opts = GenerateOptions()
    messages = [ChatMessage(role="user", content="hi")]

    with pytest.raises(Transient):
        fake.generate(messages, [], opts)
    assert fake.generate(messages, [], opts).text == "recovered"


def test_raises_assertion_error_when_script_exhausted() -> None:
    fake = FakeProvider("fake", [_reply("only")])
    opts = GenerateOptions()
    messages = [ChatMessage(role="user", content="hi")]

    fake.generate(messages, [], opts)
    with pytest.raises(AssertionError):
        fake.generate(messages, [], opts)


def test_records_every_call() -> None:
    fake = FakeProvider("fake", [_reply("ok")])
    opts = GenerateOptions()
    messages = [ChatMessage(role="user", content="hi")]

    fake.generate(messages, [], opts)

    assert len(fake.calls) == 1
    assert fake.calls[0][0] == messages


def test_health_check_and_capabilities_defaults() -> None:
    fake = FakeProvider("fake", [])
    assert fake.health_check().available is True
    assert fake.capabilities.tool_calling is True


def test_any_provider_error_subtype_can_be_scripted() -> None:
    fake = FakeProvider("fake", [AuthError("bad key")])
    with pytest.raises(AuthError):
        fake.generate([], [], GenerateOptions())
