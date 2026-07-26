# HUMAN_TODO

Read at session start. Surface every open item in every session summary. **Only the human checks
an item off** — agents add items and append to the changelog, never tick a box.

Declared as this repo's human-action file in `.agent-harness/tier.json` (`human_todo`).

## Open

- [ ] **H-1** — Deploy floor **1.6.12** to `~/.claude/hooks` (installed floor is still **1.6.5**): `py -3 harness.py sync-global --config-root <claude-config checkout>` to preview, then `--apply`, from a clean `main`. See [HANDOFF.md](HANDOFF.md#human-gates-only-you-can-do-these).
- [ ] **H-2** — After H-1, re-trust in a fresh session in the exact CWD (`/hooks`) and run a live allow/deny canary **against the newly deployed bytes**, per [SPECS §5](SPECS.md).
- [ ] **H-3** — Push the pending `~/.claude` commit `e42e211` (ESTATE + memory); blocked by a dirty `settings.json` holding session-only `effortLevel: xhigh`.
- [ ] **H-4** — Prune accumulated `.worktrees/` checkouts by hand until [#41](https://github.com/Chris0Jeky/agent-harness/issues/41) lands; never prune one a live session holds.

## Changelog

- 2026-07-26 — File created and declared in `tier.json`; the repo had `human_todo: null`, so law 5
  had no file to surface. Seeded with the four gates left open by the floor 1.6.5 → 1.6.12 session.
- 2026-07-26 — H-1/H-2 order corrected: deploying after canarying meant the canary exercised the
  old 1.6.5 bytes and the new ones shipped untested. Deploy first, canary the deployed bytes.
- 2026-07-26 — Dropped an entry tracking PR #71's review triage: that is agent work, and an item
  no agent may check off would have become a permanent stale line. It lives in `HANDOFF.md`.
