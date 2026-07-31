# Active workstreams

Snapshot: 2026-07-31. Shared base: `576b540b0e856ed61dc1b062b1cdae0abbcd89dd`.
Two workstreams are active, with one writer in each isolated checkout.

## A — AH-1 continuity refresh

- **Observable outcome:** canonical state, roadmap, active-plan, measured-evidence, and dated-handoff
  homes agree with live Git/GitHub evidence after PRs #173–#178, including the measured CI-budget
  follow-up #179.
- **Evidence:** branch `docs/workbench-continuity-final` starts from PR #178 merge `576b540`; PRs
  #152/#156/#164/#165 are closed; PRs #154/#155 are closed unmerged and superseded; GitHub had no
  open PR at the base snapshot; 66 open issues require one primary epic each.
- **In:** `docs/SYSTEM_STATE.md`, `ROADMAP.md`, this file, `docs/BENCHMARKS.md`, and
  `handoffs/2026-07-31-workbench-pivot.md`.
- **Out:** runtime behavior, root `HANDOFF.md`, legacy floor limitations, H-2 activity, live estate
  mutation, plugin extraction, public replay, or another checkout.
- **Architecture seam:** evidence and state ownership across the workbench, not enforcement.
- **Tests/fixtures/corpus:** no fixture or corpus change; issue-map, document-budget, JSON,
  audit/Doctor, Markdown/diff, review, hosted CI, aging, and triage gates apply.
- **Measurement:** only directly measured B-006–B-010 entries are added; no current estate
  baseline, longitudinal Doctor series, or performance improvement is claimed.
- **Limitation:** GitHub, tier, deployed bytes, and worktree ownership can change after this dated
  snapshot; successors must refresh them before mutation.
- **Exact verification:** `py -3 -B harness.py audit . --offline`; `py -3 -B harness.py doctor
  --repo . --offline`; parse `.agent-harness/tier.json`; prove every open issue maps exactly once;
  enforce document budgets; `git diff --check origin/main...HEAD`.
- **Next executable handoff:** after workstream B lands or parks, refresh this branch against
  `origin/main`, record the exact result, then complete one bounded review/CI/aging pipeline and
  merge with a merge commit.

## B — AH-6 partial-apply reporting (#168)

- **Observable outcome:** after one worktree removal succeeds and a later registry revalidation
  fails, the command emits complete JSON/text, reports the removed candidate, retains the failing
  and later candidates, and returns nonzero.
- **Evidence:** two synthetic reproductions on `main@5df147b` removed the first candidate, retained
  the second, raised before rendering, emitted zero stdout bytes, and left no top-level apply error
  or summary. Issue #166 is closed, so #168 is unblocked.
- **In:** narrow expected-error normalization at the per-candidate fresh-list boundary, stable
  partial-apply reason codes, rendering, synthetic JSON/text tests, and one `SPECS.md` sentence.
- **Out:** retries, rollback, force removal, pruning, branch deletion, preservation-gate changes,
  broad exception swallowing, or live `worktrees --apply`.
- **Architecture seam:** `apply_worktree_plan` into `summarize_worktree_plan`,
  `render_worktree_plan`, and `worktrees_command`.
- **Tests/fixtures/corpus:** three removable synthetic candidates prove one removal and two
  fail-closed retentions in JSON and text; no committed fixture or replay corpus change.
- **Measurement:** current two-candidate reproduction yields one unreported removal and zero
  output; target three-candidate matrix reports exactly one removal and two retained/refused
  candidates.
- **Limitation:** an earlier successful removal cannot be rolled back; the contract is exact
  partial-mutation reporting, not transactional apply.
- **Exact verification:** focused partial-apply tests; all `WorktreeCloseoutTests`; full unit and
  smoke suites; audit/Doctor; Black/Ruff/compile; `git diff --check origin/main...HEAD`.
- **Next executable handoff:** sole writer checkout `partial-apply-report-20260731` implements and
  pushes one present-tense commit, then PR review/CI/aging/triage proceeds without combining #167
  or #170–#172.

## Parked or queued, not active

- #179 is the measured AH-1 Windows aggregate CI-budget repair; inventory timings before changing
  the workflow and never skip or allow-fail a proving check.
- #167/#170/#171/#172 remain bounded AH-6 follow-ups; #167 overlaps #168 and must not run in
  parallel. None authorizes live estate cleanup.
- #160 is the remaining bounded Doctor topology follow-up. #177 is the bounded replay
  lone-surrogate parity follow-up.
- PRs #154/#155 are closed unmerged and superseded; their remote branches remain historical
  evidence, not active writers.
- H-2 is owner-parked. Do not run estate-wide canaries or disable the harness.
- AH-10 extraction and a public replay repository remain deferred.
