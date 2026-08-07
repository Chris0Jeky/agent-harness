# Agent Harness roadmap

Snapshot: 2026-08-07, implementation state through `main@3ade22b1e494c2d303fcd73fd8669b899b42559b`
(a `.gitignore`-only commit on top of PR #230's merge `731624106fc38a9f46e21553c61b3cb0ee56dfeb`,
which remains the last commit to change implementation content).
The mission and epic outcomes are authoritative in `AGENT_HARNESS_AGENT_BRIEF.md`; this file owns
live dependency, evidence, issue, and PR mapping. Refresh GitHub before selecting work.

## Epic map

| Epic | Dependency | Evidence and outcome state | Primary open issues |
|---|---|---|---|
| AH-1 — authority and baseline | none | **Active.** The workbench brief, immutable floor tag, and state homes exist; PR #182 closed the measured CI-budget defect #179. Bounded consumer-smoke proving issue #185 is queued. #233 asks whether the declared two-workstream cap is a hard count or a region/collision rule, after a 2026-08-07 four-lane dispatch diverged from it on a named assumption. | #4, #95, #138, #185, #233 |
| AH-2 — internal Policy Lab | AH-1 truth and corpus provenance | **Implemented core; bounded follow-ups queued.** PR #140 merged deterministic replay evidence; PRs #159/#163 repaired report/manifest contracts; PRs #174/#176/#187 closed #152/#156/#177 with reproduction and schema/runtime proof. Replay remains internal and experimental. | #141, #142, #143, #145, #146, #147, #150, #157, #158 |
| AH-3 — Pattern Guard v2 | AH-1 baseline + AH-2 replay + AH-8 measurements | **Bounded security-preservation exception implemented.** PR #193 closed #184 after repairing its four public-push gaps; PR #200 closed #196 with five retained fail-closed usability narrowings, and PR #202 withdrew the unprovable sixth case after late review. PR #230 closed #227 with the valid valueless Git-config record repair in source 1.6.27; its runtime rollout is tracked under AH-7. #201 owns the remaining numeric-boolean edge and #225 owns parser/audit parity for the public-synthetic route. Beyond those bounded cases, use #21 evidence for small catastrophic families; universal-parser expansion is out. | #3, #12, #17, #24, #26, #32, #38, #58, #59, #62, #65, #77, #78, #81, #125, #128, #129, #130, #133, #134, #135, #136, #137, #201, #225 |
| AH-4 — Doctor v2 | existing Doctor foundation + reproduced configuration failures | **Partial.** PR #161 implemented static MCP topology diagnosis and closed #87; PRs #175/#178 closed shared-source identity and Docker command-position defects #164/#165; PR #204 closed #89 with static Windows Git command-fidelity diagnosis; PR #205 closed #189 with diagnosis-only static Claude-hook topology reporting; PR #212 closed #98 with canonical guidance-source identity before byte comparison. PR #208 closed documentation-only trust-bootstrap issue #85 without a runtime claim. PR #219 closed #160 with the selected disabled mixed-transport topology precedence. | #19, #107 |
| AH-5 — runtime/external adapters | AH-2 stable source and report contracts | **Partial.** Recorded and generic process sources exist; runtime surface parity remains bounded. | #86, #88 |
| AH-6 — estate operations | AH-1 authority + AH-4 findings | **Partial; executable closeout implemented.** PRs #162/#169/#180 established guarded fail-closed closeout; PR #183 bounded reachability and closed #171; PR #194 made fingerprint expiry suspend-aware and closed #167; PR #197 retained direct non-commit `ORIG_HEAD` identity and closed #172; PR #198 skipped synthetic native-Windows mode deltas and closed #170; PR #206 published the tailored new-repo contract and closed #131. PR #209 closed linked-worktree validation documentation #84 without changing runtime behavior. Merge-gate completeness, creation, retirement, portability, and branch teardown remain queued. | #76, #91, #101, #122, #139, #186, #188, #190, #191, #192 |
| AH-7 — shadow/canary/enforcement evidence | AH-3/AH-4/AH-5 candidates + explicit owner scope | **Prior 1.6.26 rollout complete; 1.6.27 proof blocked on human-only runtime steps.** PR #230 changed the producer marker; claude-config PR #127 and supported clean-main sync then established static global 1.6.27 deployment. The remainder is strictly ordered per SPECS §5 — agent-harness **producer** exact-CWD re-trust and canaries first, then fresh global Claude proof, and only then consumer marker refresh. The three consumer marker PRs (EvidenceDeck #21, collaborative-hill-lab #5, SwarmingLilMen #52) were closed unmerged at that gate with branches preserved. Nothing is inherited from the completed 1.6.26 wave; H-2 stays closed for that dated inventory only. #232 is the durable tracker. | #39, #232 |
| AH-8 — integrated measurement | evidence from all executable capabilities | **Historical measurements exist; integrated current baseline unverified.** PR #211 made cross-product shapes executable and closed #109. Keep warning, approval, and denial metrics separate. | #21, #110, #118, #120 |
| AH-9 — claude-config integration | AH-4 diagnosis + AH-6 operations + private boundary | **Queued.** Define data/command interfaces without importing private internals. Secondary seam #101 remains; #160 is closed and retains historical AH-9 lineage. | none |
| AH-10 — public extraction/compatibility | demonstrated internal stability and demand | **Deferred/frozen.** No public replay repository or blueprint-plugin extraction is authorized. | none |

