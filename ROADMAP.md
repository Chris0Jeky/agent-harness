# Agent Harness roadmap

## Dependency checkpoint — 2026-10-29

The maintenance baseline is [`main@471ff6c`](https://github.com/Chris0Jeky/agent-harness/commit/471ff6c92457986b30da1091eea8e4e67613896a).
[ACTIVE](plans/ACTIVE.md) lists reviewed source candidates and human gates;
[SYSTEM_STATE](docs/SYSTEM_STATE.md) records accepted source, evidence and limits. PR pages own
current head/check/merge status. This roadmap grants no deployment or runtime authority.

The mission and epic outcomes remain in [AGENT_HARNESS_AGENT_BRIEF](AGENT_HARNESS_AGENT_BRIEF.md).
The old epic census and PR chronology are [archived](docs/archive/status-2026-10.md); their issue
counts and open/closed labels are historical, not a current backlog inventory.

## Remaining dependencies

| Work | Remaining acceptance and owner boundary |
|---|---|
| Trusted learning evidence — [#520](https://github.com/Chris0Jeky/agent-harness/issues/520), [#517](https://github.com/Chris0Jeky/agent-harness/issues/517) | Immutable cohort assignment, executed-genome receipts, store import times, beacon selection and destination install verification need a trusted backend. #579 makes comparisons observational while that evidence is absent. |
| Outcome ingestion — [#511](https://github.com/Chris0Jeky/agent-harness/issues/511) | Trusted append-only ingestion/offsets, omitted-tail detection and stable event-ID/cursor migration remain. #579 addresses regression weighting and triage deduplication; it does not complete the stream's provenance boundary. |
| Frozen dispatcher follow-ups — [#107](https://github.com/Chris0Jeky/agent-harness/issues/107), [#225](https://github.com/Chris0Jeky/agent-harness/issues/225) | Remote diagnostics still cross-contaminate. Publication parity still differs for explicit null, SSH ports and duplicate identical push rows. Any change needs its own bounded freeze-compliant scope and proof. |
| Numeric parity — [#201](https://github.com/Chris0Jeky/agent-harness/issues/201), [#243](https://github.com/Chris0Jeky/agent-harness/issues/243) | #239 shipped the portable numeric core. The documented toolchain-dependent cases remain fail-closed; full numeric parity is not complete. |
| Consumer smoke — [#185](https://github.com/Chris0Jeky/agent-harness/issues/185) | #217 shipped flushed producer progress. A real consumer launcher/manifest must define bounded conformance, interruption and cleanup. PID/start-time checks or taskkill alone do not prove descendant ownership. |
| Consumer retirement and launchers — [#188](https://github.com/Chris0Jeky/agent-harness/issues/188), [#190](https://github.com/Chris0Jeky/agent-harness/issues/190) | Retirement planning awaits a second concrete consumer and owner-reviewed manifest. Interpreter selection awaits an exact generated launcher call site. No generic engine or inferred ownership is authorized. |
| Guarded worktree creation — [#191](https://github.com/Chris0Jeky/agent-harness/issues/191) | Taskdeck #1551 has merged; separate its portable create/initialize contract and fixtures from consumer-specific behavior. Preserve dirty/ignored state and explicit process-ownership limits. |

[Taskdeck #1551](https://github.com/Chris0Jeky/Taskdeck/pull/1551) merged on 2026-08-12 as
`d603079241d422bde5430f1463cb665720538786`. This satisfies #191's merge prerequisite;
it does not supply the portable producer operation. Its issue now records that distinction.

The earlier #556/#558/#563 follow-ups are closed by merged
[#566](https://github.com/Chris0Jeky/agent-harness/pull/566) and
[#565](https://github.com/Chris0Jeky/agent-harness/pull/565). Keep their completed source work
out of the active queue; concurrent-writer exclusion and ledger input-size limits were not claimed.

## Source acceptance receipts

Native sync qualification is implemented in [#587](https://github.com/Chris0Jeky/agent-harness/pull/587):
seven required native tests passed, covering alias refusal and a disjoint success control.
[#580](https://github.com/Chris0Jeky/agent-harness/pull/580) owns absent-name lookup and recovery maps.
[#584](https://github.com/Chris0Jeky/agent-harness/pull/584) owns the Doctor shell anchors,
wrapper quoting and single reference probe. Their current full CI and merge receipts own
acceptance for #523, #278 and #78; these are no longer unimplemented source dependencies.
Observed identities still do not exclude concurrent writers, and static Doctor does not prove trust.

## Outcome ordering

1. Integrate reviewed source changes only after their exact-head native checks and merge gate
   are satisfied. [ACTIVE](plans/ACTIVE.md) links the bounded maintenance PRs and their proof.
2. Build trust or portability interfaces from concrete evidence and consumers. Keep diagnosis,
   source acceptance and runtime activation independently evidenced.
3. Preserve the dispatcher freeze in [BLUEPRINT](BLUEPRINT.md); use measured failures and the
   ratified exceptions to scope any repair.
4. Complete the human-owned billing, publication and per-root runtime conditions in
   [HUMAN_TODO](HUMAN_TODO.md): H-18, H-19 and H-22. Historical source or canary results do not
   close a new root's adapter, trust or live proof.
5. Keep [replay extraction](REPLAY_TOOL_PRODUCT.md) within its approved public/Apache-2.0 scope
   and path-pinned manifest. The [blueprint plugin](BLUEPRINT_PLUGIN_PRODUCT.md) remains deferred.
