Purpose: Locked operating brief for a future public blueprint plugin extracted from proven private `claude-config` components.
Status: DEFERRED AND LOCKED; no implementation task is authorised until every precondition in this document is satisfied and the owner records an explicit unlock.
Authority relationship: This document wins only for blueprint-plugin unlock conditions,
extraction allowlist format, fictional-estate scope, and candidate evidence;
`CLAUDE_CONFIG_OPERATIONS.md` wins for private operation and supervision. The replay public-product
brief is deferred under AH-10 and does not weaken this document's conjunctive unlock.
Last-reviewed date: 2026-07-30
Owner: Cristian Tcaci

# OPEN items

- **OPEN BP-001:** Select a final plugin/repository name only after the unlock conditions hold.
- **OPEN BP-002:** Select the first supported packaging target: Claude Code plugin only, standards-based files only, or another bounded target. No multi-runtime promise is assumed.
- **OPEN BP-003:** Select the plugin licence after source-provenance review; no licence is inherited by assumption.
- **OPEN BP-004:** Confirm where the explicit unlock record will live. This document recommends `HUMAN_TODO.md` plus `extraction/UNLOCK.md` in the private repository.
- **OPEN BP-005:** Determine whether any candidate component has already met the cross-repository evidence threshold. Current status is treated as unproven.

# Lock statement

- **CONSTRAINT:** Any agent starting implementation, extraction, fictional-estate construction, repository creation, packaging, or publication before every precondition below holds is out of policy.
- **CONSTRAINT:** An out-of-policy attempt must stop immediately, append a redacted failure record using `CLAUDE_CONFIG_OPERATIONS.md#failure-and-friction-ledger`, and route the proposed work to `HUMAN_TODO.md`.
- **CONSTRAINT:** Planning or polishing this product is not a substitute for the active
`agent-harness` workbench mission. No replay launch or date independently unlocks it.

# Preconditions: all must hold

- **DEFERRED BP-PRE-01:** `CharterReplay` or its final-name equivalent has a clean public `v0.1.0` release and satisfies the portfolio-completion criteria in `REPLAY_TOOL_PRODUCT.md`.
- **DEFERRED BP-PRE-02:** The confirmed continuation review has occurred on or after 2026-09-30, or the owner has explicitly waived that date after recording why the blueprint has higher priority.
- **SATISFIED BP-PRE-03:** The owner explicitly lifted `claude-config` maintenance-only mode on
  2026-07-30. This satisfies only BP-PRE-03 and does not unlock blueprint implementation while any
  other precondition remains unsatisfied.
- **DEFERRED BP-PRE-04:** At least two candidate components have each solved the same problem class in at least two distinct repositories or contexts.
- **DEFERRED BP-PRE-05:** Each candidate has measured or directly reviewed net benefit, a bounded trigger, a removal condition, and no unresolved private-data dependency.
- **DEFERRED BP-PRE-06:** At least one manual Gardener cycle and one manual promotion review have produced a useful owner-approved outcome without automatic installation.
- **DEFERRED BP-PRE-07:** The extraction allowlist contains at least one owner-approved entry and has passed privacy/provenance review.
- **DEFERRED BP-PRE-08:** The fictional-estate specification below has been owner-approved as the only demonstration environment.
- **DEFERRED BP-PRE-09:** A clean-repository, name, licence, packaging-target, and maintenance-owner decision has been recorded.
- **DEFERRED BP-PRE-10:** `extraction/UNLOCK.md` contains the owner, date, satisfied-precondition evidence, allowed first task, and maximum initial time budget.

- **CONSTRAINT:** Preconditions are conjunctive. Nine of ten is locked.
- **CONSTRAINT:** An agent may verify and report precondition status before unlock; it may not produce implementation artifacts while any item is unsatisfied.

# Non-Goals

- **CONSTRAINT:** The future plugin is not a public copy of the private repository.
- **CONSTRAINT:** It does not export estate registry, machine paths, personal memory, raw failure ledger, telemetry, transcripts, private project facts, client information, model-routing preferences, credentials, or Git history.
- **CONSTRAINT:** It does not promise a self-improving agent operating system, automatic skill creation, autonomous policy evolution, scheduled Gardener, universal safety, or support for every coding-agent runtime.
- **CONSTRAINT:** It does not duplicate the replay tool, command guard, sandbox, CI system, or repository-host permission model.
- **CONSTRAINT:** No component is extracted because it is elegant, large, or already implemented; only evidence unlocks extraction.

# Extraction allowlist manifest

- **DECISION:** The sole authoritative manifest path is `claude-config/extraction/allowlist.yaml`.
- **DECISION:** Export is default-deny. A source path not present in an owner-approved entry is not exportable.
- **CONSTRAINT:** The manifest uses this exact v1 structure:

