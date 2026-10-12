# Learning evaluator evidence boundaries

Follow-through for #521, #522 and the retrieval-metric portion of #500.
This changes offline evaluation, not the runtime dispatcher or an LLM merge gate.

## Independent evidence

The selected hold-out counts each `input_ref` once. Exact oracle clones on the
same input remain deduplicated only when both variants' output records and any
judge labels agree. Missing versus present evidence also conflicts. Different
oracles or contradictory observations on the same selected input refuse the run,
instead of treating correlated facets as independent wins or
silently picking a favourable facet. Producers needing multiple facets must
provide an explicitly designed aggregate trial; this evaluator does not invent
one. `input_ref` is still supplied metadata, not proof of real-world independence.
Broader clustered inference and provenance qualification remain under #513.

## Retrieval metrics

The denominator comes from selected `ranked_recall` cases, not from whether a
variant returned usable output. Missing outputs, errors and missing item lists
contribute zero recall and reciprocal rank for that arm. Both arms retain the
same denominator, including an all-failed retrieval run.

A `retrieval_regression` gate cannot pass if either mean recall-at-k or mean
reciprocal rank falls below baseline, even when unrelated case wins satisfy the
existing paired sign test. The other gate types retain their existing paired
policy. This is a conservative no-regression guard, not a claim to estimate
rank-metric confidence intervals or to complete every concern in #500.

A named retrieval gate with no selected `ranked_recall` inputs is `insufficient`
and emits no gate, even if unrelated cases all win. `offline_eval` remains usable
for those non-retrieval suites. Mixed suites retain the declared overall-case
minimum and sign policy: their measured retrieval denominator is reported as `n`,
not represented as retrieval-only statistical power. Retrieval-specific sample
size, clustered inference and policy authority remain separate work under #513;
this repair does not silently invent a new threshold or count unrelated cases as
ranked-recall observations.

## Regular-expression oracles

Compilation and matching run in a fresh standard-library Python subprocess with
`-I -S`; patterns and output text are JSON data on stdin, never executable source.
Each worker has a two-second wall-clock deadline. A timeout kills and reaps the
worker and refuses evaluation; launch failure, nonzero exit or malformed worker
output likewise cannot become a passing grade. Invalid expressions refuse before
grading. Repeated patterns are compiled once during one selection pass, without
retaining a cross-run cache of private output text.

This bounds one regex operation, not the number of cases in a supplied suite or
arbitrary policy code. The worker executes only the fixed regex helper and does
not spawn descendants. The regression uses a deliberately backtracking pattern
and a separate ten-second outer watchdog so a broken timeout cannot wedge tests.

## Report identity and verification

Evaluator identity advances to `agent-harness:scripts/learning_eval.py@2` and is
included in the derived report ID. The same records evaluated by another tool
revision therefore do not silently reuse an old report identity. The identity also
binds the full selected case contracts, including their oracle and input/anchor
fields. Outputs are explicitly bound to baseline/candidate roles, so swapping the
arms cannot reuse the same ID. Recursive JSON key ordering and supplied case order
do not change the identity. `holdout_digest` remains the digest of selected case
IDs, not their contents; report schemas, contract bundle bytes and historical
reports are unchanged. These consistency bindings are not authentication of the
producer's claimed provenance or of unobserved execution.

Run `python -m unittest discover -s tests -p test_learning_eval.py -v` for the
synthetic evidence controls, and the full repository unit, smoke and Doctor
commands before publication. Native hosted OS results are separate evidence from
local Linux tests; no live transcripts, promotion deployment or runtime canaries
are exercised by these tests.
