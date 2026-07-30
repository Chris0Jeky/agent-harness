Purpose: Authoritative product, repository, launch, release, distribution, and continuation brief for the public decision-replay tool.
Status: ACTIVE under the owner-confirmed 2026-08-16 launch date and 24-hour total cap; public release still requires owner confirmation.
Authority relationship: This document wins for the public replay product, clean-repository decision, working name, README, release, outreach, and continuation gate; `AGENT_HARNESS_OPERATIONS.md` wins for replay-kernel technical contracts and `CLAUDE_CONFIG_OPERATIONS.md` wins for owner-supervision policy.
Last-reviewed date: 2026-07-30
Owner: Cristian Tcaci

# Decision register

- **DECISION RP-001:** The owner confirmed the launch deadline of **2026-08-16**.
- **DECISION RP-002:** The owner confirmed the hard launch budget of **24 focused hours**, split as 13 hours under `AGENT_HARNESS_OPERATIONS.md` and 11 hours under this document.
- **DECISION RP-003:** The owner confirmed the continuation review date of **2026-09-30**.
- **OPEN RP-004:** Select the final repository, Python package, and CLI name. `CharterReplay` / `charter-replay` is the working recommendation.
- **OPEN RP-005:** Select the licence after provenance review. The recommendation is Apache-2.0 when all extracted code is owner-controlled and compatible; otherwise preserve the most restrictive compatible existing licence and record the reason.

# Repository decision

- **DECISION:** The public replay product is a **clean new repository**, not a public release branch inside the existing `agent-harness` repository.
- **DECISION:** The clean repository receives only the allowlisted replay kernel, schemas, synthetic/redacted charter corpus, deterministic tests, product documentation, and examples.
- **CONSTRAINT:** The clean repository receives no legacy dispatcher source, private configuration, private corpus, raw history, machine paths, client/project identity, or private Git history.
- **CONSTRAINT:** The existing `agent-harness` repository remains the evidence archive, frozen baseline source, postmortem source, and extraction workspace.
- **DECISION:** This separation is chosen because the public product must install and reproduce its report without the 12,000-line legacy environment, and because selective copying is safer and easier to explain than history rewriting.
- **CONSTRAINT:** Repository creation, visibility selection, public push, package-name reservation, and release publication require owner review under `CLAUDE_CONFIG_OPERATIONS.md#autonomy-boundary`.

# Candidate names

| Candidate | Classification | Decision rationale |
|---|---|---|
| `CharterReplay` / `charter-replay` | **DECISION: working recommendation** | Distinctive, tied to the small charter corpus, and broad enough to compare recorded and executable policies without claiming full agent replay. The README tagline supplies immediate meaning. |
| `PolicyReplay` / `policy-replay` | **OPEN alternative** | Maximally descriptive but generic, harder to search, and more likely to collide with existing policy-replay terminology. |
| `CommandPolicyReplay` / `command-policy-replay` | **OPEN alternative** | Technically explicit and honest, but long for a repository, package, and CLI command. |

- **CONSTRAINT:** Before public creation, the owner must recheck GitHub, PyPI, package-manager, and basic web-name availability. Search findings are time-sensitive and are not a reservation.
- **CONSTRAINT:** The implementation uses `charter_replay` as the provisional import package and `charter-replay` as the provisional CLI until RP-004 is resolved.

# Product definition

- **DECISION:** Product sentence:

> `CharterReplay` compares two coding-agent command-policy decision sources over a pinned corpus and fails when the candidate introduces configured safety or interruption regressions.

- **DECISION:** The primary user is a developer or maintainer changing a command guard, hook, or policy who needs a reproducible before/after decision report.
- **DECISION:** The primary portfolio outcome is a credible engineering case study backed by executable proof.
- **DECISION:** External product adoption is conditional and is evaluated separately on 2026-09-30 if that date is confirmed.
- **CONSTRAINT:** The product is described as decision replay, not agent replay, environment replay, command execution, sandboxing, or complete safety enforcement.
- **CONSTRAINT:** The public core implements exactly the technical contract in `AGENT_HARNESS_OPERATIONS.md`; this document does not redefine the event or decision schemas.

