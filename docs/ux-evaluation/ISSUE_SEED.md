# Evidence-bound issue seeds

T4 #285. This is a formatter contract, not a GitHub publisher. A coordinator must search the target repository before filing. Use existing labels only after checking they exist.

## Required structured fields

`finding_id`, `repository`, `subject_revision`, `scenario_id`, `step_ids`, `dimension`, `severity`, `status` (`observed`, `hypothesis`, `needs_reproduction`), `evidence_sufficiency`, `confidence` with rationale, `observation`, `expected`, `actual`, `reproduction`, `artifact_refs`, `limitations`, `dedupe_key`, `related_issues`, `proposed_fix` (optional), `authority: advisory`, `gate_eligible: false`.

Compute a stable dedupe key from product + journey + affected affordance + normalized failure mechanism, not the model's title or severity. Keep exact evidence revision separately so a new build can retest the same finding. A changed severity is not a new defect. Similarity matches are suggestions, not permission to close existing issues.

## Markdown output template

```markdown
## Observed behavior
[Specific action, actual UI/state outcome, expected contract. No unsupported causal claim.]

## Reproduction and scope
Product revision: [full SHA]
Scenario/steps: [IDs]
Fixture/configuration: [sanitized reference]
Status: [observed / hypothesis / needs_reproduction]
Actions: [ordered minimal sequence]

## Evidence
[Artifact IDs, step/region/time references, sanitized accessible links if approved.]
Missing or unverified: [layers and environments not observed]

## Impact
Dimension: [effectiveness / usability / simplicity / clarity / feel]
Severity: [S0-S4, with impact rationale]
Confidence: [with evidence rationale, not a fabricated probability]

## Follow-through
Existing issue matches: [links or recorded none]
Proposed regression: [observable deterministic invariant, or explicitly subjective]
Proposed fix: [optional; separate from the observation]
Retest: [new revision and evidence required]

Advisory finding; not a merge/release verdict.
```

Do not publish this unfilled template as a product bug. The first dry-run may retain a filled draft locally rather than file it. Evidence referenced by a seed must exist and match its manifest. An inaccessible screenshot is not made public by embedding its local path.

S0/S1 concerns receive prompt human attention without automatic destructive action. S4 taste suggestions are batched under the design owner. A clean run produces an evidence summary, not an empty issue. A blocked observer produces a harness/environment finding, not an invented product defect. Future tests should prove duplicate suppression, missing-evidence refusal, safe redaction and separation of observations from suggested fixes.
