# Agentic development evaluation taxonomy: v0

Research cut and estate inspection: 2026-09-23.
Status: proposed vocabulary freeze; no runner, enforcement change, or new measurement.
Parent: [#299](https://github.com/Chris0Jeky/agent-harness/issues/299).
Scope: [#300](https://github.com/Chris0Jeky/agent-harness/issues/300).
Companion authority contract: [#304](https://github.com/Chris0Jeky/agent-harness/issues/304).

## Scope and vocabulary

**INFER:** Freeze five observation layers: unit, tool-use, trajectory, scenario,
and online/prod. These are not a maturity ladder or increasing levels of authority.
Tool-use makes an implicit seam in the earlier four-layer draft explicit.
Prod-like-local is an environment qualifier, not a sixth layer.

| Axis | What to record | What it does not establish |
|---|---|---|
| Layer | Which behavior or observation boundary is examined | Whether its oracle is valid |
| Oracle | How expected and observed behavior are compared | Whether execution occurred |
| Environment | Controlled dev, prod-like local, or live prod; relevant versions and state | Production equivalence |
| Authority | Existing owning policy and applicability, or advisory/unknown | Permission derived from a score or taxonomy label |

**FACT** means directly supported by an identified source. **INFER** marks this
estate's proposed synthesis. **OVERSOLD** marks a conclusion beyond the evidence.
A classification example is not an executed experiment.

Only an applicable, repo-owned, contract-valid deterministic oracle may acquire
automated merge authority. LLM semantic judgments, review-bot verdicts, vendor
scores, telemetry, and HQ coverage may not. Eligibility is not enrollment:
nothing in this file makes a check required or changes existing tier/review rules.
See the existing [oracle practice](../REVIEW_EVIDENCE.md) and companion #304.

## Five-layer taxonomy

**INFER:** Classify checks, not entire tools. Conditional eligibility below requires
a valid contract, controlled/reproducible execution, revision binding, and explicit
repository adoption. The online/prod row has no direct v0 merge authority.

| Layer | Question answered | Typical oracle | Gate-eligible? | Dev / prod-like local / prod | Main failure modes |
|---|---|---|---|---|---|
| Unit | Does a bounded function or invariant behave as specified? | Exact value, exception, schema, property or valid metamorphic relation | Conditional | Isolated fixture / real packaging and config / related runtime invariant | Wrong expected value; copied implementation logic; mocks hide integration |
| Tool-use | Does a tool boundary enforce arguments, authority, and intended effects? | Adapter contract, allow/deny decision, filesystem or database post-state | Conditional | Stub / real adapter with disposable state / actual calls and effects | Valid JSON but wrong action; mock drift; success without persistence |
| Trajectory | Does a sequence respect hard invariants, and what path did it take? | State-machine assertion for hard rules; advisory process analysis | Conditional for hard invariants only | Controlled sequence / realistic isolated loop / observed live sequence | Incomplete trace; unsafe shortcut; valid alternative path penalized |
| Scenario | Does a complete task reach its required external state without prohibited effects? | Built CLI/API/E2E assertion, durable post-state, regression control | Conditional; not benchmark aggregate | Repo fixture / built artifact and seeded store / real task or dogfood observation | Happy-path overfit; setup failure; overspecific oracle; environment skew |
| Online/prod | What happens under live tasks, dependencies, state, and change? | Runtime invariants, incident/SLO observations, advisory interpretation | No for merge | Replay approximation / isolated realistic workload / live population | Confounding; missing telemetry; delayed outcomes; drifting denominators |

### Mixed and overlapping cases

A smoke suite can contain tool-use and scenario checks. A scenario can include a
trajectory and several tool calls. Split a mixed report's hard assertion results
from its semantic scores; neither inherits authority from the other.

Online/prod is the cross-cutting live-observation layer, not a claim that a unit
test becomes a new kind of unit test in production. A live permission failure can
be described as online/prod evidence at a tool-use boundary. State the primary
question and secondary boundary rather than forcing one exclusive label.

An exact comparator over a newly sampled model run does not make the whole check
reproducible. Such a capability trial stays advisory in v0. A fixed patch generated
by an agent can still be tested by the repository's ordinary deterministic suite.
A recorded model response used as a fixture tests the replayed software boundary,
not the live model's reliability.

## Environment qualifiers

**INFER:** Environment is a separate qualifier for evidence, not an authority grant.

| Property | Offline dev | Prod-like local | Online/prod |
|---|---|---|---|
| Input and state | Pinned fixtures; disposable stores | Seeded durable state; built artifacts; safe real adapters | Organic tasks; shared and changing state |
| Dependencies | Stubs or controlled dependencies | Isolated real services, emulators, or recorded responses; disclose substitutions | Real services, failures, quotas, versions |
| Clock and randomness | Pin when relevant; retain seeds | Control or record conditions; disclose remaining variability | Observe actual conditions |
| Purpose | Fast regression | Exercise boundaries hidden by mocks | Detect failures the laboratory did not model |
| Maximum claim | This contract passed these inputs | This contract crossed these real boundaries | This outcome occurred in this population/window |

A local laptop doing real work on real repositories is production for that agent
loop. A disposable local sandbox is not production merely because the same binary
runs there. A canary supplements controlled tests rather than proving the
laboratory represents every live condition; see [R5](#primary-sources).
Separate rollout/incident policies are outside this merge-evaluation freeze.

## Estate map and maximum claims

**FACT:** The following source inventory was inspected at agent-harness
`b586bbf10629b50bcdb08d8b5f99bc60b06795ec`. **INFER:** Its layer assignments and
maximum-claim descriptions apply only to the named boundaries. Source inspection
does not prove a check ran or that GitHub branch protection requires it.

| Surface and source | Layer / environment | Oracle and authority treatment | Maximum claim / explicit non-claim |
|---|---|---|---|
| [Harness tests](../../tests/test_harness.py) | Unit; selected tool/scenario fixtures / dev | Exact owned assertions; existing review/CI rules govern | Checked software contracts, not estate-wide correctness |
| [Floor smoke](../../templates/hooks/smoke_test.py) | Tool-use and bounded scenario / controlled host | Expected policy outcomes and hook outputs; existing floor-change rules apply | Named cases under declared posture, not a sandbox or universal command safety |
| Hosted [Verify](../../.github/workflows/ci.yml) | Mixed unit/tool/scenario / hosted CI | Unit, replay, smoke, Ruff, Black, compile steps | Their executed contracts; job name alone is not oracle qualification |
| Local [AGENTS verification recipe](../../AGENTS.md) | Unit, smoke and static configuration inspection / local | Includes Doctor; do not describe Doctor as a hosted Verify step | Local observations only; Doctor does not execute a real agent session |
| [Floor declaration](../../.agent-harness/tier.json) and [limitations](../../FLOOR_LIMITATIONS.md) | Configuration / declared state | This producer declares `floor_wiring: none`; limitations are a ledger, not an oracle | Tests do not imply this checkout has an active runtime floor |
| [Replay](../../replay_v0) | Unit/tool/scenario according to assertion / recorded or synthetic | Exact fixture contracts can qualify; aggregate metrics remain advisory | Replay behavior, not live policy quality or agent reliability |
| [BENCHMARKS](../BENCHMARKS.md) | Cross-layer historical evidence | Measurement ledger; no automatic merge authority | Bounded measured results with limitations, not refreshed baselines |
| [Reviewer packet](../REVIEW_EVIDENCE.md) | Cross-layer evidence / declared environment | Authoring and review aid; exact source results remain distinct | Presence of fields or digests does not authenticate execution |
| [UX evaluation](../ux-evaluation) and [#281](https://github.com/Chris0Jeky/agent-harness/issues/281) | Scenario and product observation | Separate owner; semantic judgments remain advisory | Classify only; no UX rubric or observe/judge implementation here |
| Taskdeck [CI source](https://github.com/Chris0Jeky/Taskdeck/blob/56e4b6acbca399aa2b98e612270c0cc282a41996/.github/workflows/ci-required.yml) | Unit and integration/scenario / CI | Existing backend, API, migration jobs; Taskdeck owns adoption | Workflow calls were inspected, not all test oracles or current check results |

### Proposed and unqualified surfaces

**FACT, 2026-09-23 inspection:** Open PRs [#295](https://github.com/Chris0Jeky/agent-harness/pull/295),
[#296](https://github.com/Chris0Jeky/agent-harness/pull/296), and
[#298](https://github.com/Chris0Jeky/agent-harness/pull/298) describe reviewer-packet
diagnostics, logical-job accounting, and mapped authority-document drift.
They are not dependencies of this document or evidence of shipped capability.
Their deterministic diagnostic reports do not acquire product merge authority.

**INFER:** Muse/OpenCode/Claude Code/Codex runs use the same vocabulary, but no
native run was qualified here. Proposed examples include an approval-before-write
sequence (trajectory), an adapter denial (tool-use), a complete issue-resolution
task (scenario), and a live failed/retried job (online/prod).
Do not invent captured spans, tool support, task success, or measured coverage.

### agent-hq indexing without authority

**FACT:** [agent-hq#10](https://github.com/Chris0Jeky/agent-hq/issues/10), created
2026-09-22, specifies descriptive coverage with `authority: "none"` and
`gate_eligible: false`. It prohibits treating completeness as correctness,
approval, or promotion.

**INFER:** An eval index may describe subject/revision, producer, source result,
layer, environment, metric denominator, synthetic/recorded/live status,
availability, and limitations. These are conceptual indexing needs, not additions
to HQ's current schemas. Keep payloads and sensitive source data at their owner.

| Indexed source | What HQ may preserve | What HQ must not infer |
|---|---|---|
| Deterministic CI result for SHA A | Source status, exact identity and provenance | That HQ now implements or may waive that gate |
| Judge report for SHA A | Advisory assessment and its limitations | That a high score approves A |
| Incident observation for live run B | Observed outcome and population/window | That an unrelated PR is mergeable or blocked |

A producer verdict remains source data. Even complete HQ coverage remains
`gate_eligible: false`; metadata completeness is not evidence of semantic success.

## Reliability and confidence limits

### pass@k and pass^k

**FACT:** [R1](#primary-sources) defines pass@k as the chance that at least one of
k independent, identically distributed trials succeeds. [R2](#primary-sources)
defines pass^k as the chance that all k such trials succeed, averaged across tasks.
They answer different questions: search yield versus consistent success.

**INFER:** Report pass@1 beside either aggregate. Retain task population,
per-task attempts, successes, retry/selection protocol, model/tool/check versions,
environment, costs, missing outcomes, and uncertainty. Never discard failed
attempts to make the denominator more favorable.

For one task with true success probability p under those assumptions, the
corresponding probabilities are 1-(1-p)^k and p^k; these are not instructions to
substitute an empirical pooled success rate. For n >= k trials with c successes,
the papers give per-task estimators 1-C(n-c,k)/C(n,k) and C(c,k)/C(n,k), respectively,
then average across tasks. C(a,k) is the binomial coefficient, zero when a < k.

Do not raise a pooled success rate across heterogeneous tasks to k and call it
measured pass^k. Correlated trials, adaptive retries, and missing outcomes need
an explicit protocol; the formulas alone do not validate those assumptions.

Neither aggregate gates an individual PR. Repetition can investigate suspected
flakiness, but identical deterministic fixture reruns are not independent new
evidence of agent capability. Do not freeze a universal k or invent precision
from a tiny sample.

### Golden journeys and fixture oracles

**INFER:** A golden journey is a curated scenario, not privileged truth. It helps
when initial state is pinned, the actual boundary is exercised, and relevant
durable effects and forbidden side effects are observed. A model-assisted journey
does not inherit deterministic eligibility from an exact final-state comparator.

Use a known-good control, candidate, and named-broken/negative control where
appropriate. A control must fail for the intended reason after reaching the
boundary; import errors, dead services, and missing credentials are not proof
of defect sensitivity. Record unsafe or infeasible historical reproduction and
its weaker substitute. See [existing control practice](../REVIEW_EVIDENCE.md).

Fixtures help with parser, policy, serialization, migration, and historical
regressions. They fake confidence when assertions repeat implementation logic,
a no-op still passes, persistence is unobserved, or synthetic coverage is presented
as production quality. A schema/file-existence assertion can prove its narrow
contract; it cannot prove the artifact's semantic truth.

### LLM judges and LGTM theater under PR flood

**FACT:** [R4](#primary-sources) studies useful judge agreement alongside systematic
limitations; its conversational evaluation is not proof of coding correctness.
**INFER:** Apply the following failure analysis inside the existing review budget.

| Failure mode | PR-flood consequence | Useful response |
|---|---|---|
| Position, verbosity, or presentation sensitivity | Reward review-shaped prose rather than the changed behavior | Keep semantic scores advisory |
| Missing runtime state or incomplete diff | Plausible verdict without observing persistence, permissions, or callers | Reproduce at the executable boundary |
| Shared generator/test/judge assumptions | Several models repeat the same blind spot | Use a genuinely different observation mechanism |
| False positives and duplicate comments | Attention consumed without distinct actionable defects | Deduplicate and require causal evidence |
| No findings interpreted as approval | Unexamined paths appear reviewed | State inspected scope and unknowns |
| Provider, model, or rubric drift | Judgment changes without a repository change | Version advisory evidence; do not grant it authority |

LGTM theater means review-shaped activity without an independently falsifiable
correctness claim. Comment count, agreement, and bot silence are not acceptance.
A confirmed defect can inform existing severity/review handling; the bot verdict
itself cannot veto or authorize a merge.

## Benchmark marketing boundary

**FACT:** SWE-bench evaluates issue resolution in repository snapshots [R3].
The 2026-02-23 first-party retrospective [R6] reports test-design and contamination
problems in a selected audit. It is not an independent audit of all benchmarks.

**OVERSOLD:** The interpretations below are excluded, not attributed as quotations
to every benchmark author. **INFER:** Borrow protocols without borrowing authority.

| Do not adopt as a merge gate | Retain as useful evidence |
|---|---|
| Model rank or SWE-bench percentage implies less PR verification | Repo scenarios and independently reviewed regression contracts |
| A deterministic benchmark or the word Verified guarantees oracle validity | Audits of task/test alignment and environment assumptions |
| One successful retry proves dependable unattended operation | pass@1, attempts, pass@k/pass^k, cost, and protocol |
| Human-preference agreement proves semantic correctness | Advisory findings and counterexamples |
| Bot catch-rate, approval, or silence completes review | Causal findings and their reproducible evidence |
| Fixture, screenshot, or HQ coverage completeness proves product success | Separate artifact structure, execution, assertion result, and indexing |
| Green cost/latency dashboards prove merge readiness | Bounded operational diagnosis |

## Ownership, gaps, and next slices

**FACT:** The earlier [E1 comment](https://github.com/Chris0Jeky/agent-harness/issues/300#issuecomment-5798216001)
identifies production trajectory observability as the gap beyond the oracle/flood
scavenge. **INFER:** This freeze addresses classification, not that instrumentation.

| Gap or deliverable | Existing owner | Acceptance boundary for the next slice |
|---|---|---|
| Explicit tool-use; environment and estate mapping | [#300](https://github.com/Chris0Jeky/agent-harness/issues/300) | Five layers distinguishable by observation boundary, not whether an LLM is involved |
| Oracle admission and non-authority rules | [#304](https://github.com/Chris0Jeky/agent-harness/issues/304) | Compact contract, gate/advisory tables, Never list, comment template |
| Actual flood sample and oracle sensitivity | [#301](https://github.com/Chris0Jeky/agent-harness/issues/301) | Named cohort and controls; no inferred acceptance from a packet |
| Live tool/trajectory telemetry and redaction | [#303](https://github.com/Chris0Jeky/agent-harness/issues/303) | Content-minimized plan/tool/edit/verify sketch; telemetry never gates |
| Extension and later packaging | [#302](https://github.com/Chris0Jeky/agent-harness/issues/302) | Extend existing seams after contracts stabilize; no second harness |
| Product UX observe/judge | [#281](https://github.com/Chris0Jeky/agent-harness/issues/281) | Link only; do not define its rubric or product features |

The machine-local `agent-eval-scavenge-2026-09-23` and
`agent-eval-obs-2026-09-23` handoff packs were not directly inspected in this
connector-based slice. The gap comparison above is issue-reported, not a file diff.
A local maintainer should reconcile ORACLES/REVIEW_BOTS/PATTERNS and the handoff
drafts before closing #300; record any disagreement in that issue. No new child
issue is justified merely by exposing tool-use or an environment qualifier.

## Sources and inspection record

### Estate sources

The source links above are bounded by the inspected harness revision
`b586bbf10629b50bcdb08d8b5f99bc60b06795ec`; relative links follow the checkout being
read. [Pinned source snapshot](https://github.com/Chris0Jeky/agent-harness/tree/b586bbf10629b50bcdb08d8b5f99bc60b06795ec).
Taskdeck's cited workflow was inspected at
`56e4b6acbca399aa2b98e612270c0cc282a41996`; job calls are source facts, not test results.
Issue contents are mutable and were inspected on 2026-09-23.

BENCHMARKS labels its snapshot 2026-07-31. No result there was rerun or promoted to
a current baseline. The completed 2026-09-23 eval-taxonomy research and approved
two-document handoff informed this synthesis; that does not resolve the separate
older brief's B0 provenance item in `docs/review-evidence/SOURCES.md`.

### Primary sources

Accessed 2026-09-23. Publication dates and supported claims are separate from this
document's policy recommendations. No vendor performance score establishes a gate.

| ID | Source and date | Supported use and limitation |
|---|---|---|
| R1 | [Chen et al., Evaluating Large Language Models Trained on Code](https://arxiv.org/html/2107.03374v2), first submitted 2021-07-07 | pass@k and functional code tests; not repository-agent production reliability |
| R2 | [Yao et al., tau-bench](https://arxiv.org/html/2406.12045v1), 2024-06-17 | Final database-state evaluation and pass^k; simulated users and model-driven trials remain stochastic |
| R3 | [Jimenez et al., SWE-bench](https://arxiv.org/abs/2310.06770), first submitted 2023-10-10 | Repository-level issue scenarios; not local merge governance |
| R4 | [Zheng et al., Judging LLM-as-a-Judge](https://arxiv.org/abs/2306.05685), first submitted 2023-06-09 | Judge capabilities and limitations in conversational preference evaluation; not coding-oracle qualification |
| R5 | [Google SRE Workbook, Canarying Releases](https://sre.google/workbook/canarying-releases/), undated web chapter, accessed 2026-09-23 | Production exposure complements tests; practitioner guidance, not this estate's measurement |
| R6 | [OpenAI, SWE-bench Verified retrospective](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/), 2026-02-23 | First-party selected-task audit and contamination report; not independent model-ranking evidence |
