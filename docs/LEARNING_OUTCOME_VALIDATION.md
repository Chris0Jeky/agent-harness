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

## Preserved policy and limitations

This bounded #511 slice leaves the documented Beta formula, triage counting,
event IDs, projections, source attribution and cursor ordering unchanged. It
neither chooses a policy for clean-plus-regression outcomes nor deduplicates
feedback refs. Those choices remain on #511.

The checks cannot prove that a newest event was not omitted, authenticate
producer clocks, or detect a consistent rewrite of the whole history. The
existing version-derived IDs still change their meaning after some late-arrival
re-projections. Readers must not trust a cursor across re-projection. Trusted
ingestion offsets or authenticated snapshot manifests remain separate work.

#543 changes account projection in a disjoint hunk of this module. Reconcile
current main before either merge and retain its explicit source kind/key
projection; do not overwrite that newer source with a whole older file.
