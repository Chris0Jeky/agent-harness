# Agent-Harness — Agent Build Directive

**Purpose:** Direct high-autonomy agents to evolve `agent-harness` into an active agent-operations and policy workbench, while preserving continuity across many agents and PRs.  
**Status:** Active repository-level direction; replay is a central module, not the repository's entire mission.  
**Authority:** This file supersedes any extraction-only or replay-only restriction that conflicts with the mission below. Existing safety, destructive-operation, secret-handling, and human-review rules remain binding.  
**Owner:** Cristian Tcaci  
**Last reviewed:** 2026-07-30  

## 1. Mission

Build `agent-harness` into a practical **agent-operations workbench** for Cristian's real Claude Code and Codex workflows.

The workbench should eventually provide four integrated capabilities:

1. **Policy Lab** — replay, compare, benchmark, and regression-test command policies.
2. **Pattern Guard** — a bounded, high-confidence, explainable tripwire for destructive or unwanted actions.
3. **Configuration Doctor** — show which instructions, hooks, rules, plugins, sandboxes, and repository declarations are actually active, stale, contradictory, or unverifiable.
4. **Estate Operations** — seed, audit, validate, and safely synchronise repository agent configuration.

The existing universal dispatcher is valuable evidence and a compatibility layer, but it is not the architecture to keep expanding.

> Hard security boundaries remain sandboxes, permissions, credential scope, branch protection, CI, and deployment controls. The guard is defence in depth, not a universal shell safety proof.

## 2. Scope correction

Do **not** treat this repository as a frozen extraction workspace whose only purpose is a small public replay tool.

Preserve useful work from `AGENT_HARNESS_OPERATIONS.md`, especially:

- immutable or reproducible baselines;
- recorded-decision policy sources;
- versioned replay inputs and run manifests;
- deterministic reports;
- explicit `indeterminate`;
- corpus digests and privacy controls;
- no universal-parser expansion.

Supersede only the claims that:

- replay is the sole active implementation;
- Doctor, estate tooling, adapters, and a new bounded guard are abandoned;
- the repository must be split before its internal architecture proves the boundary;
- a short launch budget permanently limits the repository.

A clean public extraction remains a possible later decision. It must be earned by a stable internal module and external demand.

## 3. Core operating rule

> Maintain an ambitious system roadmap, but permit only one or two bounded implementation workstreams at a time.

Do not grow the old parser to cover every wrapper and shell edge case.  
Do not reduce the whole repository to replay.  
Do not stop at architecture when an end-to-end slice can be implemented and measured.

Each active slice must end in a reproducible command, test, report, benchmark, deployed shadow observation, or explicit owner-blocked handoff.

## 4. Target architecture

Treat these as stable responsibility boundaries. Reuse existing paths where practical; do not reorganise merely for visual neatness.

```text
runtime / configuration sources
        |
        v
adapters and bounded normalisers
        |
        +-------------------+
        |                   |
        v                   v
policy replay          configuration doctor
        |                   |
        v                   v
reports / benchmarks   evidence / remediation plan
        |
        v
pattern guard in observe -> coach -> protect rollout
```

Recommended internal domains:

### 4.1 `legacy`

Owns the existing dispatcher and its historical evidence.

- pin a reviewed baseline;
- preserve tests and known limitations;
- permit critical correctness, attribution, observability, and deployment fixes only when measured;
- reject new universal-parser ambition;
- generate recorded decisions for replay.

A freeze means no expanding interpreter. It does not mean refusing every measured false-positive or dangerous-reason fix.

### 4.2 `replay`

Owns deterministic policy comparison.

- versioned `CommandEvent` and decision records;
- recorded-decision sources;
- generic process adapters;
- corpus validation and digests;
- run manifests;
- JSON and Markdown diffs;
- configured regression exits;
- deterministic tests;
- private and synthetic corpora.

Decision replay must be described honestly: it re-evaluates recorded inputs; it does not reproduce the original shell, agent trajectory, environment, or side effects.

### 4.3 `policy`

Owns policy interfaces and bounded facts.

Start with code-based command-family facts and predicates. Do not design a general DSL before repeated rules prove a stable grammar.

Candidate fact families:

- Git push and history facts;
- Git reset/clean/worktree-loss facts;
- recursive delete target facts;
- sensitive-path mutation facts;
- runtime/sandbox facts where explicitly available.

Unknown input is an observable state, not automatically a parser backlog item.

### 4.4 `guard`

Owns Pattern Guard v2.

The guard should:

- recognise a small set of concrete command families;
- default to allow outside those families unless a selected profile explicitly says otherwise;
- distinguish high-confidence match from uncertainty;
- explain the actual failed condition;
- provide a usable next action;
- support shadow measurement before enforcement;
- remain independently testable by rule family.

Do not begin with broad production-mutation, exfiltration, or arbitrary nested-interpreter claims unless structured evidence supports them.

### 4.5 `doctor`

Owns read-only configuration reality.

Build incrementally from observed failures. Findings should distinguish:

- declared;
- discovered;
- observed;
- remotely verified;
- inferred;
- unavailable;
- stale.

Initial high-value findings include:

- active and duplicate hooks;
- stale deployed versions;
- missing paths;
- conflicting instructions;
- source-versus-deployed drift;
- repository declarations that cannot be verified;
- a policy claiming visibility into a tool surface it cannot observe;
- sandbox or approval assumptions that differ from runtime reality.

Diagnosis and mutation remain separate:

```text
doctor -> plan -> explicit reviewed apply
```

### 4.6 `estate`

Owns existing seed, audit, doctor, and sync workflows.

It should help maintain multiple repositories without duplicating policy prose or silently changing live configuration.

### 4.7 `benchmarks`

Owns corpora, metrics, experiment definitions, environment records, and result history.

### 4.8 `adapters`

Owns runtime and external-policy translation.

Build one real adapter at a time. Let the second adapter reveal what must be generalised. Avoid speculative universal event models.

## 5. Required agent workflow

### 5.1 First agent after receiving this directive

1. Read root instructions, current operating documents, `README`, `BLUEPRINT`, `SPECS`, limitation records, open PRs/issues, recent commits, and existing test commands.
2. Identify which parts of replay, Doctor, estate tooling, and the legacy floor already exist and are deployed.
3. Correct any root document that still defines the repository as extraction-only or replay-only.
4. Produce or update a verified system-state report:
   - implemented;
   - deployed;
   - benchmarked;
   - experimental;
   - frozen;
   - unverified;
   - stale.
5. Map current issues and PRs to the roadmap in section 7; do not create duplicates.
6. Select the highest-leverage unblocked implementation slice, complete it, verify it, and leave the next slice ready.
7. Preserve replay work already completed. Reframe it as the evidence centre of the wider workbench.

### 5.2 Every later agent

1. Read this file.
2. Read the active workstream and latest handoff.
3. Re-run the relevant baseline or fast checks before editing.
4. Continue the active epic unless evidence says it is complete or wrong.
5. Implement one independently verifiable slice.
6. Add or update tests, corpus cases, metrics, documentation, and limitations.
7. Record discovered follow-on work without silently expanding scope.
8. Leave an exact executable handoff for the next agent.

An agent should not spend an entire session restating strategy already captured here.

## 6. Continuity contract

Before creating a file, find whether an equivalent already exists. Reuse one canonical home.

| Role | Recommended location | Required content |
|---|---|---|
| Product direction | this file | mission, scope, architecture |
| Verified current state | `docs/SYSTEM_STATE.md` | what exists and evidence level |
| Long-term roadmap | `ROADMAP.md` | epics, dependencies, outcome status |
| Active workstream | `plans/ACTIVE.md` | current epic, current slice, queued slices |
| Architecture decisions | `docs/decisions/ADR-*.md` | decision and consequences |
| Limitations | existing limitations file | explicit unsupported cases and rationale |
| Benchmarks | `docs/BENCHMARKS.md` plus result files | definitions, baselines, trends |
| Human-only actions | existing `HUMAN_TODO.md` or owner-defined equivalent | exact external decision/action |
| Session handoffs | `handoffs/<date>-<workstream>.md` | verified completion and next task |

If an existing file already owns a role, record the mapping in `docs/SYSTEM_STATE.md` and do not create a duplicate.

### Handoff template

```markdown
# Handoff: <workstream and date>

## End-to-end objective
<user-visible or operational outcome>

## Completed
- <code, test, report, or deployment change>

## Verification and measurements
- `<exact command>` -> <result>
- Baseline:
- Candidate:
- Result files:

## Decisions and limitations
- <what was learned>
- <what is deliberately unsupported>

## Exact next task
- Objective:
- Files likely touched:
- Acceptance criteria:
- Verification command:
- Required corpus/benchmark update:
- Do not redo:
```

## 7. Roadmap to seed and continuously refine

Seed missing epics, merge duplicates, and close completed work only with evidence.

### Epic AH-1 — Restore repository authority and measured baseline

**Outcome:** the repository has a truthful architecture statement and a reproducible baseline for the deployed legacy floor.

