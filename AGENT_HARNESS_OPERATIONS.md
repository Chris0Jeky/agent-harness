Purpose: Authoritative freeze, extraction, and replay-kernel contract for the existing private `agent-harness` repository.
Status: ACTIVE for freeze and extraction only; universal-parser feature development is stopped.
Authority relationship: This document wins for the legacy dispatcher freeze, source-asset extraction, and replay-kernel technical contracts; `CLAUDE_CONFIG_OPERATIONS.md` wins for autonomy and evidence handling, while `REPLAY_TOOL_PRODUCT.md` wins for public naming, release, launch, and continuation decisions.
Last-reviewed date: 2026-07-30
Owner: Cristian Tcaci

# OPEN items

- **OPEN AH-001:** Confirm the exact immutable legacy tag name. This document recommends `floor-v1-final`.
- **OPEN AH-002:** Confirm the current paths of the legacy dispatcher, replay script, corpus fixtures, and test suites. The paths in this document are target paths and must be adapted without moving unrelated files.
- **OPEN AH-003:** Confirm the existing repository test and lint commands. Agents must preserve current tooling and must not add a dependency without owner review.
- **OPEN AH-004:** Confirm whether the legacy dispatcher can execute in a clean isolated environment. The public baseline does not depend on this answer because recorded decisions are first-class.
- **OPEN AH-005:** Confirm the launch calendar and 13-hour allocation for the tasks in this document. `REPLAY_TOOL_PRODUCT.md` owns the overall assumed 2026-08-16 deadline and 24-hour cap.

# Authority and operating decision

- **DECISION:** The existing repository becomes a frozen evidence source and extraction workspace, not the public product repository.
- **DECISION:** The legacy dispatcher is preserved at a reviewed commit and immutable tag; it is not rewritten, reformatted, or expanded to support new command shapes.
- **DECISION:** The only active implementation scope is the decision-replay kernel defined below and the minimum extraction support needed to move it into the clean public repository.
- **CONSTRAINT:** Cross-repository autonomy, mandatory owner review, `HUMAN_TODO.md`, failure-ledger schema, and manual promotion policy are defined only in `CLAUDE_CONFIG_OPERATIONS.md`; agents must apply those rules by reference.
- **CONSTRAINT:** Any discovered work outside this contract becomes a backlog proposal with an evidence trigger. It must not be implemented in this repository.
- **CONSTRAINT:** A green legacy test suite does not reopen universal-parser development.

# Freeze contract

- **DECISION:** The recommended tag is `floor-v1-final` and must point to the last owner-reviewed universal-parser state.
- **CONSTRAINT:** Creating or pushing the tag requires owner review.
- **CONSTRAINT:** After the tag, the legacy dispatcher path is read-only except for a security-critical preservation fix explicitly approved by the owner.
- **CONSTRAINT:** New bypasses, false positives, and environment incompatibilities are recorded as evidence or corpus candidates; they are not automatically fixed in the legacy parser.
- **CONSTRAINT:** The freeze record must contain the commit SHA, dispatcher path, line count, test command, known environment assumptions, known false-positive families, known false-negative families, and the location of recorded decisions.
- **CONSTRAINT:** The public replay repository must not require the legacy code, its private configuration, or its machine environment at runtime.

# V0 product boundary

- **DECISION:** V0 performs **decision replay**: it re-evaluates or compares recorded command events and recorded policy decisions. It does not reproduce the original agent, shell, filesystem, repository state, network, or side effects.
- **DECISION:** The v0 domain is command-policy comparison, not a generic agent-tool event model.
- **CONSTRAINT:** The only decision effects are `allow`, `deny`, and `indeterminate`.
- **CONSTRAINT:** `indeterminate` means the source could not provide a trustworthy decision for the event. It must never be silently converted to `allow` or `deny`.
- **CONSTRAINT:** V0 has no `warn`, `ask`, `approve`, `escalate`, severity, confidence, or authorisation semantics.
- **CONSTRAINT:** V0 has no live enforcement path.