# Non-Goals

- **CONSTRAINT:** No live command blocking, approval workflow, sandbox, policy authoring language, shell interpreter, generic tool-event model, agent trajectory replay, observability platform, configuration doctor, promotion engine, or blueprint plugin.
- **CONSTRAINT:** No claim that a policy is universally safe, that a command was executed, or that an original failure was reproduced.
- **CONSTRAINT:** No hosted service, account system, database, web UI, telemetry collection, or network requirement in v0.
- **CONSTRAINT:** No broad integration framework. External systems use the generic process contract or recorded decisions.
- **CONSTRAINT:** No benchmark, leaderboard, academic paper, or “industry standard” language for the initial charter corpus.

# Sixty-second README specification

- **DECISION:** The first visible screen of `README.md` contains exactly these five product elements before architecture or history.

## 1. One-line purpose

- **DECISION:** Use:

> Compare coding-agent command policies against a pinned replay corpus and catch decision regressions before release.

## 2. Demo GIF

- **DECISION:** The GIF storyboard is 60–90 seconds and shows:
  1. A single `charter-replay replay` command.
  2. A baseline recording and candidate process policy.
  3. A summary with one newly allowed dangerous case, zero newly denied benign cases, and one indeterminate case.
  4. Exit code `1` and the generated Markdown report.
  5. The limitation line: “Recorded decisions were compared; no command was executed.”
- **CONSTRAINT:** The GIF contains fictional paths, synthetic commands, no username, no home directory, no private repository, and no terminal history outside the demo.

## 3. One install command

- **DECISION:** The release README shows one install command only.
- **OPEN:** Preferred command, if the PyPI name is secured:

```bash
pipx install charter-replay
```

- **OPEN:** If PyPI publication is not approved or the name is unavailable, replace the block with one exact immutable Git-tag install command. Do not show both alternatives above the fold.

## 4. One replay command

- **DECISION:** Use this shape with paths included in the repository:

```bash
charter-replay replay \
  --baseline recorded:examples/legacy-baseline/decisions.jsonl \
  --candidate process:python,examples/candidate-policy/policy.py \
  --corpus corpora/charter/events.jsonl \
  --output reports/demo
```

## 5. One limitation statement

- **DECISION:** Use:

> This re-evaluates recorded command events and decisions. It does not reproduce the original agent, environment, shell effects, or operating-system boundary.

- **CONSTRAINT:** The README may link to the postmortem, threat model, schemas, and extension guide below the first screen, but it may not insert feature tables or architecture diagrams before the five required elements.

# Public repository layout

- **DECISION:** The clean repository uses this bounded layout:

```text
charter-replay/
  REPLAY_TOOL_PRODUCT.md
  README.md
  LICENSE
  SECURITY.md
  CONTRIBUTING.md
  pyproject.toml
  src/charter_replay/
    __init__.py
    cli.py
    compare.py
    corpus.py
    digests.py
    manifests.py
    policy_sources.py
    reports.py
    schemas/
  corpora/charter/
  examples/
    legacy-baseline/
    candidate-policy/
    dcg/
  tests/
    unit/
    contract/
    charter/
  docs/
    decision-replay-boundary.md
    postmortem.md
    continuation-review.md
  .github/workflows/
```

- **CONSTRAINT:** No `legacy/`, `experimental/`, private overlay, raw transcript, or copied planning archive is included.
- **CONSTRAINT:** Background design is summarised through the postmortem; the public repository does not ship the entire planning corpus.

# Versioning and release process

