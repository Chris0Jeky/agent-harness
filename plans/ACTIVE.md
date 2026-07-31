# Active workstreams

Snapshot: 2026-07-31. Base: `81125c57ec6d1a750ddd43b0110c6928f9f4a860`.
Exactly two workstreams are active; do not start a third until one lands or parks.

## A — AH-1/AH-2 continuity state

- **Observable outcome:** canonical current-state, roadmap, active-plan, benchmark, and dated
  handoff records replace contradictory root status without rewriting historical `HANDOFF.md`.
- **Evidence:** the workbench brief requires the four homes; they were absent on merged `main`;
  README still claimed the 2026-07-24/v1.5.4 state and `FLOOR_LIMITATIONS.md` called merged PR #71 open.
- **In:** `README.md`, `.agent-harness/tier.json`, `FLOOR_LIMITATIONS.md`, `docs/SYSTEM_STATE.md`,
  `docs/BENCHMARKS.md`, `ROADMAP.md`, this plan, and a dated `handoffs/` record.
- **Out:** policy behavior, floor expansion, deployment, H-2, private data, and historical handoff rewrites.
- **Architecture seam:** continuity and evidence ownership only.
- **Tests/fixtures/corpus:** no executable fixture change; run offline audit, Doctor, doc references,
  JSON parsing, budget/format checks, and `git diff --check`.
- **Measurement:** transcribe only the bounded results already recorded on #21, #39, #118, #120,
  and merged PR #140; no new performance claim.
- **Limitation:** GitHub and deployed runtime state can drift immediately after this snapshot.
- **Exact verification:** `py -3 harness.py audit . --offline`; `py -3 harness.py doctor`;
  `py -3 -m json.tool .agent-harness\tier.json`; `git diff --check`.
- **Next executable handoff:** publish, review once, pass hosted CI, age the exact head, triage once,
  and merge with a merge commit.

## B — AH-2 issue #153 literal Markdown report text

- **Observable outcome:** policy-controlled Markdown table cells render literally without changing
  JSON evidence or gate outcomes.
- **Evidence:** issue #153 records a reproduced table-structure injection in replay output.
- **In:** the smallest comparison/report rendering seam, focused tests, and extraction-manifest hashes.
- **Out:** HTML sanitization beyond Markdown table text, policy grammar, parser expansion, global
  enforcement, public extraction, and unrelated replay follow-ups.
- **Architecture seam:** deterministic human-readable report presentation after comparison.
- **Tests/fixtures/corpus:** focused metacharacter cases; no corpus expansion unless the behavior
  requires a committed fixture.
- **Measurement:** correctness assertions only; no latency or general rendering benchmark.
- **Limitation:** this protects the generated Markdown table contract, not every downstream renderer.
- **Exact verification:** `py -3 -m unittest replay_v0.tests.unit.test_compare -v`;
  `py -3 -m unittest discover -s replay_v0\tests -v`; replay Ruff/Black/compile/extraction checks;
  `git diff --check`.
- **Next executable handoff:** commit the bounded fix, independent adversarial review, publish, hosted
  CI, three-minute aging, one comment/thread triage, and merge-commit preservation.

## Parked or queued, not active

- PR #154/#151 and PR #155/#87 stay parked on their recorded cross-platform blockers.
- #144 and #152 remain bounded AH-2 candidates after #153; neither is active.
- H-2 is owner-parked. Do not run estate-wide canaries or disable the harness.
- AH-10 extraction and a public replay repository remain deferred.
