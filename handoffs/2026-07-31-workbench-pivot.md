# Handoff: workbench pivot continuity — 2026-07-31

Refresh refs, PRs, issues, checks, reviews, comments, threads, worktrees, and tier declarations
before acting. This is a factual checkpoint, not authority to reuse stale gate evidence.

## Mission and invariants

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

## Proven completed work

- PR #140 merged as `81125c57ec6d1a750ddd43b0110c6928f9f4a860`, with parents
  `7a07238fb8a4d1af826343158abaf863051b6ef5` and
  `6261c32e9040815ab38a15cb2c668d15358e2a05`. `origin/main` contains the requested
  `fd87e06c1c55ceed5cef3c736710b513317f3c89` and every successor commit. #148/#149 closed;
  all 27 original threads plus later triage were resolved, and the post-merge feedback check found
  no late finding.
- PR #159 closed #153's literal-Markdown report defect. Merge `8d4b69d147b4f1e930b3388e5b3ce7d2661ab82e`
  preserved head `e0f8fa5ab75147085d3bfcc5aaa0d7ebcb8222f6`; run `30626399786` passed all nine jobs;
  the one post-merge feedback check was empty.
- PR #161 closed #87's static MCP-topology slice. Merge
  `bea61078937a93aa73e2015ac533f2c9d061f5e8` preserved head
  `416046b746280422348419619a9cab286fa75617`; run `30627690916` passed all nine jobs. Its two
  non-blocking false-positive findings were resolved and tracked as #164/#165; no late feedback
  appeared after merge.
- PR #163 closed #144's run-manifest gate-class mismatch. Merge
  `347ab97cfc800dcc3621ffd15d041f4e949e3fd6` has parents `bea61078937a93aa73e2015ac533f2c9d061f5e8`
  and `c2c139bf1300ed235cc99ad0cf4fbf4411cb80c8`, preserving implementation commit
  `d41d311e2a3a929dbd2724e9d62cc8140a825458`. Exact-head run `30628366731` passed all nine jobs;
  #144 closed; comments, reviews, threads, and the one post-merge feedback check were empty.
- The protected `floor-v1-final` tag remains object
  `5a939540bdce51e511d6b3bae98358e3e2ad9148`, peeled
  `02bd14cfe094f9b6af85b966de481ff3f45264cf`.

## Live state and ownership

- Published `main` at this snapshot: `347ab97cfc800dcc3621ffd15d041f4e949e3fd6`.
- GitHub has 64 open issues. `ROADMAP.md` maps each exactly once to AH-1 through AH-8; AH-9/AH-10
  are secondary/deferred seams.
- Open PRs are #154, #155, and #162. #154 is superseded by #162; #155 is superseded by merged
  #161. Do not revive either parked predecessor.
- Exactly two workstreams are active:
  1. continuity branch `docs/workbench-continuity-20260731` in
     `C:\Users\jekyt\source\agent-harness\.worktrees\workbench-continuity-20260731`;
  2. PR #162/#151 in `...\.worktrees\issue151-successor`, owned by its existing writer.
- PR #162 current head is `c58a0ea` with merge-base `347ab97`. Two earlier hosted attempts failed
  only because platform-alias fault injections compared a canonical command cwd to a noncanonical
  fixture root. The current one-line test repair canonicalizes that root; run `30629391405` is the
  exact-head hosted gate and was still in progress at this snapshot. Do not edit its checkout.
- #160/#164/#165 are bounded Doctor follow-ups. They are mapped, not active.
- #152 is the next bounded replay candidate only after an active slot opens.

## Continuity branch

The branch creates or updates:

- `docs/SYSTEM_STATE.md` — implemented/deployed/benchmarked/experimental/frozen/unverified/stale;
- `ROADMAP.md` — AH-1 through AH-10 dependencies, evidence, outcome state, and complete issue/PR map;
- `plans/ACTIVE.md` — exactly the two active workstreams above;
- `docs/BENCHMARKS.md` — only measured inputs/methods/results/limitations;
- `README.md` — workbench mission and current-state correction;
- `FLOOR_LIMITATIONS.md` — canonical legacy limitation wording only;
- `.agent-harness/tier.json` — 2026-07-31 review date;
- this dated handoff.

Root `HANDOFF.md` is deliberately untouched and classified as historical/stale. The branch has
merged current `origin/main`; query `git rev-parse HEAD` and `git merge-base HEAD origin/main`
rather than relying on a prose SHA. It must be refreshed again if PR #162 or any other PR lands.

Before publication, finish the exact current-range verification and fresh-context review. The
initial pre-#161 range already passed review, offline audit, Doctor, tier parsing, issue mapping,
line budgets, and diff checks; that evidence is not a substitute for the refreshed range.

## Occupied worktrees

- `crossproduct-gate`: tracked-clean; remote branch is gone. Preserve until separately audited.
- `issue151-successor`: active PR #162 writer checkout. Read-only to every other agent.
- `issue27-temporal-config`: tracked-clean occupied historical branch.
- `replay-tool`: user-owned staged `scripts/replay_corpus.py`; never reset, restore, stash, or remove.
- `replay-v0-freeze`: branch is behind remote and contains ignored `.local/` evidence plus caches.
  It was intentionally left untouched; never remove it without separately proving and preserving
  anything needed outside the worktree.
- `workbench-continuity-20260731`: current writer checkout.

The completed #153 and #144 worktrees were removed with plain `git worktree remove` only after
confirming they held no tracked/untracked work and only disposable caches. Their remote branches
were preserved.

## Exact continuation

1. Run `git fetch origin --prune`; refresh `.agent-harness/tier.json`, `origin/main`, PR #162, open
   issues/PRs, comments/reviews/threads, and `floor-v1-final` before mutation.
2. At the next PR #162 workflow event, inspect run `30629391405`. If any job is red, identify the
   cause and leave its writer checkout untouched. If it merges, prove merge parents/head history,
   #151 closure, and one late-feedback check.
3. Merge current `origin/main` into this continuity branch if the base moved. Reconcile README and
   live issue/PR/active-state facts once; do not rewrite root `HANDOFF.md`.
4. Verify the open-issue map, document budgets, tier JSON, `git diff --check`, offline audit, and
   Doctor. Obtain one fresh-context exact-range review.
5. Publish a ready PR, allow automatic review without summoning it, run all required hosted CI,
   age the final head three minutes, triage every comment/thread once, and merge with an exact-head
   merge commit only when the declared gate is green.
6. After continuity lands, the next safe executable slice is #152: platform-valid replay
   reproduction commands, bounded to structured argv/rendering and Windows/POSIX proof.

## Refresh commands

```powershell
git fetch origin --prune
git rev-parse origin/main
git show-ref -d refs/tags/floor-v1-final
gh pr view 162 --repo Chris0Jeky/agent-harness --json headRefOid,baseRefOid,state,mergeable,mergeStateStatus,statusCheckRollup,reviews,comments,closingIssuesReferences
gh pr list --repo Chris0Jeky/agent-harness --state open --limit 100
gh issue list --repo Chris0Jeky/agent-harness --state open --limit 200
py -3 harness.py audit . --offline
py -3 harness.py doctor
git diff --check origin/main..HEAD
```
