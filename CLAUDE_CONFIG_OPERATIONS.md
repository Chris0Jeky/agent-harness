Purpose: Authoritative operating contract for high-autonomy agent work in the private `claude-config` repository.
Status: ACTIVE; the owner lifted maintenance-only mode and approved immediate,
dependency-ordered work under named task contracts.
Authority relationship: This document wins for private `claude-config` operations,
cross-repository autonomy, failure-ledger, promotion-review, and private/public-boundary policy.
`AGENT_HARNESS_AGENT_BRIEF.md` wins for the current `agent-harness` workbench mission; this file
cannot defer that repository's Doctor, estate, adapter, measurement, or bounded-guard roadmap.
Last-reviewed date: 2026-07-30
Owner: Cristian Tcaci

# Decision register

- **DECISION CC-001:** The owner lifted maintenance-only mode and removed its calendar end date.
  An otherwise authorised task may start immediately in dependency order.
- **DECISION CC-002:** The former replay launch programme recorded **24 focused hours** across
  replay extraction and a possible public repository. That is historical accounting, not a cap on
  the wider `agent-harness` workbench or a separate allowance for this repository.
- **OPEN CC-003:** Confirm the repository's currently supported Python versions and existing test/lint entry points. Until confirmed, agents must not install or replace tooling merely to satisfy the proposed quality-gate interface.
- **DECISION CC-004:** The owner placed this canonical policy document at the root of the currently public `agent-harness` repository in commit `6d6e22e`. The policy prose is public, but the document remains excluded from the replay-v0 extraction allowlist and does not authorize exporting private Claude-config data.
- **OPEN CC-005:** Confirm whether the existing Gardener already has a kill switch. If it does, preserve the existing mechanism and record it in `policy/catalog.yaml`; do not add a second switch.

# Authority and classification rules

- **DECISION:** This file is the sole authoritative home for the owner's cross-repository agent-autonomy classes, mandatory-review classes, `HUMAN_TODO.md` routing, failure-ledger schema, manual promotion-review procedure, and private/public allowlist principle.
- **CONSTRAINT:** `AGENT_HARNESS_OPERATIONS.md`, `REPLAY_TOOL_PRODUCT.md`, and `BLUEPRINT_PLUGIN_PRODUCT.md` must link to the relevant section here rather than restating these policies.
- **CONSTRAINT:** Earlier strategic repositioning, technical design, learning-system blueprint,
  and research documents are background evidence only. `AGENT_HARNESS_AGENT_BRIEF.md` is not in
  that class: it is the active repository mission for `agent-harness`.
- **CONSTRAINT:** Every new policy statement must have exactly one canonical source path and one `policy/catalog.yaml` entry. Summaries elsewhere must link to that source and may not paraphrase the rule as a second normative statement.

# Active operating mode

- **DECISION:** `claude-config` is no longer in maintenance-only mode. Tasks whose own authority,
  dependencies, and stop conditions are satisfied may start immediately.
- **CONSTRAINT:** Removing the date gate does not waive budgets, review requirements, repository
  authority, private/public boundaries, or a task's named evidence and owner-approval triggers.
- **CONSTRAINT:** A private Claude-config promotion engine, scheduled Gardener, telemetry
  expansion, fictional estate, public plugin packaging, new agent platform, new policy compiler,
  speculative cross-runtime adapter framework, and automated skill creation remain unavailable
  until their own named trigger and explicit owner approval exist. This does not defer bounded,
  evidence-driven Doctor, estate, adapter, or measurement slices inside `agent-harness`.
- **CONSTRAINT:** An agent that discovers work without a satisfied task contract appends a backlog
  proposal to `HUMAN_TODO.md` with an evidence trigger; it does not infer authorisation.
- **DEFERRED:** Scheduled Gardener operation unlocks only after three useful manual cycles, no consecutive unmerged proposals, a tested kill switch, and explicit owner approval.
- **DEFERRED:** Telemetry expansion unlocks only when a named operational question cannot be answered from the minimal telemetry set and the owner approves the additional field before collection.
- **DEFERRED:** Public extraction work unlocks only under the preconditions in `BLUEPRINT_PLUGIN_PRODUCT.md`.

# Non-Goals

- **CONSTRAINT:** This private operations repository is not itself a public product.
- **CONSTRAINT:** This repository does not autonomously rewrite its own instructions, skills, hooks, policies, or memory.
- **CONSTRAINT:** This repository does not schedule recurring agent work until the named scheduling
  trigger and explicit owner approval are satisfied.
