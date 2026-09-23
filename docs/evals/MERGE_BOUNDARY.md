# Evaluation merge-boundary contract: v0

Decision proposal and source inspection: 2026-09-23.
Parent: [#299](https://github.com/Chris0Jeky/agent-harness/issues/299).
Scope: [#304](https://github.com/Chris0Jeky/agent-harness/issues/304).
Classification companion: [#300](https://github.com/Chris0Jeky/agent-harness/issues/300).

Status: proposed documentation contract, not a new required check, approval
service, policy engine, or change to tier/review authority. The compact core below
is normative proposal text; explanatory notes and source facts follow separately.

## Normative contract

### Decision and admission

Only applicable, repo-owned, contract-valid deterministic oracles may receive
automated merge authority. Eligibility is not enrollment; this document adds none.

Admission requires a ratified observable contract, reproducible execution and
decision, explicit owning policy, tested revision and fixture/check identity,
distinct failure states, independent-enough observation, and appropriate
known-good/broken sensitivity controls. A comparator over a stochastic live model
trial is not automatically a deterministic gate. Copying implementation logic is
not independent observation.

### Always gate: applicable existing contracts

Existing required checks retain their declared scope. These are eligible classes,
not new requirements or blanket certification of every test.

| Gate-eligible evidence | Maximum justified claim |
|---|---|
| Exact unit, parser, build, or artifact-contract check | Specified property for tested inputs and revision |
| Harness Verify floor/smoke assertions | Named policy/wiring cases, not universal safety or live activation |
| Taskdeck backend/API/migration contract tests | Checked behavior/state transitions, not UX or production reliability |
| Controlled tool/trajectory/scenario invariant | Declared effects or sequence contract in its stated environment |

### Advisory-only: no merge authority

| Evidence | Permitted use |
|---|---|
| LLM judgments and review-bot findings/approvals | Investigation and counterexamples |
| Vendor/benchmark scores, pass@k/pass^k, coverage or mutation percentages | Bounded study interpretation, not accepting this SHA |
| Spans, dashboards, cost/latency, missing telemetry, live quality estimates | Operational diagnosis |
| HQ completeness or imported source verdicts | Descriptive indexing; `gate_eligible: false` |

### Never

- Require an LLM semantic verdict, including pinned, temperature-zero, cached,
  or consensus judgments.
- Require an advisory bot's approval, silence, completion, availability, or
  catch-rate claim, directly or through an aggregate status.
- Substitute vendor rank, benchmark score, or Muse computer-use output for a
  repository-owned correctness contract.
- Turn telemetry presence/absence or HQ coverage into a merge gate.
- Treat valid JSON, digests, screenshots, or self-reported PASS as proof of
  execution or semantic correctness.
- Let an agent-generated expectation appoint itself authoritative.

### Failure semantics and advisory discoveries

Product FAIL, setup ERROR, BLOCKED, and NOT RUN are distinct from PASS.
Missing required deterministic evidence cannot establish its contract; missing
advisory telemetry is not a merge blocker. Timeout without its expected
observation is not a passing negative control.

An advisory finding may inform existing review. Independent reproduction can
lead to a separately reviewed deterministic regression; the original bot verdict
never gains authority. Preserve existing tier, severity, and bounded review rules.

Verify red does not block the docs-only #300/#304 deliverables. Record outcomes
honestly without workflow changes, suppression, or protection bypasses. This
scoped documentation instruction does not waive implementation-PR requirements.

## Explanatory notes

### Authority is narrower than deterministic computation

**INFER:** This proposal excludes all LLM semantic judgments, not only those called
flaky. Pinning a model or caching its JSON can repeat an opinion; it does not make
that opinion a ratified contract. A deterministic threshold over an LLM score is
still a model-judgment gate. Nor may a required parent check wait for an optional
judge to finish before reporting success.

Tests of a judge adapter's parser, bounded input handling, or output serialization
can qualify as exact software-contract tests without running a judge. Their
authority is over that software property, never the opinion inside the report.
Likewise, a schema/existence check may prove a required artifact's structure or
presence, but cannot prove its truth or authorize the product it describes.

An agent may propose tests. Expected results must be reviewed against an existing
issue/API/invariant or other independent contract; changing implementation and
expected output together does not automatically qualify an oracle. No new
universal human-review round or compulsory mutation exercise is introduced.

### Source results, identity, and existing practice

**FACT:** [REVIEW_EVIDENCE](../REVIEW_EVIDENCE.md) already separates author-written
expectations from observed results, preserves controls and failed attempts, and
retains tier/global-law authority. It also limits static Doctor and fixture claims.
This file tightens the admission boundary without copying the packet schema or
creating another review procedure.

**INFER:** Bind evidence to the actual tested head or CI merge commit, the relevant
base, and check/fixture/environment revisions. A synthetic merge commit is not the
PR head. Preserve older unaffected evidence with explicit scope mapping; never
relabel it as a fresh run. A digest identifies bytes, not the truth of execution.

**FACT:** GitHub's [required-check guidance](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks),
accessed 2026-09-23, distinguishes head and test-merge checks and documents skipped
or neutral states. **INFER:** Platform acceptance of a status is not evidence
that the intended assertion executed; record applicability and execution state.

For an existing required check with suspected bad-oracle behavior, investigate
under the owning repository's policy. This proposal does not silently demote it,
waive red, invent a bypass, or change branch protection. The #300/#304 docs-only
instruction is not a general fail-open policy.

### Telemetry, rollout, and HQ stay separate

**FACT:** [agent-hq#10](https://github.com/Chris0Jeky/agent-hq/issues/10), created
2026-09-22, requires coverage to remain descriptive with `authority: "none"` and
`gate_eligible: false`. **INFER:** Importing a source verdict must not transfer its
authority to HQ. A complete packet, an empty findings list, or a successfully
generated report can coexist with a failed product assertion.

**INFER:** Testing a telemetry serializer against pinned fixtures is a software
contract; demanding live spans, a Langfuse/Phoenix score, or dashboard completeness
before merge is not. A captured incident may motivate a deterministic regression.
Rollout safety, runtime interlocks, and human incident decisions remain separate;
this contract does not disable them or invent an automatic promotion policy.

[#303](https://github.com/Chris0Jeky/agent-harness/issues/303) owns observability.
[#281](https://github.com/Chris0Jeky/agent-harness/issues/281) owns product UX
observe/judge. No UX rubric, telemetry SDK, collector, scanner infrastructure, or
product feature belongs in this document's implementation.

## Boundary conformance examples

**INFER:** These are authored policy-review cases, not executed experiments or
new CI fixtures. Review them within the existing process; no extra review round.

| Case | Expected disposition | Reason |
|---|---|---|
| Exact fixture asserts the wrong requirement | Not qualified for new gate admission | Determinism is insufficient; existing checks are not silently waived |
| Temperature-zero or cached judge says PASS | Advisory; never semantic authority | Repeated opinion is not a valid oracle |
| Five models agree on a review | Advisory | Consensus does not create independent executable proof |
| Valid report contains a failed product assertion | Report structure may pass; product result remains FAIL | Structure and semantics are distinct |
| Hermetic scenario checks durable state and forbidden side effects | Potentially gate-eligible after adoption | Bounded reproducible behavioral contract |
| Live agent trial has an exact final-state comparator | Advisory capability evidence in v0 | Trial remains stochastic/uncontrolled |
| Production span is missing or exporter fails | Advisory missing evidence | Telemetry is not a merge prerequisite |
| HQ coverage_complete is true | Descriptive; gate-ineligible | Completeness is not correctness |
| Bot finding reproduced by a reviewed regression test | New test may qualify; bot remains advisory | Authority belongs to the independent contract |
| Negative control fails to start because credentials are absent | Setup failure, not sensitivity proof | Intended boundary was not exercised |
| Judge adapter parser rejects malformed input | Exact parser test may qualify | Does not judge semantic correctness |
| Earlier head passed; changed head has no results | No fresh pass claim | Revision mismatch is not evidence |
| Required wrapper depends on a nominally advisory judge | Reject the authority dependency | Advisory availability must not become an indirect veto |
| Verify is red on the docs-only freeze | Complete and review docs; preserve actual status | No unrelated CI repair dependency or bypass |

## Maintainer PR comment template

Use the canonical main link after integration. While this document is in draft,
replace it with the draft PR's file URL; do not claim the main path already exists.

> This would give advisory model output merge authority, which the [merge-boundary contract](https://github.com/Chris0Jeky/agent-harness/blob/main/docs/evals/MERGE_BOUNDARY.md) excludes.
> Keep the judge or review-bot output optional and non-blocking, including its availability, score, and approval state.
> A concrete finding can inform existing review and, after independent reproduction, become a separately reviewed deterministic regression check; the model verdict itself never becomes required.

## Sources and inspection record

### Estate facts

Inspected 2026-09-23 at agent-harness
`b586bbf10629b50bcdb08d8b5f99bc60b06795ec`.
[Source snapshot](https://github.com/Chris0Jeky/agent-harness/tree/b586bbf10629b50bcdb08d8b5f99bc60b06795ec).

| Source | Fact used | Limit |
|---|---|---|
| [AGENTS](../../AGENTS.md), [tier declaration](../../.agent-harness/tier.json), [REVIEW_EVIDENCE](../REVIEW_EVIDENCE.md) | Existing verification and authority owners | No authority setting changed; root-prose drift remains separate |
| [Hosted CI](../../.github/workflows/ci.yml) | Verify runs unit/replay/smoke/lint/format/compile checks | This document does not certify all oracles or their latest executions |
| [Floor limitations](../../FLOOR_LIMITATIONS.md) | Floor scope limits have an existing home | The ledger is not a merge verdict; static tests are not runtime activation |
| [Taskdeck CI](https://github.com/Chris0Jeky/Taskdeck/blob/56e4b6acbca399aa2b98e612270c0cc282a41996/.github/workflows/ci-required.yml) | Backend/API/migration job calls at that revision | Source inspection, not a test run or changes to Taskdeck policy |
| [BENCHMARKS](../BENCHMARKS.md), snapshot 2026-07-31 | Results require input, method, number, and limitation | Historical rows are not current baseline proof |
| [#304 discussion](https://github.com/Chris0Jeky/agent-harness/issues/304#issuecomment-5798216357) and [HQ #10](https://github.com/Chris0Jeky/agent-hq/issues/10) | Telemetry and coverage are non-authoritative | Issue contracts are not rollout evidence |

The machine-local ORACLES/REVIEW_BOTS scavenge files were not directly inspected.
This file links their published #304 scope and the landed REVIEW_EVIDENCE note
instead of inventing a reconstruction. It does not resolve an older research
wave's B0 provenance item.

### Research and proposed policy

**FACT:** [Zheng et al.](https://arxiv.org/html/2306.05685v4), first submitted
2023-06-09, document LLM-judge capabilities and limitations in conversational
evaluation. [Yao et al.](https://arxiv.org/html/2406.12045v1), 2024-06-17, separate
repeated-trial reliability from finding one successful attempt.
Both were checked on 2026-09-23; neither gives this estate a merge policy.

**INFER:** The admission checklist, conformance cases, and complete exclusion of
LLM semantic merge authority implement the owner's requested v0 boundary.
They are not measured improvements in defects, reviewer effort, or throughput.

**OVERSOLD:** Catch-rate marketing, leaderboard rank, preference agreement,
retry success, and complete evidence coverage do not prove this particular SHA
correct. No such score is adopted as a gate here.
