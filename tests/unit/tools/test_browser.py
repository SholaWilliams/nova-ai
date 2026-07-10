"""browser: URL normalization, safe search, blocklist, error codes (docs/07 §5)."""

from __future__ import annotations

import pytest

from nova.core.errors import ToolError
from nova.tools.base import ToolContext
from nova.tools.browser import BrowserParams, BrowserTool


class _Opener:
    def __init__(self, result: bool = True) -> None:
        self.urls: list[str] = []
        self._result = result

    def __call__(self, url: str) -> bool:
        self.urls.append(url)
        return self._result


def test_search_uses_duckduckgo_safe_search(ctx: ToolContext) -> None:
    opener = _Opener()
    data = (
        BrowserTool(opener=opener)
        .execute(BrowserParams(action="search", target="how volcanoes work"), ctx)
        .data
    )
    assert opener.urls == ["https://duckduckgo.com/?q=how+volcanoes+work&kp=1"]
    assert data["kind"] == "search"
    assert "volcanoes" in data["summary"]


def test_open_url_forces_https(ctx: ToolContext) -> None:
    opener = _Opener()
    BrowserTool(opener=opener).execute(
        BrowserParams(action="open_url", target="http://example.com/page"), ctx
    )
    assert opener.urls == ["https://example.com/page"]


def test_bare_domain_gets_scheme(ctx: ToolContext) -> None:
    opener = _Opener()
    BrowserTool(opener=opener).execute(
        BrowserParams(action="open_url", target="wikipedia.org"), ctx
    )
    assert opener.urls == ["https://wikipedia.org"]


def test_invalid_url(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        BrowserTool(opener=_Opener()).execute(
            BrowserParams(action="open_url", target="not a url"), ctx
        )
    assert excinfo.value.code == "invalid_url"


def test_blocked_domain_and_subdomain(ctx: ToolContext) -> None:
    tool = BrowserTool(blocked_domains=["example.com"], opener=_Opener())
    for target in ("example.com", "sub.example.com"):
        with pytest.raises(ToolError) as excinfo:
            tool.execute(BrowserParams(action="open_url", target=target), ctx)
        assert excinfo.value.code == "blocked_domain"


def test_browser_refuses(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        BrowserTool(opener=_Opener(result=False)).execute(
            BrowserParams(action="search", target="cats"), ctx
        )
    assert excinfo.value.code == "browser_error"
