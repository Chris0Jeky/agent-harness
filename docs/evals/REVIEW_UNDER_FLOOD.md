# Review under flood

Status: proposed documentation profile, 2026-09-23. Qualification: NOT RUN.
Profile: `ah-review-packet/0`.
Parent: [#299](https://github.com/Chris0Jeky/agent-harness/issues/299).
Spike: [#301](https://github.com/Chris0Jeky/agent-harness/issues/301).

## Purpose and authority

Provide one compact evidence index for a coding-agent PR: what changed, which contract was
checked, against which revision, what happened, and what remains unknown. Start with the
claim, revision, contradictory observations and next action; keep full logs behind references.

READY is a triage designation. Packet completeness is a documentation property. Check success
is a bounded observation. Merge authorization remains governed by existing repository policy.
None substitutes for another. This profile adds no approval service or mandatory review round.

Only applicable deterministic checks may be gate-eligible under existing policy. LLM summaries,
bot approvals, coverage dashboards and telemetry remain advisory. A reproduced deterministic
defect is separate evidence, not a promotion of the model that suggested it. Known blocking
findings remain visible even when every previously declared check is green.

## Relationship to the existing packet

Extend [Review evidence](../REVIEW_EVIDENCE.md) and its
[v0 authoring template](../review-evidence/packet.template.json), not another harness.
Keep `document_kind: authoring_template_not_execution_receipt`, `template_version: 0` and
`merge_authority: existing_repository_policy_only` unchanged. The profile identifier above is
not a serialized receipt version or a claim that a parser accepts flood metadata.

The field map describes information in the Markdown review view. Put additional flood metadata
alongside the existing packet. Do not add keys, statuses or authority to the JSON template in
this wave. An unfilled template stays unexecuted; a recorded author claim is not verification.

### Field map: required, conditional and optional

Required means the section must exist, with unknown values and their reasons made explicit.
An empty required section cannot support a claim of complete evidence. Conditional requirements
need a stated applicability decision; optional material cannot replace required observations.

| Information | Requirement | Existing field or Markdown companion | What it establishes, and its limit |
|---|---|---|---|
| Document identity | Required | Existing identity/version/status fields; profile and date in Markdown | Interpretation and authoring state, not execution authenticity |
| PR and revision identity | Required | `identity.repository`, `pr_url`, `merge_base_sha`, `reviewed_head_sha`, `tested_revision_sha`, `tested_revision_kind` | Source state for a claim; distinguish source head, merge base, target base and tested CI merge object |
| Contract and change boundary | Required | `intent`, `risk` | Outcome, invariant, falsifier, changed seams, consumers, data/authority effects and recovery; not correctness |
| Stack/dependency identity | Conditional: dependent work | Markdown companion to risk | Parent PR and revision, merge order and affected evidence; parent CI never qualifies the child automatically |
| Cohort membership | Required for study packets | Markdown cohort record | Selection provenance and READY criteria, not permission to merge |
| Planned checks and manifest | Required | `planned_checks` plus Markdown applicability map | Check ID, contract, oracle revision, expected outcome, independence limits and existing gate reference or advisory classification |
| Attempt observations | Required section; empty when NOT RUN | `observations` | Retained attempts, actual revision/action/environment/outcome and evidence reference; author claims still require inspection |
| Scope and raw result | Required for claimed execution | Linked run and companion details | Selected tests/paths, check/fixture revision, relevant environment, timestamps, raw exit/conclusion and skipped work; zero exit alone is insufficient |
| Controls | Conditional: claimed regression/discrimination | Planned controls and distinct observations | Known-good, named broken state and candidate; why the defect was detected, not universal bug coverage |
| Artifact provenance/access | Required for cited evidence | Evidence reference plus companion details | Producer, run/job/attempt, retrieval status, observation date and digest when available; hashes identify bytes, not truthful execution |
| Prior evidence | Required section | `retained_prior_evidence` | Original identity, unchanged scope and reasoned applicability; not a relabelled fresh run |
| Findings/disposition | Required section | `review_dispositions` | Source, affected claim, causal evidence, fixing revision or reasoned disposition; no generated merge verdict |
| Unknowns/next action | Required | `unverified_layers`, `next_action` | Missing, stale, contradictory or blocked evidence and next owner; unknown is not zero |
| Publication scope | Required | Markdown companion | Redaction, access limits and artifact-sharing permission; inaccessible evidence is not independently verified |
| LLM/bot analysis | Optional, advisory | Separate linked section | Source evidence, model/prompt revision when known, candidate findings and limitations; no authority from confidence or consensus |
| Trace references | Optional, advisory | Links coordinated with #303 | Correlation and known missing children, not correctness or proof that all required checks ran |
| Effort/cost | Optional | Existing measurement references | Observed values, units, collection method and missingness; no fabricated zero-cost retries or inferred savings |

### Expected evidence and completeness

Before evaluating outcomes, map each relevant existing requirement and changed contract to a
stable check ID. Record requirement source, applicability, expected candidate/control evidence
and evidence class separately. Required/conditional/optional is not the same axis as
gate-eligible/advisory. Authors cannot make an existing required check optional by omitting it.

For every expected item, show observed attempt IDs, missing evidence and reasons. Resolve any
conditional applicability explicitly. An empty manifest or unresolved applicability cannot be
presented as a complete acceptance packet. N/A needs a contract-based rationale, not a green badge.

Use separate review-view statements for deterministic observations, evidence gaps, telemetry
gaps, and unresolved findings. Do not add a top-level `QUALIFIED`, `SHIP` or merge verdict.
A diagnostic statement of incomplete evidence is not a newly installed CI gate.

**Missing check versus missing span:** an absent required check observation is an evidence gap
regardless of a green parent summary. An absent optional child span is an observability gap;
when independent check evidence is present, it does not erase that result or block a merge.
Never infer zero work from an absent child, and never require telemetry to prove a check passed.

### Attempts, revisions and controls

The observation roles/statuses below follow the **pending**, inspected
[#295 reader documentation](https://github.com/Chris0Jeky/agent-harness/blob/a642f7aa53acbf065092b6bc13aa1596ef2cdfcf/docs/REVIEW_PACKET_TOOL.md).
They describe a reuse target, not a shipped API requirement or a prerequisite merge of #295.
Roles: `candidate`, `successful_control`, `regression_control`.
Statuses: `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`, `N/A`.
That proposal uses `RECORDED` for a packet containing recorded claims, never verified execution.

Retain every attempt, including an earlier FAIL followed by PASS. Record changed inputs and the
explanation or remaining uncertainty. Do not calculate an unconditional latest-pass verdict.
A regression-control PASS means the named bad behavior was detected for the intended reason;
its raw process exit may be nonzero. Import errors, absent credentials or dead services are
setup failures, not successful detection. Infeasible controls stay explicitly unproven.

Record the actual tested revision. A CI merge object is not the PR head: retain its source-head
and target-base relationship with a source pointer. A common merge base alone is insufficient.
After head/base movement, reassess affected evidence and dependencies. Retain unaffected review
evidence with its original identity and scope mapping; neither blindly reuse affected checks
nor restart every review. Existing freshness requirements remain unchanged.

Packet commands, logs and links are untrusted data. Reading a packet does not authorize command
execution, arbitrary artifact fetching or repository changes. A future reader must preserve that
boundary. Redact copies before publication; distinguish a redacted copy's digest from its source.

## Gate-eligible versus advisory

Gate-eligible means potentially usable under an existing applicable repository check. A tool's
name alone never grants that status. No row installs a gate or changes a merge requirement.

| Evidence | Classification | Necessary limit |
|---|---|---|
| Named deterministic tests, smoke checks or replay assertions | Potentially gate-eligible | Applicable, reproducible, ratified contract; identified revision/environment and retrievable result |
| Deterministic Playwright journey | Potentially gate-eligible | Explicit assertions at the relevant boundary and controlled fixtures; screenshot or click completion alone is insufficient |
| Doctor/audit check | Potentially gate-eligible for declared scope | Static configuration inspection does not prove runtime activation or product acceptance |
| Existing deterministic secret scan | Potentially gate-eligible for configured scope | Record detector/configuration and scanned inputs; absence of findings is not absence of every possible secret |
| Reader success/populated packet | Advisory diagnostic | Structure and field presence do not authenticate observations or prove correctness |
| LLM summary, bot LGTM, confidence or consensus | Advisory | Candidate findings, never an LLM merge check |
| Coverage/catch-rate/evidence dashboard | Advisory | Counts do not establish oracle adequacy, permission or estate safety |
| Trace/span/cost summaries | Advisory | Telemetry is not a merge gate; unknown children/cost remain unknown |
| Muse or other computer-use observation | Advisory | Never merge-adjacent proof; separately recorded deterministic checks stand on their own evidence |

Human or existing-process authorization remains separate from these evidence classes. This
profile does not impose universal human sign-off or relax existing required reviews.

## Patterns and failure modes

| Pattern | Useful evidence | Failure to prevent |
|---|---|---|
| Golden journey | Named contract through an existing product boundary, including durable effects when relevant | Testing only a mock, screenshot or happy path; silently expanding into UX scoring |
| Fixture diff | Pinned before/after inputs, explicit normalization and independently reviewed expected differences | Regenerating expectations from candidate behavior or accepting two implementations sharing the same defect |
| Replayable verify | Exact invocation, check/fixture revisions, environment, inputs and retained attempts | Hidden workstation state, wrong source mapping, unrelated setup failure or executing untrusted packet commands |
| Small READY cohort | Frozen universe, declared selection method, risk strata and retained unavailable cases | Choosing only small/green/easy PRs or replacing difficult selections after outcomes are known |

The [existing anti-LGTM checklist](../REVIEW_EVIDENCE.md#anti-lgtm-theater-check-inside-the-existing-review-budget)
remains the reusable review guidance. Apply it within the existing review budget; record its
cohort application in a follow-up issue, not another policy file. Green checks do not erase a
known counterexample, and multiple model opinions do not establish oracle independence.

## Real Taskdeck READY samples

### Fill from live READY

Sample status: **UNFILLED**. No PR below is asserted to be a verified READY sample.

Resolve the authoritative READY/security Priority II triage source. Do not assume READY is a
GitHub label, infer it from green CI, or translate Priority II into a harness tier. Record source
URL/revision and observation time, then inspect each selected PR's live state and source head.

The [scout comment](https://github.com/Chris0Jeky/agent-harness/issues/301#issuecomment-5798217153)
provides discovery pointers only. Never expand its numeric range into membership. A historical
or convenience example may be useful, but must be labelled separately and excluded from the
live-cohort denominator. A pointer that cannot be inspected stays unavailable.

### Placeholder cohort record

| Cohort field | Value |
|---|---|
| Snapshot time, UTC | UNFILLED |
| Authoritative READY source and revision/permalink | UNFILLED |
| READY criteria used by that source | UNFILLED |
| Candidate-universe artifact and digest, if available | UNFILLED |
| Selection rule, seed/tie-break and predeclared budget | UNFILLED |
| Risk/size/dependency strata and quotas | UNFILLED |
| Selected / inspected / unavailable counts | UNFILLED |
| Collector identity and access limitations | UNFILLED |

| Exact PR URL | Head at selection | READY evidence permalink | Risk / Priority II source | Selection reason | Inspection outcome |
|---|---|---|---|---|---|
| UNFILLED: fill from live READY | UNFILLED | UNFILLED | UNFILLED | UNFILLED | NOT RUN |

The placeholder row is not a sample. Leaving it unfilled permits document review, not E4
sample acceptance. A future curated manifest can be linked instead of copying a mutable list.

### Avoiding easy-PR bias

Freeze eligibility and the candidate universe before detailed outcome review. Predeclare the
budget, risk/scope strata, allocation and reproducible selection rule; record a seed and stable
tie-break if using a draw. Preserve security Priority II representation where present and
record shared dependencies so a PR stack is not treated as independent evidence.

Keep selected blocked, withdrawn, changed-head and inaccessible PRs in the record. If the head
moves, preserve the selected identity and record a separate inspection identity. Do not silently
replace cases or update the original cohort after seeing results. Record every deviation.

Report per-stratum counts and missingness. If a budget cannot cover all strata, disclose what
was omitted. A five-case purposive pilot is calibration, not an estate-wide defect-rate or
reviewer-time estimate. Five is a proposed budget inherited from the existing review document,
not a research-derived constant or a new workstream cap.

## Ranked qualification experiments

Plans below are INFER, not executed results. Issue #301 remains open for empirical evidence.
These experiment IDs are local to this profile, not replacements for the epic's E1-E5 labels.

| Priority | Experiment | Acceptance after execution | Limit |
|---|---|---|---|
| F1 | Frozen-cohort packet read-through | Each selected case has a traceable record or explicit unavailability; no missing check becomes PASS; no known blocker disappears behind green CI | No substitutions or estate-wide rate |
| F2 | Oracle discrimination on existing regression evidence | Named bad state fails for the intended reason; corrected state and known-good control succeed; setup failure is distinguished | No product mutation or newly fabricated defect required in this docs wave |
| F3 | Head/stack-drift evidence audit | Original and inspected identities remain visible; affected evidence is re-owed; parent CI does not qualify a child | Use existing history read-only; no Taskdeck PR |
| F4 | Advisory/completeness tabletop | Bot LGTM cannot override a failed check; missing required evidence remains a gap; missing optional span does not invalidate independent evidence | Synthetic cases are labelled and excluded from real-cohort measurements |

## Submission and completion boundary

Before submitting the flood document, attach the exact documentation base/head, checked source
links, actual documentation-check results and either the UNFILLED placeholder or a separately
curated manifest. State NOT RUN for unperformed product, control, model and computer-use trials.
A schema review or tabletop is not an executed runtime experiment.

Documentation acceptance checks field compatibility, authority separation, missingness,
revision/control semantics and the live-sample instructions. E4 qualification additionally
needs real sample identities, retrievable observations and any bounded gate-eligible example
established from those sources. A document or parser passing does not finish that qualification.
Only executed measurements belong in [BENCHMARKS](../BENCHMARKS.md).

The [#302 direction](https://github.com/Chris0Jeky/agent-harness/issues/302#issuecomment-5798216936)
says Verify-red work on #295/#296/#298 does not block docs proposals. Do not change CI, claim
those checks passed or waive an existing merge requirement. Qualify this PR's own head separately.

## Dated sources and related ownership

FACT, inspected 2026-09-23: [main at b586bbf](https://github.com/Chris0Jeky/agent-harness/commit/b586bbf10629b50bcdb08d8b5f99bc60b06795ec)
contains the review guidance and v0 template linked above. #295's observation contract is pending
at the pinned revision cited above. The scout's off-repository handoff files were not inspected;
this document does not attribute details to those unseen files or claim benchmark validation.

INFER: the flood profile, manifest, selection protocol and experiments are proposed extensions.
OVERSOLD: "all green means ship", "the bots agreed", "the packet parsed", or "computer-use
completed the flow, therefore the PR is proven". No vendor performance claim is used.

Related homes: [taxonomy #300](https://github.com/Chris0Jeky/agent-harness/issues/300),
[merge boundary #304](https://github.com/Chris0Jeky/agent-harness/issues/304),
[trace vocabulary #303](https://github.com/Chris0Jeky/agent-harness/issues/303) and
[extension notes #302](https://github.com/Chris0Jeky/agent-harness/issues/302).
Use issue links until sibling docs land; do not duplicate their full contracts here.

No code, serialized-schema changes, CI changes, opentelemetry-sdk, collector, second harness,
product rewrite, Taskdeck PR, auto-merge or LLM merge gate. Sister
[UX epic #281](https://github.com/Chris0Jeky/agent-harness/issues/281) remains outside this scope.
[claude-config#308](https://github.com/Chris0Jeky/claude-config/issues/308) skills/workflow
packaging is explicitly deferred until the source-of-truth docs and packet mapping stabilize.
