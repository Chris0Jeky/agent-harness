# Taskdeck-first adapter sketch

T5 [#286](https://github.com/Chris0Jeky/agent-harness/issues/286), T1 [#282](https://github.com/Chris0Jeky/agent-harness/issues/282), product [#2901](https://github.com/Chris0Jeky/Taskdeck/issues/2901). Proposal only; browser execution is NOT RUN.

## Verified source map

Inspected Taskdeck commit `622d9d820f48e68ac7fa77d94c9ca2536155ddf8`:

- `frontend/taskdeck-web/tests/e2e/workspace-overhaul.spec.ts`: `keeps Home capture and saved thinking across all experience combinations`; `retains separate approval and apply gates while switching experiences`.
- `tests/e2e/support/authSession` and `boardHelpers` are used by that specification for synthetic auth and board setup. Its local `setup` and `seedCard` helpers are not exported adapters.
- `frontend/taskdeck-web/playwright.config.ts` provides `TASKDECK_E2E_DB`, `TASKDECK_E2E_WORKERS`, API/frontend origin resolution and project `chromium`; default traces retain failures only.
- Taskdeck `AGENTS.md` names an available project browser controller for interactive reproduction (default Chrome DevTools) and Playwright for durable regression. Do not impose a second controller on one session.

Source links: [specification](https://github.com/Chris0Jeky/Taskdeck/blob/622d9d820f48e68ac7fa77d94c9ca2536155ddf8/frontend/taskdeck-web/tests/e2e/workspace-overhaul.spec.ts), [configuration](https://github.com/Chris0Jeky/Taskdeck/blob/622d9d820f48e68ac7fa77d94c9ca2536155ddf8/frontend/taskdeck-web/playwright.config.ts). Revalidate on the actual candidate; current source is not an execution receipt.

## First local deterministic baseline

From an authorized isolated Taskdeck checkout, after its documented dependencies/browser/backend setup, use a run-owned synthetic database and verify no live provider credentials or personal services are reused. An example command, not executed here:

```powershell
Set-Location frontend/taskdeck-web
$env:TASKDECK_E2E_DB = Join-Path $env:TEMP ('taskdeck-ux-' + [guid]::NewGuid().ToString() + '.db')
$env:TASKDECK_E2E_WORKERS = '1'
npx.cmd playwright test tests/e2e/workspace-overhaul.spec.ts --project=chromium --grep 'keeps Home capture and saved thinking across all experience combinations' --trace on --workers=1
```

Inspect the repository's server-reuse and provider setup before running; a new database environment variable does not prove an already-running server uses it. Refuse an unknown/non-isolated server. Trace-on is a local evidence override so successful controls are retained, not a proposed CI change. The command exercises an existing test, not the new JSON scenario runner. Do not imply it executes every assertion in the draft pack.

## Proposed adapter boundary

Future harness-owned module home: `ux_evaluation/adapters/taskdeck.py`, after T1 semantics are accepted. No such module is shipped here. Interfaces are a design sketch, not callable APIs:

- `bind(pack, product_checkout, capability_receipt) -> BoundScenario`: resolve exact source/fixture/controller/environment; no execution on mismatch.
- `observe(bound_scenario, run_root) -> ObservationManifest`: call only reviewed project operations and collect per-step evidence.
- `validate_observation(manifest, run_root) -> EvidenceValidation`: deterministic completeness/digest/identity checks, no quality judgment.
- `judge(validated_evidence, rubric, budget) -> AdvisoryFindings`: model-independent result contract, no publication.
- `prepare_issue(findings, existing_issue_index) -> DraftIssue`: deduplication and sanitized Markdown/JSON, no automatic filing.

Harness owns binding/evidence/adapters. Taskdeck owns actual fixture helpers, product invariants and any later test changes. claude-config owns invocation recipes. Do not export product internals or rewrite app code just to satisfy this sketch.

## Coverage and limits

The example binds UX-01 from #2901: preserve the unsaved Home thought while switching experiences, then explicitly save. Existing source asserts preserved text and later durable thinking; the draft adds explicit counter requirements for zero unwanted capture/proposal/provider/approval/apply effects. Those counter bindings are missing work, not proved coverage.

A follow-up covers the review/apply journey using the second existing test. UX-02 moderated comparison, the full 4×3×2 shell invariant matrix, renderer/Auto resolution and UX-04 observation import/export remain owned by #2901; one pilot does not complete them. Rotate experience order for preference studies, retain raw outcomes and never declare a winning experience from this synthetic pack.

Before T2 runs, record capability probes, exact fixture/reset recipe and counter sources. Collect a known-good control plus one seeded defect in a disposable fixture; do not deliberately mutate product main. After a real finding is reproduced, the product repo gets the smallest deterministic regression PR. Keep `.github`, branch protections and subjective CI gates untouched.