# Interface contracts

## `CommandEvent` v1

- **DECISION:** The canonical schema path in the extraction workspace is `replay_v0/schemas/command-event.v1.schema.json`.
- **CONSTRAINT:** Every event contains the three required identity fields requested for v0: `schema_version`, `event_id`, and `timestamp`.
- **CONSTRAINT:** The complete v1 record is:

```json
{
  "schema_version": "command-event.v1",
  "event_id": "git-force-main-001",
  "timestamp": "2026-07-30T12:00:00Z",
  "command": "git push origin main --force",
  "cwd": "/fictional/shop-api",
  "source": "synthetic"
}
```

- **CONSTRAINT:** `event_id` is unique within a corpus, stable across policy runs, and contains no private identifier.
- **CONSTRAINT:** `timestamp` is RFC 3339 UTC.
- **CONSTRAINT:** `command` is the exact replay input after privacy review. It may be synthetic or redacted; its provenance is recorded by `source`.
- **CONSTRAINT:** `cwd` is optional in the JSON Schema and, when present, must use a fictional or redacted path.
- **CONSTRAINT:** `source` is one of `synthetic`, `historical-redacted`, or `generated-variant`.
- **CONSTRAINT:** Additional event fields are rejected in v0 unless the owner approves a schema revision. Adapter-specific metadata belongs outside the event.

## `PolicyDecision` v1

- **DECISION:** The canonical schema path is `replay_v0/schemas/policy-decision.v1.schema.json`.
- **CONSTRAINT:** The complete v1 record is:

```json
{
  "schema_version": "policy-decision.v1",
  "event_id": "git-force-main-001",
  "effect": "deny",
  "reason": "Force-pushing this shared branch is blocked by the recorded baseline."
}
```

- **CONSTRAINT:** `effect` is exactly `allow`, `deny`, or `indeterminate`.
- **CONSTRAINT:** `reason` is required, single-line, UTF-8, and no longer than 500 characters.
- **CONSTRAINT:** A policy source must return one decision for every event or the runner generates an `indeterminate` decision with a machine-readable source failure in the run report.

## Generic process policy contract

- **DECISION:** A process policy reads newline-delimited `CommandEvent` v1 objects from standard input and writes newline-delimited `PolicyDecision` v1 objects to standard output.
- **CONSTRAINT:** The policy process must preserve `event_id` exactly and emit decisions in input order.
- **CONSTRAINT:** Standard output contains decisions only. Diagnostics go to standard error.
- **CONSTRAINT:** Exit code `0` means the process completed its stream. Any non-zero exit causes every missing decision to become `indeterminate`; the runner still writes a report and returns the runner exit code defined below.
- **CONSTRAINT:** The process contract is invoked through a shell-free argv list in implementation code. A single shell command string must not be passed to `shell=True`.
- **CONSTRAINT:** The reference invocation shape is:

```bash
python -m replay_v0.cli replay \
  --baseline recorded:replay_v0/fixtures/legacy-decisions.jsonl \
  --candidate process:python,examples/candidate_policy.py \
  --corpus replay_v0/corpora/charter/events.jsonl
```

## Recorded-decision policy source

- **DECISION:** A JSONL recording is a first-class policy source and is the default way to use the frozen legacy baseline.
- **CONSTRAINT:** The recorded source file contains one `PolicyDecision` v1 object per corpus event and a sidecar manifest that identifies the original policy and commit.
- **CONSTRAINT:** A missing `event_id`, duplicate `event_id`, invalid schema, or digest mismatch produces `indeterminate` for affected events and fails input validation.
- **CONSTRAINT:** The legacy dispatcher never needs to execute in the public repository or demo.
- **CONSTRAINT:** The reference source syntax is `recorded:<path>`.

## Legacy dispatcher wrapper

