# Agent Harness roadmap

Snapshot: 2026-07-31 at `main@81125c57ec6d1a750ddd43b0110c6928f9f4a860`.
The mission and epic outcomes are authoritative in `AGENT_HARNESS_AGENT_BRIEF.md`; this file owns
live dependency, evidence, issue, and PR mapping. Refresh GitHub before selecting work.

## Epic map

| Epic | Dependency | Evidence and outcome state | Primary open issues |
|---|---|---|---|
| AH-1 — authority and baseline | none | **Active.** The workbench brief, immutable floor tag, and state homes exist; a reproducible current deployed-floor baseline remains incomplete. | #4, #95, #96, #119, #138 |
| AH-2 — internal Policy Lab | AH-1 truth and corpus provenance | **Implemented core; bounded follow-ups queued.** PR #140 merged deterministic JSON/Markdown replay evidence and closed #148/#149. Replay remains internal and experimental. | #141, #142, #143, #144, #145, #146, #147, #150, #152, #153, #156, #157, #158 |
| AH-3 — Pattern Guard v2 | AH-1 baseline + AH-2 replay + AH-8 measurements | **Queued, not implemented.** Use #21 evidence to build a small shadow guard for explicit catastrophic families. Universal-parser expansion is out. | #3, #12, #17, #24, #26, #32, #38, #58, #59, #62, #65, #74, #77, #78, #81, #125, #128, #129, #130, #133, #134, #135, #136, #137 |
| AH-4 — Doctor v2 | existing Doctor foundation + reproduced configuration failures | **Partial; no active writer.** Configuration reality is evidenced, but runtime/source ordering and missing-surface findings remain incomplete. | #19, #85, #89, #98, #107 |
| AH-5 — runtime/external adapters | AH-2 stable source and report contracts | **Partial.** Recorded and generic process sources exist; runtime surface parity remains bounded. | #86, #88 |
| AH-6 — estate operations | AH-1 authority + AH-4 findings | **Partial; parked PRs.** Seed/audit/doctor/sync exist. Cross-repository topology and closeout need portable proof. | #76, #84, #87, #91, #101, #122, #131, #139, #151 |
| AH-7 — shadow/canary/enforcement evidence | AH-3/AH-4/AH-5 candidates + explicit owner scope | **Owner-parked.** Issue #39 is measured rollout evidence. H-2 remains the only open human item; do not restart estate-wide canaries. | #39 |
| AH-8 — integrated measurement | evidence from all executable capabilities | **Historical measurements exist; integrated current baseline unverified.** Keep warning, approval, and denial metrics separate. | #21, #109, #110, #118, #120 |
| AH-9 — claude-config integration | AH-4 diagnosis + AH-6 operations + private boundary | **Queued.** Define data/command interfaces without importing private internals. | none primary; secondary #87, #98, #101 |
| AH-10 — public extraction/compatibility | demonstrated internal stability and demand | **Deferred/frozen.** No public replay repository or blueprint-plugin extraction is authorized. | none |

All 64 issues open at this snapshot have one primary epic above. Cross-cutting ownership is explicit:

- #140–#144 are Policy Lab history/work: PR #140 is merged; #141–#144 remain AH-2.
- #96 is the AH-1 freeze decision; #118/#120 are AH-8 friction evidence feeding bounded AH-3 work.
- #19/#85/#89/#98 are the Doctor/configuration-reality cluster; #19/#85 also inform AH-5.
- #87/#101/#139 are estate-operations evidence; #87/#98/#101 also feed AH-9.
- #142–#147 are primary AH-2 replay follow-ups and secondary AH-5 adapter-contract inputs.
- #21 and its measured follow-ons support bounded Pattern Guard v2; they do not authorize a
  universal parser redesign.
- #152/#153 are bounded replay follow-ups, not workbench-wide priorities.

## Open PR ownership

| PR | Epic/seam | State and next condition |
|---|---|---|
| #154 — issue #151 worktree closeout | AH-6 | Parked at `5c61b6b`; Windows/macOS path identity and process-occupancy evidence remain red. Its earlier CI predates PR #140's base change and cannot be reused. |
| #155 — issue #87 MCP topology Doctor | AH-6 with AH-4/AH-9 seams | Parked at `c37ff81`; Windows `.cmd`/`.bat` Docker recognition and path identity remain red. Its earlier CI predates PR #140's base change and cannot be reused. |

Do not duplicate either occupied branch. Oldest/base work lands first, and every base change
re-proves the affected head.

## Outcome ordering

1. Keep AH-1 state and measured baseline truthful while preserving the frozen legacy floor.
2. Finish PR-sized AH-2 report/source defects from direct evidence; do not turn replay into the
   whole workbench.
3. Use AH-8 evidence to choose bounded AH-3 families and measure them in shadow before enforcement.
4. Advance AH-4/AH-6 only from reproduced configuration and estate failures; keep diagnosis and
   mutation separate.
5. Leave AH-7 owner-parked and AH-10 deferred until their explicit evidence gates change.
