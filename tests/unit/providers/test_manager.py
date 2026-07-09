"""Tests for ProviderManager's selection/retry/fallback/cooldown state machine (docs/10 §3)."""

from __future__ import annotations

import time

import pytest

from nova.core.errors import AuthError, RateLimited, SafetyBlocked, Transient
from nova.core.models import ChatMessage, ProviderStatus
from nova.providers.base import GenerateOptions, LLMResponse, TokenUsage
from nova.providers.fake import FakeProvider
from nova.providers.manager import ProviderManager

_MESSAGES = [ChatMessage(role="user", content="hi")]
_OPTS = GenerateOptions()


def _reply(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=(), finish_reason="stop", usage=TokenUsage(10, 5))


def test_happy_path_uses_primary_and_reports_normal_status() -> None:
    gemini = FakeProvider("gemini", [_reply("hello")])
    manager = ProviderManager({"gemini": gemini}, active="gemini")
    statuses: list[ProviderStatus] = []
    manager.status_changed.connect(statuses.append)

    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "hello"
    assert statuses[-1] == ProviderStatus(active="gemini", mode="normal", detail="Gemini")


def test_transient_error_retries_once_same_provider_then_succeeds() -> None:
    gemini = FakeProvider("gemini", [Transient("blip"), _reply("recovered")])
    manager = ProviderManager({"gemini": gemini}, active="gemini")

    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "recovered"
    assert len(gemini.calls) == 2


def test_rate_limited_honors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    gemini = FakeProvider("gemini", [RateLimited("slow down", retry_after=5.0), _reply("ok")])
    manager = ProviderManager({"gemini": gemini}, active="gemini")

    manager.generate(_MESSAGES, [], _OPTS)

    assert sleeps == [5.0]


def test_auth_error_skips_retry_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    gemini = FakeProvider("gemini", [AuthError("bad key")])
    groq = FakeProvider("groq", [_reply("from groq")])
    manager = ProviderManager({"gemini": gemini, "groq": groq}, active="gemini")

    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "from groq"
    assert len(gemini.calls) == 1  # no retry attempted


def test_primary_failure_falls_back_and_reports_fallback_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    gemini = FakeProvider("gemini", [Transient("down"), Transient("still down")])
    groq = FakeProvider("groq", [_reply("from groq")])
    manager = ProviderManager({"gemini": gemini, "groq": groq}, active="gemini")
    statuses: list[ProviderStatus] = []
    manager.status_changed.connect(statuses.append)

    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "from groq"
    assert statuses[-1] == ProviderStatus(active="groq", mode="fallback", detail="Groq (fallback)")


def test_primary_cooling_skips_straight_to_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    gemini = FakeProvider(
        "gemini", [Transient("down"), Transient("still down"), _reply("should not be reached")]
    )
    groq = FakeProvider("groq", [_reply("first fallback"), _reply("second fallback")])
    manager = ProviderManager({"gemini": gemini, "groq": groq}, active="gemini")

    manager.generate(_MESSAGES, [], _OPTS)  # primary fails -> cools -> fallback
    manager.generate(_MESSAGES, [], _OPTS)  # primary still cooling -> straight to fallback

    assert len(gemini.calls) == 2  # only the first request's attempt (+ its 1 retry)
    assert len(groq.calls) == 2


def test_primary_probed_again_after_cooldown_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    gemini = FakeProvider("gemini", [Transient("down"), Transient("still down"), _reply("back")])
    groq = FakeProvider("groq", [_reply("fallback")])
    manager = ProviderManager({"gemini": gemini, "groq": groq}, active="gemini")

    manager.generate(_MESSAGES, [], _OPTS)  # primary fails, cools for 60s
    fake_now[0] += 61.0
    result = manager.generate(_MESSAGES, [], _OPTS)  # cooldown expired -> primary probed again

    assert result.text == "back"


def test_both_providers_failing_raises_and_reports_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    gemini = FakeProvider("gemini", [Transient("down"), Transient("still down")])
    groq = FakeProvider("groq", [Transient("also down")])
    manager = ProviderManager({"gemini": gemini, "groq": groq}, active="gemini")
    statuses: list[ProviderStatus] = []
    manager.status_changed.connect(statuses.append)

    with pytest.raises(Transient):
        manager.generate(_MESSAGES, [], _OPTS)

    assert statuses[-1].mode == "down"


def test_no_provider_configured_raises_with_friendly_message() -> None:
    manager = ProviderManager({}, active="gemini")

    with pytest.raises(Exception, match="no provider configured"):
        manager.generate(_MESSAGES, [], _OPTS)


def test_selected_primary_missing_key_uses_the_other_configured_provider() -> None:
    groq = FakeProvider("groq", [_reply("only option")])
    manager = ProviderManager({"groq": groq}, active="gemini")  # gemini selected, no key

    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "only option"


def test_safety_blocked_never_retries_never_cools_never_falls_back() -> None:
    gemini = FakeProvider("gemini", [SafetyBlocked("nope")])
    groq = FakeProvider("groq", [_reply("should not be called")])
    manager = ProviderManager({"gemini": gemini, "groq": groq}, active="gemini")

    with pytest.raises(SafetyBlocked):
        manager.generate(_MESSAGES, [], _OPTS)

    assert len(gemini.calls) == 1
    assert len(groq.calls) == 0


def test_set_active_hot_swaps_the_primary() -> None:
    gemini = FakeProvider("gemini", [_reply("gemini says hi")])
    groq = FakeProvider("groq", [_reply("groq says hi")])
    manager = ProviderManager({"gemini": gemini, "groq": groq}, active="gemini")

    manager.set_active("groq")
    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text == "groq says hi"
    assert manager.active_name == "groq"


def test_check_health_reports_no_key_configured_for_unconfigured_provider() -> None:
    manager = ProviderManager({}, active="gemini")

    available, detail = manager.check_health("gemini")

    assert available is False
    assert detail == "No key configured"