- **CONSTRAINT:** This repository does not collect prompts, source text, raw commands, credentials, private URLs, repository names, or transcripts as default telemetry.
- **CONSTRAINT:** This repository does not duplicate enforcement already provided by a sandbox, repository permission, protected branch, CI gate, or deployment environment.
- **CONSTRAINT:** A recurring failure is not evidence that a skill is the correct intervention.

# Information placement

## Canonical placement matrix

| Classification | **DECISION: canonical home** | **CONSTRAINT: placement test** |
|---|---|---|
| Always-relevant stable behaviour | `CLAUDE.md` or the repository's single global instruction file | It applies to nearly every task, is concise, and is not an enforcement claim. |
| Repository fact, build command, architecture seam | Repository instruction file or path-scoped instruction | It is factual, repository-specific, and can be verified locally. |
| Multi-step, judgement-bearing procedure | `skills/<skill-id>/SKILL.md` | It has a clear trigger, anti-trigger, stop condition, and repeated use evidence. |
| Deterministic lifecycle action | `hooks/` plus one catalogue entry | It must happen at a named event regardless of model judgement. |
| Volatile personal or project learning | `private/memory/` or the runtime's local memory | It may change without changing policy and is not required in every session. |
| Human approval, secret, account action, or subjective decision | `HUMAN_TODO.md` | An agent cannot truthfully complete it from repository state alone. |
| Machine-verifiable invariant | Tests, CI, sandbox, permissions, or server-side control | Failure must not depend on prompt adherence. |
| Failure or friction evidence | `private/ledger/failures.jsonl` | The record is redacted, append-only, and follows the schema below. |
| Public extraction eligibility | `extraction/allowlist.yaml` defined in `BLUEPRINT_PLUGIN_PRODUCT.md` | Default deny; every exported path is explicitly approved. |

- **CONSTRAINT:** Instructions may describe intent but must not claim to enforce a hard boundary.
- **CONSTRAINT:** Skills may not contain always-relevant global policy; they contain task-triggered procedure only.
- **CONSTRAINT:** Hooks may not become general interpreters. A hook must have one bounded event contract and a mechanically testable outcome.
- **CONSTRAINT:** Memory may not override canonical policy, quality gates, or owner decisions.
- **CONSTRAINT:** `HUMAN_TODO.md` is not a backlog for work an agent could safely complete; it is for genuinely human-only or owner-review work.

## Policy catalogue contract

- **DECISION:** `policy/catalog.yaml` is the index of policy ownership; it is not a second copy of policy prose.
- **CONSTRAINT:** Each catalogue entry uses this shape:

```yaml
schema_version: 1
policies:
  - id: cc.autonomy.owner-review
    canonical_path: CLAUDE_CONFIG_OPERATIONS.md#autonomy-boundary
    scope: cross-repository
    owner: Cristian Tcaci
    mechanism: operating-contract
    enforcement_layer: human-review
    status: active
```

- **CONSTRAINT:** `canonical_path` must resolve to one normative statement. The catalogue may not include the statement text.
- **CONSTRAINT:** Duplicate `id` values, two active entries for the same policy, or a missing canonical path fail the fast quality gate.

# Autonomy boundary

## Work agents may complete autonomously

- **DECISION:** Within an owner-approved task contract, agents may read repository files, create or edit files in the named paths, run non-destructive local commands, run existing tests and lint, append redacted failure records, create a local branch, create local commits, and draft a PR description.
- **CONSTRAINT:** Autonomous work must stay inside the task's explicit paths, acceptance criteria, time box, and out-of-scope list.
- **CONSTRAINT:** Agents may make the smallest repair required to make the named acceptance criteria pass. They may not opportunistically refactor adjacent systems.
- **CONSTRAINT:** Agents must stop after the acceptance command passes; additional cleanup becomes a backlog proposal.

## Work requiring owner review before execution or merge

- **CONSTRAINT:** Destructive operations, dependency additions or upgrades, public pushes, releases, tags, scope changes, licence edits, policy edits, CI permission changes, secret or credential handling, hook activation, scheduler activation, repository-history rewriting, and deletion or mass movement of files always require owner review.
- **CONSTRAINT:** A local commit containing any item above may be prepared only when the task explicitly requests a proposal; the action itself must not be executed before review.
- **CONSTRAINT:** Every policy change requires a PR that identifies the single canonical policy home and proves that no duplicate normative statement was added.

