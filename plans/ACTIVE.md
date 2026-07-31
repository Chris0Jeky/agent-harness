# Active workstreams

Snapshot: 2026-07-31. Base: `e23e97b464208ee6035d4155ff7e9b5316f2efec`.
One workstream is active; the second slot is free.

## A — AH-1 continuity refresh

- **Observable outcome:** canonical state, roadmap, active-plan, measured-evidence, and dated-handoff
  homes agree with live Git/GitHub evidence after PRs #173–#180, including measured CI-budget
  follow-up #179 and completed partial-apply reporting #168.
- **Evidence:** branch `docs/workbench-continuity-final` contains post-PR #180 main through merge
  commit `8f17839`; PRs #152/#156/#164/#165/#168 are closed; PRs #154/#155 are closed unmerged and
  superseded; GitHub had no open PR at the base snapshot; 65 open issues require one primary epic.
- **In:** `docs/SYSTEM_STATE.md`, `ROADMAP.md`, this file, `docs/BENCHMARKS.md`, and
  `handoffs/2026-07-31-workbench-pivot.md`.
- **Out:** runtime behavior, root `HANDOFF.md`, legacy floor limitations, H-2 activity, live estate
  mutation, plugin extraction, public replay, or another checkout.
- **Architecture seam:** evidence and state ownership across the workbench, not enforcement.
- **Tests/fixtures/corpus:** no fixture or corpus change; issue-map, document-budget, JSON,
  audit/Doctor, Markdown/diff, review, hosted CI, aging, and triage gates apply.
- **Measurement:** only directly measured B-006–B-011 entries are added; no current estate
  baseline, longitudinal Doctor series, or performance improvement is claimed.
- **Limitation:** GitHub, tier, deployed bytes, and worktree ownership can change after this dated
  snapshot; successors must refresh them before mutation.
- **Exact verification:** `py -3 -B harness.py audit . --offline`; `py -3 -B harness.py doctor
  --repo . --offline`; parse `.agent-harness/tier.json`; prove every open issue maps exactly once;
  enforce document budgets; `git diff --check origin/main...HEAD`.
- **Next executable handoff:** complete one fresh exact-range review, publish a ready PR, require
  all nine hosted jobs green, age and triage the exact head once, and merge with a merge commit if
  live state remains clean.

## Completed in this wave

- AH-6 #168 merged through PR #180 as `e23e97b`, preserving implementation `c9e80c9`. Synthetic
  JSON/text matrices now report one completed removal and two fail-closed retentions after later
  registry failure. No live `worktrees --apply` ran.
- AH-4 #164/#165 merged through PRs #175/#178; AH-2 #152/#156 merged through PRs #174/#176.
- PRs #154/#155 were closed unmerged after exact supersession inventory; their branches remain
  historical evidence.

## Parked or queued, not active

- #179 is the measured AH-1 Windows aggregate CI-budget repair and the exact next safe slice.
  Inventory timings before changing the workflow; never skip or allow-fail a proving check.
- #167/#170/#171/#172 remain bounded AH-6 follow-ups. None authorizes live estate cleanup.
- #160 is the remaining bounded Doctor topology follow-up. #177 is the bounded replay
  lone-surrogate parity follow-up.
- H-2 is owner-parked. Do not run estate-wide canaries or disable the harness.
- AH-10 extraction and a public replay repository remain deferred.