```yaml
schema_version: 1
status: locked | approved
source_repository: claude-config
public_repository: null
approved_by: null
approved_at: null
entries:
  - component_id: verify-and-handoff
    source_path: skills/verify-and-handoff/
    destination_path: skills/verify-and-handoff/
    content_class: skill
    copy_mode: clean-copy
    include:
      - SKILL.md
      - tests/**
    exclude:
      - "**/.local/**"
      - "**/private/**"
      - "**/*secret*"
    evidence_refs:
      - private/reviews/promotion/PROMOTION-<id>.md
    required_transforms:
      - remove-private-assumptions
      - replace-real-examples-with-fictional
    source_sha256: null
    exported_sha256: null
    privacy_review: pending | passed | failed
    provenance_review: pending | passed | failed
    owner_approved: false
```

- **CONSTRAINT:** `clean-copy` means the public repository receives file content only, never private Git history.
- **CONSTRAINT:** `include` is an allowlist inside the source path; `exclude` is defence in depth and never broadens `include`.
- **CONSTRAINT:** Every entry requires evidence references, source and exported digests, privacy review, provenance review, and owner approval.
- **CONSTRAINT:** Generated or transformed output is reviewed as a new artifact; source approval does not automatically approve transformed content.
- **CONSTRAINT:** A manifest with `status: locked`, null approval fields, a failed review, or any `owner_approved: false` entry authorises no export.
- **CONSTRAINT:** The export process must reject symlinks, files outside the repository root, nested repositories, submodules, ignored private directories, and unlisted generated files.

# Fictional estate specification

- **DECISION:** The only public demonstration estate contains three fictional repositories:

| Repository | Classification | Required demonstration purpose |
|---|---|---|
| `shop-api` | **DECISION: normal-risk daily driver** | Minimal repository instruction, ordinary test command, one on-demand procedural skill, and one non-sensitive failure fixture. |
| `billing-service` | **DECISION: high-risk production analogue** | Explicit human approval boundary, protected deployment assumption, no real payment integration, and a rejected automatic-promotion example. |
| `research-sandbox` | **DECISION: low-risk experimental repository** | Relaxed workflow, clear non-production status, and evidence that one global rule should not be applied universally. |

- **CONSTRAINT:** All organisations, users, domains, tokens, branches, paths, incidents, and logs are invented.
- **CONSTRAINT:** Fake credentials use unmistakably invalid placeholders and are never shaped like active provider keys.
- **CONSTRAINT:** The estate demonstrates information placement, installation, removal, one accepted manual promotion, and one rejected promotion. It does not simulate a live company, production deployment, or security incident.
- **CONSTRAINT:** The estate contains no external network dependency and runs entirely from local fixtures.
- **CONSTRAINT:** The estate is created only after BP-PRE-08 and the global unlock are satisfied.

# Candidate components and required evidence

- **DEFERRED:** The entries below are candidates, not approved exports.

| Candidate component | Current belief | Evidence required before allowlisting |
|---|---|---|
| `small-safe-slice` | A potentially portable skill for bounded implementation work | Two distinct repository uses; evidence that it reduces scope drift; clear anti-trigger; no duplication of repository-specific instructions. |
| `verify-and-handoff` | A potentially portable completion and evidence skill | Two distinct task classes; measurable reduction in incomplete handoff; exact verification interface configurable by repository. |
| `resume-repo-work` | Useful only after estate-specific assumptions are removed | Two successful resumptions in different repositories; no dependency on private estate registry, paths, or memory; bounded missing-context stop rule. |
| Minimal `review-and-ship` | Potentially useful with configurable review provider and risk class | Two reviewed PRs in different repositories; no fixed model/provider; owner-reviewed merge boundary; proof it does not add review ceremony to low-risk work. |
| Failure-ledger hook | Potentially reusable capture primitive | Stable schema use in at least two repositories; privacy tests; non-blocking failure behaviour; no raw prompt/command capture. |
| Session-orientation hook | Potentially reusable if driven by a public manifest | Two repositories using the same public manifest shape; bounded latency; explicit missing-input result; no private estate lookup. |
| Gardener report agent | Highest risk of recreating platform scope | Three useful manual cycles; tested kill switch; low proposal-noise rate; read-only default; no scheduler; no automatic edits. |

- **CONSTRAINT:** The first extracted component is selected by evidence strength and simplicity, not by this table order.
- **CONSTRAINT:** A candidate that fails its evidence requirement remains private or is retired; it is not weakened into a vague public template.

# Autonomy and self-improvement references