All 59 open issues at this snapshot have one primary epic above, measured with an explicit
`gh issue list --state open --limit 300` count. (The 2026-08-03 draft recorded 57; the true count was
58, and `gh issue list`'s silent default page size of 30 is the standing trap here — always pass an
explicit `--limit`.) Cross-cutting ownership is
explicit:

- #140–#144 are Policy Lab history: PR #140 merged the core, #141–#143 remain open, and PR #163
  closed #144. #145–#147 remain bounded replay/adapter follow-ups.
- #96 closed evidence-only: PR #100 policy commit `6bedff3`/merge `62dfbb1`, the #75-to-#95 split,
  and focused cross-product proof 27/27 satisfied its decision record. PR #182 closed measured
  CI-budget defect #179; #185 is bounded consumer-smoke proving work. PR #193 merged the
  owner-authorized #184 AH-3 security-preservation
  exception; #184 then closed with exact producer proof. PR #200 closed #196, PR #202 repaired its
  confirmed late fail-closed defect, and #201 owns the remaining bounded usability follow-up.
  #118/#120 are AH-8 friction evidence feeding AH-3.
- #74 closed evidence-only after PR #71 commits `0b488e5`/`e688d1e` were proved on main and the
  full smoke suite passed 2237/2237; its invalid-descriptor residual is non-blocking. #19 remains
  the open Doctor/configuration-reality cluster; PR #204 closed #89 and PR #212 closed #98 with
  canonical guidance-source identity. PR #208 closed #85 with a static trust-bootstrap contract
  only; it did not produce fresh-session trust evidence.
- Closed #87 established the static MCP topology baseline through PR #161; #101/#139 remain
  estate-operations work, and #101 retains an AH-9 seam.
- PR #219 closed #160, the primary AH-4 follow-up from the #87 successor; it retains AH-9 lineage
  and models disabled mixed-transport precedence as static topology only. PRs #175/#178 closed
  #164/#165, while PR #205 closed #189 with static Claude-hook topology diagnosis without
  authorizing removal.
- PR #180 closed bounded AH-6 reporting follow-up #168; PRs #183/#194/#197/#198 closed
  #171/#167/#172/#170, PR #206 closed #131, and PR #209 closed #84 with linked-worktree
  validation guidance only. #186 is owned by the canonical
  `review-and-ship` skill in `claude-config`; #188 awaits an owner-reviewed consumer manifest;
  #190 awaits a real generated launcher call site. #191/#192 remain mapped creation and
  proof-aware teardown work. None authorizes live estate cleanup.
- #142–#147 are primary AH-2 replay follow-ups and secondary AH-5 adapter-contract inputs.
- #21 and its measured follow-ons support bounded Pattern Guard v2; they do not authorize a
  universal parser redesign.
- #152/#156/#177 closed through bounded PRs #174/#176/#187; #153 closed via PR #159.