- **DECISION:** Product releases use Semantic Versioning; the first public release is `v0.1.0`.
- **DECISION:** JSON schema identifiers version independently through names such as `command-event.v1`; a package patch release may fix implementation without changing a schema identifier.
- **CONSTRAINT:** A breaking schema or CLI change before `1.0.0` still requires a release-note callout, migration note, and updated fixtures.
- **CONSTRAINT:** Every release candidate must pass all quality gates, install into a clean environment, run the README command, and reproduce the checked-in demo report semantics.
- **CONSTRAINT:** Tags are annotated and created only after owner review. Public push, GitHub release, and package publication are human actions recorded in `HUMAN_TODO.md`.
- **CONSTRAINT:** Release artifacts contain source and wheel only; no binary executable, private corpus, generated local report containing machine data, or vendored third-party guard.
- **CONSTRAINT:** The package has no runtime dependency unless the owner approves one. Development dependencies are declared in one owner-reviewed `dev` extra.
- **DECISION:** Release checklist:
  1. Update version and changelog.
  2. Run fast, lint, full tests, charter replay, and build.
  3. Install the wheel into a clean virtual environment.
  4. Run the README replay command.
  5. Review generated files for private paths and secrets.
  6. Owner approves licence, tag, public push, and publication.
  7. Create `v0.1.0`, publish release notes, and verify installation.

# Licence decision

- **OPEN:** Final licence is owner-selected after checking the existing `agent-harness` licence and the provenance of every copied file.
- **DECISION:** Recommended default is Apache-2.0 because it is permissive, includes an explicit patent grant, and is legible to organisational users.
- **CONSTRAINT:** If any extracted file is incompatible with Apache-2.0, it is excluded or the repository uses the compatible licence chosen by the owner. An agent must not relicense copied code by assumption.
- **CONSTRAINT:** `LICENSE`, licence headers, `pyproject.toml`, README badges, and contribution terms must agree before release.

# `SECURITY.md` contract

- **DECISION:** `SECURITY.md` must state supported versions, private vulnerability-reporting route, response expectations without guaranteed SLA, security boundary, privacy expectations for corpus submissions, and safe reproduction rules.
- **CONSTRAINT:** It must explicitly state that the tool does not execute corpus commands and is not a sandbox or enforcement layer.
- **CONSTRAINT:** It must instruct reporters not to submit credentials, private repositories, raw transcripts, customer data, or operational exploit payloads when a synthetic reproduction is possible.
- **CONSTRAINT:** GitHub private vulnerability reporting is preferred if enabled; the owner must supply any public security contact.
- **CONSTRAINT:** Security-policy edits require owner review.

# `CONTRIBUTING.md` contract

- **DECISION:** `CONTRIBUTING.md` requires a scoped issue or proposal before new features, one-purpose PRs, synthetic fixtures, schema validation, all quality gates, and an explicit non-goal check.
- **CONSTRAINT:** Contributors may add a corpus case only with provenance, privacy review, case class, rationale, and a demonstration that it is not a duplicate.
- **CONSTRAINT:** New runtime dependencies, new policy effects, schema fields, integrations, or public claims require an owner-approved design issue.
- **CONSTRAINT:** Contributions must not include real secrets, private commands, malware, pirated software, destructive payload execution, or instructions for bypassing third-party controls.

# DCG compatibility worked example

- **DECISION:** The first external example targets Destructive Command Guard (DCG) because it is a direct command-guard neighbour and can be represented through the generic process or recorded-decision contract without changing the core.
- **DECISION:** The public example compares a pinned DCG decision recording with a candidate recording or an owner-approved local DCG shim over the same charter events.
- **CONSTRAINT:** The core package contains no DCG-specific import and does not vendor DCG.
- **CONSTRAINT:** CI reproduces the example from recorded decisions. Live DCG installation and capture are owner-reviewed optional steps documented separately.
- **CONSTRAINT:** The report is descriptive and does not rank or declare a universal winner.
- **CONSTRAINT:** The example records DCG version/commit, recording digest, corpus digest, unsupported cases, and the exact reproduction command.

# Outreach checklist

