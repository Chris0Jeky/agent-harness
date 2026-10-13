# Outcome Stream Validation Implementation Plan

> For agentic workers: use superpowers:executing-plans task by task.

**Goal:** Refuse malformed or inconsistent complete outcome streams before reducers or cursors consume them.
**Architecture:** Reuse the existing record validator in stream_errors; add merged-only maturity and nondecreasing observation times per version. Route public readers through one checked materialization.
**Tech Stack:** Python standard library, unittest; no dependency or public schema change.
**Spec:** SPECS.md section 15, One outcome stream; issue #511.

## Global Constraints
Preserve event IDs, Beta formula, projection contents, UTC cursor ordering and deterministic whole-history reading. No dispatcher, CI, installed runtime, trust, schema or bundle edits. Remain disjoint from #543's account projection hunk.

## Review Focus
Malformed records and cursors must return classified failures, not indexing exceptions.
Unmerged runs cannot contribute matured evidence.
Conflicting/duplicate versions and gaps must never select an arbitrary winner.
Equal UTC instants remain valid regardless of timestamp spelling or input order.
Missing stream tails and validly rewritten histories remain unprovable without a trusted snapshot.

### Task 1: Checked complete-stream readers
Files: scripts/learning_outcomes.py, tests/test_learning_outcomes.py.
- [ ] Add failing tests for malformed records, immature run claims, gaps, duplicates, reverse chronology and public-reader parity.
- [ ] Confirm the unchanged implementation fails the intended assertions.
- [ ] Implement diagnostic stream validation and reuse it from latest/read_since; validate cursor shape explicitly.
- [ ] Run focused and all learning tests, full root tests, smoke, Doctor, syntax and whitespace.

### Task 2: Reviewable delivery
- [ ] Document complete-stream preconditions and residual limits in docs/LEARNING_OUTCOME_VALIDATION.md.
- [ ] Reconcile current GitHub main and #543; publish an isolated draft with exact source and test evidence.
- [ ] Do not close #511 or claim independent review/hosted qualification from author tests.