## Work routed to `HUMAN_TODO.md`

- **DECISION:** `HUMAN_TODO.md` stores actions requiring credentials, external accounts, public communication, legal/licence choice, subjective product judgement, inaccessible private context, or owner approval that cannot be represented as a normal code review.
- **CONSTRAINT:** Entries use this format:

```markdown
- [ ] HT-YYYYMMDD-NNN | blocking: yes|no | owner: Cristian | action: <one human action> | reason: <why an agent cannot complete it> | evidence: <file, issue, or command output>
```

- **CONSTRAINT:** Agents append or update evidence and mark an entry complete as soon as repository evidence proves every condition. An explicit owner decision may be recorded as that evidence in the same reviewed change. Agents must never infer a human decision, approval, acknowledgement, or subjective confirmation.

# Failure and friction ledger

- **DECISION:** The canonical local ledger path is `private/ledger/failures.jsonl` unless the repository already has one established path, in which case the existing path wins and is recorded in `policy/catalog.yaml`.
- **CONSTRAINT:** The ledger is append-only. Corrections are new records referencing the original `failure_id`.
- **CONSTRAINT:** The ledger is private and ignored by Git by default. Only redacted review summaries may be committed.
- **CONSTRAINT:** Every record follows this schema:

```json
{
  "schema_version": 1,
  "failure_id": "uuid",
  "recorded_at": "RFC3339 timestamp",
  "repo_id": "local alias or salted local hash",
  "component": "instruction|skill|hook|agent|tool|test|ci|environment|other",
  "operation_class": "short redacted operation family",
  "failure_class": "bug|environment|policy-friction|missing-information|human-decision|invalid-signal|unknown",
  "impact": "low|medium|high|critical",
  "summary": "redacted summary, maximum 240 characters",
  "recurrence_key": "stable redacted key",
  "evidence_ref": "relative local path, issue id, or command id",
  "status": "open|reviewed|closed",
  "privacy_review": "pending|passed|failed",
  "supersedes": null
}
```

- **CONSTRAINT:** No field may contain a prompt, source excerpt, raw command, credential, token, private URL, customer name, or absolute machine path.
- **CONSTRAINT:** A failure-recording error must not block the user's development task. The agent records the ledger failure in `HUMAN_TODO.md` and continues only when the primary task remains safe.

# Manual self-improvement loop

- **DECISION:** The loop is manual-first: capture -> redact -> review -> classify -> propose -> owner decision -> bounded change -> verify -> observe -> retain, revise, or remove.
- **CONSTRAINT:** No agent may automatically create, install, enable, schedule, or merge a skill, hook, instruction, agent, rule, or policy from ledger data.
- **CONSTRAINT:** Recurrence count alone does not select an intervention. Impact, root cause, preventability, context cost, maintenance cost, and the existence of a stronger deterministic layer must be considered.
- **CONSTRAINT:** Every promotion candidate uses `private/reviews/promotion/PROMOTION-<candidate-id>.md` with this template:

```markdown
# Promotion review: <candidate-id>

- Status: proposed | accepted | rejected | deferred | retired
- Owner decision: pending
- Recurrence keys:
- Observation count:
- Impact:
- Root-cause confidence: low | medium | high
- Redacted evidence references:
- Alternatives considered:
  - no action
  - bug fix and regression test
  - repository instruction
  - path-scoped instruction
  - hook or CI check
  - skill
  - agent
  - permission, sandbox, or policy boundary
  - product backlog issue
- Proposed artifact and why:
- Baseline behaviour:
- Mechanical acceptance criteria:
- Expected runtime or context cost:
- Rollback:
- Review date:
```

- **CONSTRAINT:** An accepted review authorises only the bounded change described in the review. It does not authorise adjacent platform work.
- **DEFERRED:** Automated clustering unlocks only when at least ten manual reviews show that deterministic recurrence keys are insufficient and the owner approves a privacy-preserving experiment.
- **DEFERRED:** Any automated promotion or self-installation remains prohibited unless a future operating document explicitly replaces this constraint after external evidence and owner approval.

# Gardener operating procedure

- **DECISION:** Until its separate scheduling trigger and owner approval are satisfied, the
  Gardener runs only as a manual, read-only report.