- **DECISION:** Prepare five separate, concise messages after `v0.1.0` is reproducible. The owner sends them; agents may draft only.
- **CONSTRAINT:** Each message includes one report link, one reproduction command, one limitation sentence, and one specific question. No bulk generic announcement is sent as direct outreach.

| Message | Named target | Specific question |
|---:|---|---|
| 1 | `@Dicklesworthstone`, maintainer of `destructive_command_guard` | “Would a release-to-release recorded decision diff like this be useful in DCG rule-pack CI, and which output field would make it actionable?” |
| 2 | `@sheeki03`, maintainer of Tirith | “Can the generic process contract represent a useful subset of Tirith decisions without misrepresenting its broader payload/config coverage?” |
| 3 | `agent-sh` maintainers of Agnix | “Would the charter corpus format be useful for configuration-rule regression cases, or should configuration validation remain a separate future corpus?” |
| 4 | `@clay-good`, maintainer of `agent-replay` | “Is the distinction between decision replay and trajectory replay clear, and is there a compatibility boundary worth documenting?” |
| 5 | Maintainers of `microsoft/agent-governance-toolkit` | “Does the recorded-decision source format complement policy replay fixtures, and what minimum provenance would make cross-tool comparison trustworthy?” |

- **CONSTRAINT:** If a named project or maintainer has changed before launch, the owner revalidates the target. Agents must not guess contact identities.

# Success and continuation gates

## Portfolio completion

- **DECISION:** Portfolio completion is achieved when all of these exist:
  - A published or owner-approved postmortem.
  - A tagged `v0.1.0` clean repository.
  - One reproducible replay command.
  - A small charter corpus.
  - A 60–90 second demo.
  - Clear limitations.
  - Five drafted targeted messages.
- **DECISION:** Portfolio completion does not depend on stars, page views, or external adoption.

## Product continuation

- **OPEN:** Review date is 2026-09-30.
- **DECISION:** Continue expanding the public product only if at least one strong signal exists:
  - One external guard maintainer uses, links, contributes to, or requests the workflow.
  - Three unaffiliated users successfully run it and provide concrete policy or corpus feedback.
  - One external integration or corpus contribution is opened.
  - A real user identifies a policy regression they would not otherwise have caught.
- **CONSTRAINT:** Stars, impressions, likes, and post views are contextual signals only; they do not satisfy the continuation gate by themselves.
- **DECISION:** If no strong signal exists at review, freeze the tool at a clean v0.x, fix only serious defects, retain the postmortem and corpus, and return engineering time to higher-priority work.
- **CONSTRAINT:** Failure to meet the continuation gate does not reopen the legacy parser or authorise a broader product pivot.

# Deferred backlog with evidence triggers

- **DEFERRED:** Every row below is deferred exactly as stated. No row is part of v0.

| Deferred idea | Implement only when… |
|---|---|
| Capability manifest | A second real adapter lacks information that materially changes comparison validity |
| Richer event model | A real non-command event must be replayed |
| Authorisation context | An actual approval workflow becomes part of replay |
| Hazard taxonomy | Two policies cannot be compared meaningfully using simple case labels |
| Metamorphic tests | A real normalisation variation causes a regression |
| Policy DSL | Repeated code-based rules demonstrate a stable common grammar |
| Configuration Doctor | External users repeatedly cannot determine which configuration is active |
| Live runtime adapter | Users ask to move from offline comparison to interception |
| Public Claude-config blueprint | At least two components prove useful across multiple repositories |
| Promotion Engine | Several manual promotion decisions reveal a repeatable workflow |
| Academic paper | External comparisons produce a defensible methodological contribution |

- **CONSTRAINT:** A deferred item unlocks only when its named trigger is evidenced in an issue and the owner approves a new bounded task contract.

# Autonomy and self-improvement references

