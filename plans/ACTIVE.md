# Active workstreams

Snapshot: 2026-07-31. Published base: `a6a1c847392899ad0e6d0709c44ea2aa67760979`.
Two workstreams are active; each has a separate writer checkout.

## A — AH-3 public-push security preservation (#184 / PR #193)

- **Observable outcome:** four reproduced public-push narrowing gaps fail closed in canonical floor
  1.6.22 without live installation or unrelated parser expansion.
- **Evidence:** occupied branch `fix/issue184-push-narrowing` was at
  `8648e5c7fb804fed4c991418401d411973350248` on base/merge-base `a6a1c84`; one independent HIGH
  was fixed once. The superseded-head connector review left four current threads (including one P1)
  plus one outdated thread requiring bounded triage and current-head review. Hosted run
  `30666338126` was still completing at this snapshot.
- **In:** the four owner-authorized #184 cases, direct regressions, canonical version/marker, and
  exact producer proof.
- **Out:** consumer sync, live `sync-global --apply`, trust/config mutation, general floor redesign,
  or NavSentinel infrastructure that its owner has retired.
- **Architecture seam:** frozen floor security-preservation exception and public-push narrowing.
- **Tests/fixtures/corpus:** focused 31-case narrowing matrix, full unit/smoke/audit/Doctor gates,
  two exact-range security lenses, hosted CI, aging, and one discussion triage.
- **Measurement:** the four direct-allow reproductions and 31-case final matrix are correctness
  evidence, not an estate false-positive or performance baseline.
- **Limitation:** the checkout `.worktrees/issue184-push-narrowing` is externally occupied. Its
  writer must refresh the changed base and re-prove affected evidence; other workstreams must not
  modify, merge, or remove it.
- **Exact verification:** `py -3 -m unittest tests.test_sensitive_push_narrowing -v`; `py -3
  templates\hooks\smoke_test.py`; then the repository's full declared gates at the refreshed head.
- **Next executable handoff:** the owning writer refreshes `origin/main`, reconciles the base without
  rewriting commits, reruns scoped/full proof, triages every surface once, and merge-commits only if
  the refreshed exact-head gate is clean.

## B — AH-1 continuity publication

- **Observable outcome:** the five canonical continuity homes describe `main@a6a1c84`, all 69 open
  issues map exactly once, and the next session can resume without trusting the historical root
  `HANDOFF.md`.
- **Evidence:** branch `docs/workbench-continuity-20260731` starts detached from then-current
  `origin/main@a6a1c84`; PRs #181/#182/#183/#187/#194 and issues #179/#171/#177/#167 were refreshed
  from GitHub; protected tag bytes and occupied worktrees were re-proved.
- **In:** `docs/SYSTEM_STATE.md`, `ROADMAP.md`, this file, `docs/BENCHMARKS.md`, and
  `handoffs/2026-07-31-workbench-pivot.md`.
- **Out:** runtime behavior, root `HANDOFF.md`, `FLOOR_LIMITATIONS.md`, H-2 activity, live estate
  mutation, public replay, plugin extraction, or any sibling checkout.
- **Architecture seam:** evidence/state ownership across AH-1 through AH-10, not enforcement.
- **Tests/fixtures/corpus:** no fixture/corpus change; issue-map, document, JSON, audit/Doctor,
  Markdown/diff, review, hosted CI, aging, and all-surface triage gates apply.
- **Measurement:** only measured B-012 through B-014 evidence is added; no current estate baseline,
  longitudinal Doctor series, or universal policy quality is claimed.
- **Limitation:** GitHub and occupied-worktree state can change after this dated snapshot. A #193
  merge changes the base and requires this slice to refresh before publication.
- **Exact verification:** `py -3 -B harness.py audit . --offline`; `py -3 -B harness.py doctor
  --repo . --offline`; prove 69/69 issue mapping; parse tier JSON; enforce document caps; `git diff
  --check origin/main...HEAD`.
- **Next executable handoff:** publish one ready PR, complete one bounded docs review, require all
  nine hosted jobs green, age/triage the exact head once, and merge with a merge commit.

## Completed in this wave

- PR #182 closed #179 by changing only the aggregate Verify timeout from 15 to 20 minutes; all nine
  jobs passed. PR #183 closed #171 by reducing reflog reachability probes from up to five Git
  processes to one stdin-fed traversal with equivalent fail-closed results.
- PR #187 closed #177 with schema/runtime surrogate parity. PR #194 closed #167 with suspend-aware,
  rollback-detecting fingerprint expiry and global stop-on-invalidity. No live closeout apply ran.
- PRs #154/#155 were closed unmerged after exact supersession inventory; branches and historical
  review evidence remain preserved.

## Parked or queued, not active

- #160 is reproduced and owner-blocked on disabled mixed-transport precedence. Recommended rule:
  effective disablement suppresses only cross-layer conflict; same-table conflict remains invalid.
- #172 is the exact next independent safe slice after #193 and continuity settle: preserve direct
  non-commit `ORIG_HEAD` identity with additive fingerprint evidence. #170 additionally needs a
  POSIX/mode-capable proving environment.
- #185/#186/#188–#192 are mapped follow-ups, not permission to broaden the active wave.
- H-2 is the sole open human item and owner-parked. Do not run estate-wide canaries or disable the
  harness. AH-10 extraction and a public replay repository remain deferred.
