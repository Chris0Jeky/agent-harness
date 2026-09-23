# Coding-agent loop observability v0

Status: proposed documentation contract, 2026-09-23. No exporter, SDK, native-agent
qualification, measurement result, or merge-policy change is delivered here.
Parent [#299](https://github.com/Chris0Jeky/agent-harness/issues/299), child
[#303](https://github.com/Chris0Jeky/agent-harness/issues/303).

Classification: **FACT** paragraphs describe cited sources inspected on 2026-09-23;
**INFER** is proposed engineering design dated 2026-09-23, including all unmarked
contract tables, examples, and recommendations below. **OVERSOLD** labels claims
that must not be treated as evidence. Access dates are not publication dates.

## Boundary and ownership

**Telemetry ≠ merge gate.** Missing spans, disabled capture, exporter failures,
coverage gaps, cost/latency observations, and LLM/vendor scores must never become
merge-blocking CI conditions. Structural requirements describe captured records,
not a requirement to produce telemetry before merging. A deterministic computation
over telemetry does not make that telemetry eligible to gate.

Independently defined, applicable deterministic oracles may gate under existing
repository policy. Their original results remain authoritative for the tested
property. A telemetry event referencing a test result neither authenticates the
execution nor proves a different revision. See [review evidence](../REVIEW_EVIDENCE.md)
and [#304](https://github.com/Chris0Jeky/agent-harness/issues/304).

| Owner | Responsibility | Excluded authority or duplication |
|---|---|---|
| `agent-harness` | This canonical observation contract and future thin adapters | No second harness, scheduler, approval service, or replacement receipt format |
| `agent-hq` | Index evidence identity and descriptive coverage | No correctness, qualification, merge or release promotion |
| Existing oracle/CI | Original independently defined checks and exact tested scope | Telemetry copies do not replace check results |
| Existing ops work [#288](https://github.com/Chris0Jeky/agent-harness/pull/288) / [#296](https://github.com/Chris0Jeky/agent-harness/pull/296) | Logical-job/attempt accounting and denominators | This document supplies observations, not another financial or job ledger |
| Later `claude-config` packaging | Reference and explain this contract through existing skills | Do not fork the schema or alter review doctrine; coordinate through #302 |
| Optional vendors | Render, aggregate or translate captured observations | No backend or chat proxy is the sole evidence or release source of truth |

**FACT:** [agent-hq#10](https://github.com/Chris0Jeky/agent-hq/issues/10) specifies
`authority: none` and `gate_eligible: false`, including for deterministic coverage.
Do not import raw telemetry into that index as a new evidence protocol. Any later
bridge must explicitly map an existing supported evidence schema.
[Policy Lab](../../REPLAY_TOOL_PRODUCT.md) replays decisions; it is not a trajectory
ledger. Product UX observe/judge remains in [#281](https://github.com/Chris0Jeky/agent-harness/issues/281).

## Operation vocabulary and parenting

**FACT:** The reviewed GenAI agent/client/event/metric documents are Development,
not Stable. Use their names only where meanings match; this local format is
OTel-shaped, not OTLP or a claim of stable GenAI compliance. [S1], [S2], [S3], [S4], [S5]

Choose one bounded user turn or explicit agent invocation as a loop. A standalone
loop starts a trace; an invocation with genuine upstream context retains it.
Multiple turns may share a genuine conversation ID without becoming one giant
terminal-session span. Preserve native causal relationships across resumed turns.

| Boundary | Operation / kind | Parent rule |
|---|---|---|
| Local invocation | `invoke_agent`, `INTERNAL` | Actual caller if observed; otherwise a known local root |
| Explicit planning | `plan`, `INTERNAL` | Invocation; omit when planning cannot be distinguished reliably |
| Model request | API-appropriate operation such as `chat`, usually `CLIENT` | Planning request under `plan`; other decisions under the active invocation; retain actual upstream nesting |
| Local agent-side tool | `execute_tool`, `INTERNAL` | Active causal invocation, not automatically the model span that requested it |
| Edit / test / lint / build | `execute_tool` plus `agent_harness.phase=edit` or `verify` | Same tool rule; the phase does not assert success |
| Delegated agent | `invoke_agent` only if an invocation boundary is observed | Actual launching operation; otherwise preserve native children without inventing an invocation span |

**FACT:** Planning inference belongs beneath `plan`, while execution of its plan
normally belongs beside it under the invocation. OTel advises omitting `plan` when
instrumentation cannot identify it. A logical inference span includes automatic
retries. [S1], [S2] Model-local inference can use `INTERNAL`; do not relabel remote
calls as local merely because a coding CLI runs on a developer machine.

Names use `operation` plus a safe agent/model/tool name when available. Do not put
prompts, commands, paths, PR titles or other arbitrary text into span names. Do not
invent standard operations named `edit` or `verify`, or a workflow wrapper simply
for presentation. Timeline arrows express order, not parentage.

## Local record sketch

A future adapter may write bounded UTF-8 JSONL and a console projection using this
vocabulary. No writer is implemented here. Console output is not assumed to be
machine-readable JSONL. Unknown fields/versions must remain uninterpreted rather
than acquiring a verdict. A future reader should reject malformed records from
aggregation with a diagnostic, not stop the coding operation or a merge.

| Field | Type / units / presence | Meaning and unavailable handling |
|---|---|---|
| `record_kind` | `span` or `event`; required | Completed observed interval or timestamped observation, respectively |
| `name` | safe string; required | Operation-based span name or documented event name |
| `trace_id`, `span_id` | nonzero 32 / 16 lowercase hex digits on spans | Preserve genuine context; generate only for a boundary actually instrumented, not to pretend an unseen native operation exists |
| `parent_span_id` | 16 hex digits if known; null only for known root | Omit when unknown and record that gap; an absent parent record may simply be outside the capture |
| `span_kind` | `INTERNAL` / `CLIENT` for the boundaries above | Span-only; do not confuse a vendor AI category with OTel span kind |
| `start_time`, `end_time`, `duration_ms` | UTC RFC3339 strings and finite nonnegative milliseconds; completed spans | Duration uses the source's elapsed clock; disclose wall-clock-only estimates. Do not invent an end for interrupted operations |
| `time` | UTC RFC3339 string; events | Observation time, not an invented span start |
| `status` | `UNSET`, `OK`, `ERROR`; spans | Source operation status, never a descendant roll-up or merge verdict |
| `attributes` | bounded object; required | Only interpreted allowlisted metadata; no arbitrary vendor object passthrough |
| `agent_harness.schema.version` | string `0`; required attribute | Version of this proposed local contract, independent of SDK/version numbers |
| `agent_harness.source.name` / `.version` | safe source identifier / observed version | Required name; omit unknown version. A document's version is not an installed runtime measurement |
| `agent_harness.content.capture` | `off` or `redacted`; required attribute | Off by default; redacted means explicitly permitted fields after filtering, never unrestricted raw capture |
| `agent_harness.unavailable` | optional object: field name to reason | Reasons: `not_exposed`, `not_observed`, `not_applicable`, `redacted`, `incomplete`, `invalid`; never substitute zero |

The `agent_harness.*` keys are inside `attributes`; object-valued extensions are
local JSON only and would need an explicit translation for any future OTLP adapter.
Events use trace/span IDs only when associated with a genuine known context. An
uncorrelated source event can remain an event with an explicit gap. Partial native
records are retained only as safe event observations, not fabricated completed
spans. This is a sketch for an existing-harness adapter, not a new runnable schema
validator, transport specification, evidence receipt or append-only attestation.

### Correlation and observations

All source-dependent attributes below are optional when unavailable. Structural
capture must not enable content to obtain a missing identifier. IDs are opaque
correlation values, not authentication tokens; credentials are never identifiers.

| Attribute | Type / source / meaning |
|---|---|
| `gen_ai.operation.name` | String matching the observed operation, on semantic spans |
| `gen_ai.agent.name`, `gen_ai.tool.name` | Safe allowlisted name/category; omit unsafe raw names and record redaction |
| `gen_ai.conversation.id` | Genuine native session/thread ID when safe; never a new UUID, trace ID or content hash fallback [S3] |
| `gen_ai.tool.call.id` | Native model/tool-call ID, not tool name; correlate within producer/session scope [S2], [S3] |
| `gen_ai.response.id` | Actual completion ID, not a transport request-header ID [S3] |
| `gen_ai.provider.name` | Observed provider identity; a gateway brand alone does not prove the upstream provider |
| `gen_ai.request.model`, `gen_ai.response.model` | Requested and observed actual model respectively; never assume actual equals requested [S2], [S3] |
| `error.type` | Safe low-cardinality failure category on error, `_OTHER` when a failure is known but its type is unavailable; no full exception text |
| `agent_harness.run.id` | Existing harness run identity only when associated; standalone native runs need not pretend a harness run exists |
| `agent_harness.repo.id`, `agent_harness.repo.revision` | Safe stable repo identity and known full commit SHA; neither is a filesystem path |
| `agent_harness.repo.dirty` | Boolean only when inspected; a revision without a cleanliness observation does not identify working-tree bytes |
| `agent_harness.change.pr.number` | Positive integer only for a known associated PR; normal local runs may have none |
| `agent_harness.oracle.id`, `agent_harness.evidence.id` | Existing oracle and evidence references, not a fresh acceptance authority |
| `agent_harness.phase` | `plan`, `tool`, `edit`, `verify` when meaning is known; do not infer from a successful exit alone |
| `agent_harness.outcome` | `success`, `failure`, `cancelled`, `denied`, `unknown`; source observation separate from span status |

Keep run/session/repo/PR IDs out of metric label sets; they belong in records and
drill-down references, not unbounded aggregate dimensions. Record identity below
is distinct from logical invocation, attempt, session and delivered-job identity.

### Source-record identity and conflict handling

This is the #314 design amendment, not native qualification. All new fields below
are local attributes, not standard OTel attributes. Identity is an input claim,
not authentication, and is never sufficient to establish capture completeness.

| Attribute | Type / presence | Scope and mapping |
|---|---|---|
| `agent_harness.source.record.identity` | `native_span`, `producer_record` or `unavailable`; new normalizers emit it | Omission in an older v0 record means unavailable, never an inferred key |
| `agent_harness.source.namespace` | Opaque string; needed for either keyed mode | Stable namespace for the originating producer domain; preserved across re-exports and imports, distinct across unrelated producers |
| `agent_harness.source.instance.id` | Opaque string; needed for `producer_record` | Identifies the original producer lifetime, not the importer, collector, OS PID or conversation |
| `agent_harness.source.record.id` | Opaque string; needed for `producer_record` | Original event identity, unique within that instance and across its event streams |
| `agent_harness.normalization.profile` | Opaque string; needed for qualified deduplication | Origin normalization profile covering mapping plus privacy revision; compared as observation metadata, never part of the source key |

These identity strings and source name are case-sensitive, nonempty ASCII tokens,
1 to 128 characters, matching `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`. This syntax is
not secret detection. Producers must supply safe opaque IDs; omit an unsafe ID.
No paths, user/account names, credentials, body hashes or raw-content references
are acceptable identity fallbacks. A capture may assign an opaque producer token
once at the actual instrumented boundary and preserve it with every export; a
reader must never mint a new per-import token to repair missing source identity.

Use exact tuples, not ambiguous delimiter concatenation:

| Mode | Source key | Applicability |
|---|---|---|
| `native_span` | `(source.name, source.namespace, "span", "native_span", trace_id, span_id)` | Only completed native spans with genuine valid trace/span IDs |
| `producer_record` | `(source.name, source.namespace, "event", "producer_record", source.instance.id, source.record.id)` | Only events with established producer lifetime and original event identity |
| `unavailable` or an absent key component | No key | Retain the safe observation, report unavailable identity; never deduplicate by payload equality |

The dotted names in tuples abbreviate the full `agent_harness.*` attribute names.
A span's optional instance metadata is not part of its native key. Do not apply a
span key to its events: several different events may share a span and timestamp.
A source restart must change the producer instance before a sequence can reset.
For Claude log events, a qualified mapping may encode a native sequence as
`event:<decimal-sequence>` only with a proven lifetime scope; other independently
numbered streams need distinct prefixes. If no source lifetime can be established,
the result is unavailable. Session IDs, provider request IDs and tool-call IDs do
not repair that gap. The [Claude mapping](adapters/CLAUDE_CODE.md) documents how a
future adapter must supply these fields; it does not establish native support for
an original lifetime token or claim the adapter is implemented.

The originating normalizer assigns `agent_harness.normalization.profile` to its
reviewed mapping and privacy rules, changing it whenever those rules change.
It must preserve that token on re-export; source application version and local
schema version are not substitutes. Readers never add their own profile to old
records. Missing profile information makes deduplication unqualified, reported
as unavailable identity for counting even when the other key fields are present.
Different supplied profiles under the same source key conflict even when every
other safe field is identical. The token itself does not authenticate its meaning.

Within one declared metadata profile, compare the entire accepted, content-off
normalized observation for a source key. Ignore JSON object-key order, not missing
fields, changed status, timings, usage, normalization differences or source
versions. Unsupported fields must be reported/refused before aggregation, not
silently stripped until contradictory observations look equal. Do not hash raw
records to manufacture identity. A later reader may use canonical safe-projection
bytes for equality, but that representation is not the source key or a receipt.

Identical representations of a keyed observation are repeat exports. If any two
representations under a key differ, mark the whole key group conflicting and
exclude every member from consistent-observation aggregation. Retain safe variants
for inspection when permitted; no last-writer, first-writer, success-wins, or
"fill in missing usage" merge. A mapping/privacy-version mismatch is an unresolved
representation conflict, not proof that the native operation itself was corrupt.
Different keys remain distinct even when their redacted payloads or call IDs match.

Report received rows, keyed groups, consistent groups, duplicate rows within
consistent groups, conflicting groups/rows and unavailable-identity rows
separately. A deduplicated observation total is unavailable when any row lacks a
key or any key conflicts; an empty capture does not establish complete coverage.
Even a fully keyed input proves only the supplied-record population, never the
number of tools/jobs, whole-run usage, billing, execution authenticity or readiness.
Missing identity never invalidates independently recorded deterministic checks.

Authored controls, **SYNTHETIC / NOT RUN**; labels below are aliases, not captures:

| Input variation | Expected interpretation |
|---|---|
| Same span S re-imported, same namespace/trace/span and safe fields | One consistent source group; one duplicate export row |
| Retry S2 has same tool-call ID but a different native span ID | Two source groups, not one delivered job |
| Event sequence 7 in instances A and B after restart | Distinct event keys; no collapse across sequence reset |
| Sequence 7 but no established original instance | Unavailable identity, even if session ID and OS PID are present |
| Same provider/session/trace/span IDs in producer namespaces A and B | Distinct source keys; namespaces must be preserved from origin |
| Two events on one span, same time, different original event IDs | Two event keys, not a duplicate span |
| Three rows for S: failure, success, failure | One conflicting key, all three rows excluded from consistent totals |
| Two identical redacted observations without original identity | Two unavailable rows; deduplicated total unknown, not one or zero |

The executable follow-through is separately scoped in
[#315](https://github.com/Chris0Jeky/agent-harness/issues/315). The
[offline identity inspector](IDENTITY_INSPECTOR.md) documents its accepted subset,
resource bounds, executed synthetic controls and native-qualification limitations.
It does not imply native capture or full v0 schema support.

### Checkpoint events

| Event | Safe payload / interpretation |
|---|---|
| `agent_harness.edit.applied` | Observed outcome and files-touched count when known; no diff or path list. A tool returning success is not proof the intended edit persisted |
| `agent_harness.verify.result` | Oracle/evidence references, `agent_harness.verify.result` from pass/fail/error/not_run, original exit code if observed, tested repo/revision and dirty-state observations; no claim of overall correctness |
| `agent_harness.request.attempt` | Request/attempt identity and attempt number when exposed, category/status and timing; no new logical inference count for each export |
| `agent_harness.quota.observed` | Provider, native unit/window, value, observation time and reset time if exposed; never inferred authoritative headroom |

A check that launches and reports failed assertions differs from a check that
cannot launch. Preserve `fail`, `error` and `not_run`; don't call every nonzero exit
a product defect. Associate each verifier observation with the original evidence
and tested scope. Dirty local work, an old head and a CI merge revision must not be
silently relabelled as the current PR head. Parent `OK`/`UNSET` never erases a failed
child; a recovered error remains in history.

## Privacy and content opt-in

**FACT:** OTel content guidance makes messages/instructions and tool arguments and
results non-default, sensitive fields. Native Claude content gates are useful
mapping references, not a portable privacy policy or a guarantee of redaction. [S2], [S6]

| Data class | Default / permitted treatment |
|---|---|
| User/model bodies, system instructions, tool I/O, source files, diffs | Off. Explicit field-scoped debugging opt-in may retain a filtered bounded subset |
| Commands, environment values, absolute paths, raw exceptions, arbitrary tool/agent names | Off. Prefer allowlisted categories; no automatic raw fallback |
| Credentials, auth headers, session access tokens, private keys, secret values | Never emit, including with content opt-in |
| Reasoning text | Not captured in v0; provider-supplied reasoning-token counts can be retained without text |
| Safe timing, operation/category, outcome, correlation and available usage | Retained with content off; omit unsafe identifiers rather than claim metadata cannot be sensitive |
| Content hashes and body/file references | Not a substitute for redaction; no raw-payload reference to auto-open, no secret hashing as anonymization |

Opt-in must identify the run, allowed fields, destination, policy version and
retention period before persistence. Never infer consent from another vendor
switch. Filter before serialization, console output or disk writes; truncation
alone is not redaction. A failed filter omits the affected field and emits a safe
category when possible, without blocking the coding task or a merge. Do not promise
perfect secret detection; omit classes that cannot be safely filtered.

Proposed local retention: bounded rotation and a 14-day maximum by default, with
any debugging exception explicit. Storage limits/rotation implementation need a
later reviewed slice; no deletion job or settings change is shipped here. Public
PRs contain synthetic examples only. Local records can still carry linkable IDs;
shipping them to a vendor is separate authorization, not implicit in local capture.

## Usage, clocks and quota burn

**FACT:** The reviewed registry defines input/output, cache and reasoning token
attributes. Cache counts are parts of input totals; reasoning is part of output.
The reviewed registry has no standard cost attribute. [S2], [S3]

| Observation | Field / units / interpretation |
|---|---|
| Input / output | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`: nonnegative integer tokens, source-defined billed counts where separately available |
| Cache read / write | `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_write.input_tokens`: input subsets, not extra tokens to add again |
| Reasoning | `gen_ai.usage.reasoning.output_tokens`: output subset, never inferred from text length |
| Latency | `duration_ms`; custom `agent_harness.latency.first_token_ms` only for actual TTFT; use `gen_ai.response.time_to_first_chunk` in seconds only for that precise source meaning |
| Retries / rate limits | `agent_harness.request.attempt_count`: observed integer, at least one for an attempted logical request; error category/HTTP status when available; unknown attempts remain unknown |
| Compaction | `gen_ai.conversation.compacted=true` only when reliably detected; absence is not proof it did not happen [S3] |
| Monetary estimate | `agent_harness.cost.amount` nonnegative finite decimal string, `.currency` explicit, `.basis` estimated or vendor_reported, `.source` and `.pricing_as_of` when estimated; optional observations, not invoices |
| Quota | `agent_harness.quota.value` finite nonnegative number, `.unit` and `.window` strings, `.observed_at` and `.reset_at` UTC timestamps when known; preserve provider scope and whether value means used or remaining via `.kind` |

Derive diagnostics from observed request/tool records, not a new metrics SDK:
cache-read/input ratio, calls per loop, retries/rate limits, model share, and tokens
per named deterministic oracle outcome. Unknown/zero denominators are undefined,
not zero efficiency. State included/excluded runs and observed versus expected
counts; absent source coverage is not a zero-cost run.

Count each usage observation once. Do not add native metrics, request events,
request spans and parent summaries together. A successful final attempt may omit
usage from failed attempts: report the partial observed total, not full spend.
Keep unsuccessful/abandoned loops visible. A repeated cheap check passing is not
another delivered job; #288/#296 owns logical-job outcomes and accounting.

Elapsed loop time is not the sum of parallel child durations. Separate observed
model work, tool execution, permission waits and verifier work; unknown clocks stay
unknown. TTFT, first chunk and first content are different clocks until a source
mapping establishes equivalence. Compare weekly burn only within explicit provider
quota windows. Token estimates do not establish subscription allowances or reset
headroom. Provider billing remains accounting; these costs are advisory diagnosis.

## Authored examples: SYNTHETIC / NOT RUN

These are structural sketches, not native captures or execution receipts. Labels
`A` to `G` and `R` to `V` are diagram aliases, not literal OTel IDs. Times are authored
relative milliseconds; all content is off. `null` parent means a known root here.
No real repository, PR, model response or oracle execution is claimed.

### One loop with explicit planning, edit and verification

| Span | Parent | Operation | Start..end ms | Status / observation |
|---|---|---|---|---|
| A | null | `invoke_agent example` | 0..900 | UNSET; orchestration ended |
| B | A | `plan example` | 0..200 | UNSET; explicit planning boundary |
| C | B | `chat example-model` | 10..190 | UNSET; plan-producing model call |
| D | A | `execute_tool read` | 210..260 | UNSET; call `call-read` |
| E | A | `execute_tool edit` | 270..300 | UNSET; call `call-edit`, phase edit |
| F | A | `execute_tool test` | 320..820 | UNSET; call `call-test`, phase verify |
| G | A | `chat example-model` | 830..890 | UNSET; final summary request |

E at 300: `agent_harness.edit.applied`, observed files touched 1.
F at 820: `agent_harness.verify.result`, authored result pass, oracle
`example-unit-check`, evidence `example-evidence`. Those invented example labels
must never be indexed as observed evidence. C's authored input 1000 includes cache
read 600 and cache write 100; output 200 includes reasoning 80. The total is 1200,
not 1980. G has unavailable usage (`not_exposed`), so a whole-loop total is unknown.

### Retry, failure and interrupted coverage

| Span | Parent | Operation | Start..end ms | Status / observation |
|---|---|---|---|---|
| R | null | `invoke_agent example` | 0..1300 | UNSET; no overall success assertion |
| S | R | `chat example-model` | 10..900 | UNSET after recovery; two observed request attempts |
| T | R | `execute_tool edit` | 910..950 | UNSET; observed edit outcome success |
| U | R | `execute_tool test` | 960..1200 | ERROR; known check failed, `error.type=assertion_failure` |

S at 200: attempt 1 rate limited; S at 900: attempt 2 completed. Failed-attempt
usage is unknown; the final response's usage cannot establish total retry spend.
U at 1200: verify event records fail with its original evidence identity. An
interrupted later tool V has only a start observation at 1210 and no measured end;
retain it as a safe event/gap, not an invented successful completed span. R ending
UNSET neither clears U nor proves V completed. Missing capture remains advisory;
the original deterministic verifier result is handled independently by existing policy.

## Scout reconciliation and optional adapters

The accessible [scout summary on #303](https://github.com/Chris0Jeky/agent-harness/issues/303#issuecomment-5798215571)
was compared; the original box-local `OBSERVABILITY.md` was not available here.
This document clarifies arrows as order rather than mandatory nesting, estate
verification as a tool phase rather than a new GenAI operation, and vendor content
switches as mappings rather than canonical privacy rules. Compare the full scout
locally before claiming its entire contents reconciled.

**INFER:** Document Claude Code native mapping first because its first-party guide
exposes concrete coding-loop boundaries. Native schemas still need normalization,
not blind copying. The separate mapping deliverable is tracked in
[#312](https://github.com/Chris0Jeky/agent-harness/issues/312). Muse, OpenCode and
Codex-class adapters remain targets, not claimed qualified integrations. No
all-agent feature parity is assumed.

Langfuse/LangSmith/Phoenix/OpenInference may be later projections; Helicone-class
gateways can enrich model-plane observations. No backend is selected in v0.
**OVERSOLD:** treating generic OTel ingestion, coding-agent-assisted setup, a vendor
score, or a session tree as proof of complete uninstrumented local edit/verify
coverage. Require concrete source-to-field mapping and loss accounting instead.

## Landing plan and continuation

The table and first-week handoff below describe the initial docs-only wave,
completed through #310/#313. The owner's subsequent implementation request is
tracked separately in #315, following the #314 identity amendment above; it does
not authorize native telemetry activation or turn earlier examples into captures.

| Rank | Slice | Done when |
|---|---|---|
| P0 | This #303 contract plus README link | Source-checked definitions, privacy/cost baseline and both NOT RUN examples reviewed; docs-only diff |
| P1 | Separate Claude native mapping note, #312 | Native field/unit/availability and loss tables distinguish tool counts, request IDs and token totals; no native qualification claim |
| P1 | Future bounded local qualification proposal | Human names safe synthetic task, runtime/version, capture route and comparison oracle; no runtime work is authorized by this table alone |
| P2 | Later adapter implementation | Separately reviewed existing-harness seam and failure-isolation tests; no merge-gating telemetry or new accounting system |
| P2 | Packaging under #302 | Canonical contract is settled; instructions link here, no second skill-policy home |

First week: day 1 reconcile sources and core contract; day 2 review the two sketches;
day 3 review privacy/unknown accounting; day 4 land native mapping documentation;
day 5 reconcile issue checklists and record the next bounded proposal. This week
produces docs PRs only, no SDK dependency or CI workflow change.

Local-agent handoff (difficulty M): inspect live main and #299/#303; revise this
contract and the README link on `docs/303-agent-loop-spans`, keeping scope to the
listed documentation. Review source semantics, examples, privacy and ownership,
record actual checks and NOT RUN layers, and publish a draft while writing. Do not
stack on or repair Verify reds in #295/#296/#298: they are not prerequisites for
these docs. This PR's own applicable checks and existing review policy still apply.
No `opentelemetry-sdk`, CI changes, collector, SCITT/signing, UX #281 work, native
activation, product PRs or skill packaging. Completion means reviewed documentation,
not implemented observability or a qualified coding agent.

## Dated primary sources

OTel references below are pinned to source revision
`8ffdf568e1b4391a99adb081db16e8102e36918e` (2026-09-22 commit), inspected 2026-09-23.
S6 is a living first-party page inspected 2026-09-23; recheck feature/version claims
before native qualification. The research input was the completed
“v0 Observability Model for Coding-Agent Loops” brief dated 2026-09-23. Source review
supports design choices; it is not a workstation experiment.

| Ref | Source | Claim boundary |
|---|---|---|
| [S1] | GenAI agent/framework spans | Development operation and planning relationships |
| [S2] | GenAI client/tool spans | Logical inference, tools and content guidance |
| [S3] | GenAI attribute registry | Correlation, token subsets, compaction; no standard cost field at reviewed revision |
| [S4] | GenAI metrics | Development latency/usage vocabulary, not a required SDK |
| [S5] | GenAI events | Development optional content event; not the required local envelope |
| [S6] | Claude Code monitoring | Documented native surfaces, not proof they exist in an installed version/configuration |

[S1]: https://github.com/open-telemetry/semantic-conventions-genai/blob/8ffdf568e1b4391a99adb081db16e8102e36918e/docs/gen-ai/gen-ai-agent-spans.md
[S2]: https://github.com/open-telemetry/semantic-conventions-genai/blob/8ffdf568e1b4391a99adb081db16e8102e36918e/docs/gen-ai/gen-ai-spans.md
[S3]: https://github.com/open-telemetry/semantic-conventions-genai/blob/8ffdf568e1b4391a99adb081db16e8102e36918e/docs/registry/attributes/gen-ai.md
[S4]: https://github.com/open-telemetry/semantic-conventions-genai/blob/8ffdf568e1b4391a99adb081db16e8102e36918e/docs/gen-ai/gen-ai-metrics.md
[S5]: https://github.com/open-telemetry/semantic-conventions-genai/blob/8ffdf568e1b4391a99adb081db16e8102e36918e/docs/gen-ai/gen-ai-events.md
[S6]: https://code.claude.com/docs/en/monitoring-usage