- **DECISION:** The legacy wrapper exists only to generate or refresh a private decision recording from the pinned legacy environment.
- **CONSTRAINT:** The wrapper must import or invoke the tagged dispatcher without modifying it.
- **CONSTRAINT:** The wrapper reads the same `CommandEvent` stream and writes `PolicyDecision` records, but it may run only in the private repository or an owner-approved isolated environment.
- **CONSTRAINT:** If the legacy dispatcher cannot process an event or cannot start, the wrapper emits `indeterminate`; it does not patch the dispatcher.
- **CONSTRAINT:** The wrapper output must include a manifest with the exact legacy commit and environment notes before it can be used as a baseline recording.

# Corpus contract

- **DECISION:** The v0 charter corpus contains approximately 50 privacy-safe command events.
- **DECISION:** The target composition is 20 dangerous canonical cases, 20 benign near-misses, and 10 historical regressions or deliberately opaque cases.
- **CONSTRAINT:** Every event is synthetic, historically redacted, or generated from an approved synthetic base. No raw transcript entry is committed.
- **CONSTRAINT:** Dangerous and benign classification is stored in `replay_v0/corpora/charter/cases.jsonl`, keyed by `event_id`; it is not inferred from baseline decisions.
- **CONSTRAINT:** Each case record uses:

```json
{
  "schema_version": "charter-case.v1",
  "event_id": "git-force-main-001",
  "case_class": "dangerous",
  "case_family": "shared-history-rewrite",
  "rationale": "A force push can rewrite shared history.",
  "provenance": "synthetic"
}
```

- **CONSTRAINT:** `case_class` is `dangerous`, `benign`, or `opaque`.
- **CONSTRAINT:** A historical regression must be re-authored with fictional paths, branches, repositories, and identifiers before inclusion.
- **CONSTRAINT:** Benign near-misses must resemble a dangerous case while remaining non-executing or non-destructive, such as quoted documentation, `echo`, dry-run, help output, or an unrelated safe flag combination.
- **CONSTRAINT:** Quoting variants, path variants, and argument-order variants count only when they represent a distinct regression risk. Bulk permutations are out of scope.
- **CONSTRAINT:** The charter corpus is a curated conformance corpus, not an industry benchmark claim.
- **CONSTRAINT:** The corpus must contain no credential-like values, private URLs, absolute owner paths, customer names, or repository names.

# Digests and manifests

## Corpus manifest

- **DECISION:** `replay_v0/corpora/charter/corpus-manifest.json` records exact-byte SHA-256 digests.
- **CONSTRAINT:** The manifest contains:

```json
{
  "schema_version": "corpus-manifest.v1",
  "corpus_id": "charter-v0.1",
  "event_count": 50,
  "files": [
    {"path": "events.jsonl", "sha256": "<hex>"},
    {"path": "cases.jsonl", "sha256": "<hex>"}
  ]
}
```

- **CONSTRAINT:** Digests cover the exact committed bytes. Line-ending changes therefore require a manifest update.
- **CONSTRAINT:** The runner validates all listed digests before invoking any policy source.

## Run manifest

- **DECISION:** Every comparison writes `run-manifest.json` beside its reports.
- **CONSTRAINT:** The manifest contains:

```json
{
  "schema_version": "replay-run.v1",
  "run_id": "sha256-derived-id",
  "generated_at": "RFC3339 timestamp",
  "runner_version": "0.1.0",
  "baseline": {"kind": "recorded", "id": "floor-v1-final", "sha256": "<hex>"},
  "candidate": {"kind": "process", "id": "candidate-policy", "sha256": "<hex>"},
  "corpus": {"id": "charter-v0.1", "manifest_sha256": "<hex>", "event_count": 50},
  "fail_on": ["newly-allowed", "newly-indeterminate"]
}
```

- **CONSTRAINT:** `run_id` is derived from runner version, policy-source digests, corpus-manifest digest, and gate configuration. It must not contain time or machine identity.
- **CONSTRAINT:** `generated_at` is informational and is excluded from semantic report comparisons.
- **CONSTRAINT:** The manifest contains no absolute path, hostname, username, environment variable, or private repository identifier.

