# Learning evaluator evidence boundaries

Follow-through for #521, #522 and the retrieval-metric portion of #500.
This changes offline evaluation, not the runtime dispatcher or an LLM merge gate.

## Independent evidence

The selected hold-out counts each `input_ref` once. Exact oracle clones on the
same input remain deduplicated. Different oracles on the same selected input
refuse the run, instead of treating correlated facets as independent wins or
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
revision therefore do not silently reuse an old report identity. Report schemas,
public contract bundle bytes and historical reports are unchanged.

Run `python -m unittest discover -s tests -p test_learning_eval.py -v` for the
synthetic evidence controls, and the full repository unit, smoke and Doctor
commands before publication. Native hosted OS results are separate evidence from
local Linux tests; no live transcripts, promotion deployment or runtime canaries
are exercised by these tests.
