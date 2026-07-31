# Active workstreams

Snapshot: 2026-07-31. Published base: `b2c2fd40a1e3d99821983b6ad38a1fecd1d22809`.
One workstream is active; the second slot is free.

## A — AH-1 continuity publication (PR #195)

- **Observable outcome:** the five canonical continuity homes describe `main@b2c2fd4`, all 69 open
  issues map exactly once, and the next session can resume without trusting historical root
  `HANDOFF.md`.
- **Evidence:** branch `docs/workbench-continuity-20260731` preserves its original continuity commit
  while merging current `origin/main`; PR #193 merged as `b2c2fd4`, preserving head `8648e5c`; all
  nine jobs in run `30666338126` passed; six connector threads were tracked in #196 and resolved.
- **In:** `docs/SYSTEM_STATE.md`, `ROADMAP.md`, this file, `docs/BENCHMARKS.md`, and
  `handoffs/2026-07-31-workbench-pivot.md`.
- **Out:** runtime behavior beyond the merged base, root `HANDOFF.md`, `FLOOR_LIMITATIONS.md`, H-2
  activity, live estate/config/Docker mutation, public replay, plugin extraction, or sibling edits.
- **Architecture seam:** evidence/state ownership across AH-1 through AH-10, not enforcement.
- **Tests/fixtures/corpus:** no fixture/corpus change; live issue-map, JSON, audit/Doctor,
  Markdown/diff, fix-diff review, hosted CI, aging, and all-surface triage gates apply.
- **Measurement:** only measured B-012 through B-014 evidence is added; no current estate baseline,
  longitudinal Doctor series, or universal policy quality is claimed.
- **Limitation:** deployed global floor remains 1.6.21 while canonical source is 1.6.22. Static
  Doctor cannot prove fresh-session trust; GitHub state can change after this dated snapshot.
- **Exact verification:** `py -3 -B harness.py audit . --offline`; `py -3 -B harness.py doctor
  --repo . --offline`; prove 69/69 live issue mapping; parse tier JSON; `git diff --check
  origin/main...HEAD`.
- **Next executable handoff:** push the base-refresh fix, verify the exact head against `b2c2fd4`,
  require all nine hosted jobs green, finish one fix-diff review, age/triage once, and merge-commit.

## Completed in this wave

- PR #182 closed #179 by changing only the aggregate Verify timeout from 15 to 20 minutes. PR #183
  closed #171 by reducing reflog reachability probes from up to five Git processes to one stdin-fed
  traversal with equivalent fail-closed results.
- PR #187 closed #177 with schema/runtime surrogate parity. PR #194 closed #167 with suspend-aware,
  rollback-detecting fingerprint expiry and global stop-on-invalidity. No live closeout apply ran.
- PR #193 merged the four owner-authorized #184 public-push security repairs as `b2c2fd4`; #184 then
  closed with exact producer proof, without authorizing live installation. Five pre-merge and one post-merge fail-closed usability
  findings were classified once, recorded in #196, and resolved without another fix loop.
- PRs #154/#155 were closed unmerged after exact supersession inventory; branches and historical
  review evidence remain preserved.

## Parked or queued, not active

- #160 is reproduced and owner-blocked on disabled mixed-transport precedence. Recommended rule:
  effective disablement suppresses only cross-layer conflict; same-table conflict remains invalid.
- #172 is the exact next independent safe slice after PR #195 settles: preserve direct non-commit
  `ORIG_HEAD` identity with additive fingerprint evidence. #170 additionally needs a real
  POSIX/mode-capable proving environment.
- #196 is the bounded AH-3 follow-up for six fail-closed public-push usability edges; it is not
  permission to reopen #193 or broaden the parser.
- #185/#186/#188–#192 are mapped follow-ups, not permission to broaden the active wave.
- H-2 is the sole open human item and owner-parked. Do not run estate-wide canaries or disable the
  harness. AH-10 extraction and a public replay repository remain deferred.
