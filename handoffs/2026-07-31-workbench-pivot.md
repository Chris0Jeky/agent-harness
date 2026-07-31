# Handoff: workbench pivot continuity — 2026-07-31

Refresh refs, PRs, issues, checks, reviews, comments, threads, worktrees, and tier declarations
before acting. This is a factual checkpoint, not authority to reuse stale gate evidence. Root
`HANDOFF.md` is historical pre-pivot context and must not be rewritten as current state.

## Objective and invariants

- Operate `agent-harness` as the agent-operations workbench: frozen legacy floor, internal replay
  Policy Lab, Doctor, estate operations, bounded Pattern Guard v2, measurement, adapters, and
  private integration through small executable slices.
- Authority at the post-PR #178 snapshot is T3 with `push: free` and `merge: free`. Preserve commits
  with merge commits; never squash, use admin/auto merge, or delete a PR branch during merge.
- Every changed head/base needs scoped proof, three-minute aging, one bounded review pipeline,
  green required CI, and one comments/reviews/threads triage. Never post routine `@codex review`.
- Keep at most two active workstreams and one writer per checkout.
- Do not expand the universal parser, activate global blocking, start blueprint-plugin extraction,
  or create a public replay repository.
- H-2 is the only open `HUMAN_TODO.md` item and is owner-parked. Do not restart estate-wide
  canaries or disable the harness.

## Completed and directly verified

- PR #140 merged as `81125c57ec6d1a750ddd43b0110c6928f9f4a860`; `origin/main` contains
  `fd87e06c1c55ceed5cef3c736710b513317f3c89`; #148/#149 closed; all 27 original threads were
  resolved; the post-merge late-feedback check was empty.
- PR #159 merged as `8d4b69d147b4f1e930b3388e5b3ce7d2661ab82e`, preserved head
  `e0f8fa5ab75147085d3bfcc5aaa0d7ebcb8222f6`, passed run `30626399786`, and closed #153.
- PR #161 merged as `bea61078937a93aa73e2015ac533f2c9d061f5e8`, preserved head
  `416046b746280422348419619a9cab286fa75617`, passed run `30627690916`, and closed #87.
- PR #163 merged as `347ab97cfc800dcc3621ffd15d041f4e949e3fd6`, preserved head
  `d41d311e2a3a929dbd2724e9d62cc8140a825458`, passed run `30628366731`, and closed #144.
- PR #162 merged as `bb20cdd2528d7191a74a4dd2486bb622d6e80df1`, preserved its guarded-closeout
  commits, passed run `30629391405`, and closed #151. PR #169 repaired every confirmed late-review
  preservation defect and merged as `27ec3b6b0c8430058b4aa2570b0f4a9dda66938f`, preserving head
  `cb43065c6d06675e0cff1393628512778ec767ae`; run `30634860134` passed and #166 closed.
- PR #173 merged continuity state as `c4fdbe897f4679d85a421b18d8097683fc7c58ce`, preserving
  head `ff21787c0ef2d5cabf16353104fd3c4c50cedb71`; run `30636462032` passed.
- PR #174 merged platform-valid replay reproduction as
  `7f9134f517865c2b5f9ebf646ee82ce756e69ecf`, preserving head
  `2ccf60dcbc2a6d394d9c009c8bae655cc42b7a8d`; run `30639136818` passed and #152 closed.
- PR #175 merged shared MCP source identity as `82e8a16a9255c987c46dc408a8e35662d4fb6b9d`,
  preserving head `c8863e002a46fe39fc2baa1f3b8404694c9509ef`; run `30640903741` passed and
  #164 closed.
- PR #176 merged PolicyDecision newline parity as
  `5df147b0ec62d48902942a876073c180f9b0914c`, preserving head
  `440492c10eb6743ce2636a8f6cb238f653bd832a`; run `30642286808` passed, #156 closed,
  and bounded lone-surrogate follow-up #177 remains open.
- PR #178 merged bounded Docker gateway subcommand recognition as
  `576b540b0e856ed61dc1b062b1cdae0abbcd89dd`, with parents `5df147b` and `bdc3f1b`,
  preserving both implementation commits `e53ed4d723a15dc962ef7f55f8929e82f7d6e578` and
  `bdc3f1b5218c35e71dc696936f1e604f80e3bdb0`; #165 closed. Exact-head local gates passed
  844 tests with 13 declared skips and 2237/2237 smoke cases. Run `30645532130` passed all nine
  jobs after the Windows failed-job rerun. One HIGH review finding was fixed once; the final
  fix-range review was clean; four connector threads were triaged and resolved; post-merge
  feedback was checked once.
- PRs #154/#155 were closed unmerged after independent exact inventory proved them stale,
  conflicting, and superseded by #161/#162/#169/#175. Their remote branches and historical
  threads were preserved; no branch was deleted.
- The protected `floor-v1-final` tag remains object
  `5a939540bdce51e511d6b3bae98358e3e2ad9148`, peeled
  `02bd14cfe094f9b6af85b966de481ff3f45264cf`.

