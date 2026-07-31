# Active workstreams

Snapshot: 2026-07-31. Base: `347ab97cfc800dcc3621ffd15d041f4e949e3fd6`.
Exactly two workstreams are active; do not start a third until one lands or parks.

## A — AH-1/AH-2 workbench continuity

- **Observable outcome:** the root mission and four canonical state homes agree with live Git,
  GitHub, deployed-byte, benchmark, and human-action evidence.
- **Evidence:** branch `docs/workbench-continuity-20260731` creates `docs/SYSTEM_STATE.md`,
  `ROADMAP.md`, `plans/ACTIVE.md`, and `docs/BENCHMARKS.md`; it preserves root `HANDOFF.md` as
  history and uses this dated handoff for continuation. PRs #140/#159/#161/#163 are merged.
- **In:** continuity documents, the root mission/status paragraph, tier review date, and stale
  wording in the canonical legacy-limitations ledger.
- **Out:** runtime behavior, new policy, issue creation, floor expansion, H-2 canaries, plugin
  extraction, public replay, and changes in another writer's checkout.
- **Architecture seam:** evidence/state ownership across the workbench, not executable enforcement.
- **Tests/fixtures/corpus:** no fixture or corpus changes; audit/Doctor, issue-map, line-budget,
  JSON, Markdown/diff, and fresh-context review gates apply.
- **Measurement:** `docs/BENCHMARKS.md` contains only measurements with recorded inputs, methods,
  results, and limitations; this slice adds no new performance claim.
- **Limitation:** active PR #162 overlaps `README.md` and can advance `main`; publish only after its
  writer lands or parks it, then merge current `origin/main` and refresh every live-state claim.
- **Exact verification:** `py -3 harness.py audit . --offline`; `py -3 harness.py doctor`;
  parse `.agent-harness/tier.json`; prove every open issue is mapped exactly once; enforce the
  document budgets; `git diff --check origin/main..HEAD`.
- **Next executable handoff:** wait for a PR #162 workflow event, reconcile its result once, run a
  fresh exact-range review and scoped verification, then publish this branch as a ready PR.

## B — AH-6 PR #162 guarded worktree closeout

- **Observable outcome:** a read-only-by-default worktree audit and explicitly leased apply path
  can remove only a fully proven, inactive worktree with plain `git worktree remove`.
- **Evidence:** PR #162 supersedes #154 and closes #151. Current head `c58a0ea` records the lease,
  canonical-path, reachability, fingerprint, and no-force contract on current base `347ab97`.
- **In:** only the existing PR #162 branch/worktree and its bounded fix/review/base-refresh pipeline.
- **Out:** global prune, force removal, branch deletion, hidden bypasses, process authentication,
  live estate-wide cleanup, or edits from another checkout.
- **Architecture seam:** cooperative worktree ownership and guarded estate closeout in `harness.py`.
- **Tests/fixtures/corpus:** focused worktree fixtures plus full harness/replay/smoke gates; no replay
  corpus changes.
- **Measurement:** exact-head local suite counts and hosted cross-platform results; no claim that
  cooperative leases detect a non-cooperating external writer.
- **Limitation:** two earlier hosted attempts missed platform path aliases in fault-injection test
  fixtures. The product seam was unchanged; exact-head run `30629391405` is still in progress, so
  no cross-platform result is final yet.
- **Exact verification:** the existing writer must inspect both failure logs, prove the causal fix,
  merge current `origin/main`, rerun relevant local gates and fresh review, then obtain nine green
  hosted jobs at the exact head with three-minute aging and one comment/thread triage.
- **Next executable handoff:** the existing #162 writer owns any change. Other agents remain
  read-only and revisit only at a workflow event.

## Parked or queued, not active

- PR #154/#151 is superseded by #162; PR #155/#87 is superseded by merged #161. Preserve both
  occupied evidence branches until separately proven safe to close or remove.
- #160/#164/#165 are bounded Doctor follow-ups, not active workbench-wide priorities.
- #152 is the next bounded replay candidate after continuity and #162; it is not active.
- H-2 is owner-parked. Do not run estate-wide canaries or disable the harness.
- AH-10 extraction and a public replay repository remain deferred.
