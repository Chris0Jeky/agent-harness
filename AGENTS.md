# Agent Harness

This repository is the runtime-neutral source for the tier model, safety floor, and portable
bootstrap/audit tooling used across Codex and Claude repositories.

## Where to look

Read what the task needs, not the whole stack; these files are large, so search them for the
section you need.

- `README.md` for executable commands and current shipped state.
- `BLUEPRINT.md` when a change touches durable policy: the tier ladder, laws, regions, routing,
  or the deny floor.
- `SPECS.md` before changing any contract it specifies: its `## §N` headings index the tier
  schema and root selection, budgets, skeletons, hook wiring, the deny-floor matrix, stop hooks,
  model routing, the harness CLI, Gardener, skill-forge, concurrency and the review pipeline.
- `BOOK.md` only when the rationale behind a policy is needed.
- Never run anything in `legacy/`; those scripts are historical source material.

## Change rules

- `templates/hooks/dispatch.py` is shared infrastructure. Any change requires its smoke suite,
  harness unit tests, and an independent read-only review. It is feature-frozen (BLUEPRINT.md,
  "FEATURE-FROZEN"): only false-positive fixes, the ratified #21 slices and SPECS §6 charter
  repairs may change it; a newly found bypass family becomes one line in `FLOOR_LIMITATIONS.md`.
- Keep `harness.py` dependency-free and portable across Windows/macOS/Linux.
- Do not hard-code a user profile. Discover `$HOME`, `$CODEX_HOME`, and Git roots at runtime.
- `seed` must be write-once. `sync-global` must show a dry-run and back up overwritten files.
- Codex and Claude may share policy and parsing, but runtime-specific hook output stays explicit.
- When a repo's PreTool floor is enabled, a new-session exact-CWD `/hooks` review, individual
  trust/re-trust, enabled-state confirmation, and then live allow/deny canaries are mandatory; a
  disabled floor has no runtime claim and is not canaried until it is re-enabled.
- Add a test with every new enforcement or migration behavior.

## Verify

While iterating, run the tests for the module you changed. Before pushing, run the full set
below once, and rerun it after any further change.

```powershell
py -3 -m unittest discover -s tests -v
py -3 templates\hooks\smoke_test.py
py -3 harness.py doctor
```

Small, present-tense commits are expected. Pushes are allowed; merge policy is declared in
`.agent-harness/tier.json`.
