# Architecture additives — perfect assistant → estate owners

Status: proposed documentation, 2026-10-01.
Parent: [#299](https://github.com/Chris0Jeky/agent-harness/issues/299).
Companion: [PERFECT_ASSISTANT](./PERFECT_ASSISTANT.md).

Thin map only. Prefer extending existing docs/issues; do not fork tracks.

| Pattern (external) | Estate additive | Home | Issue | Status |
| --- | --- | --- | --- | --- |
| Tool-use loop + verify + budget | Document loop contract; keep delegate-runtime L1 | `docs/agentic/PERFECT_ASSISTANT.md` | #299 | This PR |
| Deterministic Oracle/Nop solvability | Cite for flood sample design | `docs/evals/REVIEW_UNDER_FLOOD.md` | #301 | Schema landed; sample open |
| FAIL_TO_PASS ∩ PASS_TO_PASS | Eval bakeoffs / Bug Hunt sister | `docs/evals/TAXONOMY.md` | #325 sister | Cross-link |
| Merge boundary lock | Reuse the existing proposal | `docs/evals/MERGE_BOUNDARY.md` | #304 | Landed proposal; gate adoption separate |
| Metadata-first OTel spans | Adapter + native trial | `docs/observability/*` | #320 | Docs landed; native NOT RUN |
| Review bots advisory | Severity bar + packet | `docs/evals/REVIEW_UNDER_FLOOD.md` | #301 | Landed schema |
| Session vs durable memory | Persist ledger/decisions only | delegate-runtime journal · harness ledger | runtime journal issue / harness ledger PRs | Cite |
| MCP isError + timeouts | Reliability checklist (docs) | this folder · later skill | #299 / configuration-repository skill issue later | Docs now; skill park |
| Human interrupt / approve | Draft-first · decision@2 · estop | the console · the merge gate | console round 4 · control-plane issue | Cite delegate-runtime pack |
| Coverage without gate | `gate_eligible: false` | control-plane evidence | coverage-evidence issue (closed) | Boundary cite |
| UX observe→judge | Separate epic | `docs/ux-evaluation/` | **#281** | Cross-link only |
| Design-grade playbooks | Separate control-plane epic | control-plane playbooks | **control-plane playbooks issue** | Cross-link only |

## Sequencing

1. Land this docs pair (draft → human review → merge when ready).
2. Run #320 content-off native trial on workstation.
3. Finish #301 READY sample via #307 curation.
4. Close #300 only after the ORACLES/PATTERNS agreement comment.
5. Defer configuration-repository skill packaging until SoT docs stable ([HARNESS_EXTENSION](../evals/HARNESS_EXTENSION.md)).

## Non-goals

No CI changes · no opentelemetry-sdk · no second harness · no LLM merge gate · no #281 product work in this PR.
