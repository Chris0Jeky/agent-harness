# Replay v0 extraction inventory

Status: **COMPLETE for current `main` at `8f468231cb02632b2f2062e501ce7ccdd708675c`**

Recorded: 2026-07-30

This inventory implements Task 2 of `AGENT_HARNESS_OPERATIONS.md`. It identifies candidate
assets without moving, copying, executing, or opening private transcript/corpus data. Git and the
published repository state outrank older branch or handoff prose.

## Decision vocabulary

- **Keep legacy reference** — useful evidence in this existing repository, but never copied into
  replay v0.
- **Rewrite** — retain only the contract or case idea and implement it afresh against the v0
  schemas. No source-level copy.
- **Drop** — unrelated, unsafe to extract, or explicitly outside the product boundary.
- **Create** — a required v0 asset does not exist and must be authored from privacy-reviewed
  synthetic or redacted inputs.

Effort estimates are extraction effort within the operations program, not historical effort or a
promise about the unconfirmed launch calendar.

## Candidate assets

| Current path or source | Current purpose | Disclosure/privacy risk | Decision | Estimated extraction effort |
|---|---|---|---|---:|
| `templates/hooks/dispatch.py` at proposed freeze commit `02bd14c` | Live legacy deny-floor implementation and source of recorded policy identity | Low disclosure risk in the already-public repository, but copying it would violate the v0 no-legacy-runtime boundary and carry repository-specific enforcement semantics | **Keep legacy reference; drop from bundle.** Identify it only by commit/version in a recording manifest | 0.1 h |
| `templates/hooks/smoke_test.py` | Self-counting canonical allow/deny matrix for the legacy dispatcher | Mostly synthetic commands, but tightly coupled to legacy effects, tiers, runtime responses, and host probes; wholesale reuse would turn v0 into a parser conformance suite | **Rewrite selected case concepts.** Re-author a small privacy-safe charter; do not copy the harness | 0.6 h in Task 9 |
| `tests/test_prefix_wrapper_crossproduct.py` | Large both-direction wrapper/prefix gate over the legacy deny corpus | Synthetic, but contains legacy parser taxonomy, expected bypasses, and executable-shape fixtures far beyond v0 | **Drop implementation; rewrite only a few distinct regression ideas** that survive charter review | 0.2 h in Task 9 |
| Focused dispatcher tests under `tests/test_*.py` other than replay tests | Unit/contract evidence for floor parsing, Git/config probes, worktrees, adapters, and false-positive fixes | Low direct disclosure risk; high coupling and scope contamination | **Keep legacy reference; drop from bundle.** Cite issue/family evidence rather than copying tests | 0.1 h |
| `FLOOR_LIMITATIONS.md` plus public issues #21, #96, #133–#138 and merged PR #132 review evidence | Decision history, measured false-positive families, accepted limits, and unresolved review claims | Public evidence, but examples can still encode legacy-specific assumptions and must not be treated as truth labels automatically | **Keep as background; rewrite case rationales.** Never infer charter class from a legacy verdict | 0.3 h in Task 9 |
| `scripts/replay_corpus.py` | Offline comparison of two dispatcher versions over real Claude/Codex transcript commands; can emit raw JSON/corpus cache | **High.** Its own privacy contract warns that commands can include repository paths, branch names, private prompts, and pasted tokens; full command text belongs only in scratch output | **Keep legacy reference; drop/rewrite.** v0 gets new schema-bound sources, comparison, and reports with no transcript scanner | 0 h copy; Tasks 4–8 implement replacements |
| `tests/test_replay_corpus.py` | Tests the legacy transcript scanner, multiprocessing, offline stubs, cache integrity, and old/new dispatcher invocation | Medium: fixtures and assumptions include machine/repository identity signals; behavior is coupled to private transcript ingestion and legacy `check()` signatures | **Drop/rewrite.** Create focused v0 unit and contract tests from the operations contract | 0.4 h across Tasks 3–8 |
| `tests/fixtures/floor_1_2_0_dispatch.py` | Historical dispatcher source fixture used to exercise legacy replay signature compatibility | Low direct disclosure risk, but it is legacy implementation code rather than a decision recording | **Keep legacy reference; drop from bundle.** Recorded `PolicyDecision` JSONL replaces executable baselines | 0 h |
| `scripts/generate_curl_option_arity_fixture.py`, `tests/fixtures/curl_8_21_0_option_arity.json`, `tests/test_curl_option_arity.py` | Generates and verifies Curl option-arity data for the legacy parser | Low-to-medium: includes external URL/path vocabulary and is unrelated to decision replay | **Drop.** No v0 contract depends on Curl option parsing | 0 h |
| `HANDOFF.md` and historical branch/PR narratives | Operational history for prior floor work | Stale by construction; may cite local scratch paths and superseded heads | **Drop.** Freeze record and live Git/GitHub evidence are the extraction sources of truth | 0 h |
| Occupied `.worktrees/replay-tool` checkout on `tooling/corpus-replay` | Local continuation of the already-merged legacy replay tool | **High work-loss/collision risk.** It is about 310 commits behind current `main` and has a staged, uncommitted `scripts/replay_corpus.py` change (+209/−9) owned by another writer | **Do not touch or extract.** Current `main` plus this inventory define the usable baseline | 0 h |
| Tracked JSONL corpus or `PolicyDecision` recording | Required v0 event/decision input | **Absent.** `git ls-files` found no tracked `*.jsonl`, `replay_v0/`, recorded baseline, or charter corpus | **Create** only after schemas exist, using reviewed synthetic/redacted records and exact-byte manifests | 0.7 h in Tasks 4 and 9 |

