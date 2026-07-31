# Active workstreams

Snapshot: 2026-07-31. Base: `27ec3b6b0c8430058b4aa2570b0f4a9dda66938f`.
One workstream is active; the second slot remains free until this continuity slice lands or parks.

## A — AH-1/AH-2 workbench continuity

- **Observable outcome:** the root mission and four canonical state homes agree with live Git,
  GitHub, deployed-byte, benchmark, and human-action evidence, and the next agent has one exact
  executable handoff.
- **Evidence:** branch `docs/workbench-continuity-20260731` creates `docs/SYSTEM_STATE.md`,
  `ROADMAP.md`, `plans/ACTIVE.md`, and `docs/BENCHMARKS.md`; it preserves root `HANDOFF.md` as
  history and uses the dated workbench handoff for continuation. PRs #140/#159/#161/#162/#163/#169
  are merged; #87/#144/#151/#153/#166 are closed.
- **In:** continuity documents, the root mission/status paragraph, tier review date, and stale
  wording in the canonical legacy-limitations ledger.
- **Out:** runtime behavior, new policy, floor expansion, H-2 canaries, plugin extraction, public
  replay, and changes in another writer's checkout.
- **Architecture seam:** evidence/state ownership across the workbench, not executable enforcement.
- **Tests/fixtures/corpus:** no fixture or corpus changes; audit/Doctor, issue-map, line-budget,
  JSON, Markdown/diff, exact-range review, hosted CI, and PR aging/triage gates apply.
- **Measurement:** `docs/BENCHMARKS.md` contains only measurements with recorded inputs, methods,
  results, and limitations; this slice adds no new performance claim.
- **Limitation:** GitHub, tier, deployed bytes, and worktree ownership can change after this dated
  snapshot; every successor must refresh them before mutation.
- **Exact verification:** `py -3 harness.py audit . --offline`; `py -3 harness.py doctor`; parse
  `.agent-harness/tier.json`; prove every open issue is mapped exactly once; enforce document
  budgets; `git diff --check origin/main..HEAD`.
- **Next executable handoff:** finish one fresh exact-range review and scoped verification, publish
  this branch as a ready PR, require all hosted jobs green, age and triage the final head once, and
  merge with a merge commit if the exact state remains clean.

## Parked or queued, not active

- PR #154/#151 is superseded by merged PR #162; PR #155/#87 is superseded by merged PR #161.
  Their parked remote branches remain evidence and are not active writer checkouts.
- #167/#168/#170/#171/#172 are bounded AH-6 follow-ups from guarded closeout; none authorizes live
  estate cleanup.
- #160/#164/#165 are bounded Doctor follow-ups, not active workbench-wide priorities.
- #152 is the recommended next executable slice after continuity: add platform-valid replay
  reproduction commands with structured-argv/rendering proof on Windows and POSIX.
- H-2 is owner-parked. Do not run estate-wide canaries or disable the harness.
- AH-10 extraction and a public replay repository remain deferred.