# Diff semantics and reports

- **DECISION:** The replay engine compares effects by `event_id` and writes both `report.json` and `report.md`.
- **CONSTRAINT:** The report groups cases as `unchanged`, `newly-allowed`, `newly-denied`, `newly-indeterminate`, and `resolved-indeterminate`.
- **CONSTRAINT:** `newly-allowed` means baseline `deny` and candidate `allow`.
- **CONSTRAINT:** `newly-denied` means baseline `allow` and candidate `deny`.
- **CONSTRAINT:** `newly-indeterminate` means the baseline was determinate and the candidate is `indeterminate`.
- **CONSTRAINT:** `resolved-indeterminate` means the baseline was `indeterminate` and the candidate is determinate.
- **CONSTRAINT:** The Markdown report begins with counts, gate result, policy identities, corpus identity, and the exact reproduction command.
- **CONSTRAINT:** The JSON report contains every event result and remains the machine-readable source of truth.
- **CONSTRAINT:** The report may describe a change; it may not claim that the original command was safe, executed, or reproduced.

## Exit codes

- **DECISION:** The CLI uses these exit codes:

| Exit code | **DECISION: meaning** |
|---:|---|
| `0` | Inputs valid, policies evaluated, and no configured regression class is present. |
| `1` | Inputs valid and comparison complete, but at least one configured regression class is present. |
| `2` | Corpus, schema, manifest, or digest validation failed. |
| `3` | A policy source or runner failed in a way that prevented a trustworthy complete comparison. |

- **CONSTRAINT:** A configured regression is selected only through `--fail-on`; supported v0 values are `newly-allowed`, `newly-denied`, and `newly-indeterminate`.
- **CONSTRAINT:** The default is `--fail-on newly-allowed,newly-indeterminate`.
- **CONSTRAINT:** Reports are written before exit `1` or `3` whenever enough information exists to do so safely.

# Determinism contract

- **DECISION:** The same runner version, exact policy-source bytes, corpus bytes, and gate configuration must produce the same semantic JSON report.
- **CONSTRAINT:** Tests set `SOURCE_DATE_EPOCH` and normalise `generated_at` before byte comparison.
- **CONSTRAINT:** The v0 fast lane performs no network access and no live legacy execution.
- **CONSTRAINT:** Tests use temporary directories and fictional paths only.
- **CONSTRAINT:** Running the same fixture twice must produce identical `run_id`, classifications, counts, event ordering, and semantic JSON content.

# Non-Goals

- **DECISION:** The following exclusions define the v0 non-goals and are not implementation backlog.


- **CONSTRAINT:** No live command interception or enforcement.
- **CONSTRAINT:** No universal shell parsing, recursive wrapper interpretation, variable expansion, repository-state inference, or network probes.
- **CONSTRAINT:** No generic `ToolEvent`, file-edit event, MCP event, GitHub event, cloud event, or agent trajectory replay.
- **CONSTRAINT:** No policy DSL, YAML rule compiler, rule precedence engine, risk profiles, approval workflow, or authorisation context.
- **CONSTRAINT:** No Configuration Doctor, telemetry platform, failure clustering, promotion engine, blueprint plugin, fictional estate, or scheduler.
- **CONSTRAINT:** No academic benchmark claim, leaderboard, or broad safety claim.
- **CONSTRAINT:** No external integration in core v0. The DCG compatibility demonstration belongs to `REPLAY_TOOL_PRODUCT.md` as an example shim.
- **CONSTRAINT:** No new legacy-parser feature or broad refactor.

# Repository layout for extraction work

- **DECISION:** The private extraction workspace uses this bounded shape, adapted to existing paths where necessary:

