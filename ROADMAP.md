# Agent Harness roadmap

Snapshot: 2026-07-31 at `main@e23e97b464208ee6035d4155ff7e9b5316f2efec`.
The mission and epic outcomes are authoritative in `AGENT_HARNESS_AGENT_BRIEF.md`; this file owns
live dependency, evidence, issue, and PR mapping. Refresh GitHub before selecting work.

## Epic map

| Epic | Dependency | Evidence and outcome state | Primary open issues |
|---|---|---|---|
| AH-1 — authority and baseline | none | **Active.** The workbench brief, immutable floor tag, and state homes exist; a reproducible current deployed-floor baseline remains incomplete. PR #178 exposed the measured aggregate Windows CI-budget defect tracked in #179. | #4, #95, #96, #119, #138, #179 |
| AH-2 — internal Policy Lab | AH-1 truth and corpus provenance | **Implemented core; bounded follow-ups queued.** PR #140 merged deterministic replay evidence; PRs #159/#163 repaired report/manifest contracts; PRs #174/#176 closed #152/#156 with reproduction and schema/runtime proof. Replay remains internal and experimental. | #141, #142, #143, #145, #146, #147, #150, #157, #158, #177 |
| AH-3 — Pattern Guard v2 | AH-1 baseline + AH-2 replay + AH-8 measurements | **Queued, not implemented.** Use #21 evidence to build a small shadow guard for explicit catastrophic families. Universal-parser expansion is out. | #3, #12, #17, #24, #26, #32, #38, #58, #59, #62, #65, #74, #77, #78, #81, #125, #128, #129, #130, #133, #134, #135, #136, #137 |
| AH-4 — Doctor v2 | existing Doctor foundation + reproduced configuration failures | **Partial.** PR #161 implemented static MCP topology diagnosis and closed #87; PRs #175/#178 closed shared-source identity and Docker command-position defects #164/#165. Remaining configuration-reality gaps stay bounded. | #19, #85, #89, #98, #107, #160 |
| AH-5 — runtime/external adapters | AH-2 stable source and report contracts | **Partial.** Recorded and generic process sources exist; runtime surface parity remains bounded. | #86, #88 |
| AH-6 — estate operations | AH-1 authority + AH-4 findings | **Partial; executable closeout implemented.** PR #162 added guarded closeout, PR #169 repaired every confirmed late-review work-loss path, and PR #180 closed #168 with complete fail-closed partial-apply reporting. | #76, #84, #91, #101, #122, #131, #139, #167, #170, #171, #172 |
| AH-7 — shadow/canary/enforcement evidence | AH-3/AH-4/AH-5 candidates + explicit owner scope | **Owner-parked.** Issue #39 is measured rollout evidence. H-2 remains the only open human item; do not restart estate-wide canaries. | #39 |
| AH-8 — integrated measurement | evidence from all executable capabilities | **Historical measurements exist; integrated current baseline unverified.** Keep warning, approval, and denial metrics separate. | #21, #109, #110, #118, #120 |
| AH-9 — claude-config integration | AH-4 diagnosis + AH-6 operations + private boundary | **Queued.** Define data/command interfaces without importing private internals. Secondary seams remain #98, #101, and #160. | none |
| AH-10 — public extraction/compatibility | demonstrated internal stability and demand | **Deferred/frozen.** No public replay repository or blueprint-plugin extraction is authorized. | none |

All 65 issues open at this snapshot have one primary epic above. Cross-cutting ownership is explicit:

- #140–#144 are Policy Lab history: PR #140 merged the core, #141–#143 remain open, and PR #163
  closed #144. #145–#147 remain bounded replay/adapter follow-ups.
- #96 is the AH-1 freeze decision; #179 is the measured AH-1 CI-budget defect; #118/#120 are
  AH-8 friction evidence feeding bounded AH-3 work.
- #19/#85/#89/#98 are the Doctor/configuration-reality cluster; #19/#85 also inform AH-5.
- Closed #87 established the static MCP topology baseline through PR #161; #101/#139 remain
  estate-operations work, and #98/#101 retain AH-9 seams.
- #160 remains the primary AH-4 follow-up from the #87 successor and retains AH-9 lineage;
  PRs #175/#178 closed #164/#165.
- PR #180 closed bounded AH-6 reporting follow-up #168; #167/#170/#171/#172 remain queued and do
  not authorize live estate cleanup.
- #142–#147 are primary AH-2 replay follow-ups and secondary AH-5 adapter-contract inputs.
- #21 and its measured follow-ons support bounded Pattern Guard v2; they do not authorize a
  universal parser redesign.
- #152/#156 closed through bounded PRs #174/#176; #153 closed via PR #159; #177 retains the
  remaining lone-surrogate schema/runtime boundary.

## Open PR ownership

No PR was open at this snapshot. PRs #154/#155 were closed unmerged after exact inventory proved
their outcomes and review findings were superseded by merged PRs #161/#162/#169/#175. Their
branches and unresolved historical threads were preserved as defect evidence; do not revive or
delete them. PRs #173–#180 then merged bounded continuity, replay, Doctor, and estate-reporting
slices through `main@e23e97b`. Every base or head change re-proves affected evidence.

## Outcome ordering

1. Keep AH-1 state and measured baseline truthful while preserving the frozen legacy floor.
2. Finish PR-sized AH-2 report/source defects from direct evidence; do not turn replay into the
   whole workbench.
3. Use AH-8 evidence to choose bounded AH-3 families and measure them in shadow before enforcement.
4. Advance AH-4/AH-6 only from reproduced configuration and estate failures; keep diagnosis and
   mutation separate.
5. Leave AH-7 owner-parked and AH-10 deferred until their explicit evidence gates change.