## Current state and canonical homes

- Published base for the active wave: `origin/main@576b540b0e856ed61dc1b062b1cdae0abbcd89dd`.
- Immediately after PR #178, GitHub had zero open PRs and 66 open issues. `ROADMAP.md` maps each
  open issue exactly once; new #179 is primary AH-1 CI proving-substrate work.
- Canonical state: `docs/SYSTEM_STATE.md`. Issue/PR ownership: `ROADMAP.md`. Active work:
  `plans/ACTIVE.md`. Measurements: `docs/BENCHMARKS.md`. Legacy limitations:
  `FLOOR_LIMITATIONS.md`. Human action: `HUMAN_TODO.md`.
- Canonical/deployed floor bytes match after LF normalization at SHA-256
  `EA4FB45DC71A44E80392E7EA423BC70DCB604538E956CB13CF34B750118974B5`; deployed raw CRLF
  bytes are `E1A4E7714913788DD801F0FA43A3E5B30EA0433709F97142509B56B1C442EF68`.
- Issue #179 records the exact-head Windows CI variance: attempt 1 canceled at 15m05s after
  assertions had passed through replay; attempt 2 passed in 11m33s. Do not weaken a check; measure
  recent distributions before changing the aggregate budget or stage topology.

## Active workstreams

### A — continuity docs

- Writer checkout: `.worktrees/workbench-continuity-final-20260731`.
- Branch: `docs/workbench-continuity-final`; base `576b540`.
- Scope is exactly the five canonical continuity files. Root `HANDOFF.md`, runtime behavior,
  floor limitations, and H-2 remain untouched.
- Before publication, refresh after workstream B lands or parks, then prove the 66-entry issue map,
  document budgets, tier JSON, exact diff, offline audit/Doctor, fresh review, hosted CI, aging,
  and discussion triage.

### B — #168 partial-apply reporting

- Sole writer checkout: `.worktrees/partial-apply-report-20260731`.
- Branch: `fix/issue168-partial-apply`; base `576b540`.
- Synthetic reproduction removed the first worktree, retained the next after a controlled registry
  probe failure, then raised before rendering: zero stdout, no summary, no top-level apply error.
- Implement only complete/fail-closed JSON/text reporting, stable reason codes, synthetic tests,
  and one `SPECS.md` sentence. No live apply, retry, rollback, prune, force, or #167/#170–#172 work.
- After implementation, run focused/full local gates, one bounded review pipeline, all nine hosted
  jobs, three-minute aging, triage once, and merge with commit preservation if clean.

## Occupied worktrees to preserve

- Primary checkout: clean but intentionally behind `origin/main`; preserve user state.
- `crossproduct-gate`: tracked-clean historical test branch; remote branch is gone; ignored caches.
- `issue27-temporal-config`: tracked-clean occupied historical floor branch; ignored caches.
- `replay-tool`: user-owned staged `scripts/replay_corpus.py`; never reset, restore, stash, or remove.
- `replay-v0-freeze`: ignored `.local/` evidence/caches and recovery evidence; never remove without
  separately proving and copying everything that must survive.
- `workbench-continuity-final-20260731` and `partial-apply-report-20260731`: the two current writer
  checkouts, one writer each.
- Empty, unregistered `.worktrees/replay-platform-reproduction-20260731` may remain locked by an
  external handle. It was verified empty and unregistered; leave it alone unless separately proving
  it safe to remove.

The completed #175/#176/#178 writer worktrees were removed with plain `git worktree remove` only
after tracked/untracked/ignored inspection found nothing except disposable caches. No parked branch
was deleted. `replay-v0-freeze` and its ignored evidence were never touched.

## Next safe queue

Finish #168 first; it is independently reproduced and already isolated. After #168 and continuity
land, #179 is the strongest new substrate candidate because a required gate was directly canceled
by the measured 15-minute aggregate budget. Its first action is read-only duration inventory, not a
timeout guess. Then re-rank #170/#171/#172 and #160 from refreshed evidence. #98 remains unsuitable
until source-versus-deployed global-guidance provenance is resolved.

Exact #179 inventory command:

```powershell
gh run view <run-id> --repo Chris0Jeky/agent-harness --json status,conclusion,attempt,jobs
```

Do not combine #179 with product behavior, skip/allow-fail a check, or turn it into general CI
architecture. Its outcome is only an evidence-backed budget or the smallest independent stage
partition that preserves every assertion.

## Refresh commands

```powershell
git fetch origin --prune
git rev-parse origin/main
git show-ref -d refs/tags/floor-v1-final
gh pr list --repo Chris0Jeky/agent-harness --state open --limit 100
gh issue list --repo Chris0Jeky/agent-harness --state open --limit 200
py -3 -B harness.py audit . --offline
py -3 -B harness.py doctor --repo . --offline
git diff --check origin/main...HEAD
```
