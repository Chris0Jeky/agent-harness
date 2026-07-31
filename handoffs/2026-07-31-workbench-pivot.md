# Handoff: workbench pivot continuity — 2026-07-31

Refresh all refs, PRs, issues, checks, reviews, comments, and worktrees before acting. This record
captures the state after PR #159 merged, with PR #161 and issue #144 active and continuity parked.

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
- PR #159 merged issue #153's literal-Markdown report fix as merge commit
  `8d4b69d147b4f1e930b3388e5b3ce7d2661ab82e`, with parents `81125c57` and `e0f8fa5a`.
  Exact-head hosted run `30626399786` passed all nine jobs, #153 closed, and the one post-merge
  feedback check found no later comment, review, or thread.
- The continuity slice is locally complete in
  `C:\Users\jekyt\source\agent-harness\.worktrees\workbench-continuity-20260731`, branch
  `docs/workbench-continuity-20260731`. It creates the four canonical state homes, maps the live
  queue, corrects README and legacy-limitation contradictions, refreshes the tier review date,
  and preserves root `HANDOFF.md` as history. It merged `origin/main@8d4b69d`, passed its initial
  exact-range review, and is parked because concurrent PR #161 overlaps README.
- Workstream B is the sole writer in
  `C:\Users\jekyt\source\agent-harness\.worktrees\issue144-manifest-gates`, branch
  `fix/issue144-manifest-gates`, created detached from `origin/main@8d4b69d` before the branch switch.
  It owns only issue #144's manifest gate-class contract.
- Concurrent PR #161 is the other active workstream. It supersedes PR #155 for #87 at `f824fe7`.
  Its nine hosted jobs passed against pre-#159 base `81125c57`, but two review threads remain
  unresolved and live `main` is now `8d4b69d`, so base, gates, and triage are not final.
- Issue #160 was filed from that successor's review evidence and maps primarily to AH-4, with
  secondary AH-6/AH-9 ownership. No duplicate was filed.

## Verification and measurements

- `py -3 harness.py audit . --offline` -> exit 0, T3 declaration and `HUMAN_TODO.md` verified.
- `py -3 harness.py doctor` -> exit 0; floor comparison is correctly `UNPROVEN` because the
  Workstream A checkout is a feature branch rather than canonical clean `main`.
- `.agent-harness/tier.json` parses with `py -3 -m json.tool`.
- Live issue set versus ROADMAP primary map -> 64 open, 64 mapped, no difference.
- `docs/SYSTEM_STATE.md` -> 53 lines; `FLOOR_LIMITATIONS.md` -> 54 lines, both within budget.
- Canonical and deployed Claude-hook `dispatch.py` SHA-256 both measured
  `E1A4E7714913788DD801F0FA43A3E5B30EA0433709F97142509B56B1C442EF68`, version 1.6.21.
- PR #159 at `e0f8fa5`: focused tests 6/6; replay unittest 108 passed with 10 declared
  Windows skips; pytest 98 passed with 10 skips and 58 subtests; Ruff, Black, compileall,
  extraction-manifest exactness, diff checks, independent review, and nine-job hosted CI passed.
- Measured baselines and their limitations are transcribed in `docs/BENCHMARKS.md`; no new
  performance or rollout claim was inferred.

## Decisions and limitations

- Exactly two workstreams are active: PR #161 and issue #144. Continuity is parked; do not start a third.
- H-2 is the sole open `HUMAN_TODO.md` item and is owner-parked. Do not restart estate-wide
  canaries or disable the harness.
- PR #154/#151 and PR #155/#87 remain parked; #161 supersedes #155. Do not duplicate their occupied
  worktrees or reuse CI from an earlier base as current proof.
- Issue #21 plus #118/#120 is evidence for bounded Pattern Guard v2, not universal-parser expansion.
- #152 is a replay follow-up, not a workbench-wide priority; #153 is complete. AH-10 public
  extraction remains deferred; do not create a public replay repository or blueprint plugin.
- Duplicate replay suites must run serially: a deliberately parallel local attempt during #153
  collided on their deterministic shared snapshot root. Both declared serial commands passed.
- Existing occupied worktrees include clean historical branches `crossproduct-gate`,
  `issue151-successor`, `issue27-temporal-config`, and `issue87-successor`; `replay-tool` has a
  staged user change; `replay-v0-freeze` has ignored evidence and is behind its remote. Inspect
  `git status --porcelain --ignored` independently before any removal and never force it.

## Exact next task

- **Objective:** finish #144 through its bounded review-and-ship pipeline; leave PR #161 to its
  existing writer; resume continuity only after #161 lands or parks.
- **Files likely touched:** only the existing #144 writer checkout; the #161 writer owns its checkout.
- **Acceptance criteria:** #144 gets one fresh-context review, bounded fixes only for confirmed
  CRITICAL/HIGH defects, exact-head hosted CI, three-minute aging, one comment/thread triage, and
  merge-commit preservation. Continuity repeats scoped state verification after #161 resolves.
- **Verification command, Workstream A:**
  `py -3 harness.py audit . --offline`; `py -3 harness.py doctor`;
  `py -3 -m json.tool .agent-harness\tier.json`; `git diff --check`.
- **Verification command, Workstream B:**
  `py -3 -m unittest replay_v0.tests.unit.test_manifests -v`;
  `py -3 -m unittest discover -s replay_v0\tests -v`;
  `py -3 -m pytest -q replay_v0/tests`; replay Ruff/Black/compile/extraction checks;
  `git diff --check`.
- **Required corpus/benchmark update:** none for #144; focused in-memory tests are sufficient. Do not
  add a benchmark number without a pinned input, method, environment, result, and limitation.
- **Do not redo:** PR #140/#159 closed pipelines or post-merge checks; H-2; estate-wide canaries;
  parked PR #154/#155 work; floor parser expansion; public extraction.
