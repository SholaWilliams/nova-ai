"""Request-ID generation shared by every caller that starts a new request (docs/11 §1)."""

from __future__ import annotations

import secrets


def new_request_id() -> str:
    return f"req_{secrets.token_hex(4)}"