## Baseline recording gap

There is no committed decision recording that satisfies `PolicyDecision` v1. In particular:

- the historical dispatcher fixture is executable Python, not recorded decisions;
- the smoke matrix embeds expected legacy outcomes in test code, not stable event-keyed JSONL;
- legacy replay JSON/cache output is scratch-only and can contain unreviewed private commands; and
- no manifest binds a committed decision set to a legacy commit, environment note, or digest.

Task 4 must therefore implement a recorded-decision source against synthetic fixtures. Task 9 must
author or owner-review a matching privacy-safe baseline recording and sidecar manifest. Missing,
duplicate, malformed, or digest-mismatched records must remain `indeterminate`; no task may fill the
gap by executing the frozen dispatcher in the public product repository.

## Safe inputs for the charter

The charter may draw **ideas**, not files, from these reviewed categories:

- canonical destructive Git and filesystem shapes already represented with fictional identifiers;
- benign quoted documentation, help, dry-run, and non-executing near-misses;
- a small number of historically important wrapper, redirection, interpreter, and worktree cases;
  and
- deliberately opaque cases whose expected class is `opaque`, independent of any legacy decision.

Every selected case must be re-authored with a new stable `event_id`, fictional/redacted `cwd`,
approved provenance, and no owner path, private URL, repository identity, credential-like value,
customer/staff/student data, or raw transcript text. A case that cannot preserve its relevant
structure after sanitisation remains private and is replaced with a synthetic case.

## Explicit extraction denylist

Task 10's allowlisted public bundle must exclude:

- `templates/hooks/` and every legacy dispatcher fixture;
- `scripts/replay_corpus.py` and `tests/test_replay_corpus.py`;
- all raw transcript, cache, report, or locally generated replay output;
- `.git/`, Git history, `.worktrees/`, local failure ledgers, and machine state;
- `HANDOFF.md`, private scratch references, and unreviewed historical examples; and
- any file not explicitly named by `docs/extraction/public-v0-manifest.json`.

## Prerequisites and blockers carried forward

- The live GitHub repository is public even though `AGENT_HARNESS_OPERATIONS.md` calls it private.
  Treat every tracked artifact as public; H-12 owns the visibility decision.
- `CLAUDE_CONFIG_OPERATIONS.md` and `REPLAY_TOOL_PRODUCT.md` are absent from the searched repository,
  history, and local authority locations. H-9 owns their authoritative locations.
- Ruff and Black are pinned in `requirements-dev.txt`; CI uses `unittest`. Pytest is installed on
  this machine but is not an approved repository dependency. H-10 owns the Task 3 command-contract
  choice.
- The exact tag, launch calendar, and time allocation remain owner decisions in H-8 and H-11.

None of these blocks local, standard-library, privacy-safe implementation that makes no public or
cross-repository change. They do block claims that publication, naming, licensing, schedule, or the
Pytest-based merge gate is approved.

## Verification performed

- Inspected tracked-path inventory on current `main` and the occupied replay checkout's Git
  metadata without modifying it.
- Confirmed PR #33 is merged and no current PR owns `tooling/corpus-replay`.
- Used static help/docstring and symbol searches; did not run replay against transcripts or open raw
  corpus/cache output.
- Confirmed no tracked `replay_v0/`, JSONL corpus, or recorded decision baseline exists.
- Confirmed this task moved or copied no source asset.