- **CONSTRAINT:** The canonical kill switch is the existing repository mechanism if one exists. Otherwise, use the sentinel file `private/control/GARDENER_DISABLED`.
- **CONSTRAINT:** When the kill switch exists, every Gardener entry point must exit without mutation and return exit code `78`.
- **CONSTRAINT:** A manual run may read the redacted ledger, skill-usage summaries, policy catalogue, and `HUMAN_TODO.md`; it may produce a report under `private/reports/gardener/`; it may not edit policy or implementation files.
- **CONSTRAINT:** The manual command contract is:

```bash
python tools/gardener.py report --read-only --output private/reports/gardener/latest.md
```

- **CONSTRAINT:** If the existing implementation uses another command, preserve it and document the exact command in `policy/catalog.yaml`; do not add a second entry point merely to match this example.
- **CONSTRAINT:** The Gardener must report missing inputs explicitly. An empty ledger is not reported as evidence of zero failures.
- **DEFERRED:** Proposal branches unlock after one useful read-only run and explicit owner approval.
- **DEFERRED:** Scheduling unlocks only after three useful manual cycles, no consecutive unmerged
  proposals, a tested kill switch, and explicit owner approval.

# Minimal telemetry

- **DECISION:** The minimal telemetry set is limited to operational counters needed to identify self-inflicted friction.
- **CONSTRAINT:** The local default path is `private/telemetry/session-summary.jsonl`, ignored by Git.
- **CONSTRAINT:** Each record contains only:

```json
{
  "schema_version": 1,
  "session_id_hash": "salted local hash",
  "recorded_at": "RFC3339 timestamp",
  "hook_latency_ms_p95": 0,
  "tool_failures": 0,
  "policy_interruptions": 0,
  "human_overrides": 0,
  "gardener_result": "not-run|no-op|report-produced|disabled|failed"
}
```

- **CONSTRAINT:** No prompts, source text, raw commands, paths, repository names, model reasoning, or credentials are collected.
- **CONSTRAINT:** Missing data remains missing; agents must not infer zero.
- **CONSTRAINT:** No telemetry field may be added without a named operational question and explicit
  owner approval. A request becomes a `HUMAN_TODO.md` proposal before collection.

# Private/public boundary

- **DECISION:** Public extraction is default-deny and allowlist-only.
- **CONSTRAINT:** The authoritative allowlist format and preconditions live only in `BLUEPRINT_PLUGIN_PRODUCT.md#extraction-allowlist-manifest`; this file does not redefine them.
- **CONSTRAINT:** Raw ledger data, telemetry, estate registry, machine paths, personal memory, private project facts, client information, credentials, transcripts, and Git history are never exported.
- **CONSTRAINT:** Public extraction uses a clean repository and copied allowlisted files; it does not publish or rewrite the private repository history.
- **CONSTRAINT:** Redaction is not treated as sufficient permission to export. A path must still appear in the approved allowlist.
- **DEFERRED:** No fictional estate or public plugin files may be produced before all preconditions in `BLUEPRINT_PLUGIN_PRODUCT.md` hold.

# Quality gates

- **OPEN:** Bind the commands below to the repository's existing tooling in Task 1. If the repository lacks the required tool, stop and request owner review before adding a dependency.
- **DECISION:** The stable quality-gate interface is:

```bash
python tools/repo_gate.py fast
python tools/repo_gate.py lint
python tools/repo_gate.py test
```

- **CONSTRAINT:** `fast` must complete in under 60 seconds on the owner's normal development machine and must validate operation-document structure, policy-catalog uniqueness, JSON/JSONL syntax for committed fixtures, and Gardener kill-switch behaviour.
- **CONSTRAINT:** `lint` must run existing repository linters and `git diff --check`; it must not auto-format files.
- **CONSTRAINT:** `test` must run the full existing non-destructive test suite.
- **CONSTRAINT:** Required CI checks before merge are `operations-contract`, `fast`, `lint`, `tests`, and `privacy-boundary`.
- **CONSTRAINT:** A CI check may not silently skip because an input is missing. It must fail or report `not-applicable` under an explicitly tested condition.

# Backlog-proposal format

- **DECISION:** Out-of-scope discoveries are recorded in `HUMAN_TODO.md` using this evidence-trigger extension:

```markdown
- [ ] HT-YYYYMMDD-NNN | blocking: no | owner: Cristian | action: Decide whether to unlock <proposal> | reason: Outside current scope | evidence: <references> | evidence trigger: <observable condition that would justify implementation>
```

