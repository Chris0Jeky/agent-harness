# Offline reviewer-packet diagnostics

This is the first executable helper for [review/oracle proposal #290](https://github.com/Chris0Jeky/agent-harness/pull/290).
It reads that proposal's v0 authoring packet. It does not create another receipt authority,
execute a check, fetch an artifact, contact a model, change a repository, or approve a merge.
The original brief remains unavailable in #290's source ledger; this implementation is a new
bounded recommendation, not a result attributed to that brief.

## Run locally

```sh
python scripts/review_evidence.py /path/to/packet.json --expected-head FULL_SOURCE_PR_HEAD
python -m unittest discover -s tests -p test_review_evidence.py -v
```

The first command writes JSON to stdout. Keep the packet and output local unless a human has
reviewed their publication scope. No output file is written automatically. The expected head
must be a full lowercase Git object ID. Without it, the identity comparison is UNKNOWN, even
when a packet declares a head. The helper does not authenticate that declaration against GitHub.

Exit **0** means the input was interpreted and an advisory report produced, even when it reports
FAIL, BLOCKED, missing evidence, or a different head. Exit **2** means invalid/unreadable input.
Neither exit status is a product acceptance or merge verdict. CI runs deterministic tests of the
reader's behavior, not this command as a new merge gate. LLM judgments remain advisory.

## Packet compatibility

Keep `document_kind: authoring_template_not_execution_receipt` and `template_version: 0` from
#290. Required sections are `identity`, `planned_checks` and `observations`. The original
unfilled template is valid and produces no claimed execution. Intent, risk and other authoring
fields remain in the original packet for a human reviewer; this helper is not a full semantic
validator for them. Unknown extension fields are ignored, never treated as authority.

Each planned check has a unique printable `id`. To record an observation, add an object with:

| Field | Meaning |
|---|---|
| `id` | Unique attempt ID. Keep failed attempts instead of overwriting them. |
| `check_id` | Exact ID of an existing planned check. |
| `role` | `candidate`, `successful_control`, or `regression_control`. |
| `status` | `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`, or `N/A`. |
| `tested_revision_sha` | Full actual tested revision, not a relabelled source head. |
| `command_or_action` | What was actually run or manually performed. Never executed by this helper. |
| `environment` | Relevant test configuration and isolation. |
| `actual_outcome` | Observation or reason for BLOCKED/N/A, not a copied expectation. |
| `evidence_ref` | Retriever-independent artifact/run reference. Never dereferenced by this helper. |

For a regression control, PASS means that the named broken behavior was detected for its
intended reason, not necessarily that the process exited zero. Setup failure belongs in
BLOCKED; a dead service is not successful defect detection. A recorded PASS or FAIL missing
revision, action, environment, outcome or evidence reference is INCOMPLETE. These are checks for
field presence, not proof that the field is truthful, retrievable, independent, or useful.

The top-level `execution_status: NOT RUN` in an unfilled template must not be silently retained
when outcome claims are added. Set it to `RECORDED` for a packet containing recorded claims.
Contradictions remain visible as warnings; this field never overrides the observation list.

## Reading the report

`execution_verified` is always false and `merge_verdict` is always null. `RECORDED` means only
that the specified evidence fields are present. It does not mean independently verified.
Candidate observations are compared with the explicitly expected source head, or the declared
reviewed head when no expected head was supplied. A missing target is UNBOUND; a different
revision is OTHER_REVISION. Controls may intentionally exercise a different revision.

A CI merge revision must remain its actual merge object ID. This first helper does **not**
authenticate the source-head/base relationship of a merge object. Such a candidate observation
is reported as OTHER_REVISION relative to the source head and must be mapped manually in the
existing PR evidence. Do not substitute the source SHA to silence the report.

`checks_with_candidate_observations` counts check IDs with any candidate entry, including NOT
RUN. It is not executed coverage or a pass rate. Control entries do not increase that count.
Every attempt remains in the output; both PASS and FAIL on one check trigger a mixed-outcome
warning rather than a convenient latest-pass summary. BLOCKED, NOT RUN and N/A remain distinct.

The input SHA-256 identifies bytes, not their author or execution. Commands, raw outcomes,
environment text and evidence references are deliberately not echoed in the report. IDs and
revisions may still be sensitive metadata. There is no automatic publication or telemetry.

## Bounded implementation and next evidence

The CLI accepts regular UTF-8 JSON files up to 1 MiB, rejects duplicate keys and non-finite
numbers (including exponent overflow), and rejects unknown versions, statuses, roles and check
references. It is a local diagnostic, not a sandbox for adversarial concurrent filesystem changes.
The tests cover identity mismatch, incomplete evidence, setup states, preserved failures,
control/candidate separation, strict JSON and commands that must never execute.

The next E1 step remains a declared cohort of actual PR slices, including parked and failed work.
Measure reviewer effort and missing evidence separately. Unit tests and synthetic parser controls
do not establish adoption, reviewer-time savings, product usefulness, native skill activation,
or an estate-wide failure rate. Floor, Doctor, replay and existing merge policy are unchanged.
