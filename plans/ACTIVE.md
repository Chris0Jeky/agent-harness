# Active workstreams

Snapshot: 2026-08-08. Published `main` head: `a8ed1d481b8903e71b0d0443a67887274d692d92` (PR #240's
merge). The four lanes below were cut from `731624106fc38a9f46e21553c61b3cb0ee56dfeb` (PR #230's
merge); `main` then moved twice under them — `3ade22b` (a `.gitignore`-only direct push, #236) and
the lane merges themselves — so each remaining lane rebases onto the current head and re-proves
against it rather than inheriting. One bounded rollout workstream is blocked on human-only runtime
proof; implementation lanes are listed under "Active implementation" below.

Current runtime state, unchanged by this wave: canonical source, the producer marker, and deployed
global bytes are **1.6.27**; all runtime canaries remain at **1.6.26**, the last directly proved
version. Nothing merged on 2026-08-07/08 touched `templates/hooks/dispatch.py` — the one lane that
does (#201/PR #239) is still open — so `FLOOR_VERSION` is still 1.6.27 and no marker moved. The
changed producer marker and every later consumer-marker change require their own exact-root proof.

## Active rollout — issue #232, blocked on human-only runtime proof

Static deployment is complete and is NOT runtime proof:

- Claude-config PR #127 merged as `6aac87507c5afbb35da39f38628b880feb38921a`; both authoring
  and deployed checkouts are clean at that merge. The explicit `sync-global` dry run and apply were
  identity-only, and Doctor proves canonical == deployed 1.6.27 from clean published mains.

The remaining rollout is STRICTLY ORDERED. SPECS §5 fixes a five-phase order, and this file uses
that numbering and no other:

| Phase | SPECS §5 step | State |
|---|---|---|
| P1 | producer merge | **done** — PR #230 |
| P2 | reviewed clean-main install | **done** — claude-config PR #127, sync-global identity-only |
| P3 | producer exact-CWD re-trust and canaries | **NOT DONE** |
| P4 | consumer marker refresh | **NOT DONE — blocked by BOTH P3 and P3b** |
| P5 | each consumer's exact-CWD re-trust and canaries | **NOT DONE — blocked by P4** |

Only P1 and P2 are complete. Everything below is outstanding. Perform it in this sequence and never
out of it:

- **P3 — producer, first and alone.** In a new normal Codex TUI launched from the agent-harness
  exact repository root, complete `/hooks` review and re-trust of the sole project handler, confirm
  its enabled state, run `py -3 harness.py doctor --repo .` (bare `doctor` runs only the global
  checks and skips the producer adapter, activation, and project-floor checks), then collect BOTH
  1.6.27 canary legs — the harmless allow (`git status --short --branch`) and the inert local deny
  probe (`git push --dry-run --no-verify --force . HEAD:refs/heads/codex-h2-deny-canary`).
- **P3b — fresh global Claude proof**, independently, against the deployed 1.6.27 bytes. Claude and
  Codex are distinct runtimes; neither proves the other.
- **P4/P5 — only after P3 and P3b both succeed.** The three consumer marker PRs — EvidenceDeck #21,
  collaborative-hill-lab #5, SwarmingLilMen #52 — were closed unmerged at the producer-first gate;
  their reviewed branches and heads are preserved. Reopen them one at a time, each for its own
  exact-root proof. SwarmingLilMen additionally carries a separate owner gate under its own issue
  #91.

Refreshing or validating any consumer marker before P3 and P3b both pass is out of order and is not
authorized by this file. No runtime proof is inherited from deployment, from Doctor, or from the
completed 1.6.26 wave.

## Active implementation

Four bounded lanes were dispatched 2026-08-07, each in its own isolated worktree with a declared
region boundary. Exactly one touched `templates/hooks/dispatch.py`; the other three were forbidden
from it, so no two lanes could collide on `FLOOR_VERSION`, the adapter marker, or the charter
digests. **Two landed, two remain open with confirmed blockers.** Every region boundary held: no
lane wrote outside its declared region.

| Lane | PR | Outcome |
|---|---|---|
| #110 cross-product gate | **#240** | **MERGED `a8ed1d4`** at head `f06b304`. Nine green, adversarial review MERGE with zero blocking findings and every claim reproduced. |
| #130 secret-file reading | **#237** | **MERGED `8134cf4`** at head `c1da78a`. Nine green, adversarial review MERGE with zero blocking findings. `Refs #130`, not `Closes` — the charter ruling is the owner's. |
| #201 numeric `push.followTags` | **#239** | **OPEN, blocked.** Nine green at `6b93c9a`, but review verdict FIX with two blocking findings: it conflicts with `main` after #234, and its `plans/ACTIVE.md` asserted "1.6.27 was never deployed", which is false. |
| #139 nested logical root | **#238** | **OPEN, blocked.** Nine green at `5e7aa28` and all seven acceptance criteria met, but two independent reviewers converged on three P1 correctness defects in `harness.py`. |

Neither open PR is parked: each has one fix round remaining within law 2's budget, and the exact
blockers are recorded on the PR thread. Do not restart either lane from scratch — the evidence
already gathered is sound and was independently reproduced.

**#239's blockers, precisely.** (1) Rebase onto current `main`, taking `main`'s structure — it
carries the P1–P5 rollout phase table — and adding the 1.6.28 facts to it rather than restoring the
branch's older shape. (2) The correct state is **deployed 1.6.27, runtime-proved 1.6.26**; "never
deployed" and "deployed, not yet runtime-proved" are materially different and the second is true.
(3) A base change counts as a head change, so CI and review are owed again on the rebased head.
`dispatch.py` itself does not conflict, so the parser evidence carries; the documentation evidence
does not. Residual toolchain-dependent over-block tracked as #243.

**#238's blockers, precisely.** (1) `harness.py:3988` — Windows junctions are followed by the
nested-root search although SPECS §2.1 and the new docstring both promise they are skipped;
`entry.is_dir(follow_symlinks=False)` classifies a junction as an ordinary directory, and the repo
already owns the correct predicate in `path_is_alias()` at `harness.py:471`. (2) `harness.py:3999`
— the downward search can select a nested independent Git repository or submodule, so `git status`
and `git remote` answer for the wrong repository, contradicting SPECS §2.1's "Git facts stay the
checkout's" which this PR wrote. (3) `harness.py:8018` — Doctor's canonical adapter is retargeted to
a downward-resolved root while the layer walk still runs to the requested path, so
`canonical_root_floor_count` is structurally 0 for exactly the new case and a previously-certified
configuration regresses. Plus a non-blocking P2 (`frontier.pop(0)` is quadratic).

**Declared-cap tension, recorded rather than resolved.** `README.md` declares this file as allowing
"at most two active, executable workstreams", and four implementation lanes plus one blocked rollout
exceed that count. The count was not silently rewritten to fit. The reading applied here is that the
cap's purpose is collision avoidance on shared T4-class infrastructure — the hazard the previous
snapshot named explicitly was a *second dispatcher slice* — and that disjoint-region lanes do not
create it. That reading is an assumption, not a ratified change: **Assumption: a region-disjoint lane
does not consume a workstream slot. Reason: the cap protects against colliding edits to
`dispatch.py`/`FLOOR_VERSION`/the adapter marker, and exactly one lane can touch those.** Issue #233
tracks re-expressing the cap as a region/collision rule or reaffirming it as a hard count; until that
is decided, the declared count in `README.md` stands as written and this note records the divergence.

**Reversal path, updated now that two lanes have landed.** The original note said the divergence was
reversible by closing the three non-dispatcher PRs. That is no longer accurate: #237 and #240 are
merged, so reversing them means reverting two merge commits (`8134cf4`, `a8ed1d4`), not closing
PRs. Only #238 and #239 remain closable. Recorded rather than quietly dropped, because a stated
reversal path that has silently expired is worse than none.

**What the experiment measured, for whoever rules on #233.** Four region-disjoint lanes produced no
region collision and no merge conflict *between lanes* — the boundaries held exactly as predicted.
The costs that did appear were elsewhere and are the real input to the decision: `main` moved twice
under in-flight branches (once from a merged lane, once from a `.gitignore` push, see #236), which
forced a rebase and invalidated one branch's documentation evidence; and review attention, not
region overlap, became the binding constraint — #234 alone consumed four review rounds. That is
evidence for reading B (reviewer bandwidth) as the cap's real content even though reading A
(collision avoidance) is what the prose describes.

## Completed current snapshot

- PR #234 merged as `8a1a685` and published this ledger, superseding parked PR #231 after a
  confirmed late P1 on its rollout ordering; #231 closed unmerged with its branch preserved. It
  fixed the producer-first ordering, added **H-14** for the human-only 1.6.27 proof, and recorded
  the four-lane dispatch. It took **four** review rounds, each producing an ordering or gating P1
  on a *different* surface; #242 records that as a document-structure problem — the rollout order is
  restated in three places, so any edit can desynchronize them — and proposes stating it once.
- PR #240 merged as `a8ed1d4` and closed #110. `_composable()` now detects executable separators
  outside inert quoted spans instead of by raw substring, so the flagship SPECS §6 must-allow class
  (prose *containing* dangerous-looking text) is measured rather than silently dropped:
  `SMOKE_BENIGN_CORPUS` 416 → 459, swept `(case, shape)` pairs 107,699 → 111,342. The aggregate
  `CHARTER_RULE_DENY_FLOOR` is replaced by `CHARTER_RULE_DENY_PAIRS`, 569 exact `(probe, shape)`
  pairs asserted as set membership across 8 postures, so added coverage can no longer compensate for
  lost coverage. It surfaced 69 pre-existing over-blocks, recorded in `DOCUMENTED_CASE_OVER_BLOCKS`
  and reported as #235 — without touching `dispatch.py`.
- PR #237 merged as `8134cf4` and advanced #130 (`Refs`, not `Closes`). It measured the secret
  matcher rather than asserting it, and disproved half the issue's premise: `.pem` **is** protected
  by `\.pem$`, present since the repo's first commit. Because the `secrets?\.` and `\.pem$`
  fragments and SPECS §6's wording have coexisted unchanged since `c87e906`, BLUEPRINT §2 class (c)
  ("a listed must-block form NEWLY allowed") is not met, so the freeze's default governs and it
  landed as a `FLOOR_LIMITATIONS.md` ledger line plus a SPECS §6 scope note. #130 stays open for the
  owner's charter ruling; #244 tracks the remaining description-precision defects.
- PR #230 merged as `731624106fc38a9f46e21553c61b3cb0ee56dfeb` and closed #227. Canonical
  source 1.6.27 parses Git's valueless `push.followTags` record as true, preserves the exact
  `--no-follow-tags` override, and fails closed on every other separator-free or unterminated
  configuration listing. All nine hosted jobs and two distinct T3 review lenses passed.
- PR #200 merged the six-case bounded #196 public-push narrowing repair and closed #196. A confirmed
  late P1 showed that ordinary-submodule metadata could not prove a unique primary checkout, so
  PR #202 withdrew only that exception and restored the fail-closed boundary. Both exact heads
  passed all nine hosted checks; #202 also passed its required independent read-only review.
- EvidenceDeck, SwarmingLilMen, and collaborative-hill-lab completed the bounded consumer rollout;
  no other registered default checkout owns a tracked adapter.
- Do not infer priority from issue number alone or reopen the completed #196/#200/#202 pipeline.

## Completed in this wave

- PR #182 closed #179 by changing only the aggregate Verify timeout from 15 to 20 minutes. PR #183
  closed #171 by reducing reflog reachability probes from up to five Git processes to one stdin-fed
  traversal with equivalent fail-closed results.
- PR #187 closed #177 with schema/runtime surrogate parity. PR #194 closed #167 with suspend-aware,
  rollback-detecting fingerprint expiry and global stop-on-invalidity. No live closeout apply ran.
- PR #193 merged the four owner-authorized #184 public-push security repairs as `b2c2fd4`; #184 then
  closed with exact producer proof, without authorizing live installation. PR #200 closed #196 with
  five retained fail-closed usability narrowings; PR #202 removed the sixth after late review proved
  its positive case unprovable. #201 records the remaining non-blocking numeric-boolean edge.
- PR #195 published the current workbench continuity homes. PR #197 preserved direct non-commit
  `ORIG_HEAD` identity and closed #172; its exact-head run passed all nine hosted jobs, and the
  post-merge review/comment/thread refresh found no late feedback.
- PR #198 skipped only the synthetic native-Windows executable-mode comparison, retained every
  ordinary preservation probe, preserved the POSIX mode-only blocker, and closed #170. PR #199
  published its state closeout.
- PR #204 closed #89 with static Windows Git command-fidelity diagnosis; exact head `2150b420`,
  base `6b49a67`, and all nine jobs in run `30714604384` passed before merge `77a9759`. PR #206
  closed #131 with the tailored new-repo documentation contract; exact head `47fd5c1` and run
  `30717285862` passed before merge `ace7d77`. PR #205 closed #189 with diagnosis-only static
  Claude-hook topology reporting; exact head `ebfb03b`, base `ace7d77`, run `30718502986`, and
  zero unresolved threads passed before merge `e6d0558`.
- #74 closed on current executable evidence: PR #71 commits `0b488e5`/`e688d1e` are ancestors of
  main and the full hook smoke suite passed 2237/2237; the invalid-descriptor residual remains
  non-blocking. #96 closed on its existing PR #100 policy evidence (commit `6bedff3`, merge
  `62dfbb1`), the #75-to-#95 split, and focused cross-product proof 27/27.
- Documentation-only PR #208 closed #85 (base `0b3317d`, head `02cd197`, merge `02e3ba6`): all
  nine jobs in run `30722065509` passed with zero unresolved threads. It documents Codex project
  hook trust bootstrap only; no trust mutation, canary, or deployment ran. Documentation-only PR
  #209 closed #84 (base `02e3ba6`, head `0e5845e`, merge `aee3ea6`): all nine jobs in run
  `30722999868` passed with zero unresolved threads. It documents linked-worktree candidate
  validation only; no Doctor behavior, trust/canary/deployment, or consumer rollout changed.
- Documentation-only PR #210 published the preceding state ledger (merge `4203e7c`). PR #211
  closed #109 by making cross-product shapes executable (merge `b483709`). PR #213 closed #119
  by isolating the non-temporary prefix fixture (head `0134bb81`, base `b483709`, merge
  `446e14f`); all nine hosted checks passed before merge.
- PR #212 closed #98 by making `doctor --config-root` compare source guidance only after proving
  a clean, current `main` checkout of the harness origin's `claude-config` sibling. Final head
  `62a59a8`, base `446e14f`, merge `ac3266a`, and all nine jobs in run `30731418878` passed. The
  cross-platform fixture P1 and macOS physical-root error were fixed before that run; three P2
  robustness notes were triaged without reopening the bounded fix round. No global deploy, trust
  mutation, or live canary ran.
- PRs #154/#155 were closed unmerged after exact supersession inventory; branches and historical
  review evidence remain preserved.

## Parked or queued, not active

- #160 closed through PR #219: effective disablement suppresses only a cross-layer mixed-transport
  conflict; same-table conflict remains invalid and a later re-enable fails closed. Doctor reports
  static topology only, not complete Codex parser acceptance for inactive definitions.
- #201 is no longer held. The hold read "while dispatcher/smoke ownership is occupied", and #227
  released that ownership when PR #230 shipped, so #201 is dispatched as the sole dispatcher lane
  under "Active implementation" above. It remains bounded exactly as before: it is not permission to
  reopen #193/#196 or to broaden the parser beyond `push.followTags`.
- #186 is owned by the canonical `review-and-ship` skill in `claude-config`, not this runtime.
  #188 awaits an owner-reviewed consumer manifest; #190 awaits a real generated launcher call
  site. #185/#191/#192 remain mapped follow-ups. Replay slices remain held while the replay-tool
  worktree is occupied; `tooling/corpus-replay` remains at preserved `afb1c0a`, one local commit
  ahead, and is ineligible until that checkpoint receives tests, review, and an explicit publish
  decision.
- H-2 is closed after the exact current-consumer marker/review/trust/canary wave. AH-10 extraction
  and a public replay repository remain deferred.
