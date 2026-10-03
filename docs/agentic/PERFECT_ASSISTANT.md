# Perfect autonomous agentic assistant — estate synthesis

Status: proposed documentation, 2026-10-01.
Parent: [#299](https://github.com/Chris0Jeky/agent-harness/issues/299).
Research pack: private handoff notes (not published).
Sister (do not merge tracks): [#281](https://github.com/Chris0Jeky/agent-harness/issues/281) product UX observe→judge.

This note synthesizes best-of-breed harness patterns onto the owner’s estate.
It does **not** invent runners, collectors, CI jobs, or LLM merge gates.
The mappings below are proposed or inherited contracts, not receipts of native
implementation. Research-source acceptance and native qualification remain separate.

## Hard rule

| May receive automated merge authority | Stays advisory forever |
| --- | --- |
| Applicable, repo-owned **deterministic oracles** (see [MERGE_BOUNDARY](../evals/MERGE_BOUNDARY.md)) | LLM judgment, review-bot scores/approvals, telemetry health, vendor catch-rates, control-plane coverage evidence (`gate_eligible: false`) |

**Reject:** LGTM theater · flaky LLM-as-merge-CI · auto-merge on vendor scores.

## What “perfect” means here

A strong autonomous agentic assistant for this estate is a **system**, not a single model:

1. **Harness loop** — plan → tool use → observe ground truth → verify → retry under budget → stop or escalate.
2. **Independent deterministic proof** before merge (tests, contracts, host prove, exact-head checks).
3. **Advisory judges** for flood triage and (separately) UX feel under #281.
4. **Metadata-first observability** (OTel-shaped; content opt-in) that never becomes a gate.
5. **Draft-first human gates** for irreversible, secret, billing, and App actions.
6. **Durable memory** of decisions, conventions, fingerprints, and outcomes — not raw transcripts by default.

Primary pattern sources (access 2026-10-01): Anthropic [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents); Claude Code [verification loops](https://claude.com/blog/building-verification-loops-in-claude-code-with-skills) / [monitoring](https://code.claude.com/docs/en/monitoring-usage); OpenAI Agents [running agents](https://openai.github.io/openai-agents-python/running_agents/) / [guardrails](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals); Harbor Oracle/Nop [TASK_REVIEW_AUTOMATION](https://github.com/harbor-framework/frontier-bench/blob/main/docs/TASK_REVIEW_AUTOMATION.md).

## Loop contract (map to estate)

```
intent → tools (ACI) → env feedback → verify (deterministic preferred)
       → retry ≤ budget → stop | escalate human/estop
       → publish + proof → the merge gate (model-free) merge
```

| Loop step | Estate owner | Gate? |
| --- | --- | --- |
| Tool use / scrub / deny floor | agent-harness templates + scrubber | Policy floor, not product correctness |
| Host prove / Verify smoke | delegate-runtime prove · harness Verify | Deterministic when required |
| Review under flood | [REVIEW_UNDER_FLOOD](../evals/REVIEW_UNDER_FLOOD.md) · #301 | Advisory bots; severity bar |
| Merge authority | the merge gate (configuration repository) · branch protection | Model-free checks only |
| UX observe→judge | #281 | Advisory → issues; only a repo-owned deterministic Playwright check (Plane B) could gate later, never a judge verdict |
| Spans / cost / tool ids | [AGENT_LOOP_SPANS](../observability/AGENT_LOOP_SPANS.md) · #320 | Advisory only |

## Oracle vs judge (compact)

- **Oracle:** same inputs → same pass/fail without an LLM. Harbor requires Oracle≈1.0 and Nop≈0.0 before agent trials — use as a *design* pattern for flood samples, not as invented task-board membership.
- **Judge:** LLM or bot opinion. Useful for triage; **never a required merge condition**, alone or combined with deterministic checks. Its approval, completion, availability or score must not become an indirect gate through an aggregate status.
- Full contract: [MERGE_BOUNDARY](../evals/MERGE_BOUNDARY.md). Taxonomy: [TAXONOMY](../evals/TAXONOMY.md).

## Memory — session vs durable

| Persist (durable) | Do not persist by default |
| --- | --- |
| Campaign/decision inbox answers | Raw user prompts / assistant text |
| Outcome ledger fingerprints + matured outcomes | Tool I/O bodies / raw API JSON |
| CLAUDE.md / skills / conventions | Unredacted MCP payloads |
| Estop / tier / merge-gate exceptions (human-owned) | Hobby SaaS transcript dumps |

Session resume (JSONL) is continuity, not learning. Cross-session learning lands in ledger/journal/decisions after provenance rules.

## MCP / tool reliability (ACI)

1. Tool failures must be **model-visible** (tool error / `isError`), not silent protocol crashes.
2. Timeouts on every external call; capped retries with backoff; circuit-break after repeated failure.
3. Namespaces, pagination, truncation, absolute paths — treat tool docs as seriously as prompts.
4. Content-bearing tool args/results stay **opt-in** in telemetry (`OTEL_LOG_TOOL_*` off for #320).

## Human gates / draft-first

Irreversible sends, secrets, billing, Apps, and merge exceptions stay human-owned (draft → inbox card → explicit approve). Assistant-gateway and console pilot controls do **not** merge or deploy. The merge-gate human-exceptions list starts empty.

## Observability posture

OTel-shaped spans for `invoke_agent` → `chat`/`llm_request` → `execute_tool` → verify, with `gen_ai.tool.call.id` correlation. Prefer metadata-first / content-off. Native qualification of one capture route is [#320](https://github.com/Chris0Jeky/agent-harness/issues/320) — offline inspector success ≠ native field proof.

## Explicit non-goals

- Second harness or framework rewrite (LangGraph/Crew/OpenHands as references only).
- LLM merge CI, vendor auto-merge, LGTM theater.
- Absorbing #281 product UX scoring into this document’s authority.
- Collector / SCITT / paid hobby tiers as prerequisites.
- Cloud agents as default land path (local-agent preferred; cloud exception-only).

## Related

- Additives table: [ARCHITECTURE_ADDITIVES](./ARCHITECTURE_ADDITIVES.md)
- Research pack, delegate-runtime swarm notes, and prior eval/observability notes: private handoff material, not published.
