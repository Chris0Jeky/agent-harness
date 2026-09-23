# Advisory agent-operations measurements

Status: proposed benchmark extension, 2026-09-23. No collector, new enforcement,
installed adapter, scheduler or model-quality gate is introduced here.

## Ownership and compatibility

[BENCHMARKS.md](BENCHMARKS.md) remains the canonical measurement index and measured-results
ledger. This registered extension defines the proposed agent-operations cohort and its acceptance
cases; it is not a second results ledger or session handoff. Session-specific continuation belongs
in `handoffs/` and the relevant PR. The first offline accounting slice is tracked in
[#296](https://github.com/Chris0Jeky/agent-harness/pull/296); it does not implement native observation.

The [active build directive](../AGENT_HARNESS_AGENT_BRIEF.md) owns the workbench mission.
[BLUEPRINT.md](../BLUEPRINT.md) and [SPECS.md](../SPECS.md) retain policy authority.
Doctor, replay, estate tooling and existing benchmark records remain their respective sources.
This proposal does not expand the frozen dispatcher, change floor posture, add runtime hooks,
change `sync-global`, or modify a native wrapper result schema.

Use the directive's evidence distinctions: declared, discovered, observed, remotely verified,
inferred, unavailable and stale. A repository may deliberately have no wired floor. Do not
activate one to satisfy an evidence table, or label absent runtime observation as a successful
canary. A worktree lease is cooperative coordination, not proof against non-cooperating writers.

The declared workstream cap remains unchanged. [#233](https://github.com/Chris0Jeky/agent-harness/issues/233)
owns the unresolved collision-versus-review-bandwidth decision; these measurements can inform it,
not decide it by reporting a more convenient count.

## Measurement unit: the logical job, not the chat session

A future read-only adapter should join existing native receipts to one canonical work item.
Record the logical job identifier, attempt identifier, parent/root budget identity, target revision,
input and recipe/configuration digests, runtime version, capability mode and evidence references.
Keep native result/exit values intact and label any scheduling interpretation as derived.
These are required questions for an adapter design, not a second serialized schema to deploy.

Separate four clocks: time waiting for capacity, active execution, verification, and waiting for
review or a decision. A model that finishes quickly can still increase end-to-end delivery time.
Record clock source and observation gaps. Do not derive active time from a single wall-clock
interval spanning workstation sleep, or treat a lost heartbeat as proof the process is dead.

The source of a receipt matters. Bind an observed result to exact inputs and tested head; a digest
only binds bytes, not truth or observer identity. Distinguish synthetic fixtures, hosted CI and
native workstation evidence. None inherits another environment's capabilities.

## Proposed metric set

| Question | Definition and denominator | Required caveat |
|---|---|---|
| Does routing produce accepted work? | Accepted logical jobs divided by all admitted logical jobs in a fixed cohort; separately report pending, rejected and blocked counts | Pending work is not silently dropped; acceptance rubric and observer are named |
| What happened before admission? | Candidate -> eligible -> admitted -> started -> verified -> accepted counts, with refusal reasons | Show the whole funnel so routing cannot look better by hiding difficult candidates |
| What did accepted work consume? | Total observed cost for every attempt in the cohort divided by accepted jobs; also report observed cost coverage | If cost coverage is incomplete, total cost per accepted job is unavailable, not a lower-bound estimate presented as complete |
| Is local/cheap routing actually cheaper to supervise? | Total human/coordinator review and recovery minutes across every included attempt, divided by accepted jobs; report observed and missing supervision-time counts | If any required supervision observation is missing, complete total and per-accepted-job time are unavailable; a partial observed sum is labeled partial. Subscription quota, currency, wall time and GPU occupancy remain separate units |
| Are agents silently blocked? | Count and duration of no-progress incidents beyond a predeclared deadline, categorized by policy, capacity, environment, tool bootstrap, verification or cleanup uncertainty | Lifecycle started is not tool-effect completion; observer outage or missing elapsed-time evidence cannot establish a stall |
| Is coordination improving? | Duplicate assigned scope, rejected handoffs, stale-head verification, integration rework and reopened outcomes per cohort | A duplicate message is not necessarily duplicate work; use work-item/revision evidence |
| Is backlog growing faster than review? | Ready-for-review count/age and arrival versus disposition rate over the same window | A PR being closed or merged is not sufficient proof of accepted quality |

Use nullable observations, sample counts and explicit cohort boundaries. A zero denominator is
not a zero rate. For multi-attempt jobs, do not count a later retry as a second success. Do not
attribute account-wide usage deltas to one job when other sessions were active. Missing review,
recovery or other clock observations obey the same coverage rule as missing cost: they never
silently become zero or disappear from the completeness denominator. Failed and rejected attempts
still contribute observed burden; complete means coverage of the declared cohort, not all estate work.

No single organization-health score is proposed. A dashboard with several imperfect but explained
measurements is more useful than an opaque green badge. LLM assessments may be attached as
advisory evidence, never as merge-blocking CI or substitutes for deterministic checks.

## Blocked-agent evidence packet

A future adapter should reference: last observed native lifecycle event and its timestamp;
last verified artifact or tool effect; configured deadline; elapsed time on a named clock;
observer heartbeat and observation coverage; outstanding tool identifiers; the native result;
process-cleanup evidence and its coverage; and the next condition that would permit safe resumption.
Avoid raw prompts, host paths, personal text or command logs in committed evidence.
Public examples must be synthetic.

Classify only the boundary actually observed. A live supervisor, a tool-start event and no effect
before the configured first-effect deadline mean in progress, not stalled. The same observations
after a predeclared deadline, with continuous trustworthy observation and an elapsed-time source
that accounts for sleep, may support a suspected tool bootstrap stall. Missing timing or observer
coverage means unknown. None of these observations proves why the vendor stalled or that the shell
command ran. Timeout, terminated process, empty owned process group and rolled-back filesystem
are four different facts.

Keep execution and observation failures separate. On lost observer state, retain artifacts and
quarantine uncertain ownership before retry. A new model or higher effort cannot repair a missing
executable, blocked policy, occupied slot or unqualified shell boundary.

## Offline extension acceptance cases

Implement a bounded, offline report over existing receipts only, after selecting the smallest
existing benchmark/measurement seam. No agent calls, network access, scheduler, new policy engine
or mutation of source receipts. Reuse existing summarization semantics where compatible; for
example claude-config's `tools/summarize_trials.py` already distinguishes missing observations.
Do not copy that parser into a second owner without a demonstrated incompatible requirement.

| Synthetic input | Expected report behavior |
|---|---|
| One job, two attempts, final accepted outcome | One accepted job, both attempts charged where observed |
| Missing usage on one attempt | Unknown cost coverage; no complete-total claim |
| Missing review or recovery time on one attempt | Partial supervision coverage; no complete total or per-accepted-job claim |
| Tool started, no effect, live supervisor, before configured first-effect deadline | In progress, not a suspected stall |
| Same observations after the configured deadline with continuous observer coverage and valid elapsed time | Suspected tool stall; not a completed command |
| Tool started without reliable elapsed-time or observer-coverage evidence | Unknown progress; do not count a stall |
| Heartbeat missing after sleep or observer loss | Observation gap; process state unknown |
| Success receipt for an old head | Stale verification, not current acceptance |
| Policy refusal or missing declaration | Explicit refusal category; no quality-failure or permission escalation |
| Cleanup not observed | Reconciliation required before retry; preserve artifact references |
| No accepted jobs | Undefined per-accepted-job rate, not zero |

These are specification cases, not executed tests in this documentation PR. The implementation PR
must identify which cases are executable and which native evidence remains absent, then run the
relevant deterministic checks. Observe a small fixed cohort without changing routing and compare
against an inline baseline before recommending more parallelism or a learned routing scorer.

## Research basis and cross-repository handoff

The complete earlier Deep Research report was unavailable to this authoring session. This is a
 dated, source-checked design synthesis, not an imported report or measured result.

[RouteLLM](https://arxiv.org/abs/2406.18665) (2024, revised 2025) studies learned routing between
models on response benchmarks. It motivates testing outcome-based routing; it does not establish
reliable workstation task execution or transfer a benchmark saving to this estate.
[Temporal failure detection](https://docs.temporal.io/encyclopedia/detecting-activity-failures)
(accessed 2026-09-23) distinguishes timeout and heartbeat mechanisms. We borrow the distinction,
not a requirement to adopt Temporal or a claim that these wrappers have its guarantees.

Execution packaging stays in [claude-config#244](https://github.com/Chris0Jeky/claude-config/issues/244)
and [#249](https://github.com/Chris0Jeky/claude-config/issues/249); spend attribution remains
[#245](https://github.com/Chris0Jeky/claude-config/issues/245). Local qualification is
[local-llm-ops#64](https://github.com/Chris0Jeky/local-llm-ops/pull/64).
HQ's [Evidence Exchange #9](https://github.com/Chris0Jeky/agent-hq/pull/9) and coverage work are
separate in-flight consumers; do not treat draft evidence schemas or descriptive coverage as
production authorization. Decision presentation belongs to Action Stack. The design/UX sister
wave [claude-config#308](https://github.com/Chris0Jeky/claude-config/issues/308) is cross-linked only.