```text
agent-harness/
  AGENT_HARNESS_OPERATIONS.md
  experimental/
    floor_v1/                 # existing legacy code or immutable reference
  replay_v0/
    cli.py
    compare.py
    corpus.py
    digests.py
    manifests.py
    policy_sources.py
    reports.py
    schemas/
    corpora/charter/
    fixtures/
    tests/
  docs/background/            # prior plans and postmortem inputs; non-authoritative
  HUMAN_TODO.md
```

- **CONSTRAINT:** Do not move the legacy implementation merely to match this diagram if doing so risks history, imports, or tests. A reference path is acceptable.
- **CONSTRAINT:** Only files approved by the extraction manifest are copied into the clean public repository.

# Autonomy, evidence, and stop policy

- **CONSTRAINT:** Apply `CLAUDE_CONFIG_OPERATIONS.md#autonomy-boundary` without restatement.
- **CONSTRAINT:** Use the failure schema and manual promotion process from `CLAUDE_CONFIG_OPERATIONS.md`; the local recommended ledger path is `.local/failure-ledger.jsonl`, ignored by Git.
- **CONSTRAINT:** Any destructive Git operation, tag creation, dependency change, public push, licence change, policy change, or extraction-scope change requires owner review.
- **CONSTRAINT:** An agent must halt when the legacy environment is missing rather than repairing it. Recorded decisions are the fallback.

# Quality gates

- **OPEN:** Bind these commands to the repository's existing tooling during Task 1; do not add missing tools without owner review.
- **DECISION:** The target commands are:

```bash
python -m pytest -q replay_v0/tests
python -m ruff check replay_v0
python -m pytest -q replay_v0/tests/unit replay_v0/tests/contract
```

- **CONSTRAINT:** The third command is the fast lane and must complete in under 60 seconds without network access or live legacy execution.
- **CONSTRAINT:** Required CI checks before merging extraction work are `replay-fast`, `replay-lint`, `replay-tests`, `charter-digests`, `recorded-baseline`, and `operations-contract`.
- **CONSTRAINT:** If Pytest or Ruff is not already approved in the repository, the agent must route the tooling decision to `HUMAN_TODO.md`; it may use existing equivalents but must update this document through owner-reviewed PR before changing the command contract.

# Calendar and budget allocation

- **OPEN:** The schedule below assumes the owner confirms the 2026-08-16 launch and 24-hour total cap.
- **DECISION:** These ten tasks have a combined maximum of **13 hours**. `REPLAY_TOOL_PRODUCT.md` owns the remaining **11 hours**.
- **CONSTRAINT:** When the cumulative logged time reaches 13 hours, the agent stops extraction work and presents the completed subset. Deferred polish does not consume the public-product allocation without owner approval.

# First 10 tasks

## Task 1 — Record and prepare the legacy freeze

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-07-30 to 2026-08-02
- **Objective:** Produce the freeze record and identify the exact commit proposed for `floor-v1-final` without creating or pushing the tag.
- **Paths touched:** `docs/freeze/floor-v1-final.md`, `HUMAN_TODO.md`.
- **Acceptance criteria:** The record contains commit SHA, dispatcher path, line count, known test command, environment assumptions, known limitation references, and a copy-paste tag command marked human-review-only.
- **Verify:** `git diff --check && python -c "from pathlib import Path; assert Path('docs/freeze/floor-v1-final.md').is_file()"`
- **Out of scope:** Tag creation, history rewrite, dispatcher edits, test repair, or repository reorganisation.
- **Stop condition:** Halt when the candidate commit has uncommitted changes, failing preservation tests, or unclear ownership; record the blockers rather than selecting another commit silently.

## Task 2 — Inventory extractable replay assets and baseline recordings

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-07-30 to 2026-08-02
- **Objective:** Identify existing replay code, tests, corpora, and legacy decision outputs that can seed v0.
- **Paths touched:** `docs/extraction/inventory.md`; no source moves.
- **Acceptance criteria:** Every candidate asset has current path, purpose, private-data risk, keep/rewrite/drop decision, and estimated extraction effort; a recorded baseline gap is explicit.
- **Verify:** `git diff --check && python -c "from pathlib import Path; assert Path('docs/extraction/inventory.md').is_file()"`
- **Out of scope:** Copying files, redesigning modules, generating new telemetry, or executing the legacy parser on private workloads.
- **Stop condition:** Halt on any asset containing unreviewed private paths, commands, URLs, or repository identities; list it as private-only without opening or copying unnecessary content.

