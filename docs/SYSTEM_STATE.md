# System state

## Source maintenance checkpoint — 2026-10-29

Inspected baseline: [`main@471ff6c`](https://github.com/Chris0Jeky/agent-harness/commit/471ff6c92457986b30da1091eea8e4e67613896a),
the merge of [#577](https://github.com/Chris0Jeky/agent-harness/pull/577). The canonical dispatcher
reports **1.8.1**. This checkpoint measures source and reconciles issue state; it does not
remeasure an installed home, native consumer, trust decision or live canary.

[ACTIVE](../plans/ACTIVE.md) owns the current work queue. [ROADMAP](../ROADMAP.md) owns remaining
dependencies. All earlier status text, including dated runtime evidence, is preserved in the
[October archive](archive/status-2026-10.md).

## Source already on the baseline

| Surface | Accepted source and evidence | Limit |
|---|---|---|
| Learning and replay records | [#544](https://github.com/Chris0Jeky/agent-harness/pull/544) validates complete outcome streams; [#562](https://github.com/Chris0Jeky/agent-harness/pull/562) refuses nonfinite/non-JSON publication; [#565](https://github.com/Chris0Jeky/agent-harness/pull/565) adds recursive string-key validation and strict advisory-ledger JSONL. #558/#563 are closed. | Trusted ingestion, omitted-tail detection and event identity remain #511. The advisory ledger is distinct from the learning stream; its line size remains uncapped. |
| Sync identity and cost | [#559](https://github.com/Chris0Jeky/agent-harness/pull/559) compares selected-tree identities in both directions; [#566](https://github.com/Chris0Jeky/agent-harness/pull/566) reuses snapshots within one preflight and retains fresh apply revalidation. #556 is closed. | Snapshots do not exclude concurrent writers. The later native bind-mount proof is recorded in #587 below. |
| Replay publication | [#555](https://github.com/Chris0Jeky/agent-harness/pull/555) privately stages output and binds caller parents; [#560](https://github.com/Chris0Jeky/agent-harness/pull/560) checks named inputs, visited transcripts and fellow outputs. | Existing target security and scanner limits remain; no multi-output crash-atomicity claim. |
| Canary chronology | [#548](https://github.com/Chris0Jeky/agent-harness/pull/548) excludes observations before the candidate/genome cutoff. | Labels and producer timestamps do not prove enrolled execution. #520/#517 retain the trusted backend boundary. |
| Replay regressions | [#577](https://github.com/Chris0Jeky/agent-harness/pull/577) pins duplicate-decision and tree-symlink refusal behavior. | The later macOS acknowledgement failure is tracked in #578 and addressed by candidate #581. |

Verified merge receipts: #565 is `21b35d1012d4aa7ffca754bf58a6f8f6a0bea560`; #566 is
`c2da76cf4912d4e379e93bfd6cfce8fb65abd890`. Both merged on 2026-10-14. They supersede the
2026-10-13 pages' open claims for #556/#558/#563; their historical records remain intact.

## Reviewed maintenance work

The source PRs below have independent reviews with no confirmed findings. Windows CI on #580
exposed collision-message and CRLF-fixture test assumptions; corrections preserve refusal
and exact source-byte checks. Use each PR's current head, checks, review
receipts and merge result when integrating; another branch's green suite does not prove that tree.

| PR | Behavior under review | Remaining acceptance |
|---|---|---|
| [#579](https://github.com/Chris0Jeky/agent-harness/pull/579) | System comparisons become explicitly observational and emit no canary gate. Promotion consumers reject old system-run authority. Regression weighting and triage deduplication are corrected; compatibility bundle advances to v5. | #520/#517 need trusted assignment/execution/store evidence. #511 needs trusted ingestion offsets and event-ID/cursor migration. Follow the PR's archival-read and derived-data rebuild contract. |
| [#580](https://github.com/Chris0Jeky/agent-harness/pull/580) | Bundle failures name recovery bytes and component/target mappings. Native name-only lookup checks absent destination and recovery spellings after identity/device preflight. | Carries #278's closure. The local managed environment cannot run mount qualification; #587 supplies the native CI proof. |
| [#581](https://github.com/Chris0Jeky/agent-harness/pull/581) | Atomic fixture acknowledgement, honest POSIX group cleanup, isolated Windows supervisor startup, bounded regex replies/stderr and execution-contract identity. | Carries #578/#576's closure. Native CI supplies Windows/macOS/Linux evidence. |
| [#582](https://github.com/Chris0Jeky/agent-harness/pull/582) | Tests own their fixture roots and match the Codex executable basename. | Local root suite: 2,114 tests, 68 skips; affected modules: 501 tests, seven skips. These results belong to #582's head. Native CI remains the platform gate. |
| [#583](https://github.com/Chris0Jeky/agent-harness/pull/583) | Recorded 50-case replay lab, visual docs entry point and bounded public asset staging. The browser displays recorded comparisons. | 102 Python staging/link tests, four JavaScript tests, Pages deployment and desktop/mobile browser verification passed. Filtering never changes the 50-case gate denominator; no live execution or canary claim. |
| [#584](https://github.com/Chris0Jeky/agent-harness/pull/584) | Platform/quote-aware shell anchors and reuse of one canonical-reference result, including UNPROVEN. | Carries #78's closure, including wrapper-variable and duplicate-probe follow-ups. Independent review ran 59 tests: 58 passed, one native-Windows skip; native CI supplies platform proof. |
| [#587](https://github.com/Chris0Jeky/agent-harness/pull/587) | Real same-device bind aliases refuse before probes or writes; a disjoint bind-mounted home installs successfully. | [Native job 123247166458](https://github.com/Chris0Jeky/agent-harness/actions/runs/40812903773/job/123247166458) passed seven tests with zero skips at head 63bc177. Carries #523's closure. Full CI and merge receipts own source acceptance; no concurrent-writer exclusion is claimed. |

The combined maintenance tree before #587's test-only addition ran **2,155 root unit tests
with 70 expected skips and no failures**. Local full smoke remains limited by read-only home fixtures; the
native per-platform CI jobs supply full smoke evidence. The lab's [browser receipt](https://github.com/Chris0Jeky/agent-harness/pull/583#issuecomment-6487216972)
records the deployed desktop, mobile, keyboard, filtering and gate checks.

Operating contracts: [learning outcome validation](LEARNING_OUTCOME_VALIDATION.md),
[replay output boundary](REPLAY_OUTPUT_BOUNDARY.md), [replay input errors](REPLAY_INPUT_ERRORS.md),
[test fixture startup](TEST_FIXTURE_STARTUP.md), and [SPECS](../SPECS.md).

## Runtime and human evidence

**Historical observation, 2026-10-13:** Doctor reported source 1.8.1 versus installed 1.8.0
and an unproven worktree canonical comparison. That observation is preserved in the archive;
it is not a measurement of this session's runtime.

[HUMAN_TODO](../HUMAN_TODO.md) retains **H-18** (private Actions billing), **H-19** (PyPI trusted
publisher) and **H-22** (adapter prerequisites and per-root trust/canaries, including extract-api
and the other workstation). Its recorded deployment and canary history is dated evidence.
A source merge, local invocation or static Doctor result cannot supply fresh-session runtime proof.

The dispatcher remains feature-frozen under [BLUEPRINT](../BLUEPRINT.md). Source maintenance
here does not extend its scope or complete the separate consumer rollout.

## Authority, products and canonical homes

The 2026-09-29 owner decision permits merges after exact-head checks, global law 2 review and
the three-minute aging floor, using merge commits only. No squash. Re-read the declared tier
before mutation; [SPECS](../SPECS.md) and the global laws own the gate.

Owner-authored repository content is **GPL-3.0-only**, with the curl-derived fixture under its
own licence ([LICENSING](../LICENSING.md), [third-party notices](../THIRD_PARTY_NOTICES.md)).
The approved clean `charter-replay` extraction is **Apache-2.0**; its manifest is path-pinned by
the 2026-10-04 decision. [REPLAY_TOOL_PRODUCT](../REPLAY_TOOL_PRODUCT.md) owns that scope;
[blueprint-plugin extraction](../BLUEPRINT_PLUGIN_PRODUCT.md) remains deferred. Record any
change of source direction before the harness and extracted product diverge.

Measurements live in [BENCHMARKS](BENCHMARKS.md); frozen-floor limits live in
[FLOOR_LIMITATIONS](../FLOOR_LIMITATIONS.md). The [workspace receipt lab](ux-evaluation/WORKSPACE_RECEIPT_LAB.md)
and [handoff profile](ux-evaluation/WORKSPACE_HANDOFF_PROFILE.md) are bounded reference contracts.
Their synthetic evidence does not establish native adoption or authenticate external receipts.

Evidence terms: **implemented** means accepted source exists; **deployed** means destination bytes
were measured; **runtime-proven** requires the applicable live observations; **experimental**
limits the compatibility claim; **historical** evidence applies only to its recorded date and scope.
