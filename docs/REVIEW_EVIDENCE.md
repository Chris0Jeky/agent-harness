# Review evidence and acceptance oracles

Status: proposed practice and authoring templates, 2026-09-23. No new runner, receipt
format, gate, review round, merge permission, or measured estate result is shipped here.
[Source ledger](review-evidence/SOURCES.md) separates inspected decisions, external
references, and new recommendations. The requested completed research brief was not
available to inspect; this document is not a transcription of it.

## Ownership and existing decisions

The tier declaration, global laws and existing bounded `review-and-ship` pipeline retain
merge authority. [Estate consolidation #101](https://github.com/Chris0Jeky/agent-harness/issues/101)
explicitly rejects competing local review doctrine. This proposal adds evidence to the
existing PR conversation, not another approval service or mandatory human review for every tier.
Preserve current review ceilings, severity rules and affected-scope revalidation.

| Existing seam | Use in this wave | Claim it must not acquire |
|---|---|---|
| `harness.py audit` / `doctor` | Link the actual report when configuration is in scope | Static inspection proves runtime activation or product acceptance |
| Existing tests / replay | Link exact inputs, check revision and observed outputs | Fixture success proves production quality or user value |
| `docs/BENCHMARKS.md` | Add results only after a bounded measured trial | Planned samples or generated examples are measurements |
| Global workflows in `claude-config` | Package the procedure once, render both adapters | Another policy home or third skill tree |
| UX evidence #281 / PR #289 | Refer to a relevant observation if one exists | QA auditor or LLM judge owns merge authority |
| Ops measurements PR #288 | Reuse relevant recorded identities and denominators | Reimplement routing, job queues, or backlog decision tools |

The dispatcher remains frozen infrastructure. This proposal changes no floor wiring,
Doctor status semantics, runtime trust, coordinator-owned state documents or active-workstream cap.

## One slice, one reviewable outcome

Recommendation: choose a coherent behavior and its proof, not a universal line-count quota.
A reviewer should be able to state what changed, what did not, and what would falsify the claim.
Keep the first real consumer with a new interface; do not manufacture small PRs by shipping
unused abstractions. Separate mechanical moves from semantic changes where practical.

Split when a second independent acceptance decision or rollback boundary appears, or when
unrelated fixes obscure the causal diff. A necessary cross-layer transaction can stay together;
record why its intermediate states would be invalid. Stack dependencies explicitly and keep
landed states operable. Risk is a description of the changed seam, not a replacement tier:
name data loss, permission, migration, shared infrastructure, compatibility and recovery exposure.

## Reviewer packet

Use the existing PR body or one linked artifact. The
[JSON template](review-evidence/packet.template.json) is an authoring aid, NOT a harness
receipt or evidence that anything executed. Null observations are deliberately not passes.

| Field | Minimum useful content |
|---|---|
| Intent and boundary | User-visible outcome, invariant, non-goals, issue/contract source |
| Identity | Repository, merge base, reviewed head, tested head or CI merge SHA, fixture and check revisions |
| Risk and blast radius | Changed consumers, persistence/authority effects, dependencies, recovery route |
| Oracle | Expected observable result, test method, why it tests the contract rather than copies implementation |
| Controls | Known-good behavior and a named broken/negative case; result and reason for each |
| Observations | Exact command/action, environment, status, actual outcome, retrievable artifact or run link |
| Review disposition | Causal findings and their resolution in the existing review; retained evidence scope |
| Unknowns and next action | Skipped layers, unavailable environment, unresolved blocker and owner |

Do not paste full logs into every handoff. Keep a compact decision summary and pointers to the
underlying artifacts. Separate author-written expectations from runner-observed outputs.
Hashes identify bytes; they neither authenticate the author nor prove execution.

When the head changes, retain unaffected review evidence with its original identity and a
reasoned scope mapping. Re-run checks for changed behavior, dependencies or environment.
Never relabel old results as a fresh run, invalidate everything solely because time passed,
or start a new review round for a routine refresh with unchanged risk and reviewed diff.
A CI merge SHA is not the PR head: record both and the tested base relationship.

## Oracle taxonomy and limits

| Oracle class | Useful proof | Limit / treatment |
|---|---|---|
| Format / structure | JSON parses; schema matches; generated trees agree | Artifact well-formedness only, not outcome correctness |
| Exact behavioral contract | CLI exit/output/files; API response and durable effects; state-transition invariant | May gate when applicable, reproducible and ratified in the existing repo |
| Successful control + regression control | Expected-good path succeeds; named broken behavior is rejected for the intended reason | Shows sensitivity for these cases, not complete bug detection |
| Differential / metamorphic | Baseline/candidate comparison; equivalent input ordering; idempotent repeat | Check baseline validity and relation assumptions; two wrong implementations can agree |
| Product-facing acceptance | Real UI action plus persisted result; actual CLI/API boundary | Use the existing product runner; mocks alone do not establish the full boundary |
| Fixed visual comparison | Pinned renderer/viewport/fonts and reviewed reference image | Visual contract only; timing and rendering variance require calibration |
| Human usefulness rubric | Observed task friction, comprehension, repeat use | Advisory product decision, not deterministic correctness |
| LLM / heuristic review | Candidate findings and counterexamples for a reviewer | Advisory; model agreement, confidence or keywords are not semantic ground truth |

A deterministic computation can still implement a bad oracle. Coverage percentages, a file
existing, a screenshot being produced, keyword similarity and a green mock run are insufficient
for broader outcome claims. Screenshots do not establish persistence, accessibility or a
successful interaction unless the relevant property was separately tested.

**No flaky LLM judgment enters merge-blocking CI.** An existing required review process can
consume advisory findings with the repository's human-override route; this document adds no
LLM status check or new override power. A reproduced deterministic defect is handled by the
existing severity and merge policy, not by a model score. Never silently waive an existing red
check or reinterpret infrastructure failure as product success.

## Outcome-contract patterns

Write expectations before implementation where possible, anchored in an issue, published API,
user task, historical defect or independently reviewed invariant. Agent-authored tests are not
independent merely because another model wrote them. Disclose shared prompts, helpers, mocks
and copied logic. Favor a genuinely different observation boundary over a second paraphrase.

| Boundary | Contract sketch | Observation and controls |
|---|---|---|
| UI journey | Review a proposed change; before explicit execution there is no board mutation; after allowed execution the intended item survives reload | Observe UI, request and durable state with seeded non-sensitive data; valid execution succeeds; reject/cancel leaves state unchanged |
| CLI | Valid input returns the documented exit code and exact output/file effect; invalid input reports an error without partial overwrite | Invoke the built CLI, inspect stdout/stderr and filesystem; include known-good input and the named malformed/permission case |
| API | Authorized valid request changes only the intended resource; invalid/unauthorized request preserves state | Invoke actual boundary, inspect response and persisted state; do not share the implementation's parser as the only oracle |

These are examples, not new Taskdeck/API/CLI contracts. Product owners bind exact values and
existing fixtures. Unknown prerequisites are BLOCKED or NOT RUN, never an invented expected pass.

For a regression, prove the same focused check rejects the named broken revision or an isolated
fault injection for the intended reason, then accepts the candidate and the known-good control.
Import errors, absent credentials and dead servers are setup failures, not successful regression
controls. Where replaying the old revision is unsafe or infeasible, record why and the weaker
substitute. Do not mutate real user data or land a deliberate defect just to obtain a red result.
For a new capability, baseline absence is expected, not evidence of a baseline regression.

## Anti-LGTM-theater check, inside the existing review budget

- Can the reviewer connect changed lines to a reachable input/state and observable consequence?
- Did the control really reach the intended boundary, rather than fail before setup completed?
- Would a hardcoded response, no-op or skipped persistence still pass this oracle? Check the
  relevant counterexample, not a ritual mutation for every docs edit.
- Are production-facing layers and unknowns explicit, including private artifacts the reviewer
  cannot retrieve? Unavailable evidence is not independently verified evidence.
- Are introduced, worsened, pre-existing and intended behavior distinguished? Are non-blockers
  tracked or declined rather than triggering another fix/review loop?

## Bounded qualification, not rollout

E1: trial the packet on the next five eligible slices in one repo. Predeclare eligibility and
include parked/failed slices. Record reviewer active effort, missing evidence, confirmed blockers
and escapes found during a fixed follow-up window. Five slices cannot establish an estate rate.

E2: on two existing contract-sensitive regressions, compare a known-good control with the named
broken revision. Record whether the purported oracle detects the defect for the right reason.
Do not count newly generated tests or mutants as independent field defects.

E3: use Taskdeck's existing dogfood programme for one manual before/after task comparison.
Correctness results, synthetic practice and organic use stay separate. No audience or retention
claim follows from a successful synthetic task.

These are proposed starting budgets, not research-derived constants or changes to #233. Log
experiments and follow-up ownership in the PR/issue conversation; only executed results belong
in `docs/BENCHMARKS.md`. Keep the first three-repo wave in draft until source provenance,
applicable local checks and the changed procedures receive the required review.
