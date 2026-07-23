"""Scrub real secret values out of a recorded golden fixture before committing it (S-6).

Usage: uv run python scripts/scrub_fixture.py <fixture.json> [<fixture.json> ...]

Run after any `-m record` test regenerates a fixture, before committing the diff — review the
diff too (CODING_STANDARDS.md: "regenerated only via -m record with a diff review").
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from nova.core.config import Secrets

# Regex safety net for common provider key prefixes, in case a derived/rotated token slips
# past the exact-value replacement below (mirrors core.logging's secret-scrubber approach).
_KEY_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),  # Gemini API keys
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),  # Groq API keys
]

_PLACEHOLDER = "***SCRUBBED***"  # noqa: S105 - a placeholder marker, not a credential


def scrub_text(text: str, secrets: Secrets) -> str:
    for real_value in (secrets.omniroute_api_key, secrets.groq_api_key):
        if real_value:
            text = text.replace(real_value, _PLACEHOLDER)
    for pattern in _KEY_PATTERNS:
        text = pattern.sub(_PLACEHOLDER, text)
    return text


def main(paths: list[str]) -> int:
    if not paths:
        print("usage: scrub_fixture.py <fixture.json> [<fixture.json> ...]", file=sys.stderr)
        return 1

    secrets = Secrets.load()
    for raw_path in paths:
        path = Path(raw_path)
        original = path.read_text(encoding="utf-8")
        scrubbed = scrub_text(original, secrets)
        if scrubbed != original:
            path.write_text(scrubbed, encoding="utf-8")
            print(f"scrubbed: {path}")
        else:
            print(f"clean (no change): {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
