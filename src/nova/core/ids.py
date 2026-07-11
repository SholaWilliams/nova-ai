"""ID generation shared by every caller that starts a new request/fact/session (docs/11 §1,
docs/09 §3)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime


def new_request_id() -> str:
    return f"req_{secrets.token_hex(4)}"


def new_fact_id() -> str:
    """docs/09 §3 `facts.json` example: `"f_9c2e1a"` (3 bytes hex)."""
    return f"f_{secrets.token_hex(3)}"


def new_session_id() -> str:
    """docs/09 §3 example filename: `"2026-07-08_a3f2.jsonl"` (date + 2 bytes hex)."""
    return f"{datetime.now(UTC):%Y-%m-%d}_{secrets.token_hex(2)}"
