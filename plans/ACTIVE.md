# Active workstreams

Snapshot: 2026-08-01. Published base: `744b2f21d36053a9c0152a617b8af02a4b72b4a8`.
One workstream is active; the second slot is free.

## A — AH-6 native Windows executable-mode capability (#170)

- **Observable outcome:** guarded closeout does not retain a clean native-Windows worktree merely
  because Git's forced mode comparison synthesizes `100755` to `100644`, while a genuine POSIX
  executable-mode-only change remains a preservation blocker even when `core.fileMode=false`.
- **Evidence:** PR #169's bounded review reproduced the Windows false keep and opened #170. On the
  current branch, a real Git-for-Windows fixture first reproduces the synthetic delta, and the
  unchanged WSL2 fixture proves a real `chmod` delta is still detected on a mode-capable filesystem.
- **In:** the closeout mode-comparison capability seam, causal Windows and POSIX fixtures, and the
  README/SPECS contract qualification.
- **Out:** temporary write probes, live closeout apply, force removal, branch deletion, estate
  cleanup, mode emulation on unknown POSIX mounts, or any floor/runtime deployment.
- **Architecture seam:** `harness.py` worktree candidate inspection before the existing forced
  `core.fileMode=true` comparison.
- **Tests/fixtures/corpus:** one native-Windows executable-baseline fixture plus the existing POSIX
  mode-drift and probe-failure fixtures; no replay corpus change.
- **Measurement:** correctness matrix only; do not infer filesystem prevalence or estate impact.
- **Limitation:** native Windows cannot preserve a working-tree Unix executable bit. POSIX mounts
  that also cannot expose it may still conservatively retain a candidate; that is a false keep,
  never removal authority.
- **Exact verification:** focused Windows/WSL controls; full closeout and unit suites; smoke;
  audit/Doctor; Black, Ruff, compile, diff checks; hosted Windows/macOS/Linux CI; one independent
  read-only review; aging and all-surface triage.
- **Next executable handoff:** publish one PR closing only #170, with no live apply or consumer
  rollout, then merge-commit only after exact-head evidence is green.

## Completed in this wave

- PR #182 closed #179 by changing only the aggregate Verify timeout from 15 to 20 minutes. PR #183
  closed #171 by reducing reflog reachability probes from up to five Git processes to one stdin-fed
  traversal with equivalent fail-closed results.
- PR #187 closed #177 with schema/runtime surrogate parity. PR #194 closed #167 with suspend-aware,
  rollback-detecting fingerprint expiry and global stop-on-invalidity. No live closeout apply ran.
- PR #193 merged the four owner-authorized #184 public-push security repairs as `b2c2fd4`; #184 then
  closed with exact producer proof, without authorizing live installation. Five pre-merge and one
  post-merge fail-closed usability findings were classified once, recorded in #196, and resolved
  without another fix loop.
- PR #195 published the current workbench continuity homes. PR #197 preserved direct non-commit
  `ORIG_HEAD` identity and closed #172; its exact-head run passed all nine hosted jobs, and the
  post-merge review/comment/thread refresh found no late feedback.
- PRs #154/#155 were closed unmerged after exact supersession inventory; branches and historical
  review evidence remain preserved.

## Parked or queued, not active

- #160 is reproduced and owner-blocked on disabled mixed-transport precedence. Recommended rule:
  effective disablement suppresses only cross-layer conflict; same-table conflict remains invalid.
- #196 is the bounded AH-3 follow-up for six fail-closed public-push usability edges; it is not
  permission to reopen #193 or broaden the parser.
- #185/#186/#188–#192 are mapped follow-ups, not permission to broaden the active wave.
- H-2 is the sole open human item and owner-parked. Do not run estate-wide canaries or disable the
  harness. AH-10 extraction and a public replay repository remain deferred.
