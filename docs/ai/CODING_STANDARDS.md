# CODING_STANDARDS.md — Style & Idiom (humans and AI agents)

Single source for code style (referenced by CONTRIBUTING and Phase 17). Mechanics are enforced by `ruff` (lint + format) and `mypy` — this file covers what tools can't check.

## Python

- **Python 3.12**, `ruff format` formatting (don't hand-format), line length 100.
- Type hints on all public functions/methods; `mypy --strict` zone: `core/`, `agent/` — keep it strict, don't `# type: ignore` your way out (justify any ignore with a comment).
- **Data shapes:** frozen `@dataclass` for cross-thread transfer/events; Pydantic `BaseModel` at validated boundaries (tool params/outputs, settings, external APIs). Naked dicts don't cross layer boundaries.
- **Errors:** raise `NovaError` subtypes at layer boundaries; never bare `except:`; catch narrowly, re-raise with context. User-visible failure = pipeline ERROR event + friendly message, never a stack trace.
- Naming: modules/functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE`; tool names `^[a-z][a-z0-9_]{2,30}$`.
- Docstrings (Google style) on every public class/function — one line for the *what*, body for the *why* when non-obvious. `pdoc` builds the API reference from these.
- No module-level side effects (imports must be free to happen anywhere); composition only in `app.py`.

## Qt / PySide6

- Widgets and any `QObject` UI state: main thread only. Cross-thread = signals carrying frozen dataclasses via queued connections — never direct method calls into another thread's objects.
- Animations: use the shared helpers in `ui/animations.py` and motion tokens from `theme.py` — no ad-hoc durations/easings (Phase 5 §8 budget).
- Styling through theme tokens/QSS — no hardcoded hex values in widget code.
- Every `connect` has a matching lifecycle owner; long-lived subscribers to the EventBus must unsubscribe (RAM trend test will catch you).

## Tests

- Test names state behavior: `test_denied_confirmation_returns_denied_result`, not `test_executor_2`.
- Fakes over mocks (Phase 13 §2); patch only at true process edges.
- Every bug fix lands with the test that would have caught it.
- Golden fixtures are committed, scrubbed, and regenerated only via `-m record` with a diff review.

## Copy & content

- Child-facing strings: Phase 5 §9 rules (≤ 10-word stage details, no jargon, blame-free errors). Copy lives where the feature's spec says — not scattered inline.
- Comments explain constraints and *why*, never narrate the next line. Match the file's existing density.

## Commits & PRs

- Conventional Commits: `feat|fix|docs|test|refactor|chore(scope): imperative summary` — scope = package (`tools`, `agent`, `ui`, …).
- One logical change per PR; PR description says what + why + how verified; template checklist completed honestly.