- **CONSTRAINT:** Apply `CLAUDE_CONFIG_OPERATIONS.md#autonomy-boundary`; destructive operations, dependencies, public pushes, scope changes, licences, and policy edits require owner review.
- **CONSTRAINT:** Apply the canonical failure-ledger schema and manual promotion-review template from `CLAUDE_CONFIG_OPERATIONS.md`; this repository defines no variant.
- **CONSTRAINT:** Any agent observation outside the thin scope becomes a backlog proposal with an evidence trigger. No automatic skill or documentation creation is permitted.

# Quality gates after unlock

- **DEFERRED:** The target quality-gate interface activates only after all preconditions hold:

```bash
python tools/plugin_gate.py fast
python tools/plugin_gate.py lint
python tools/plugin_gate.py test
python tools/plugin_gate.py privacy
```

- **CONSTRAINT:** `fast` must complete in under 60 seconds and validate manifest lock state, allowlisted paths, plugin structure, synthetic fixtures, and install/remove smoke tests.
- **CONSTRAINT:** Required CI checks before merge are `plugin-fast`, `plugin-lint`, `plugin-tests`, `privacy-boundary`, `allowlist-provenance`, and `operations-contract`.
- **CONSTRAINT:** Missing runtime tooling or a desired dependency is an owner-review stop; agents do not install it automatically.

# First 10 tasks

- **CONSTRAINT:** Every task below is **DEFERRED AND LOCKED** until BP-PRE-01 through BP-PRE-10 all hold. Listing a task does not authorise it.

## Task 1 — Verify and record all unlock preconditions

- **Classification:** DEFERRED
- **Time box:** 1 hour
- **Objective:** Produce a binary precondition report with evidence links and no implementation artifacts.
- **Paths touched:** `claude-config/extraction/precondition-report.md`, `HUMAN_TODO.md`.
- **Acceptance criteria:** All ten preconditions are marked satisfied or unsatisfied; no “partially satisfied” item unlocks work; owner decision field remains pending until reviewed.
- **Verify:** `python -c "from pathlib import Path; p=Path('extraction/precondition-report.md'); assert p.is_file(); t=p.read_text(encoding='utf-8'); assert all(f'BP-PRE-{i:02d}' in t for i in range(1,11))"`
- **Out of scope:** Creating `UNLOCK.md`, exporting files, choosing a name, or changing private components.
- **Stop condition:** Halt after the report when any precondition is unsatisfied.

## Task 2 — Create the owner unlock record

- **Classification:** DEFERRED
- **Time box:** 1 hour
- **Objective:** Record the explicit owner unlock, initial time budget, and first authorised component.
- **Paths touched:** `claude-config/extraction/UNLOCK.md`, `HUMAN_TODO.md`.
- **Acceptance criteria:** The owner, date, evidence links, chosen first task, maximum hours, and rollback are present; the file is created only after owner review.
- **Verify:** `python -c "from pathlib import Path; t=Path('extraction/UNLOCK.md').read_text(encoding='utf-8'); assert all(k in t for k in ['Owner:', 'Approved date:', 'First authorised task:', 'Maximum hours:', 'Rollback:'])"`
- **Out of scope:** Repository creation, code export, or broad approval of all candidates.
- **Stop condition:** Halt when owner approval is absent, ambiguous, or grants more scope than one bounded extraction slice.

## Task 3 — Create the thin plugin quality gate

- **Classification:** DEFERRED
- **Time box:** 1–2 hours
- **Objective:** Implement a standard-library-first `tools/plugin_gate.py` with only the checks required by this document.
- **Paths touched:** `tools/plugin_gate.py`, `tests/plugin_gate/`.
- **Acceptance criteria:** The tool exposes `self-test`, `preconditions`, `allowlist`, `export`, `fictional-estate`, `privacy`, `fast`, `lint`, and `test`; it adds no dependency; `fast` measures elapsed time and is designed to remain below 60 seconds.
- **Verify:** `python tools/plugin_gate.py self-test`
- **Out of scope:** General plugin framework, auto-remediation, remote scanning, packaging support for multiple runtimes, or policy compilation.
- **Stop condition:** Halt if a required check needs a new dependency or broad inspection of private content; request owner review or narrow the check.

## Task 4 — Approve one allowlist entry

- **Classification:** DEFERRED
- **Time box:** 1–2 hours
- **Objective:** Complete privacy, provenance, evidence, transformation, and digest fields for one component only.
- **Paths touched:** `claude-config/extraction/allowlist.yaml`, one component's evidence review.
- **Acceptance criteria:** Manifest validates; exactly one entry is approved; all other entries remain absent or false; source path contains no symlink or nested repository.
- **Verify:** `python tools/plugin_gate.py allowlist --component <component-id>`
- **Out of scope:** Batch approval, public copying, history export, or adding evidence after approval by inference.
- **Stop condition:** Halt on missing provenance, failed privacy review, or any unlisted file needed for the component to function.

