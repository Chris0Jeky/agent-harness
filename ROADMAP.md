# Agent Harness roadmap

Snapshot: 2026-08-01 at `main@c8a1d2649bd4b2eb7ba7dec18089d43caccd08d7`.
The mission and epic outcomes are authoritative in `AGENT_HARNESS_AGENT_BRIEF.md`; this file owns
live dependency, evidence, issue, and PR mapping. Refresh GitHub before selecting work.

## Epic map

| Epic | Dependency | Evidence and outcome state | Primary open issues |
|---|---|---|---|
| AH-1 — authority and baseline | none | **Active.** The workbench brief, immutable floor tag, and state homes exist; PR #182 closed the measured CI-budget defect #179. Bounded consumer-smoke proving issue #185 is queued. | #4, #95, #96, #119, #138, #185 |
| AH-2 — internal Policy Lab | AH-1 truth and corpus provenance | **Implemented core; bounded follow-ups queued.** PR #140 merged deterministic replay evidence; PRs #159/#163 repaired report/manifest contracts; PRs #174/#176/#187 closed #152/#156/#177 with reproduction and schema/runtime proof. Replay remains internal and experimental. | #141, #142, #143, #145, #146, #147, #150, #157, #158 |
| AH-3 — Pattern Guard v2 | AH-1 baseline + AH-2 replay + AH-8 measurements | **Bounded security-preservation exception implemented.** PR #193 closed #184 after repairing its four public-push gaps; #196 owns six review-proven fail-closed usability edges. Beyond those bounded cases, use #21 evidence for small catastrophic families; universal-parser expansion is out. | #3, #12, #17, #24, #26, #32, #38, #58, #59, #62, #65, #74, #77, #78, #81, #125, #128, #129, #130, #133, #134, #135, #136, #137, #196 |
| AH-4 — Doctor v2 | existing Doctor foundation + reproduced configuration failures | **Partial.** PR #161 implemented static MCP topology diagnosis and closed #87; PRs #175/#178 closed shared-source identity and Docker command-position defects #164/#165. #160 is reproduced and owner-blocked on precedence; #189 adds a bounded duplicate-Claude-floor seam. | #19, #85, #89, #98, #107, #160, #189 |
| AH-5 — runtime/external adapters | AH-2 stable source and report contracts | **Partial.** Recorded and generic process sources exist; runtime surface parity remains bounded. | #86, #88 |
| AH-6 — estate operations | AH-1 authority + AH-4 findings | **Partial; executable closeout implemented.** PRs #162/#169/#180 established guarded fail-closed closeout; PR #183 bounded reachability and closed #171; PR #194 made fingerprint expiry suspend-aware and closed #167; PR #197 retained direct non-commit `ORIG_HEAD` identity and closed #172; PR #198 skipped synthetic native-Windows mode deltas and closed #170. Merge-gate completeness, creation, retirement, portability, and branch teardown remain queued. | #76, #84, #91, #101, #122, #131, #139, #186, #188, #190, #191, #192 |
| AH-7 — shadow/canary/enforcement evidence | AH-3/AH-4/AH-5 candidates + explicit owner scope | **Owner-parked.** Issue #39 is measured rollout evidence. H-2 remains the only open human item; do not restart estate-wide canaries. | #39 |
| AH-8 — integrated measurement | evidence from all executable capabilities | **Historical measurements exist; integrated current baseline unverified.** Keep warning, approval, and denial metrics separate. | #21, #109, #110, #118, #120 |
| AH-9 — claude-config integration | AH-4 diagnosis + AH-6 operations + private boundary | **Queued.** Define data/command interfaces without importing private internals. Secondary seams remain #98, #101, and #160. | none |
| AH-10 — public extraction/compatibility | demonstrated internal stability and demand | **Deferred/frozen.** No public replay repository or blueprint-plugin extraction is authorized. | none |

All 67 issues open at this snapshot have one primary epic above. Cross-cutting ownership is explicit:

- #140–#144 are Policy Lab history: PR #140 merged the core, #141–#143 remain open, and PR #163
  closed #144. #145–#147 remain bounded replay/adapter follow-ups.
- #96 is the AH-1 freeze decision; PR #182 closed measured CI-budget defect #179; #185 is bounded
  consumer-smoke proving work. PR #193 merged the owner-authorized #184 AH-3 security-preservation
  exception; #184 then closed with exact producer proof and #196 owns its fail-closed review
  follow-ups. #118/#120 are AH-8 friction evidence feeding AH-3.
- #19/#85/#89/#98 are the Doctor/configuration-reality cluster; #19/#85 also inform AH-5.
- Closed #87 established the static MCP topology baseline through PR #161; #101/#139 remain
  estate-operations work, and #98/#101 retain AH-9 seams.
- #160 remains the primary AH-4 follow-up from the #87 successor and retains AH-9 lineage; it is
  owner-blocked on disabled mixed-transport precedence. PRs #175/#178 closed #164/#165, while
  #189 adds static duplicate-Claude-floor diagnosis without authorizing removal.
- PR #180 closed bounded AH-6 reporting follow-up #168; PRs #183/#194/#197/#198 closed
  #171/#167/#172/#170. #186/#188/#190/#191/#192 cover merge-gate completeness, retirement,
  interpreter discovery, guarded creation, and proof-aware merged-branch teardown. None authorizes
  live estate cleanup.
- #142–#147 are primary AH-2 replay follow-ups and secondary AH-5 adapter-contract inputs.
- #21 and its measured follow-ons support bounded Pattern Guard v2; they do not authorize a
  universal parser redesign.
- #152/#156/#177 closed through bounded PRs #174/#176/#187; #153 closed via PR #159.

## Open PR ownership

No PR is open at this snapshot. PR #195 published the continuity checkpoint, PR #197 closed #172
while preserving its direct-object evidence, and PR #198 closed #170. PR #193 merged
as `b2c2fd40a1e3d99821983b6ad38a1fecd1d22809`, preserving head
`8648e5c7fb804fed4c991418401d411973350248`; run `30666338126` passed all nine jobs. Its first
five connector findings were recorded in #196 and resolved before merge; one late post-merge P2 was
added to #196, replied to, and resolved once. #184 was closed manually with exact producer proof
because #193 intentionally had no closing reference. PRs #154/#155 remain closed unmerged with branches and historical threads
preserved. PRs #181/#182/#183/#187/#194/#195/#197/#198 merged continuity, CI-budget,
reachability, replay-schema, suspend-aware closeout, workbench-state, direct-`ORIG_HEAD`, and
native-Windows mode-capability slices through `main@c8a1d26`. Every base or head change re-proves
affected evidence.

## Outcome ordering

1. Keep AH-1 state and measured baseline truthful while preserving the frozen legacy floor.
2. Finish PR-sized AH-2 report/source defects from direct evidence; do not turn replay into the
   whole workbench.
3. Use AH-8 evidence to choose bounded AH-3 families and measure them in shadow before enforcement.
4. Advance AH-4/AH-6 only from reproduced configuration and estate failures; keep diagnosis and
   mutation separate.
5. Leave AH-7 owner-parked and AH-10 deferred until their explicit evidence gates change.