## Open PR ownership

Four bounded implementation lanes were dispatched 2026-08-07 against issues #201, #110, #139 and
#130, each in an isolated worktree with an exclusive region; `plans/ACTIVE.md` carries the region
table and the boundary each lane may not cross. Their PR numbers, exact heads, and review verdicts
are recorded there as they land. PR #231 was closed unmerged and superseded after a confirmed late
P1 on its rollout ordering; its branch `codex/close-issue227-rollout-state` and review history are
preserved. PR #204 closed #89 from exact head
`2150b420f05d8244ec922643bc0ca33b64f66885` against base
`6b49a67ef7642683341d8e894faafe47a5d19c58`; run `30714604384` passed before merge
`77a9759c356f3a2add0ecada157cd95c4e14e6a5`. PR #206 closed #131 from exact head
`47fd5c18590bb3f63be27c0f3e161adf29acbd0f`; run `30717285862` passed before merge
`ace7d77474c0d35e487f3c8eba0897a4d2a7e457`. PR #205 closed #189 from exact head
`ebfb03bdc74bca72f08ae3d7a75ac7a319ba5c92` against base
`ace7d77474c0d35e487f3c8eba0897a4d2a7e457`; run `30718502986` and zero unresolved threads
passed before merge `e6d0558200d006de0b86630a1d31bb4ce8f06244`.

PR #208 closed #85 from base `0b3317d`, exact head `02cd197`, and all-nine-green run
`30722065509` with zero unresolved threads before merge `02e3ba6`; it is documentation-only
trust-bootstrap guidance, not trust or canary evidence. PR #209 closed #84 from base `02e3ba6`,
exact head `0e5845e`, and all-nine-green run `30722999868` with zero unresolved threads before
merge `aee3ea6`; it is documentation-only linked-worktree validation guidance, not Doctor, trust,
canary, deployment, or consumer-rollout behavior.

PR #210 published the preceding state ledger (merge `4203e7c`). PR #211 made cross-product shapes
executable and closed #109 (merge `b483709`); PR #213 isolated the non-temporary prefix fixture
and closed #119 (merge `446e14f`). PR #212 closed #98 by proving canonical global-guidance source
identity before byte comparison (merge `ac3266a`); final run `30731418878` passed all nine jobs.
Documentation-only PR #214 refreshed the active/system ledger (merge `c48b21e`). None of this wave
authorized runtime deployment, trust mutation, or a live canary.

PR #200 closed #196 and merged as
`59dd9644bf3660c45de4358ce99b0e2bd162cd27`; exact-head run `30708929446` passed all nine jobs.
PR #202 then repaired a confirmed late P1 by withdrawing the unprovable ordinary-submodule
allowance and merged as `93755c6532e2e32bb0c1c47364fba12440d1da8b`; exact-head run
`30709917303` also passed all nine jobs, its independent review was clean, and the original #200
thread is resolved. #201 remains the bounded non-blocking follow-up. PR #199 published #198's state
closeout. PRs #154/#155 remain closed unmerged with branches and historical threads preserved.
PRs #181/#182/#183/#187/#194/#195/#197/#198/#199/#200/#202/#210/#211/#212/#213/#214 merged continuity, CI-budget,
reachability, replay-schema, suspend-aware closeout, workbench-state, direct-`ORIG_HEAD`,
native-Windows mode-capability, state-closeout, bounded floor, guidance-identity, fixture, and
ledger slices through `main@c48b21e`.
Every base or head change re-proves affected evidence.

## Outcome ordering

1. Keep AH-1 state and measured baseline truthful while preserving the frozen legacy floor.
2. Finish PR-sized AH-2 report/source defects from direct evidence; do not turn replay into the
   whole workbench.
3. Use AH-8 evidence to choose bounded AH-3 families and measure them in shadow before enforcement.
4. Advance AH-4/AH-6 only from reproduced configuration and estate failures; keep diagnosis and
   mutation separate.
5. Preserve AH-7's evidence boundary: a future consumer, source path, marker, or handler change
   requires its own bounded review/trust/canary wave. Leave AH-10 deferred until its explicit
   evidence gates change.
