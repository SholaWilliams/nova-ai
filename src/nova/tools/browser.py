"""browser: open websites / web searches in the default browser (docs/07 §5)."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable, Sequence
from typing import Literal
from urllib.parse import quote_plus, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from nova.core.errors import ToolError
from nova.tools.base import Tool, ToolContext, ToolOutput, ToolSpec

# Safe-search on (kp=1), no account needed — kid-safer default per docs/07 §5.
_SEARCH_URL = "https://duckduckgo.com/?q={query}&kp=1"


class BrowserParams(BaseModel):
    """Arguments for the browser tool."""

    action: Literal["open_url", "search"] = Field(
        description="'open_url' opens a website address; 'search' looks something up on the web."
    )
    target: str = Field(description="The URL to open, or the search words.")


class BrowserTool(Tool):
    """stdlib `webbrowser` only; URLs forced to https; DuckDuckGo safe search."""

    spec = ToolSpec(
        name="browser",
        title="Web Browser",
        description=(
            "Open a website or search the web in the user's browser. Use when the user asks "
            "to look something up online or open a site, e.g. 'search for how volcanoes "
            "work' or 'open wikipedia.org'."
        ),
        parameters=BrowserParams,
        sensitive=False,
        icon="globe",
        detail_template="Opening the web browser",
    )

    def __init__(
        self,
        blocked_domains: Sequence[str] = (),
        opener: Callable[[str], bool] = webbrowser.open,
    ) -> None:
        # blocked_domains: presenter-extendable hook, empty by default (docs/07 §5).
        self._blocked = tuple(d.lower().lstrip(".") for d in blocked_domains)
        self._opener = opener  # test seam

    def execute(self, args: BaseModel, ctx: ToolContext) -> ToolOutput:
        del ctx
        assert isinstance(args, BrowserParams)
        target = args.target.strip()
        if not target:
            raise ToolError("The target was empty.", code="invalid_url")

        if args.action == "search":
            url = _SEARCH_URL.format(query=quote_plus(target))
            summary = f"Searching the web for '{target}'"
            kind = "search"
        else:
            url = self._normalize_url(target)
            summary = f"Opening {urlsplit(url).netloc}"
            kind = "url"

        self._check_blocklist(url)

        try:
            opened = self._opener(url)
        except Exception as exc:
            raise ToolError(f"Couldn't open the browser: {exc}", code="browser_error") from exc
        if not opened:
            raise ToolError("The browser refused to open.", code="browser_error")

        return ToolOutput(data={"opened": url, "kind": kind, "summary": summary})

    def _normalize_url(self, target: str) -> str:
        candidate = target if "//" in target else f"https://{target}"
        parts = urlsplit(candidate)
        if parts.scheme not in ("http", "https") or not parts.netloc or "." not in parts.netloc:
            raise ToolError(f"{target!r} doesn't look like a website address.", code="invalid_url")
        # scheme forced to https — no plain-http surface (docs/07 §5)
        return urlunsplit(("https", parts.netloc, parts.path, parts.query, parts.fragment))

    def _check_blocklist(self, url: str) -> None:
        host = urlsplit(url).netloc.lower().split(":")[0]
        for domain in self._blocked:
            if host == domain or host.endswith(f".{domain}"):
                raise ToolError(f"The site {host!r} is blocked.", code="blocked_domain")
