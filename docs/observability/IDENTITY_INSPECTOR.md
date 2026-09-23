# Offline source-record identity inspector

Status: first implementation for [#315](https://github.com/Chris0Jeky/agent-harness/issues/315).
Contract: [source-record identity](AGENT_LOOP_SPANS.md#source-record-identity-and-conflict-handling).
Native telemetry capture and adapter qualification: **NOT RUN**.

## Run the supplied-record diagnostic

From the repository root, using Python 3.11 or newer and the standard library:

```text
python scripts/observation_identity.py docs/observability/examples/identity.synthetic.jsonl
python -m unittest discover -s tests -p test_observation_identity.py -v
```

The first command reads one explicit file and prints one aggregate JSON object.
It does not execute observations, retrieve artifacts, scan directories, call a
model, access a network service, write a report file, or modify the input. It is
not wired into `harness.py`, a hook, a scheduler, an exporter or a required check.

Exit **0** means a report was produced, including conflicts, unavailable identity,
and empty input. Exit **2** means the entire input was unreadable or outside the
supported profile. There is no partial-success report for rejected input. Stderr
uses fixed diagnostic codes without source values, identifiers or paths. The
normal argparse `--help` response is exit 0, not an observation report.

Every report retains `execution_verified: false`, `gate_eligible: false`,
`merge_verdict: null`, and `capture_completeness: "unknown"`. Neither the exit code
nor a `consistent` identity state is product acceptance or merge authority.

## Closed input profile

This tool implements **`agent-harness-observation-identity/0`**, a deliberately
narrow profile of the existing v0 envelope, not a full v0 validator or native-log
parser. Unsupported fields fail before any counts are emitted. Do not strip fields
from an arbitrary native log merely to make the tool accept it: projection must
be performed under a separately reviewed content-off normalization contract.

Top-level object keys are closed by record kind:

| Kind | Required fields | Optional fields |
|---|---|---|
| `span` | `record_kind`, `name`, `attributes`, `trace_id`, `span_id`, `span_kind`, `start_time`, `end_time`, `duration_ms`, `status` | `parent_span_id` |
| `event` | `record_kind`, `name`, `attributes`, `time` | `trace_id` and `span_id` together |

Span names are `invoke_agent`, `plan`, `chat`, `execute_tool`,
`agent_harness.tool.execution`, or `agent_harness.tool.permission_wait`, optionally
followed by one space and one safe token. Event names are exactly
`agent_harness.edit.applied`, `agent_harness.verify.result`,
`agent_harness.request.attempt`, `agent_harness.quota.observed`, and
`agent_harness.subagent.completed`. Supporting an event name does not mean its
full native payload is supported. In particular, quota and cost values are not
accepted by this identity-only profile.

Trace/span IDs are nonzero lowercase hexadecimal strings of 32/16 characters.
A supplied non-null parent ID must be 16 such characters. Null parent means a
claimed known root; omission remains distinct. Event context is correlation only,
not its identity key. The tool does not validate parent topology or native origin.

`span_kind` is `INTERNAL` or `CLIENT`; `status` is `UNSET`, `OK`, or `ERROR`.
Timestamps use UTC `YYYY-MM-DDTHH:MM:SS[.fraction]Z`, with one to nine fractional
digits when supplied; calendar validation rejects impossible dates and leap
seconds. Duration is a finite, nonnegative number no greater than `2^63 - 1`.
The inspector does not reconcile elapsed time with wall-clock intervals or infer
which clock produced a duration. It compares supplied values, not timing accuracy.

### Accepted attributes

All keys in this table use their literal dotted spelling inside `attributes`.
Safe tokens use the canonical identity grammar: case-sensitive ASCII, 1 to 128
characters, `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`. Grammar validation does not prove
that an identifier is non-sensitive, genuine, unique or stable.

| Attributes | Accepted values |
|---|---|
| `agent_harness.schema.version` | Required string `"0"` |
| `agent_harness.content.capture` | Required string `"off"`; redacted-content mode is unsupported |
| `agent_harness.source.name` | Required safe token |
| `agent_harness.source.version`, `agent_harness.source.namespace`, `agent_harness.source.instance.id`, `agent_harness.source.record.id` | Optional safe tokens |
| `agent_harness.normalization.profile` | Safe token identifying the original mapping plus privacy revision; needed for qualified deduplication, not part of the source key |
| `agent_harness.source.record.identity` | `native_span`, `producer_record` or `unavailable`; omission means unavailable |
| `gen_ai.tool.call.id`, `gen_ai.conversation.id`, `gen_ai.response.id` | Optional safe correlation tokens, never fallback source keys |
| `agent_harness.outcome` | `success`, `failure`, `cancelled`, `denied`, `unknown` |
| `agent_harness.phase` | `plan`, `tool`, `edit`, `verify` |
| `agent_harness.verify.result` | `pass`, `fail`, `error`, `not_run`; only a claim, no authenticated check |
| `agent_harness.request.attempt_count` | Integer from 1 through `2^63 - 1` |
| `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_write.input_tokens`, `gen_ai.usage.reasoning.output_tokens` | Integer from 0 through `2^63 - 1`; compared for conflicts, never summed |
| `agent_harness.unavailable` | Map of absent supported field/attribute names to `not_exposed`, `not_observed`, `not_applicable`, `redacted`, `incomplete`, or `invalid` |

Booleans are not numbers. A gap claim for a present field is rejected. Native
resource objects, commands, raw errors, prompts, file/body references, arbitrary
extensions, monetary amounts and additional GenAI attributes are unsupported.
Missing an otherwise valid identity component or normalization profile is an
unavailable observation, not a malformed file; no key is manufactured for it.

The record's normalization profile is an origin claim distinct from this tool's
output `profile`. A producer changes its token whenever its field mapping,
privacy filtering, or normalization rules change. The inspector compares the token
but cannot authenticate its meaning. Known profile mismatches conflict under one
source key, rather than creating separate keys that hide a collision. Unsupported
profile *shapes* are rejected; no version-specific native mapper runs here.

## Counting and conflict semantics

The source key follows the canonical contract. Equality compares the complete
accepted parsed JSON object with sorted object keys. Missing fields, null parent,
changed source/profile versions and changed observations remain distinct. Integer
and floating-point representations remain conservatively different (`1000` versus
`1000.0`); insignificant JSON whitespace and object order are ignored. JSON floating
values follow Python binary64 parsing, not arbitrary-precision source-byte equality.
No payload digest is used as a source key or published as an execution receipt.

Any unequal representation under a key makes **all** rows in that group conflicting,
including repeat exports of an earlier variant. They never contribute to consistent
counts. An unknown-profile row is unavailable rather than silently joined to a
known profile; its presence keeps the overall deduplicated total null.

| Report field | Meaning |
|---|---|
| `received_records` | All accepted input rows |
| `distinct_keys` | Keyed groups, including conflicting ones |
| `consistent_records` | One observation per non-conflicting keyed group |
| `duplicate_records` | Extra identical rows in consistent groups only |
| `conflicting_keys`, `conflicting_records` | Conflicting groups and all their rows |
| `unavailable_identity_records` | Rows lacking qualified source-key/profile information |
| `deduplicated_records` | Consistent-group count only when nonempty input has no conflicts or unavailable rows; otherwise null |
| `identity_state` | `conflicting`, otherwise `unavailable`, otherwise `consistent`, otherwise `empty` |

The partition is `received = consistent + duplicate + conflicting + unavailable`.
The report has no tool/job totals, per-source identifier listing, token sum, cost
sum, completeness guarantee, verified revision or overall success field. Different
sources that lie about the same namespace/profile cannot be detected from identical
claims. Wrapper spans and child events remain different **source records**, never
extra tool invocations or independently delivered jobs.

## Synthetic fixture and verification scope

[identity.synthetic.jsonl](examples/identity.synthetic.jsonl) is authored synthetic
data, not a captured agent loop. Its eight rows contain a repeated span export,
a second span for the same call, three conflicting variants of one event, a
sequence reused after a producer restart, and one event without an instance.

Expected aggregate: received **8**, distinct keys **4**, consistent **3**, duplicate
**1**, conflicting keys **1**, conflicting rows **3**, unavailable **1**, deduplicated
**null**, state **conflicting**. Reordering the rows produces the same report.
The unit suite executes the inspector against this fixture, not a native agent.

Tests also cover profile changes/missingness, namespace and tuple-boundary
collisions, events sharing a span/time, retained errors, malformed JSON/types,
resource limits, input nonmutation, safe diagnostics, file replacement and a POSIX
FIFO refusal. Platform-dependent controls state their limitations. Existing CI
unittest discovery picks up this suite; no workflow was edited. The pre-existing
explicit Ruff/Black/compile lists do not automatically include these new modules.
Run those tools on the two named Python files when available, and report that
result separately rather than claiming broader lint coverage from a green workflow.

## Resource and filesystem limits

Input: one regular file, at most **4 MiB**, **5,000** rows, and **64 KiB** per row.
Both raw input and canonical accepted representations are bounded. LF separates
records; CRLF is accepted, a final newline is optional, and blank records are
rejected. UTF-8 BOM, duplicate JSON keys, non-finite numbers, parser-depth failures
and unsupported nested structures are refused. The pure aggregation entry point
also applies row and canonical-byte limits. It expects finite in-process iterables
of JSON-shaped records, not adversarial executable Python objects.

Leaf symlinks/reparse points, directories, FIFOs and explicit UNC/device-style
paths are refused. Regular hard links are readable, not identity evidence.
The file is checked before opening, after opening and after reading; available
nonblocking/no-follow flags prevent a POSIX FIFO/symlink swap from becoming a read.
This is not a general filesystem sandbox: hostile concurrent parent-directory
replacement, network-mounted paths, restored metadata and arbitrary non-cooperating
writers are outside its guarantee. Use a reviewed, stable, local synthetic file.

## Next bounded qualification and handoff

Do not reimplement identity or add another ledger. First identify one native
version, one authorized content-off capture route and the origin/lifetime/profile
metadata it can really preserve. Use a disposable synthetic task with one normal
tool and one failed/denied tool plus an independently recorded verifier result.
Re-import the same safe observation export, compare source IDs by inspection, and
record unavailable lifetime information honestly. Do not force a live rate limit,
enable raw bodies or infer retry usage from final-attempt tokens.

Native mapping belongs in [CLAUDE_CODE.md](adapters/CLAUDE_CODE.md); logical-job
accounting stays with #288/#296, and the broader observation programme stays #299.
The next trial requires a real local runtime and approved capture details. Synthetic
inspector tests alone do not qualify that runtime or earn a measured benchmark row.