Include:

- superseding extraction-only language;
- pinned legacy commit/tag or equivalent manifest;
- line/function/complexity and latency facts;
- false-positive and false-negative families;
- decision and reason distribution;
- real-session interruption/workaround evidence;
- environment assumptions;
- explicit freeze boundary.

### Epic AH-2 — Complete replay as an internal Policy Lab

**Outcome:** one command compares policies over a pinned corpus and generates deterministic machine- and human-readable evidence.

Preserve and finish:

- `CommandEvent` v1;
- `allow`, `deny`, `indeterminate`;
- recorded decisions as first-class policy sources;
- generic JSONL stdin/stdout process contract;
- corpus digests;
- run manifests;
- JSON/Markdown reports;
- configurable regression exits;
- deterministic tests;
- approximately 50-case charter corpus.

Then expand only from real use:

- private historical corpus;
- labelled benign near-misses;
- adapter coverage;
- reason-quality comparison;
- latency and interruption metrics.

Replay remains an internal module until a clean extraction is clearly advantageous.

### Epic AH-3 — Pattern Guard v2

**Outcome:** a small guard catches the explicit catastrophic charter with materially lower friction than the legacy floor.

Start in shadow mode with approximately three command families, for example:

- shared Git history rewriting;
- destructive working-tree/worktree loss;
- recursive deletion outside an intended workspace.

For every family require:

- concrete harm;
- bounded observable facts;
- benign near-misses;
- explicit limitation;
- explanation;
- safer next action;
- unit and corpus tests;
- baseline comparison;
- shadow metrics;
- removal or revision condition.

Do not port legacy helper functions merely because they exist.

### Epic AH-4 — Doctor v2 from real failures

**Outcome:** a user can understand which controls are active and why, without reading multiple home-directory and repository files.

Implement the smallest useful graph first:

- instruction sources and ordering;
- hook registrations and executable paths;
- policy/dispatcher versions;
- duplicates and shadowing;
- repository declarations;
- observed sandbox/approval state where available;
- evidence level per finding.

Add checks from real configuration failures. Avoid speculative coverage of every remote system.

### Epic AH-5 — Runtime and external-policy adapters

**Outcome:** the same replay/reporting path can evaluate more than one policy implementation without changing core comparison logic.

Priority:

1. recorded legacy decisions;
2. generic process adapter;
3. current Claude or Codex runtime source;
4. one external/native policy compatibility example.

Build thin shims. Do not create a broad adapter framework before two real adapters expose common needs.

### Epic AH-6 — Estate operations

**Outcome:** repository agent configuration can be seeded, audited, diagnosed, and synchronised safely across the estate.

Improve existing commands rather than replacing them reflexively.

Require:

- dry-run or plan output;
- source and destination provenance;
- backups and rollback for mutation;
- drift reporting;
- cross-platform paths;
- test fixtures;
- no silent policy duplication.

### Epic AH-7 — Shadow, canary, and enforcement evidence

**Outcome:** policy changes progress from tests to live observation to bounded enforcement using explicit evidence.

Progression:

```text
unit tests
  -> charter corpus
  -> private corpus
  -> live shadow
  -> bounded canary
  -> wider deployment
```

Do not recommend Protect/enforcement from synthetic tests alone.

### Epic AH-8 — Integrated measurement

**Outcome:** the system can distinguish protection from self-inflicted friction.

Measure separately:

- event coverage;
- determinate and indeterminate rate;
- false deny/block rate;
- false interruption/approval rate where applicable;
- hazard recall on labelled cases;
- engine and end-to-end latency;
- rule and reason distribution;
- context/probe failures;
- workarounds;
- task completion where reliable;
- Doctor finding precision;
- recurrence after mitigation.

Never combine warning, approval, and denial into one undifferentiated false-positive number.

### Epic AH-9 — Claude-Config integration

**Outcome:** `claude-config` supplies private evidence and deployment context while `agent-harness` supplies validation, diagnosis, replay, and guard evaluation.

Target loop:

```text
real work
  -> failure or friction evidence
  -> Gardener/manual diagnosis
  -> proposed intervention
  -> replay/doctor/guard validation
  -> reviewed rollout
  -> observed result
```

Define interfaces at the data and command boundary. Do not make either repository depend on the other's private internals.

### Epic AH-10 — Public extraction and compatibility

**Outcome:** stable modules may later be packaged or demonstrated independently without narrowing the existing repository.

Possible outputs include:

- replay package;
- policy corpus;
- reference guard;
- Doctor package;
- compatibility reports;
- postmortem/case study.

