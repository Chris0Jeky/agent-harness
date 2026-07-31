# Handoff: workbench pivot continuity — 2026-07-31

Refresh refs, PRs, issues, checks, reviews, comments, threads, worktrees, and tier declarations
before acting. This is a factual checkpoint, not authority to reuse stale gate evidence.

## End-to-end objective and invariants

- Operate `agent-harness` as the agent-operations workbench: frozen legacy floor, internal replay
  Policy Lab, Doctor, estate operations, bounded Pattern Guard v2, measurement, adapters, and
  private integration through small executable slices.
- Authority at this snapshot is T3 with `push: free` and `merge: free`. Preserve commits with merge
  commits; never squash, use admin/auto merge, or delete a PR branch during merge.
- Never post routine `@codex review`. Every changed head/base needs scoped proof, three-minute aging,
  one bounded review pipeline, green required CI, and one comments/reviews/threads triage.
- Keep at most two active workstreams and one writer per checkout.
- Do not expand the universal parser, activate global blocking, start blueprint-plugin extraction,
  or create a public replay repository.
- H-2 is the only open `HUMAN_TODO.md` item and is owner-parked. Do not restart estate-wide
  canaries or disable the harness.

## Completed and directly verified

- PR #140 merged as `81125c57ec6d1a750ddd43b0110c6928f9f4a860`; `origin/main` contains
  `fd87e06c1c55ceed5cef3c736710b513317f3c89` and every successor. #148/#149 closed, all
  27 original threads were resolved, and the post-merge late-feedback check was empty.
- PR #159 merged as `8d4b69d147b4f1e930b3388e5b3ce7d2661ab82e`, preserved head
  `e0f8fa5ab75147085d3bfcc5aaa0d7ebcb8222f6`, passed nine-job run `30626399786`, and closed #153.
- PR #161 merged as `bea61078937a93aa73e2015ac533f2c9d061f5e8`, preserved head
  `416046b746280422348419619a9cab286fa75617`, passed run `30627690916`, and closed #87.
  Non-blocking follow-ups #164/#165 remain open.
- PR #163 merged as `347ab97cfc800dcc3621ffd15d041f4e949e3fd6`, preserved implementation
  `d41d311e2a3a929dbd2724e9d62cc8140a825458`, passed run `30628366731`, and closed #144.
- PR #162 merged as `bb20cdd2528d7191a74a4dd2486bb622d6e80df1`, with parents `347ab97` and
  `c58a0ea`, preserving every guarded-closeout commit. Run `30629391405` passed all nine jobs and
  #151 closed. Its late review found preservation defects; every thread was triaged once.
- PR #169 repaired those confirmed work-loss paths and merged as
  `27ec3b6b0c8430058b4aa2570b0f4a9dda66938f`, with parents `bb20cdd` and
  `cb43065c6d06675e0cff1393628512778ec767ae`. All four branch commits were preserved. Exact-head
  local gates passed 842 tests with 13 skips and 2237/2237 smoke cases; hosted run `30634860134`
  passed all nine jobs. All six connector threads were triaged and resolved, #166 closed, and the
  one post-merge late-feedback check found nothing new. #170/#171/#172 hold the non-blocking work.
- The protected `floor-v1-final` tag remains object
  `5a939540bdce51e511d6b3bae98358e3e2ad9148`, peeled
  `02bd14cfe094f9b6af85b966de481ff3f45264cf`.

## Live state and canonical homes

- Published `main` at this snapshot: `27ec3b6b0c8430058b4aa2570b0f4a9dda66938f`.
- GitHub has 68 open issues. `ROADMAP.md` maps each exactly once to AH-1 through AH-8; AH-9/AH-10
  are secondary/deferred seams.
- The only open PRs are parked predecessors #154 and #155. #154 is superseded by merged #162;
  #155 is superseded by merged #161. Do not revive either.