## Task 5 — Create the clean locked public repository locally

- **Classification:** DEFERRED
- **Time box:** 1 hour
- **Objective:** Create a local repository containing only root governance, an approved manifest copy, and empty component directories.
- **Paths touched:** New repository root, `BLUEPRINT_PLUGIN_PRODUCT.md`, `.gitignore`, `HUMAN_TODO.md`.
- **Acceptance criteria:** Clean history; no private file copied; repository remains local/private; final remote/name/licence actions are human tasks.
- **Verify:** `git status --short && git log --oneline --max-count=3 && python -c "from pathlib import Path; assert Path('BLUEPRINT_PLUGIN_PRODUCT.md').is_file()"`
- **Out of scope:** Public remote, package metadata, component content, fictional estate, or plugin manifest.
- **Stop condition:** Halt before remote creation or if the approved repository name/licence is missing.

## Task 6 — Export the first allowlisted component

- **Classification:** DEFERRED
- **Time box:** 2–3 hours
- **Objective:** Clean-copy one approved component, apply named transforms, and produce source/export digest evidence.
- **Paths touched:** Only the allowlisted destination path, `docs/provenance/<component-id>.md`, manifest digest fields.
- **Acceptance criteria:** Export contains only included files; transformations are reviewed; source and exported hashes are recorded; private-pattern scan passes; component structural tests pass.
- **Verify:** `python tools/plugin_gate.py export --component <component-id> --verify-only`
- **Out of scope:** Exporting a second component, rewriting the component architecture, adding runtime dependencies, or changing its trigger.
- **Stop condition:** Halt when the component needs an unallowlisted private dependency or cannot work without estate-specific assumptions.

## Task 7 — Build the fictional-estate skeleton

- **Classification:** DEFERRED
- **Time box:** 2 hours
- **Objective:** Create only the three approved repository skeletons and synthetic manifests required to exercise the first component.
- **Paths touched:** `examples/fictional-estate/shop-api/`, `billing-service/`, `research-sandbox/`.
- **Acceptance criteria:** All names and data are fictional; no network is used; each repository states risk class and test command; only the first component is installed.
- **Verify:** `python tools/plugin_gate.py fictional-estate --fast`
- **Out of scope:** Full company simulation, real service code, cloud deployment, extra skills, or Gardener automation.
- **Stop condition:** Halt if a fixture resembles a real credential, customer, domain, repository, or incident.

## Task 8 — Add privacy and allowlist enforcement

- **Classification:** DEFERRED
- **Time box:** 1–2 hours
- **Objective:** Make default-deny export and built-artifact privacy checks mechanical.
- **Paths touched:** `tools/plugin_gate.py`, tests, `.github/workflows/ci.yml` after owner review.
- **Acceptance criteria:** Unlisted file, symlink, nested repository, absolute owner path, private-name fixture, and secret-like token fixtures fail; approved synthetic output passes.
- **Verify:** `python tools/plugin_gate.py privacy && python tools/plugin_gate.py allowlist`
- **Out of scope:** Uploading files to third-party scanners, scanning the entire private history, or auto-redacting failed output.
- **Stop condition:** Halt if enforcement requires sending private repository content outside the local/CI environment.

## Task 9 — Add plugin-structure and install/remove smoke validation

- **Classification:** DEFERRED
- **Time box:** 2 hours
- **Objective:** Validate the chosen packaging target and prove reversible installation in the fictional estate.
- **Paths touched:** Target-specific plugin manifest, local install/remove scripts, tests.
- **Acceptance criteria:** Installation affects only the documented target paths; removal restores the fixture; no global user configuration is changed; fast lane remains under 60 seconds.
- **Verify:** `python tools/plugin_gate.py fast && python tools/plugin_gate.py test`
- **Out of scope:** Supporting a second runtime, global installation, marketplace publication, or update service.
- **Stop condition:** Halt when the packaging target requires undocumented global mutation or credentials.

## Task 10 — Prepare, but do not publish, the first release candidate

- **Classification:** DEFERRED
- **Time box:** 2–4 hours
- **Objective:** Produce a local release packet containing the first proven component, fictional-estate demonstration, quality evidence, licence/provenance decision, and removal instructions.
- **Paths touched:** `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, release handoff, approved package files.
- **Acceptance criteria:** All quality gates pass; install/remove is reproducible; privacy boundary passes; one-component scope is clear; owner-only public actions are listed.
- **Verify:** `python tools/plugin_gate.py fast && python tools/plugin_gate.py lint && python tools/plugin_gate.py test && python tools/plugin_gate.py privacy`
- **Out of scope:** Public push, marketplace submission, second runtime, second component, scheduled Gardener, or automatic promotion.
- **Stop condition:** Halt at the owner-review boundary or when any precondition has become false since unlock.