Extraction is a product decision after internal proof, not the starting architecture.

## 8. Task seeding contract

Every epic must be decomposed into independently pickable, PR-sized tasks.

Use this task shape:

```markdown
# <task title>

## Outcome
<observable capability or measured result>

## Evidence
<incident, limitation, corpus gap, benchmark, or user need>

## Scope
- In:
- Out:

## Architecture seam
<module/interface/data flow affected>

## Acceptance
- [ ] implementation complete
- [ ] targeted tests pass
- [ ] corpus/fixture updated where relevant
- [ ] benchmark or measurement captured where relevant
- [ ] limitation and documentation updated
- [ ] next handoff written

## Verification
`<exact command>`

## Baseline and expected comparison
- Baseline:
- Candidate:
- Improvement or correctness condition:

## Dependencies
- <issue, PR, environment, owner review>

## Follow-on
<what becomes possible next>
```

Long epics may span many PRs. The final task in an epic must exercise the complete user or operator flow.

## 9. Quality and benchmark discipline

Discover and document exact commands. Preserve current tooling unless a reviewed change is justified.

Maintain:

1. **Fast lane:** structural and targeted tests; aim under 60 seconds.
2. **Full relevant lane:** all affected suites.
3. **Research lane:** exhaustive corpora, cross-platform matrices, repeated measurements, and live shadow analysis.

For policy work:

- one unit test per rule condition and safe exception;
- benign near-misses;
- historical regressions;
- unsupported/opaque cases;
- deterministic report tests;
- process-adapter failure tests;
- privacy and redaction tests;
- cross-platform fixtures where the command family differs.

Add metamorphic or property tests only when a real class of variations justifies them; do not generate permutations for appearance.

For benchmarks:

- pin corpus and policy digests;
- record environment and versions;
- separate engine latency from adapter/probe latency;
- preserve failed and skipped counts;
- compare against the frozen floor and previous candidate;
- store machine-readable results;
- avoid claims based solely on the charter corpus.

## 10. Policy design rules

Pattern Guard v2 must follow these rules:

- bounded command families, not arbitrary shell understanding;
- explicit facts rather than repeated raw-string interpretation;
- default allow outside supported families unless a selected profile explicitly closes a boundary;
- `unknown` or `indeterminate` is visible;
- high-impact decisions require high-confidence evidence;
- a reason names the actual condition;
- safer alternatives must be executable and not blocked by the same rule;
- a rule has an owner, source evidence, tests, metrics, and removal condition;
- repository policy may strengthen a trusted global boundary but may not silently weaken it;
- sandbox and permission controls remain the true enforcement layer.

Do not build a declarative rule language until repeated code-based rules expose a stable common grammar.

## 11. Self-improvement rules

Agent-Harness may improve from evidence, but never by unattended policy mutation.

Allowed:

- convert a verified incident into a corpus case;
- draft a rule or Doctor check on a branch;
- run baseline/candidate replay;
- produce shadow reports;
- propose retirement or simplification;
- feed redacted findings to the `claude-config` Gardener.

Not allowed without owner review:

- enable a new blocking rule globally;
- weaken an existing hard boundary;
- auto-install generated policy;
- treat one incident as sufficient for broad coverage;
- publish private corpus data;
- add dependencies, licences, or public releases;
- rewrite the legacy floor into a new universal parser.

A new guard or Doctor feature is incomplete until it has:

- an evidence source;
- tests;
- a benchmark or operational check;
- a rollout plan;
- a rollback/removal path;
- a documented limitation.

## 12. Human boundary

Follow existing repository autonomy rules. At minimum, require owner review for:

- destructive or irreversible operations;
- credentials, secrets, private accounts, or external systems;
- live global hook/policy activation;
- public releases, tags, package publication, or visibility changes;
- dependency and licence choices;
- broad scope or mission changes;
- repository-history rewriting;
- movement from shadow to enforcement;
- external claims about safety or benchmark superiority.

Route owner-only work to the repository's canonical human-action file.

## 13. Definition of success

`agent-harness` is succeeding when:

- replay makes policy changes measurable and reproducible;
- the new guard preserves high-confidence protection with materially less friction;
- Doctor accurately reveals active configuration and uncertainty;
- estate operations reduce drift without hidden mutation;
- legacy complexity stops growing;
- real failures become corpus cases, checks, or explicit limitations;
- live shadow evidence precedes enforcement;
- integrations remain thin and honest;
- the system creates less work about itself than the harm and repetition it prevents.

Continue iterating across as many tasks and agents as necessary, but keep the active work narrow, verified, and easy to hand off.