## Task 3 — Implement the v1 schemas and validators

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-03 to 2026-08-04
- **Objective:** Implement the three minimal schemas: `CommandEvent`, `PolicyDecision`, and charter case.
- **Paths touched:** `replay_v0/schemas/`, `replay_v0/corpus.py`, `replay_v0/tests/contract/`.
- **Acceptance criteria:** Valid fixtures pass; missing required identity fields, extra event fields, invalid effects, and invalid timestamps fail with deterministic messages.
- **Verify:** `python -m pytest -q replay_v0/tests/contract/test_schemas.py`
- **Out of scope:** Generic tool schemas, adapter metadata, confidence, severity, approval, or schema code generation.
- **Stop condition:** Halt when existing dependencies cannot validate JSON Schema and adding a dependency would be required; implement a bounded standard-library validator or request owner review.

## Task 4 — Add recorded decisions as a policy source

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-04 to 2026-08-05
- **Objective:** Load a decision JSONL file by `event_id` and return `indeterminate` for missing records without executing a policy.
- **Paths touched:** `replay_v0/policy_sources.py`, `replay_v0/fixtures/recorded/`, `replay_v0/tests/unit/test_recorded_source.py`.
- **Acceptance criteria:** Complete, missing, duplicate, malformed, and mismatched recordings are covered; no legacy import occurs.
- **Verify:** `python -m pytest -q replay_v0/tests/unit/test_recorded_source.py`
- **Out of scope:** Refreshing the real legacy baseline, auto-repairing recordings, or adding database storage.
- **Stop condition:** Halt if a proposed fixture includes real private commands; replace it with a synthetic recording.

## Task 5 — Implement the generic process source

- **Classification:** DECISION
- **Time box:** 1.5 hours
- **Calendar slot:** 2026-08-05 to 2026-08-06
- **Objective:** Implement shell-free JSONL stdin/stdout policy execution with timeout and missing-decision handling.
- **Paths touched:** `replay_v0/policy_sources.py`, `replay_v0/tests/fixtures/process_policies/`, `replay_v0/tests/contract/test_process_source.py`.
- **Acceptance criteria:** Ordered success, stderr diagnostics, non-zero exit, timeout, malformed output, duplicate event id, and partial output are deterministic; missing decisions become `indeterminate`.
- **Verify:** `python -m pytest -q replay_v0/tests/contract/test_process_source.py`
- **Out of scope:** Shell command strings, plugin discovery, long-running daemons, network policies, or runtime-specific adapters.
- **Stop condition:** Halt if implementation requires `shell=True`, platform-specific quoting logic, or a new process framework.

## Task 6 — Implement exact-byte digests and manifests

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-06
- **Objective:** Generate and validate corpus and run manifests using SHA-256.
- **Paths touched:** `replay_v0/digests.py`, `replay_v0/manifests.py`, manifest fixtures, tests.
- **Acceptance criteria:** Byte changes invalidate the digest; `run_id` is stable for identical inputs; absolute paths and host data are absent.
- **Verify:** `python -m pytest -q replay_v0/tests/unit/test_digests.py replay_v0/tests/unit/test_manifests.py`
- **Out of scope:** Signatures, attestations, remote storage, content-addressed databases, or cryptographic identity systems.
- **Stop condition:** Halt if a manifest proposal includes machine-specific environment data not required for reproducibility.

## Task 7 — Implement the semantic diff and JSON report

