# Advisory logical-job accounting

`python scripts/ops_cohort.py path/to/cohort.json` reports a fixed study cohort without
executing work or modifying files. Exit 0 means the report was constructed, not that a
job passed. Invalid, unsupported or inconsistent input exits 2 with sanitized diagnostics.

This implements the first accounting slice of [#288](https://github.com/Chris0Jeky/agent-harness/pull/288).
It does not activate a floor, change policy/leases, import a runtime, or select a model.

## Normalization is explicit, not another source of truth

A coordinator prepares a **temporary study export** from canonical work items, retained
native receipts and observed review results. `agent-ops-cohort/1` is that export, not a
queue protocol, work-item schema or replacement native receipt. Keep the export private.
Receipt hashes are references, not file paths: this tool never fetches them, authenticates
an observer or discovers omitted work. Use a fixed, declared cohort and preserve unknowns.

The existing `claude-config/tools/summarize_trials.py` continues to own its normalized
single-attempt trials. It groups by runtime/model/environment/revision and cannot recover
logical-job identity, cross-attempt acceptance or job admission from those groups. This
helper does not copy that parser, import its private API, reinterpret `trial_id`, or change
its schema. The normalization owner supplies the additional job join explicitly. Trial
success or a `local-exec-triage/1` review candidate is **not** human/coordinator acceptance.

## Input contract

One JSON object has exactly `schema`, `currency`, and `jobs`. `currency` is an explicit
three-letter uppercase code or null; it is a label, not an exchange-rate lookup. Null
currency requires all costs null. Never put subscription credits, tokens, GPU seconds or
account-wide usage deltas into currency-valued cost. All amounts must use the same unit.

Each job has exactly `job_id`, `input_revision`, `admitted`, `disposition`,
`accepted_attempt`, and `attempts`. IDs are bounded ASCII identifiers. Revisions are full
lowercase 40- or 64-hex object identities. Disposition is `not_admitted`, `pending`,
`blocked`, `rejected`, or `accepted`. A nonadmitted job has no attempts; an admitted one
cannot be `not_admitted`. Only accepted jobs select one of their own attempt IDs.

Every attempt has exactly the fields in this synthetic example:

```json
{
  "schema": "agent-ops-cohort/1",
  "currency": null,
  "jobs": [{
    "job_id": "synthetic-job",
    "input_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "admitted": true,
    "disposition": "pending",
    "accepted_attempt": null,
    "attempts": [{
      "attempt_id": "synthetic-attempt",
      "source_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "verified_revision": null,
      "outcome_pass": null,
      "constraints_pass": null,
      "cost": null,
      "queue_seconds": null,
      "execution_seconds": null,
      "verification_seconds": null,
      "review_seconds": null
    }]
  }]
}
```

The two acceptance observations are boolean or null. The five numeric observations are
finite, nonnegative numbers or null; a missing field is not silently converted to null.
A true acceptance observation must come from the named verification/review process, not
an agent's confidence. Measure the four clocks separately; workstation sleep or observer
loss is not active execution. IDs, receipt hashes and amounts are checked for shape and
consistency, not independently proven. Do not include prose, paths, tokens or raw logs.

## Counting and unknowns

One admitted job remains one denominator entry regardless of retries or route changes.
Every included attempt contributes its observed cost and review burden, including failed,
blocked and rejected work. Duplicate job/attempt identities or source receipt hashes
refuse instead of double counting. Pending and not-admitted jobs remain visible.

An accepted claim with a different tested revision becomes `stale_acceptance`; absent
verification or unknown outcome/constraints becomes `unverified_acceptance`; an explicitly
failed outcome/constraint becomes `contradicted_acceptance`. None counts as accepted.
A successful attempt does not promote a pending job. This is internal consistency checking,
not independent verification or a merge gate.

Each numeric field reports observed/missing attempt counts and observed sum. `complete_sum`
is null when any included attempt is unobserved, or there are no attempts. `per_accepted_job`
requires both complete observations and at least one consistent accepted job. Actual zero
is retained as zero. Complete refers only to **included attempts at this snapshot**, not
future spending, omitted attempts, unrelated sessions or the account's total usage. The
report does not estimate savings, utilization, model superiority or a hard financial cap.

## Boundaries and verification

The reader accepts one regular file, at most 4 MiB, 1,000 jobs and 5,000 attempts. It rejects
duplicate JSON keys, unknown fields, non-finite numbers, malformed references and aggregate
overflow. CLI diagnostics and aggregate output omit the input IDs; a hash binds exact input
bytes but does not make private data safe to publish. A caller-selected symlink to a regular
file is allowed; this is not a filesystem sandbox.

Run `python -m unittest discover -s tests -p test_ops_cohort.py -v`. Tests cover retry costs,
unknowns versus zeros, all denominators, stale/contradicted acceptance, duplicated receipts,
invalid numbers/shapes, deterministic ordering and the real nonmutating CLI. Repository CI
also lints, formats and compiles the two added Python files with its pinned tools.

Remaining work: adapters from actual coordinator/native receipts, fixed-cohort collection,
blocked-agent heartbeat/effect observation, and review-capacity experiments. No live costs,
productivity improvements or runtime qualifications are claimed here. Follow #288's evidence
boundaries and #233's existing workstream limits. `HUMAN_TODO.md` remains unchanged.
