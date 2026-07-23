"""Tests for ProviderManager's single-provider retry + status reporting (docs/10 §3, M9).

M2-M8's primary/fallback/cooldown state machine across multiple providers is gone — with
OmniRoute as the sole backend there's nothing left to fall back to. What remains: retry-once
on a transient failure, no retry on auth errors, `SafetyBlocked` never retries, and status
reporting for the UI.
"""

from __future__ import annotations

import time

import pytest

from nova.core.errors import AuthError, ProviderError, RateLimited, SafetyBlocked, Transient
from nova.core.models import ChatMessage, ProviderStatus
from nova.providers.base import GenerateOptions, LLMResponse, TokenUsage
from nova.providers.fake import FakeProvider
from nova.providers.manager import ProviderManager

_MESSAGES = [ChatMessage(role="user", content="hi")]
_OPTS = GenerateOptions()


def _reply(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=(), finish_reason="stop", usage=TokenUsage(10, 5))


def test_happy_path_reports_normal_status() -> None:
    omniroute = FakeProvider("omniroute", [_reply("hello")])
    manager = ProviderManager(omniroute)
    statuses: list[ProviderStatus] = []
    manager.status_changed.connect(statuses.append)

    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "hello"
    assert statuses[-1] == ProviderStatus(active="omniroute", mode="normal", detail="OmniRoute")


def test_transient_error_retries_once_then_succeeds() -> None:
    omniroute = FakeProvider("omniroute", [Transient("blip"), _reply("recovered")])
    manager = ProviderManager(omniroute)

    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "recovered"
    assert len(omniroute.calls) == 2


def test_rate_limited_honors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    omniroute = FakeProvider("omniroute", [RateLimited("slow down", retry_after=5.0), _reply("ok")])
    manager = ProviderManager(omniroute)

    manager.generate(_MESSAGES, [], _OPTS)

    assert sleeps == [5.0]


def test_auth_error_skips_retry_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    omniroute = FakeProvider("omniroute", [AuthError("bad key")])
    manager = ProviderManager(omniroute)

    with pytest.raises(AuthError):
        manager.generate(_MESSAGES, [], _OPTS)

    assert len(omniroute.calls) == 1  # no retry attempted


def test_retry_also_failing_raises_and_reports_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    omniroute = FakeProvider("omniroute", [Transient("down"), Transient("still down")])
    manager = ProviderManager(omniroute)
    statuses: list[ProviderStatus] = []
    manager.status_changed.connect(statuses.append)

    with pytest.raises(Transient):
        manager.generate(_MESSAGES, [], _OPTS)

    assert statuses[-1].mode == "down"


def test_no_provider_configured_raises_with_friendly_message() -> None:
    manager = ProviderManager(None)

    with pytest.raises(ProviderError, match="no provider configured"):
        manager.generate(_MESSAGES, [], _OPTS)


def test_safety_blocked_never_retries() -> None:
    omniroute = FakeProvider("omniroute", [SafetyBlocked("nope")])
    manager = ProviderManager(omniroute)

    with pytest.raises(SafetyBlocked):
        manager.generate(_MESSAGES, [], _OPTS)

    assert len(omniroute.calls) == 1


def test_check_health_reports_no_key_configured_when_no_provider() -> None:
    manager = ProviderManager(None)

    available, detail = manager.check_health()

    assert available is False
    assert detail == "No key configured"


def test_configured_reflects_whether_a_provider_was_given() -> None:
    assert ProviderManager(FakeProvider("omniroute", [])).configured is True
    assert ProviderManager(None).configured is False


def test_set_provider_registers_a_previously_unconfigured_provider() -> None:
    manager = ProviderManager(None)

    manager.set_provider(FakeProvider("omniroute", [_reply("hello")]))
    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "hello"
    assert manager.configured is True


def test_set_provider_replaces_an_existing_provider_instance() -> None:
    old = FakeProvider("omniroute", [_reply("should not be called")])
    manager = ProviderManager(old)

    manager.set_provider(FakeProvider("omniroute", [_reply("rotated key")]))
    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "rotated key"
    assert len(old.calls) == 0


def test_set_provider_none_clears_the_configured_provider() -> None:
    manager = ProviderManager(FakeProvider("omniroute", []))

    manager.set_provider(None)

    assert manager.configured is False