- **CONSTRAINT:** Apply the owner-review and destructive-operation rules from `CLAUDE_CONFIG_OPERATIONS.md#autonomy-boundary`.
- **CONSTRAINT:** Use the failure-ledger schema from `CLAUDE_CONFIG_OPERATIONS.md#failure-and-friction-ledger`; the recommended untracked path is `.local/failure-ledger.jsonl`.
- **CONSTRAINT:** Use the manual promotion template from `CLAUDE_CONFIG_OPERATIONS.md#manual-self-improvement-loop`; no automatic skill, rule, documentation, or integration creation is permitted.
- **CONSTRAINT:** Any discovered work outside this product scope is appended to `HUMAN_TODO.md` as a backlog proposal with a named evidence trigger; it is not implemented under v0.
- **CONSTRAINT:** Public contributors follow `CONTRIBUTING.md`; the private operating contract governs owner-supervised agents and is not a substitute for contributor terms.

# Quality gates

- **DECISION:** Pytest 9.0.3 is approved for the extraction compatibility gate. Ruff is already pinned in the extraction repository. Adding or upgrading `build`, or changing these versions in the clean product repository, still requires owner review.
- **DECISION:** Required local commands are:

```bash
python -m pytest -q tests/unit tests/contract
python -m ruff check .
python -m pytest -q
python -m build
charter-replay replay --baseline recorded:examples/legacy-baseline/decisions.jsonl --candidate process:python,examples/candidate-policy/policy.py --corpus corpora/charter/events.jsonl --output .local/release-proof
```

- **CONSTRAINT:** The first command is the fast lane and must complete in under 60 seconds without network access.
- **CONSTRAINT:** Required CI checks before merge are `fast`, `lint`, `tests`, `charter-replay`, `build`, `privacy-scan`, and `operations-contract`.
- **CONSTRAINT:** `privacy-scan` checks tracked files and built artifacts for forbidden owner paths, private repository names, credential patterns, and files outside the extraction allowlist; it does not upload repository content.
- **CONSTRAINT:** CI has read-only repository permissions unless a separately reviewed release job requires more.

# Calendar and budget allocation

- **DECISION:** The owner confirmed launch by 2026-08-16.
- **DECISION:** The first ten tasks below have a combined maximum of **11 hours**. Together with the 13-hour extraction allocation, they exhaust the 24-hour cap.
- **CONSTRAINT:** At 24 cumulative hours, agents stop, report the completed subset, and route omitted polish to the deferred backlog. The deadline does not authorise overtime or scope expansion.

# First 10 tasks

## Task 1 — Create the clean local repository and reserve the working identity

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-10 to 2026-08-12
- **Objective:** Create a local clean repository using the provisional `charter-replay` name and add only root governance files.
- **Paths touched:** New repository root, `REPLAY_TOOL_PRODUCT.md`, `.gitignore`, `HUMAN_TODO.md`.
- **Acceptance criteria:** `git log` begins with clean public-intent history; no file from private Git history is imported; `HUMAN_TODO.md` contains final name, visibility, licence, and remote-creation actions.
- **Verify:** `git status --short && git log --oneline --max-count=3 && python -c "from pathlib import Path; assert Path('REPLAY_TOOL_PRODUCT.md').is_file()"`
- **Out of scope:** Creating a public remote, reserving PyPI, adding product source, selecting licence without owner review, or copying planning archives.
- **Stop condition:** Halt before any remote creation or public push and when the final name is not owner-approved.

## Task 2 — Import the allowlisted replay bundle and package skeleton

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-12 to 2026-08-13
- **Objective:** Copy the approved v0 bundle, place it under `src/charter_replay`, and create the minimal package metadata.
- **Paths touched:** `src/charter_replay/`, `tests/`, `corpora/`, `examples/legacy-baseline/`, `examples/candidate-policy/`, `pyproject.toml`, `tools/product_gate.py`.
- **Acceptance criteria:** Only manifest-listed files are copied; import succeeds; provisional CLI help works; no runtime dependency is added; provenance is recorded in the initial commit message or `docs/extraction-provenance.md`; a small standard-library `product_gate.py` exposes `self-test`, `readme`, `public-docs`, `demo`, `privacy`, `outreach`, `release`, and `release-handoff` checks without becoming a general framework.
- **Verify:** `python tools/product_gate.py self-test && python -m pytest -q tests/unit tests/contract`
- **Out of scope:** Legacy source, private tests, history import, DCG files, release publication, or source redesign.
- **Stop condition:** Halt when any source file is absent from the approved extraction manifest, has unclear licence provenance, or contains private identifiers.

