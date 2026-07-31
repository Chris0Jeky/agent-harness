# Active workstreams

Snapshot: 2026-07-31. Base: `8d4b69d147b4f1e930b3388e5b3ce7d2661ab82e`.
Exactly two workstreams are active; do not start a third until one lands or parks.

## A — AH-4/AH-6 PR #161 MCP topology successor

- **Observable outcome:** static Doctor reports real cross-scope MCP duplication and unbounded Docker
  gateways without false failures from platform path spellings or command shims.
- **Evidence:** PR #161 supersedes parked PR #155 for #87; live head `f824fe7` has two unresolved
  automatic review threads and a base that predates merged PR #159. Follow-up #160 records a
  separate disabled mixed-transport precedence decision.
- **In:** only the existing PR #161 branch/worktree and its bounded review/base-refresh pipeline.
- **Out:** new writer checkouts, #160 implementation, live MCP mutation, process cleanup, or estate canaries.
- **Architecture seam:** read-only Doctor MCP topology discovery.
- **Tests/fixtures/corpus:** the PR's focused layered-config fixtures and full harness gates; no corpus.
- **Measurement:** read-only consumer probes already recorded in PR #161; no new estate mutation.
- **Limitation:** PR #161's current hosted CI is stale after `main` advanced to `8d4b69d`.
- **Exact verification:** refresh the PR head/base/merge-base, triage its two threads once, then run
  the repository unit/smoke/audit/Doctor gates and hosted CI at the resulting exact head.
- **Next executable handoff:** the existing #161 writer owns any fix. Other agents remain read-only,
  avoid its checkout, and revisit only at a workflow event.

## B — AH-2 issue #144 run-manifest gate validation

- **Observable outcome:** run-manifest build, run-ID derivation, and load/validation accept exactly
  the CLI's three supported gate classes and reject `unchanged`/`resolved-indeterminate`.
- **Evidence:** issue #144 records the library/CLI contract mismatch; the supported CLI already
  rejects the two extra report classes before manifest construction.
- **In:** the manifest gate-class boundary, focused build/derive/load tests, and extraction hashes.
- **Out:** the five report diff classes, CLI grammar, schemas, policy sources, parser expansion,
  global enforcement, and public extraction.
- **Architecture seam:** generated run-manifest semantic validation and stable run-ID inputs.
- **Tests/fixtures/corpus:** in-memory rejection cases; no corpus or external fixture change expected.
- **Measurement:** correctness assertions only; no latency or policy-quality benchmark.
- **Limitation:** run manifests are generated outputs rather than replay inputs, so this aligns the
  supported library contract without claiming a new external compatibility surface.
- **Exact verification:** `py -3 -m unittest replay_v0.tests.unit.test_manifests -v`;
  `py -3 -m unittest discover -s replay_v0\tests -v`; replay Ruff/Black/compile/extraction checks;
  `git diff --check`.
- **Next executable handoff:** commit the bounded fix, independent adversarial review, publish,
  hosted CI, three-minute aging, one comment/thread triage, and merge-commit preservation.

## Parked or queued, not active

- The continuity branch `docs/workbench-continuity-20260731` is locally complete and reviewed, but
  parked until overlapping PR #161 lands or parks. Then merge current `origin/main`, reconcile
  README/state facts, rerun scoped checks/review, and publish it.
- PR #154/#151 and superseded PR #155/#87 stay parked on their recorded blockers.
- #152 remains the next bounded replay candidate after #144; it is not active.
- H-2 is owner-parked. Do not run estate-wide canaries or disable the harness.
- AH-10 extraction and a public replay repository remain deferred.
