# Harness extension notes

Status: proposed, 2026-09-23.
Parent: [#299](https://github.com/Chris0Jeky/agent-harness/issues/299).
Spike: [#302](https://github.com/Chris0Jeky/agent-harness/issues/302).

## Extend the existing workbench

[Review evidence](../REVIEW_EVIDENCE.md) and its
[v0 template](../review-evidence/packet.template.json) remain canonical.
The [#301 flood profile](https://github.com/Chris0Jeky/agent-harness/issues/301)
is a review view, not another receipt authority.

Proposed paths: `docs/evals/{TAXONOMY,MERGE_BOUNDARY,REVIEW_UNDER_FLOOD}.md`
([#300](https://github.com/Chris0Jeky/agent-harness/issues/300)/
[#304](https://github.com/Chris0Jeky/agent-harness/issues/304)/#301);
`docs/observability/AGENT_LOOP_SPANS.md`
([#303](https://github.com/Chris0Jeky/agent-harness/issues/303)) owns trace vocabulary.
Use issue links until those files land.

Read-only adapter contracts, not implementations: PR/base/head/stack references map to
identity; deterministic run/fixture references map to retained observations; expected check
IDs map to observed/missing evidence; optional trace IDs map to advisory diagnostics.
Unknowns and prior attempts survive projection. Packet commands remain data.

Before implementing, reconcile the pending
[#295 reader](https://github.com/Chris0Jeky/agent-harness/pull/295) and
[#296 accounting](https://github.com/Chris0Jeky/agent-harness/pull/296) contracts.
No pending API is promised. Reader diagnostics retain `execution_verified=false` and
`merge_verdict=null`. [agent-hq#10](https://github.com/Chris0Jeky/agent-hq/issues/10)
indexes evidence, never promotes authority. Only executed measurements enter
[BENCHMARKS](../BENCHMARKS.md).

## Sequence and exclusions

Review #301, then this note; curate the real cohort separately. #295/#296/
[#298](https://github.com/Chris0Jeky/agent-harness/pull/298) Verify-red work does not block docs.
Do not change CI or waive merge requirements.

Defer [claude-config#308](https://github.com/Chris0Jeky/claude-config/issues/308)
skills/workflow packaging until source-of-truth docs and packet mapping stabilize.
No packaging PR now.

No second harness, runner, collector, opentelemetry-sdk, runtime-schema migration,
Taskdeck PR, product rewrite, UX scoring, or LLM merge gate.
