# Agent Harness

This repository is the runtime-neutral source for the tier model, safety floor, and portable
bootstrap/audit tooling used across Codex and Claude repositories.

## Read first

- `README.md` for executable commands and current shipped state.
- `BLUEPRINT.md` for durable policy and `SPECS.md` for schemas and budgets.
- Read `BOOK.md` only when the rationale behind a policy is needed.
- Never run anything in `legacy/`; those scripts are historical source material.

## Change rules

- `templates/hooks/dispatch.py` is shared infrastructure. Any change requires its smoke suite,
  harness unit tests, and an independent read-only review.
- Keep `harness.py` dependency-free and portable across Windows/macOS/Linux.
- Do not hard-code a user profile. Discover `$HOME`, `$CODEX_HOME`, and Git roots at runtime.
- `seed` must be write-once. `sync-global` must show a dry-run and back up overwritten files.
- Codex and Claude may share policy and parsing, but runtime-specific hook output stays explicit.
- Add a test with every new enforcement or migration behavior.

## Verify

```powershell
py -3 -m unittest discover -s tests -v
py -3 templates\hooks\smoke_test.py
py -3 harness.py doctor
```

Small, present-tense commits are expected. Pushes are allowed; merge policy is declared in
`.agent-harness/tier.json`.
