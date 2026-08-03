# Active workstreams

Snapshot: 2026-08-03. Published implementation base: `731624106fc38a9f46e21553c61b3cb0ee56dfeb`.
One bounded rollout workstream is active; both implementation slots are free.

Current runtime state: canonical source, the producer marker, and deployed global bytes are 1.6.27;
all runtime canaries remain at 1.6.26, the last directly proved version. The changed producer marker
and every later consumer-marker change require their own exact-root proof.

## Active rollout

- Claude-config PR #127 merged as `6aac87507c5afbb35da39f38628b880feb38921a`; both authoring
  and deployed checkouts are clean at that merge. The explicit `sync-global` dry run and apply were
  identity-only, and Doctor proves canonical == deployed 1.6.27 from clean published mains.
- Complete fresh global Claude proof and separate marker/review/trust/enable/allow-deny proof for
  agent-harness, EvidenceDeck, SwarmingLilMen, and collaborative-hill-lab. No runtime proof is
  inherited from deployment or from the 1.6.26 wave.

## Completed current snapshot

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
- #201 is the bounded AH-3 follow-up for Git numeric booleans in exact no-follow-tags narrowing; it
  remains held while dispatcher/smoke ownership is occupied and is not permission to reopen
  #193/#196 or broaden the parser.
- #186 is owned by the canonical `review-and-ship` skill in `claude-config`, not this runtime.
  #188 awaits an owner-reviewed consumer manifest; #190 awaits a real generated launcher call
  site. #185/#191/#192 remain mapped follow-ups. Replay slices remain held while the replay-tool
  worktree is occupied; `tooling/corpus-replay` remains at preserved `afb1c0a`, one local commit
  ahead, and is ineligible until that checkpoint receives tests, review, and an explicit publish
  decision.
- H-2 is closed after the exact current-consumer marker/review/trust/canary wave. AH-10 extraction
  and a public replay repository remain deferred.