- **CONSTRAINT:** The proposed implementation must not begin until the owner marks the item approved and points to a new or amended task contract.

# First 10 tasks

## Task 1 — Bind the repository quality-gate interface

- **Classification:** DECISION
- **Time box:** 1–2 hours
- **Objective:** Create or adapt `tools/repo_gate.py` as a thin, standard-library-first dispatcher to the repository's existing checks without adding dependencies.
- **Paths touched:** `tools/repo_gate.py`, existing test/lint configuration only when required, `HUMAN_TODO.md` if a dependency decision is needed.
- **Acceptance criteria:** `fast`, `lint`, and `test` subcommands exist; each prints the underlying commands; `fast` measures elapsed time; an unavailable existing tool produces a clear non-zero result rather than installing it.
- **Verify:** `python tools/repo_gate.py fast && python tools/repo_gate.py lint && python tools/repo_gate.py test`
- **Out of scope:** Replacing the test framework, adding Ruff/Pytest/Mypy, reformatting the repository, or changing CI permissions.
- **Stop condition:** Halt and add `HUMAN_TODO.md` when the existing canonical commands cannot be identified from repository files or when a new dependency would be required.

## Task 2 — Install the authority map without duplicating policy

- **Classification:** DECISION
- **Time box:** 1 hour
- **Objective:** Add this operating document and a minimal `policy/catalog.yaml` that points to canonical policy homes.
- **Paths touched:** `CLAUDE_CONFIG_OPERATIONS.md`, `policy/catalog.yaml`.
- **Acceptance criteria:** Every active policy entry has a unique id and resolvable canonical path; no catalogue entry contains normative prose; background design documents are marked non-authoritative by reference.
- **Verify:** `python tools/repo_gate.py fast`
- **Out of scope:** Rewriting existing policies, moving instruction files, or resolving policy contradictions not required by the fast gate.
- **Stop condition:** Halt when two existing files both claim canonical ownership of the same rule; record the conflict in `HUMAN_TODO.md` for owner selection.

## Task 3 — Retire the superseded maintenance-only control

- **Classification:** DECISION
- **Time box:** 1 hour
- **Objective:** Reconcile the live private repository so no date-driven maintenance-only control
  blocks an otherwise authorised task.
- **Paths touched:** The existing operating-mode control, `tools/repo_gate.py`, and its focused tests;
  do not create a second control file.
- **Acceptance criteria:** No calendar date or maintenance-only status remains executable; the fast
  gate still enforces budgets, private/public boundaries, and named task-specific locks.
- **Verify:** `python tools/repo_gate.py fast`
- **Out of scope:** Scheduling, branch protection changes, or enforcement outside local/CI checks.
- **Stop condition:** Halt if retiring the stale control would weaken an irreversible safety or
  privacy boundary rather than only removing the superseded date gate.

## Task 4 — Validate information placement and one-home policy

- **Classification:** DECISION
- **Time box:** 1–2 hours
- **Objective:** Inventory current instructions, skills, hooks, memory, and human-only items against the placement matrix without reorganising the repository.
- **Paths touched:** `private/reports/information-placement.md`, `policy/catalog.yaml`, `HUMAN_TODO.md` for unresolved ownership.
- **Acceptance criteria:** Every inventoried component has one current home, mechanism type, and owner; duplicates are reported, not automatically removed; no file moves occur.
- **Verify:** `python tools/repo_gate.py fast && python -c "from pathlib import Path; assert Path('private/reports/information-placement.md').is_file()"`
- **Out of scope:** Content rewrites, skill redesign, hook refactors, or public extraction.
- **Stop condition:** Halt on any suspected secret, client data, or private path that would be copied into a committed report; keep that detail local and record only a redacted reference.

## Task 5 — Prove the Gardener kill switch

- **Classification:** DECISION
- **Time box:** 1–2 hours
- **Objective:** Identify the existing kill switch or implement the sentinel fallback and prove all Gardener entry points honour it.
- **Paths touched:** Existing Gardener entry point, `private/control/GARDENER_DISABLED` test fixture, tests for the entry point, `policy/catalog.yaml`.
- **Acceptance criteria:** With the kill switch present, the Gardener exits `78`, creates no report, changes no tracked file, and emits a clear disabled message.
- **Verify:** `python tools/repo_gate.py fast`
- **Out of scope:** Improving Gardener recommendations, adding a scheduler, or allowing proposal branches.
- **Stop condition:** Halt when more than one Gardener entry point exists and it is unclear which is live; add a human decision item rather than normalising them automatically.

