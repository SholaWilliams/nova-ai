## What & why

<!-- One paragraph. Link the issue: Closes #NN -->

## How verified

<!-- Commands run, tests added, manual checks. "CI is green" alone is not verification of behavior. -->

## Checklist

- [ ] Quality gates green locally (`ruff`, `mypy` core/agent, `lint-imports`, `pytest`)
- [ ] Tests included (bug fix ⇒ the test that would have caught it)
- [ ] Docs synced in this PR (owning doc updated, or "no behavior change")
- [ ] Contracts untouched — or version bump + migration + golden tests updated (P-3)
- [ ] No new dependencies — or TD entry added to docs/04 (P-6)
- [ ] Child-facing copy follows docs/05 §9 (or none added)
- [ ] Safety invariants S-1…S-8 untouched (docs/ai/PROJECT_RULES.md)
- [ ] Pipeline events emitted only from code doing the actual work (S-8)

## Screenshots / recording

<!-- Required for UI changes: before/after, or a short capture of the pipeline behaving. -->
