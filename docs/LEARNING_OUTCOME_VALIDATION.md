# Outcome stream validation

The public readers in `scripts/learning_outcomes.py` consume a **complete
history**, not a batch returned by `read_since`. Accumulate or re-read the full
history before reducing it. `latest`, `posterior`, `lesson_eligible`,
`recurrences`, and `read_since` raise `ValueError` on invalid evidence before
returning a result. `stream_errors` instead returns diagnostic strings.

Validation reuses the existing record schema and semantic rules, including
identity, supersedes and success checks, then checks duplicate IDs, contiguous
per-run versions from 1, and nondecreasing UTC observation instants with advancing
versions. Equal instants are allowed; input ordering and timestamp fractional
spelling do not define chronology. A maturity claim requires `immediate: merged`,
matching the experience contract. These consumer checks do not change the
portable schema validator or exported bundle bytes.

Malformed record objects and cursor shapes fail through the same classified
boundary rather than leaking dictionary/indexing errors. A cursor has exactly
`observed_at` and `id`, both null or a real UTC instant and a nonempty string.
An empty complete stream is valid and returns the existing neutral results.
The posterior CLI reports a refusal on stderr, exits 2 and emits no score.

## Outcome evidence policy

The posterior uses the latest event for each run. Its positive parameter is
`1 + confirmed verdicts + successful clean merges`; its negative parameter is
`1 + refuted verdicts + reverted-or-regressed runs`. A clean merge contributes
positive outcome evidence only while `success` is true. An explicit regression
contributes negative outcome evidence as soon as it is observed, even before
maturity. A run that is both reverted and regressed contributes one negative
outcome unit. Triage findings are separate evidence and retain their own counts.

Projection deduplicates triage feedback within each run by `(kind, ref, signal)`.
Copies with different optional `at` or `key` metadata still count once; distinct
refs or signals remain separate. This rule does not infer that one conflicting
signal supersedes another. A duplicate-only re-observation emits no new event.
The observational system comparison uses the same rule for triage precision.

Rebuild the derived event stream from the complete experience history when
adopting this policy, and rebuild reducers from that full stream. Existing event
rows contain only aggregate verdict counts, so their duplicate source signals
cannot be recovered from the events alone. Do not append a fresh projection to
old events or resume with an old cursor after replacing the stream.

## Remaining limitations

The checks cannot prove that a newest event was not omitted, authenticate
producer clocks, or detect a consistent rewrite of the whole history. The
existing version-derived IDs still change their meaning after some late-arrival
re-projections. Readers must not trust a cursor across re-projection. Trusted
ingestion offsets or authenticated snapshot manifests remain separate work.

Source identity remains `kind` plus `key`; optional account attribution does not
alter event identity. Routing metadata changes still emit a version. The
producer's runtime and model are observer attribution, not authenticated facts
about the runtime that executed the original run. These provenance questions,
trusted ingestion offsets and event-ID migration remain on #511.