## Task 3 — Build the sixty-second README

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-13 to 2026-08-14
- **Objective:** Implement the exact first-screen README specification and a concise limitations-first continuation.
- **Paths touched:** `README.md`, static placeholder path for the demo GIF.
- **Acceptance criteria:** The first screen contains one purpose line, one GIF placeholder, one install command block, one replay command block, and one limitation statement; no architecture diagram or feature matrix precedes them.
- **Verify:** `python tools/product_gate.py readme`
- **Out of scope:** Long research summary, competitor comparison, benchmark claims, roadmap expansion, or multiple install methods above the fold.
- **Stop condition:** Halt if the final package name or install source is unresolved; leave one marked placeholder and add RP-004 to `HUMAN_TODO.md` rather than showing multiple commands.

## Task 4 — Add licence-decision package, security policy, and contribution contract

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-13 to 2026-08-14
- **Objective:** Prepare `SECURITY.md`, `CONTRIBUTING.md`, provenance evidence, and the owner licence decision item.
- **Paths touched:** `SECURITY.md`, `CONTRIBUTING.md`, `docs/licence-provenance.md`, `HUMAN_TODO.md`; `LICENSE` only after owner selection.
- **Acceptance criteria:** Both documents meet their contracts; provenance lists every extracted source path and prior licence; no unsupported contact or SLA is invented.
- **Verify:** `python tools/product_gate.py public-docs SECURITY.md CONTRIBUTING.md docs/licence-provenance.md`
- **Out of scope:** Selecting or changing the licence autonomously, adding a code of conduct without owner direction, or copying third-party policy text.
- **Stop condition:** Halt before writing `LICENSE` when provenance is incomplete or licence compatibility is uncertain.

## Task 5 — Record the demo GIF from a fictional clean terminal

- **Classification:** DECISION
- **Time box:** 1.5 hours
- **Calendar slot:** 2026-08-14
- **Objective:** Produce the 60–90 second storyboard asset showing a configured regression and generated report.
- **Paths touched:** `docs/assets/demo.cast` or source recording, `docs/assets/demo.gif`, `README.md`.
- **Acceptance criteria:** The demo follows the five storyboard steps; all paths and commands are fictional; it shows exit `1`; no unrelated terminal content is visible; the GIF remains legible at README width.
- **Verify:** `python tools/product_gate.py demo docs/assets/demo.gif && python tools/product_gate.py readme`
- **Out of scope:** Voice-over, promotional video, multiple scenarios, live destructive commands, or private screen recording.
- **Stop condition:** Halt and discard the recording if any username, token, private path, notification, browser tab, or unrelated shell history appears.

## Task 6 — Add release CI and build a local `v0.1.0` candidate

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-14 to 2026-08-15
- **Objective:** Implement least-privilege CI and produce a locally installable release candidate without publishing it.
- **Paths touched:** `.github/workflows/ci.yml`, optional owner-reviewed release workflow, `pyproject.toml`, `CHANGELOG.md`.
- **Acceptance criteria:** Required checks are present; workflow permissions default to read-only; wheel and source archive build; clean-environment install and README replay succeed.
- **Verify:** `python -m ruff check . && python -m pytest -q && python -m build && python tools/product_gate.py release dist/`
- **Out of scope:** Trusted publishing setup, PyPI upload, GitHub release, signing infrastructure, or automatic tag creation.
- **Stop condition:** Halt if a workflow requests write, id-token, package, or release permissions without a separately reviewed release need.

## Task 7 — Finish the postmortem and launch bundle