- Current state: `docs/SYSTEM_STATE.md`. Issue/PR ownership: `ROADMAP.md`. Active/queued work:
  `plans/ACTIVE.md`. Measurements: `docs/BENCHMARKS.md`. Legacy limitations:
  `FLOOR_LIMITATIONS.md`. Root `HANDOFF.md` remains historical/stale and was not rewritten.
- The continuity branch `docs/workbench-continuity-20260731` is the sole active writer until its
  PR lands or parks. If this document is already on `main`, refresh live state and treat that
  workstream as complete rather than recreating it.

## Continuity slice

The branch normally merged `origin/main@27ec3b6` and changes only:

- `.agent-harness/tier.json`, `README.md`, `FLOOR_LIMITATIONS.md`;
- `docs/SYSTEM_STATE.md`, `ROADMAP.md`, `plans/ACTIVE.md`, `docs/BENCHMARKS.md`;
- this dated handoff.

It adds no runtime behavior, fixture, corpus, deployment, or benchmark result. Before publication,
prove the 68-entry issue map, document budgets, tier JSON, exact diff, offline audit, Doctor, one
fresh-context review, required hosted CI, three-minute head age, and one comment/thread triage.

## Occupied worktrees

- Primary checkout: preserve user state; it may lag `origin/main` until the owner advances it.
- `crossproduct-gate`: tracked-clean historical test branch; remote branch is gone.
- `issue27-temporal-config`: tracked-clean occupied historical branch.
- `replay-tool`: user-owned staged `scripts/replay_corpus.py`; never reset, restore, stash, or remove.
- `replay-v0-freeze`: contains ignored `.local/` evidence plus caches and a recovery commit detected
  by the guarded audit. It was deliberately left untouched; never remove it without separately
  proving and preserving everything needed outside the worktree.
- `workbench-continuity-20260731`: current writer checkout until the continuity PR lands.

The #162/#169 writer worktrees were removed with plain `git worktree remove` only after tracked,
untracked, and ignored inspection showed nothing except disposable test caches. No parked branch
was deleted.

## Exact next safe slice after continuity

Issue #152 is the recommended next executable slice.

- **Observable outcome:** every replay report exposes structured reproduction argv plus an
  explicitly labelled platform-valid rendering; Windows paths with spaces do not use POSIX
  single-quote semantics.
- **Evidence:** #152 records that `shlex.join()` is currently used for every host and can produce a
  non-runnable `cmd.exe` command.
- **In:** `replay_v0/cli.py`, `replay_v0/reports.py`, exact Windows/POSIX rendering tests, a path
  containing spaces, and direct execution proof where the host supports it.
- **Out:** a general shell parser, universal command grammar, policy-process argv changes, private
  paths, and operational outputs in committed fixtures.
- **Architecture seam:** reproduction argv construction and Markdown rendering; structured argv is
  the portable source of truth.
- **Tests/fixtures/corpus:** add public synthetic fixtures only; no private corpus change.
- **Measurement:** record host, rendered form, and whether the fixture invocation executed.
- **Limitation:** one string cannot be portable across PowerShell, `cmd.exe`, and POSIX shells.
- **Exact verification:** `py -3 -m unittest replay_v0.tests.unit.test_compare replay_v0.tests.contract.test_cli -v` and `py -3 -m pytest -q replay_v0/tests`.
- **Next executable handoff:** create a fresh detached worktree from current `origin/main`, switch a
  new branch before committing, reproduce the Windows space-path failure first, and ship only the
  smallest structured-argv/rendering contract.

## Refresh commands

```powershell
git fetch origin --prune
git rev-parse origin/main
git show-ref -d refs/tags/floor-v1-final
gh pr list --repo Chris0Jeky/agent-harness --state open --limit 100
gh issue list --repo Chris0Jeky/agent-harness --state open --limit 200
py -3 harness.py audit . --offline
py -3 harness.py doctor
git diff --check origin/main..HEAD
```
