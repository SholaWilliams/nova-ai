"""System tests (docs/13 §5): one real Gemini call, one real Groq call, one fallback drill.

Marker `live` — manual trigger only, never runs in CI (docs/13 §1's iron rule: "CI never
calls paid/keyed APIs"). Run once real keys are present in `.env` / the environment:

    uv run pytest -m live tests/system/test_live_providers.py -v

Individual tests skip gracefully (rather than failing) when their required key is missing.
"""

from __future__ import annotations

import pytest

from nova.core.config import Secrets
from nova.core.models import ChatMessage
from nova.providers.base import GenerateOptions
from nova.providers.gemini import GeminiProvider
from nova.providers.groq import GroqProvider
from nova.providers.manager import ProviderManager

pytestmark = pytest.mark.live

_SECRETS = Secrets.load()
_OPTS = GenerateOptions(max_tokens=50)
_MESSAGES = [ChatMessage(role="user", content="Say 'hello' and nothing else.")]


@pytest.mark.skipif(not _SECRETS.gemini_api_key, reason="NOVA_GEMINI_API_KEY not configured")
def test_real_gemini_call_returns_text() -> None:
    provider = GeminiProvider(api_key=_SECRETS.gemini_api_key, model="gemini-3.5-flash")

    result = provider.generate(_MESSAGES, [], _OPTS)

    assert result.text
    assert result.finish_reason in ("stop", "length")


@pytest.mark.skipif(not _SECRETS.groq_api_key, reason="NOVA_GROQ_API_KEY not configured")
def test_real_groq_call_returns_text() -> None:
    provider = GroqProvider(api_key=_SECRETS.groq_api_key, model="openai/gpt-oss-120b")

    result = provider.generate(_MESSAGES, [], _OPTS)

    assert result.text
    assert result.finish_reason in ("stop", "length")


@pytest.mark.skipif(
    not (_SECRETS.gemini_api_key and _SECRETS.groq_api_key),
    reason="both NOVA_GEMINI_API_KEY and NOVA_GROQ_API_KEY must be configured for a fallback drill",
)
def test_fallback_drill_invalid_primary_key_falls_back_to_working_secondary() -> None:
    bad_gemini = GeminiProvider(api_key="invalid-key-for-fallback-drill", model="gemini-3.5-flash")
    real_groq = GroqProvider(api_key=_SECRETS.groq_api_key, model="openai/gpt-oss-120b")
    manager = ProviderManager({"gemini": bad_gemini, "groq": real_groq}, active="gemini")
    statuses = []
    manager.status_changed.connect(statuses.append)

    result = manager.generate(_MESSAGES, [], _OPTS)

    assert result.text
    assert statuses[-1].mode == "fallback"
    assert statuses[-1].active == "groq"