- **Classification:** DECISION
- **Time box:** 1.5 hours
- **Calendar slot:** 2026-08-15
- **Objective:** Turn the existing retrospective into a concise public postmortem linked to executable proof.
- **Paths touched:** `docs/postmortem.md`, `docs/launch-note.md`, README link.
- **Acceptance criteria:** The postmortem states the original hypothesis, measured 12–14% false-positive/friction result if supported by retained evidence, review-fix loop, architecture correction, preserved assets, decision-replay boundary, and explicit limitations; every quantitative claim has an internal evidence reference.
- **Verify:** `python tools/product_gate.py public-docs docs/postmortem.md docs/launch-note.md && python tools/product_gate.py privacy docs/postmortem.md docs/launch-note.md`
- **Out of scope:** Research literature review, blaming specific agents or vendors, broad market claims, or publishing unsupported internal metrics.
- **Stop condition:** Halt on any number that cannot be traced to retained evidence; replace it with a qualitative statement or request owner confirmation.

## Task 8 — Produce the DCG compatibility worked example

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-15 to 2026-08-16
- **Objective:** Add a thin example that compares pinned DCG decision recordings or an owner-approved local shim without changing core code.
- **Paths touched:** `examples/dcg/README.md`, `examples/dcg/decisions-*.jsonl`, manifests, `examples/dcg/report/`, optional `examples/dcg/shim.py`.
- **Acceptance criteria:** The example names the pinned source version, unsupported cases, digests, exact replay command, and neutral findings; CI reproduces it from recordings without installing DCG.
- **Verify:** `charter-replay replay --baseline recorded:examples/dcg/decisions-baseline.jsonl --candidate recorded:examples/dcg/decisions-candidate.jsonl --corpus corpora/charter/events.jsonl --output examples/dcg/report`
- **Out of scope:** Ranking DCG, bundling its binary/source, installing it without approval, opening a maintainer PR, or adding a DCG-specific core adapter.
- **Stop condition:** Halt if live capture requires a download, dependency, network access, or uncertain CLI invocation; prepare the recording contract and route capture to `HUMAN_TODO.md`.

## Task 9 — Draft the five targeted outreach messages

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-16
- **Objective:** Draft one tailored message for each named target and one public launch post, without sending any message.
- **Paths touched:** `docs/outreach/01-dcg.md` through `05-governance-toolkit.md`, `docs/outreach/public-launch.md`, `HUMAN_TODO.md`.
- **Acceptance criteria:** Each direct message contains one report, one command, one limitation, and one specific question; the public post links the postmortem, demo, and repository; no message claims endorsement.
- **Verify:** `python tools/product_gate.py outreach docs/outreach`
- **Out of scope:** Sending messages, tagging maintainers publicly without approval, repeated cross-posting, automated outreach, or follower scraping.
- **Stop condition:** Halt if a named handle cannot be verified at launch; leave the draft unsent and add a human verification item.

## Task 10 — Prepare the owner release handoff and continuation record

- **Classification:** DECISION
- **Time box:** 1 hour
- **Calendar slot:** 2026-08-16
- **Objective:** Present one owner-review packet for name, licence, remote, tag, publication, outreach, and the 2026-09-30 continuation review.
- **Paths touched:** `docs/release-handoff-v0.1.0.md`, `docs/continuation-review.md`, `HUMAN_TODO.md`.
- **Acceptance criteria:** All quality-gate outputs and reproduction commands are linked; cumulative hours are recorded; every human-only release action is explicit; continuation criteria are prefilled without fabricated results.
- **Verify:** `python tools/product_gate.py release-handoff docs/release-handoff-v0.1.0.md docs/continuation-review.md && git status --short`
- **Out of scope:** Public push, tag, PyPI publication, outreach sending, changing continuation criteria after results are known, or consuming more than the remaining hour budget.
- **Stop condition:** Halt at the owner-review boundary. No public action occurs until the owner resolves RP-001 through RP-005 and approves the release packet.
