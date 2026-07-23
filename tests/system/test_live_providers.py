"""System tests (docs/13 §5): one real OmniRoute call, one bad-key check.

Marker `live` — manual trigger only, never runs in CI (docs/13 §1's iron rule: "CI never
calls paid/keyed APIs"). Run once a real key is present in `.env` / the environment and
the local OmniRoute gateway is running:

    uv run pytest -m live tests/system/test_live_providers.py -v

Individual tests skip gracefully (rather than failing) when the key is missing. M9 removed
the multi-provider fallback drill this file used to cover (docs/04 TD-4: OmniRoute is the
sole backend, no cloud fallback) — a bad key now just fails, there's no second provider to
hand off to.
"""

from __future__ import annotations

import pytest

from nova.core.config import Secrets
from nova.core.errors import AuthError
from nova.core.models import ChatMessage
from nova.providers.base import GenerateOptions
from nova.providers.omniroute import OmniRouteProvider

pytestmark = pytest.mark.live

_SECRETS = Secrets.load()
_OPTS = GenerateOptions(max_tokens=50)
_MESSAGES = [ChatMessage(role="user", content="Say 'hello' and nothing else.")]


@pytest.mark.skipif(not _SECRETS.omniroute_api_key, reason="NOVA_OMNIROUTE_API_KEY not configured")
def test_real_omniroute_call_returns_text() -> None:
    provider = OmniRouteProvider(
        base_url="http://127.0.0.1:20128", api_key=_SECRETS.omniroute_api_key, model="auto/coding"
    )

    result = provider.generate(_MESSAGES, [], _OPTS)

    assert result.text
    assert result.finish_reason in ("stop", "length")


@pytest.mark.skipif(not _SECRETS.omniroute_api_key, reason="NOVA_OMNIROUTE_API_KEY not configured")
def test_bad_key_raises_auth_error() -> None:
    provider = OmniRouteProvider(
        base_url="http://127.0.0.1:20128", api_key="invalid-key-for-live-drill", model="auto/coding"
    )

    with pytest.raises(AuthError):
        provider.generate(_MESSAGES, [], _OPTS)
