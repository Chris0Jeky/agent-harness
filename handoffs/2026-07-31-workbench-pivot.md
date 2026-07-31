# Handoff: workbench pivot continuity — 2026-07-31

Refresh all refs, PRs, issues, checks, reviews, comments, and worktrees before acting. This record
captures the state after PR #140 merged and while the two post-merge slices were still local.

## End-to-end objective

Operate `agent-harness` as the broader agent-operations workbench: preserve the frozen legacy
floor, use replay as the internal Policy Lab/evidence centre, and advance Doctor, bounded Pattern
Guard, estate operations, measurement, adapters, and private integration through executable,
independently verifiable slices.

## Completed

- PR #140 merged with merge commit `81125c57ec6d1a750ddd43b0110c6928f9f4a860` and parents
  `7a07238fb8a4d1af826343158abaf863051b6ef5` plus
  `6261c32e9040815ab38a15cb2c668d15358e2a05`. Every named successor commit is reachable from
  `origin/main`; #148/#149 closed; the one post-merge feedback check found no later comment,
  review, or thread.
- The protected `floor-v1-final` tag remains object
  `5a939540bdce51e511d6b3bae98358e3e2ad9148`, peeled
  `02bd14cfe094f9b6af85b966de481ff3f45264cf`.
- Workstream A is the sole writer in
  `C:\Users\jekyt\source\agent-harness\.worktrees\workbench-continuity-20260731`, branch
  `docs/workbench-continuity-20260731`. It creates the four canonical state homes, maps the live
  queue, corrects README and legacy-limitation contradictions, refreshes the tier review date,
  and preserves root `HANDOFF.md` as history.
- Workstream B is the sole writer in
  `C:\Users\jekyt\source\agent-harness\.worktrees\issue153-markdown-literal`, branch
  `fix/issue153-markdown-literal`. Exact local commit
  `e0f8fa5ab75147085d3bfcc5aaa0d7ebcb8222f6` implements issue #153 without a push or PR yet.

## Verification and measurements

- `py -3 harness.py audit . --offline` -> exit 0, T3 declaration and `HUMAN_TODO.md` verified.
- `py -3 harness.py doctor` -> exit 0; floor comparison is correctly `UNPROVEN` because the
  Workstream A checkout is a feature branch rather than canonical clean `main`.
- `.agent-harness/tier.json` parses with `py -3 -m json.tool`.
- Live issue set versus ROADMAP primary map -> 64 open, 64 mapped, no difference.
- `docs/SYSTEM_STATE.md` -> 53 lines; `FLOOR_LIMITATIONS.md` -> 54 lines, both within budget.
- Canonical and deployed Claude-hook `dispatch.py` SHA-256 both measured
  `E1A4E7714913788DD801F0FA43A3E5B30EA0433709F97142509B56B1C442EF68`, version 1.6.21.
- Workstream B at `e0f8fa5`: focused tests 6/6; replay unittest 108 passed with 10 declared
  Windows skips; pytest 98 passed with 10 skips and 58 subtests; Ruff, Black, compileall,
  extraction-manifest exactness, and diff checks passed serially.
- Measured baselines and their limitations are transcribed in `docs/BENCHMARKS.md`; no new
  performance or rollout claim was inferred.

## Decisions and limitations

- At most two workstreams remain active: continuity state and issue #153. Do not start a third.
- H-2 is the sole open `HUMAN_TODO.md` item and is owner-parked. Do not restart estate-wide
  canaries or disable the harness.
- PR #154/#151 and PR #155/#87 remain parked on cross-platform blockers. Their earlier CI predates
  PR #140's base change; do not duplicate their occupied worktrees or reuse that CI as current proof.
- Issue #21 plus #118/#120 is evidence for bounded Pattern Guard v2, not universal-parser expansion.
- #152/#153 are replay follow-ups, not workbench-wide priorities. AH-10 public extraction remains
  deferred; do not create a public replay repository or blueprint plugin.
- Duplicate replay suites must run serially: a deliberately parallel local attempt collided on
  their deterministic shared snapshot root. Both declared serial commands passed, matching CI.
- The older `replay-v0-freeze` worktree has ignored evidence and the `replay-tool` worktree has a
  staged user change. Leave both untouched unless separately proving removal safe.

## Exact next task

- **Objective:** finish both current slices through the bounded review-and-ship pipeline.
- **Files likely touched:** only the two existing writer checkouts named above.
- **Acceptance criteria:** one fresh-context review per slice; any confirmed CRITICAL/HIGH defect
  gets one bounded fix; exact heads pushed; ready PRs opened; required hosted CI green; each head
  ages three minutes; all comments/threads triaged once; merge commits preserve history.
- **Verification command, Workstream A:**
  `py -3 harness.py audit . --offline`; `py -3 harness.py doctor`;
  `py -3 -m json.tool .agent-harness\tier.json`; `git diff --check`.
- **Verification command, Workstream B:**
  `py -3 -m unittest replay_v0.tests.unit.test_compare -v`;
  `py -3 -m unittest discover -s replay_v0\tests -v`;
  `py -3 -m pytest -q replay_v0/tests`; replay Ruff/Black/compile/extraction checks;
  `git diff --check`.
- **Required corpus/benchmark update:** none for #153; its focused fixture is sufficient. Do not
  add a benchmark number without a pinned input, method, environment, result, and limitation.
- **Do not redo:** PR #140's closed review pipeline or post-merge check; H-2; estate-wide canaries;
  parked PR #154/#155 work; floor parser expansion; public extraction.
