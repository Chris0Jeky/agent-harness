# HUMAN_TODO

Actions only the human can take. Agents add items here and never check them off.

Declared as this repo's human-action file in `.agent-harness/tier.json` (`human_todo`), so law 5
has a file to surface in every session summary.

## Open

- [ ] **H-1 — Re-trust the floor in a fresh session.** `main` carries floor **1.6.12**;
  `~/.claude/hooks/dispatch.py` still runs **1.6.5**, and both `.codex/hooks.json` pins changed.
  Start a new session in the exact CWD, confirm `/hooks` shows the expected active adapter, then
  run an allow/deny canary (something safe, and something the charter must block) before relying
  on it. Static analysis cannot substitute for this — `doctor`'s own docstring says so.

- [ ] **H-2 — Deploy the floor globally, after H-1.** `py -3 harness.py sync-global
  --config-root <claude-config checkout>` to preview, then `--apply`. Confirm `main` **and** a
  clean working tree first: `--apply` copies the checkout's *working tree* bytes, so an
  uncommitted edit ships as readily as a committed one.

- [ ] **H-3 — Push the pending `~/.claude` commit.** `e42e211` (ESTATE + memory updates) is
  committed but unpushed. It is blocked by a dirty `settings.json` holding a session's `/model`
  and `/effort` state; `effortLevel: xhigh` was explicitly session-only, so it should not be
  committed. Resolve that file, then `git pull --rebase && git push`.

- [ ] **H-4 — Prune accumulated worktrees.** `.worktrees/` only grows: `git worktree remove` is
  floor-blocked unconditionally and `relaxed_work_loss_guards` is false, so nothing but a human
  removes anything. Check each is clean and contained before removing, and never prune a
  checkout a live session holds. The guard itself is being fixed in **#41** — after that lands,
  a clean contained worktree can be removed by an agent and this item shrinks to the `--force`
  cases.

- [ ] **H-5 — Merge PR #71** (the cross-product gate, #63) once its exact-head CI is green. It is
  merged with main and green locally. Everything else from the 2026-07-25/26 session is landed.

## Done

_(nothing yet — this file was created 2026-07-26)_