- **Classification:** DECISION
- **Time box:** 1.5 hours
- **Calendar slot:** 2026-08-07 to 2026-08-08
- **Objective:** Compare baseline and candidate decisions and emit the complete machine-readable report.
- **Paths touched:** `replay_v0/compare.py`, `replay_v0/reports.py`, `replay_v0/tests/unit/test_compare.py`, golden JSON fixtures.
- **Acceptance criteria:** All five diff classes are covered; ordering follows the corpus; reasons are preserved; the report states decision replay limitations.
- **Verify:** `python -m pytest -q replay_v0/tests/unit/test_compare.py`
- **Out of scope:** Hazard scoring, leaderboard metrics, confusion matrices, latency benchmarking, or task-outcome claims.
- **Stop condition:** Halt if classification requires adding a fourth effect or inferring safety from command text.

## Task 8 — Add Markdown reporting, CLI, and exit codes

- **Classification:** DECISION
- **Time box:** 1.5 hours
- **Calendar slot:** 2026-08-08 to 2026-08-09
- **Objective:** Provide one reproducible command that writes JSON, Markdown, and run manifest and exits under the defined contract.
- **Paths touched:** `replay_v0/cli.py`, `replay_v0/reports.py`, CLI tests, Markdown golden fixtures.
- **Acceptance criteria:** Exit codes `0`–`3` are covered; `--fail-on` accepts only the three supported classes; the report prints a reproduction command; reports are written before exit `1`.
- **Verify:** `python -m pytest -q replay_v0/tests/contract/test_cli.py`
- **Out of scope:** Interactive UI, colours required for interpretation, configuration files, subcommands other than replay/validate, or package publication.
- **Stop condition:** Halt if the CLI begins absorbing policy-authoring or live-enforcement features.

## Task 9 — Curate the 50-case charter corpus and recorded baseline

- **Classification:** DECISION
- **Time box:** 2 hours
- **Calendar slot:** 2026-08-10 to 2026-08-12
- **Objective:** Build the small reviewed charter corpus and a matching synthetic or redacted legacy-decision recording.
- **Paths touched:** `replay_v0/corpora/charter/events.jsonl`, `cases.jsonl`, `corpus-manifest.json`, `replay_v0/fixtures/legacy-decisions.jsonl`, recording manifest.
- **Acceptance criteria:** Approximately 20 dangerous, 20 benign, and 10 historical/opaque cases; unique ids; valid schemas; exact digests; no private identifiers; owner-review checklist generated.
- **Verify:** `python -m replay_v0.cli validate --corpus replay_v0/corpora/charter && python -m pytest -q replay_v0/tests/charter`
- **Out of scope:** Bulk conversion of the old test suite, live transcript ingestion, benchmark claims, or adding cases merely to increase count.
- **Stop condition:** Halt when a case cannot be sanitised without changing the relevant command structure; keep it private and replace it with a synthetic case.

## Task 10 — Prove determinism and create the extraction bundle

- **Classification:** DECISION
- **Time box:** 1.5 hours
- **Calendar slot:** 2026-08-12 to 2026-08-13
- **Objective:** Run the full v0 fast gate twice and create an allowlisted source bundle for the clean public repository.
- **Paths touched:** `replay_v0/tests/test_determinism.py`, `docs/extraction/public-v0-manifest.json`, generated local bundle under an ignored path.
- **Acceptance criteria:** Two runs produce identical semantic JSON and `run_id`; fast lane remains under 60 seconds; the manifest lists only v0 source, schemas, synthetic corpus, tests, and approved documentation.
- **Verify:** `python -m pytest -q replay_v0/tests && python -m replay_v0.cli replay --baseline recorded:replay_v0/fixtures/legacy-decisions.jsonl --candidate process:python,replay_v0/tests/fixtures/process_policies/reference_candidate.py --corpus replay_v0/corpora/charter/events.jsonl --output .local/replay-proof`
- **Out of scope:** Creating the public repository, choosing its licence/name, pushing a release, including legacy source, or including private Git history.
- **Stop condition:** Halt when the extraction manifest contains an unreviewed path, private data, or any legacy implementation file; request owner review before copying.