## Task 6 — Validate append-only failure capture

- **Classification:** DECISION
- **Time box:** 1–2 hours
- **Objective:** Add a schema validator and one synthetic fixture for the fixed failure-ledger record.
- **Paths touched:** Ledger validation code under existing `tools/` or `hooks/`, `tests/fixtures/failure-ledger/`, tests, `.gitignore` if required.
- **Acceptance criteria:** A valid synthetic record passes; a record containing an absolute path, token-like value, or overlong summary fails; the real private ledger is never read by CI.
- **Verify:** `python tools/repo_gate.py fast`
- **Out of scope:** Clustering, semantic analysis, importing historical transcripts, or changing ledger location without evidence.
- **Stop condition:** Halt if validation would require committing a real ledger sample; create a synthetic fixture instead.

## Task 7 — Run one bounded read-only Gardener cycle

- **Classification:** DECISION
- **Time box:** 2 hours
- **Objective:** Produce one manual report from current redacted inputs without mutating instructions, skills, hooks, policy, or code.
- **Paths touched:** `private/reports/gardener/<date>.md`; no tracked implementation path.
- **Acceptance criteria:** The report lists inputs, missing inputs, candidate observations, and explicit no-action outcomes; `git status --short` shows no unintended tracked change.
- **Verify:** `python tools/gardener.py report --read-only --output private/reports/gardener/latest.md && git status --short`
- **Out of scope:** Creating a PR, editing a skill, proposing a scheduler, or declaring an empty ledger as zero failures.
- **Stop condition:** Halt immediately if the kill switch is present, the command would publish data, or the Gardener attempts any mutation.

## Task 8 — Audit minimal telemetry only

- **Classification:** DECISION
- **Time box:** 1 hour
- **Objective:** Confirm current telemetry is no broader than the minimal schema and report excess fields without collecting new data.
- **Paths touched:** `private/reports/telemetry-audit.md`, `HUMAN_TODO.md` for any proposed removal or migration.
- **Acceptance criteria:** The report maps each collected field to the minimal schema, marks disallowed fields, and records missing data as missing rather than zero.
- **Verify:** `python tools/repo_gate.py fast && python -c "from pathlib import Path; assert Path('private/reports/telemetry-audit.md').is_file()"`
- **Out of scope:** Adding collectors, backfilling sessions, reading prompts, or migrating telemetry automatically.
- **Stop condition:** Halt if the audit requires opening raw prompts, transcripts, or credentials; report the existence of the source without reading its contents.

## Task 9 — Create the private/public boundary placeholder

- **Classification:** DECISION
- **Time box:** 1 hour
- **Objective:** Add only the directory and deny-by-default placeholder needed for a future approved allowlist; do not export files.
- **Paths touched:** `extraction/README.md`, optionally `extraction/allowlist.yaml` with `status: locked` and no entries.
- **Acceptance criteria:** The placeholder links to `BLUEPRINT_PLUGIN_PRODUCT.md`; it states that no path is approved; privacy-boundary CI passes with an empty allowlist.
- **Verify:** `python tools/repo_gate.py fast`
- **Out of scope:** Fictional estate, plugin files, copying skills, rewriting history, or secret-scanning the whole private repository for publication.
- **Stop condition:** Halt if any agent proposes adding a source path before the blueprint preconditions and owner unlock exist.

## Task 10 — Produce the operating-mode review record

- **Classification:** DECISION
- **Time box:** 1 hour
- **Objective:** After the preceding tasks, record work performed, budget consumed, unresolved
  breakages, remaining named unlock triggers, and the already-recorded immediate-start decision.
- **Paths touched:** `private/reports/operating-mode-review.md`, `HUMAN_TODO.md`, and the existing
  operating-mode control only when reconciliation is still required.
- **Acceptance criteria:** The report lists work performed, hours spent, unresolved breakages,
  telemetry changes, Gardener result, and remaining human-only decisions without recreating a date
  gate.
- **Verify:** `python tools/repo_gate.py fast && python -c "from pathlib import Path; assert Path('private/reports/operating-mode-review.md').is_file()"`
- **Out of scope:** Starting blueprint extraction, enabling scheduling, or expanding telemetry as part of the closeout.
- **Stop condition:** Halt before expanding any separately deferred system whose own trigger and
  owner approval are still absent.
