# Handoff: #185 producer-smoke progress — 2026-08-02

## End-to-end objective

Make the long producer smoke run observable when its output is captured, without changing the
dispatcher contract, verdicts, or the process-control scope of issue #185.

## Completed

- PR #217 added a flushing `emit()` helper and deterministic `smoke-progress` start, seven section,
  and pass/fail completion markers to `templates/hooks/smoke_test.py`.
- The existing per-case output, `CASES`, expected decisions, timeouts, and exit semantics are
  unchanged; the change is producer-only.
- `tests/test_git_editor_terminal_flows.py` now proves a real child process streams the markers and
  representative case output through a pipe while the child is still alive, then releases and
  reaps that child cleanly.
- PR #217 merged as `b13ae2695451561c5835813251e89b730643eb12`, preserving reviewed head
  `23d98d50f9432a32b88010b08892dc477660ea37` as its second parent. The topic branch remains on the
  remote; the completed isolated worktree was removed after its ignored-file inspection found only
  disposable Ruff and Python cache directories.

## Verification and measurements

- `py -3 -m unittest tests.test_git_editor_terminal_flows -v` -> 15/15 passed.
- `py -3 templates\hooks\smoke_test.py` -> 2,237/2,237 passed; an independent captured-pipe run
  observed first output in 124 ms and all phase/final markers before completion.
- `py -3 -m unittest discover -s tests -v` -> 897 passed.
- Black, Ruff, `py_compile`, and `git diff --check` passed on the reviewed head.
- CI run `30754942900` completed all nine checks successfully on Windows, Ubuntu, and macOS.
- One fresh-context Sol review and a supplemental Luna narrow review found no CRITICAL/HIGH issue.
  Post-merge refresh found no submitted reviews or inline threads.

## Decisions and limitations

- #185 remains open. This slice intentionally does not add a consumer lane, global deadline,
  interruption handling, descendant cleanup, runtime configuration, or live-hook claims.
- The issue lacks an approved consumer launcher/manifest and concrete cleanup semantics. Do not
  infer them from the producer fixture or use PID checks as descendant-proof.
- The primary checkout has owner-pending edits to `HUMAN_TODO.md`, `docs/SYSTEM_STATE.md`, and
  `plans/ACTIVE.md` recording the 2026-08-02 estate-wide PreTool deny-floor pause. Preserve those
  edits; do not run a deny canary unless the owner explicitly re-enables the floor.

## Exact next task

- Objective: turn the remaining #185 consumer/deadline/interruption request into one bounded slice
  only after a real consumer command or owner-approved manifest defines launch, progress, timeout,
  interruption, and descendant-cleanup acceptance criteria.
- Files likely touched: the real consumer launcher/manifest and its focused tests; do not extend the
  producer smoke fixture merely to simulate an unspecified consumer.
- Acceptance criteria: a bounded command proves periodic progress, a declared deadline, interruption
  cleanup, and no surviving descendants using evidence stronger than a parent PID check.
- Verification command: start with the focused consumer test, then run the affected smoke suite,
  full unit discovery, and the T3 PR/CI/review/aging gate against its exact head.
- Required corpus/benchmark update: record bounded timing/progress evidence only if the real consumer
  path exists; do not claim a performance baseline from uncontrolled smoke durations.
- Do not redo: do not reopen #217, alter the frozen deny floor, touch global runtime configuration,
  or disturb the occupied `tooling/corpus-replay` worktree at `afb1c0a`.
