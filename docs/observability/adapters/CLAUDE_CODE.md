# Claude Code to agent-loop v0: mapping note

Status: proposed adapter design, 2026-09-23. Native qualification and adapter
execution: **NOT RUN**. This file implements documentation only.
Parent [#299](https://github.com/Chris0Jeky/agent-harness/issues/299), relates
[#303](https://github.com/Chris0Jeky/agent-harness/issues/303), tracked by
[#312](https://github.com/Chris0Jeky/agent-harness/issues/312).
Canonical contract: [AGENT_LOOP_SPANS.md](../AGENT_LOOP_SPANS.md).

**Telemetry ≠ merge gate.** No mapping, missing span, failed exporter, cost estimate
or LLM/vendor score changes merge eligibility. This note adds no mandatory review
process. Existing deterministic oracles retain their independent meaning.

Classification/date convention: FACT describes first-party documentation inspected
2026-09-23; every proposed mapping, control, example and unmarked recommendation is
INFER dated 2026-09-23. OVERSOLD marks an interpretation rejected as proof.

## Source boundary

**FACT:** The monitoring guide documents beta tracing, a hierarchy containing
interaction/model/tool spans with permission and execution children, and tool-call
correlation. It documents non-interactive inbound trace context and deferred tools
rejoining earlier turn traces. Some surrounding spans stay UNSET despite child
errors. These are documented capabilities, not measurements of this workstation. [C1]

Only map a source family whose version/configuration has been identified. Record
`agent_harness.source.name=claude_code` and the observed application version. Missing
version means version-sensitive fields remain unqualified, not that the newest
documented behavior applies. A missing plan or execution child can be a visibility
gap, denied operation or version difference; do not fabricate a successful span.

## Native boundary to canonical record

The left column names documented native records [C1]. The remaining columns are
proposed adapter decisions, not upstream requirements. Safe names still pass a
harness-owned allowlist; unknown native text never passes through by default.

| Native record | Proposed representation | Units, availability and loss |
|---|---|---|
| `claude_code.interaction` | `invoke_agent claude_code`; retain native IDs and actual parent | Native interval and `interaction.duration_ms`; do not force an upstream child to root |
| `claude_code.llm_request` | One logical inference span; operation only when API semantics are known | `duration_ms` includes retries; retain observed status, not a vendor quality verdict |
| `claude_code.tool` | One `execute_tool` span per native tool invocation | Wrapper duration includes wait/execution; choose this as the tool-invocation counting surface |
| `claude_code.tool.execution` | Auxiliary `agent_harness.tool.execution` INTERNAL span | Execution duration/outcome only; not another `execute_tool` count |
| `claude_code.tool.blocked_on_user` | Auxiliary `agent_harness.tool.permission_wait` INTERNAL span | Wait milliseconds and safe accept/reject category; no permission-policy change |
| `gen_ai.request.attempt` native span event | `agent_harness.request.attempt` event on the logical inference | Preserve source attempt identity; do not claim the native event name is a standard GenAI event |
| `claude_code.subagent_completed` | `agent_harness.subagent.completed` event | Keep completion observation; no fabricated start interval or extra cumulative usage |
| Native subagent model/tool children | Retain actual parentage under launching tool | Do not invent `invoke_agent` or `plan` intervals solely to match a prettier tree |
| Tool-result/API-request log events | Correlated auxiliary observations, or explicit events-only mode | Not additional requests/tools beside equivalent spans; do not reconstruct unknown intervals |
| Hook records | Safe category observations only where present | Not required; detailed native features are not activated by this document |

Auxiliary span names are local extensions, not GenAI operation values. Omit
`gen_ai.operation.name` on auxiliary timing spans. An events-only source remains
an events-only observation set; do not mix its invocation counts with a spans-mode
set without proving event-to-span equivalence.

### Identity, errors and model fields

**FACT:** Claude's table assigns native `gen_ai.response.id` the same request-header
value as `request_id`. OTel defines its attribute as a completion identifier. This
is a documentation-level semantic conflict, not a measured runtime bug. [C1], [O1]

**Recommendation:** copy the safe transport ID into the adapter extension
`agent_harness.provider.request.id`, not canonical `gen_ai.response.id`. Leave the
latter unavailable unless an actual completion ID is independently exposed through
an approved content-off source. Never enable raw API bodies to satisfy the field.

| Native field | Proposed destination / interpretation | Missing or unsafe treatment |
|---|---|---|
| `session.id` | `gen_ai.conversation.id`, genuine safe session identity | Omit; do not replace with trace ID, run ID or UUID |
| `tool_use_id` / `gen_ai.tool.call.id` | Canonical tool-call ID within producer/session scope | Conflict between both values is `invalid`, not an arbitrary winner |
| `request_id`, native `gen_ai.response.id` | `agent_harness.provider.request.id`, string | See conflict above; disagreements stay diagnostic |
| `client_request_id` | `agent_harness.provider.client_request.id`, final attempt | Earlier attempt IDs belong on their own observations |
| `model`, `gen_ai.request.model` | Requested model, after agreement/semantic checks | Actual response model stays unavailable unless independently observed |
| `gen_ai.system` | Candidate mapping to `gen_ai.provider.name` | Legacy name alone does not prove a custom proxy's upstream; record uncertainty |
| `tool_name_safe`, `query_source_safe` | Allowlisted tool/source categories | No automatic raw `tool_name` or `query_source` fallback |
| `error_class` | Allowlisted `error.type` on a known error | `_OTHER` for known failure of unknown class; discard free-form `error` |
| `success`, native span status | Separate source outcome and status | An UNSET wrapper never upgrades a failed execution child |
| `agent_id`, `parent_agent_id` | Safe optional native agent identity extensions | Not a second conversation or proof of a captured subagent invocation |
| `interaction.sequence`, `event.sequence` | Source ordering within a process instance | Never a global session sequence or standalone dedup key |

Do not derive repository/PR/tested revision or a deterministic verifier verdict
from model text. Bind those through the existing harness/evidence context when
available. A tool named Bash or test succeeding does not establish what property
was checked; verification-phase tagging requires an identified named check.

## Token and clock normalization

**FACT:** Anthropic Messages API input is split into uncached input, cache read and
cache creation; its total is their sum. [C2] Claude's completion-event token field
is a final-request footprint, not cumulative subagent usage. [C1]

Only apply the following arithmetic after confirming that the native usage fields
retain the documented API definitions. Components must refer to the same request,
be finite nonnegative integers, and be present or explicitly documented as zero.

| Native observation | Proposed normalized field / rule |
|---|---|
| `input_tokens` + `cache_read_tokens` + `cache_creation_tokens` | `gen_ai.usage.input_tokens`; all three source components are needed for this mapping |
| `cache_read_tokens` | `gen_ai.usage.cache_read.input_tokens`, a subset of normalized input |
| `cache_creation_tokens` | `gen_ai.usage.cache_write.input_tokens`, a subset of normalized input |
| `output_tokens` | `gen_ai.usage.output_tokens`; do not synthesize a reasoning breakdown |
| `result_tokens` on tools | Optional tool-output-size diagnostic, never provider input/output billing |
| `attempt` | `agent_harness.request.attempt_count`; not a token multiplier |
| `ttft_ms` | `agent_harness.latency.first_token_ms`, if valid |
| `first_content_ms` | Adapter extension `agent_harness.latency.first_content_ms`; not TTFT or first chunk |
| Native cost counters/events | Advisory observation with basis/source/currency; only attribute to a loop with an explicit join |
| Cumulative/delta metrics | A separate observation population, never added to equivalent spans/events |

A canonical input total already includes cache subsets: do not apply the native
addition rule a second time to normalized data. Record missing components as
unavailable; no guessing from prompt length. Failed-attempt usage may be unexposed,
so available usage is only an observed subtotal. Do not multiply final usage by
attempt count or treat a final-request footprint as total cost.

Tool-invocation count, execution-attempt count and delivered-job count are distinct.
Deduplicate identical span exports by native trace/span identity and source; scope
log identities to a known producer/process instance and sequence. Different native
span IDs with one tool-call ID remain distinct invocation/execution observations
unless a version-specific rule proves retransmission. Preserve deferral/resume
causality. If identity is ambiguous, mark counts unknown rather than drop real work.
Original job/acceptance denominators remain in #288/#296, not this adapter.

## Version and content checks, not installation instructions

**FACT:** The guide dates safe-name/error-class/first-content fields to v2.1.268,
effort to v2.1.274, and the assistant-response switch to v2.1.193. Unset assistant
capture can inherit prompt capture. Its content limit is UTF-16 code units. [C1]

| Source/configuration to inspect later | Adapter rule |
|---|---|
| `app.version`; feature availability | Qualify each field, not the whole agent from a version string |
| `CLAUDE_CODE_ENABLE_TELEMETRY`, `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA`, `OTEL_TRACES_EXPORTER` | Record enabled capability without changing it; console support is not proof of JSONL output |
| `OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_ASSISTANT_RESPONSES` | Verify both off for content-off runs; don't rely on unset implying independent consent |
| `OTEL_LOG_TOOL_DETAILS`, `OTEL_LOG_TOOL_CONTENT` | Keep off; absent content events cannot be interpreted as failed tool calls |
| `OTEL_LOG_RAW_API_BODIES`, `OTEL_LOG_MANAGED_SETTINGS` | Exclude bodies, body references, settings and pre-redaction hashes from v0 inputs/outputs |
| `CLAUDE_CODE_OTEL_CONTENT_MAX_LENGTH` | Truncation is not redaction or a UTF-8 byte bound |
| `ENABLE_BETA_TRACING_DETAILED`, `BETA_TRACING_ENDPOINT` | Exclude detailed-mode setup from this slice; don't enable a new endpoint to obtain hook detail |
| Native user/account/repository attributes | Drop unless explicitly safe and needed; do not dump the native resource object |

The core contract's never-secrets rule applies even after opt-in. Filter before
persistence or console output; don't capture first and scrub later. Raw source
retention and remote export are separate decisions, not enabled by this mapping.
Unsupported source shapes should produce bounded safe diagnostics, never a raw
payload/error fallback, a coding-operation failure or a merge veto.

## Synthetic mapping controls: NOT RUN

These are authored expected outcomes, not empirical integration results.

| Control | Expected interpretation |
|---|---|
| Native uncached input 300, cache read 600, cache creation 100, output 200 | Canonical input 1000, output 200, total 1200; cache subsets not added again |
| Same observation but cache creation absent and no zero-default contract | Input total unknown, available components retained; not 900 |
| Two attempt events, only final usage 1200 | One logical inference, two observed attempts, total retry spend unknown; not 2400 |
| One wrapper W, permission child P, execution child X, result event E, same call ID | One tool invocation, one execution attempt, one separate wait; not four tool calls |
| Another export of W with same trace/span ID | Duplicate export, no additional invocation |
| New native wrapper W2 for resumed call, same tool-call ID | Another observed invocation, not dropped as a duplicate; logical requested-call association retained |
| Wrapper UNSET, execution ERROR | Failed execution remains visible; no overall success inference |
| Only request-header ID available | Custom transport ID populated, canonical completion ID unavailable |
| Completion event final-request footprint 1200 plus request spans | Do not add 1200 again or claim it totals the subagent run |
| User-selected tool name or unsafe error text without a safe category | Omit/category fallback and gap reason, no raw content |
| Interrupted native record / unsupported beta field | Partial event or unavailable observation, never a fabricated completed span |

## Next bounded work and done-when

Documentation is complete when these tables, the core contract link and controls
receive source/semantic review. A later local qualification proposal should name
one safe synthetic coding task, actual agent version and configuration, input
capture format, content-off destination, and independent named verifier. Compare
known native IDs/timing/usage manually against the proposed mapping; include one
failed or denied tool and one unavailable signal. Do not manufacture a live 429 or
spend a quota to test retry arithmetic. Publish only sanitized/synthetic results.

The next implementation, if separately approved, is a small adapter within the
existing harness, not a new runner. It must prove malformed/partial/duplicate input
handling and privacy/failure isolation without touching CI policy. Only after a
real bounded trial should [BENCHMARKS](../../BENCHMARKS.md) acquire a measured row.
Keep later skill packaging under #302. No collector, SCITT, opentelemetry-sdk,
workflow changes, SDK install, native activation or UX #281 work belongs here.
Verify reds on #295/#296/#298 are not prerequisites for this documentation; its own
applicable existing checks still apply.

**OVERSOLD:** documented tracing or a successful dashboard import proves complete
coding-loop coverage, correct code, an accurate subscription allowance or merge
readiness. Native qualification remains NOT RUN even after this docs PR merges.

## Sources

All accessed 2026-09-23; C1/C2 are living first-party pages, not installed-version
proof. O1/O2 are pinned to upstream revision `8ffdf568e1b4391a99adb081db16e8102e36918e`.

- [C1] Claude Code monitoring: native field names, hierarchy, status and content gates.
- [C2] Anthropic prompt caching: the API input-component accounting used conditionally above.
- [O1] OTel GenAI registry: completion-ID and token definitions.
- [O2] OTel client/tool spans: logical inference and tool semantics.

[C1]: https://code.claude.com/docs/en/monitoring-usage
[C2]: https://platform.claude.com/docs/en/build-with-claude/prompt-caching#tracking-cache-performance
[O1]: https://github.com/open-telemetry/semantic-conventions-genai/blob/8ffdf568e1b4391a99adb081db16e8102e36918e/docs/registry/attributes/gen-ai.md
[O2]: https://github.com/open-telemetry/semantic-conventions-genai/blob/8ffdf568e1b4391a99adb081db16e8102e36918e/docs/gen-ai/gen-ai-spans.md
