# HUMAN_TODO

Read at session start. Surface every open item in every session summary. **Only the human checks
an item off** — agents add items and append to the changelog, never tick a box.

Declared as this repo's human-action file in `.agent-harness/tier.json` (`human_todo`).

## Open

- [ ] **H-1** — Deploy floor **1.6.12** to `~/.claude/hooks` (installed floor was **1.6.5** when this was filed — but on 2026-07-26 a later session observed a live deny banner reporting **1.6.12** already running: confirm with `py -3 harness.py doctor` before re-applying; `sync-global --apply` copies the working tree, so never run it from a dirty checkout). See [HANDOFF.md](HANDOFF.md#human-gates-only-you-can-do-these). H-2 remains owed either way.
- [ ] **H-2** — After H-1, re-trust in a fresh session in the exact CWD (`/hooks`) and run a live allow/deny canary **against the newly deployed bytes**, per [SPECS §5](SPECS.md).
- [ ] **H-3** — Push the pending `~/.claude` commit `e42e211` (ESTATE + memory); blocked by a dirty `settings.json` holding session-only `effortLevel: xhigh`.
- [ ] **H-4** — Prune accumulated `.worktrees/` checkouts by hand until [#41](https://github.com/Chris0Jeky/agent-harness/issues/41) lands; never prune one a live session holds.
- [ ] **H-5** — Resolve the unresolved merge-conflict markers in `~/.claude/ESTATE.md` (agent-harness row, `<<<<<<< HEAD` vs `9170952…`) — law 9 sends every agent to that file first, and a conflicted registry is misleading authority. Found independently by two review lenses on 2026-07-26. Related: H-3, and the unmerged claude-config branch `policy/autonomy-first` (the ratified global-law rewrite) awaiting its merge + `sync-global` deploy.

## Changelog

- 2026-07-26 — File created and declared in `tier.json`; the repo had `human_todo: null`, so law 5
  had no file to surface. Seeded with the four gates left open by the floor 1.6.5 → 1.6.12 session.
- 2026-07-26 — H-1/H-2 order corrected: deploying after canarying meant the canary exercised the
  old 1.6.5 bytes and the new ones shipped untested. Deploy first, canary the deployed bytes.
- 2026-07-26 — Dropped an entry tracking PR #71's review triage: that is agent work, and an item
  no agent may check off would have become a permanent stale line. It lives in `HANDOFF.md`.
- 2026-07-26 (later session) — H-5 added. Also observed, for H-1/H-2: a live deny banner this
  session reported the running hook as floor **1.6.12**, so H-1's deploy appears already done;
  what remains human is H-2's fresh-session `/hooks` re-trust and canary confirmation.
