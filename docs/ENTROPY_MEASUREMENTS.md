# Advisory entropy measurements

Status: measurement design and synthetic calibration inputs, 2026-09-23. No collector,
dashboard, new harness command, CI gate or automatic issue writer is implemented. This is
proposal E4 in the review/oracle wave. All pilot results are NOT RUN.

## Place in the estate

Use the existing harness measurement/ops home and `docs/BENCHMARKS.md` for genuinely executed
results. [Review/oracle PR #290](https://github.com/Chris0Jeky/agent-harness/pull/290) supplies
the evidence boundaries and source ledger, including the unavailable original research brief.
[Ops PR #288](https://github.com/Chris0Jeky/agent-harness/pull/288) owns its existing ops
measurements; [#233](https://github.com/Chris0Jeky/agent-harness/issues/233) owns workstream-cap
interpretation. This proposal settles neither routing nor capacity policy.

These detectors measure possible maintenance debt, not whether a PR or agent is good. A high
merge count is neither the denominator for usefulness nor proof that an agent caused drift.
Generated/vendor files and intentional product variation need explicit classification.

## Candidate detectors

| Detector | Bounded inputs and proposed method | Denominator / output | False-positive control |
|---|---|---|---|
| Documentation drift | Curated contract-to-doc edges; changed contract/config at a pinned revision; existing link/schema check output | Changed mapped contracts and mapped docs inspected; candidate stale claims with exact excerpts | Date-only changes, explanatory history and an accurate doc with an old update date |
| Duplicate abstraction | Allowlisted first-party modules; normalized syntax/symbol or text similarity used only to retrieve candidates | Modules inspected and candidate pairs; reviewed pairs classified equivalent/divergent/unknown | Generated adapters, intentional protocol duplication and similar syntax with different semantics |
| Unfinished surface | Declared capability-to-entrypoint map plus existing tests or a recorded manual observation | Mapped enabled affordances inspected; missing outcome evidence stays unknown | Intentional empty state, documented preview, disabled capability and unavailable provider |
| Inconsistent contract | Curated consumer/producer relationships; compare stated schemas or behavior evidence | Relationships actually checked; disagreements with fixture/revision attribution | Versioned compatibility and deliberate UI variants are not automatically inconsistent |

Existing deterministic link/schema checks keep their current status policy. The broader meaning
of a stale claim, duplicate concept or unfinished experience remains advisory. No LLM score,
heuristic similarity threshold, old timestamp or absent test becomes a merge veto.
QA findings can seed a human-triaged issue; they do not own merge gates.

## Observation contract, not another receipt

Each proposed adapter emits one observation with: repository and inspected SHA; detector ID and
version; allowlist/input digest; contract or capability ID; paths and source ranges; extraction
status; candidate rationale; local evidence pointer; known exclusions; and human disposition.
Missing inputs are UNKNOWN, not a zero count. Partial coverage records both inspected and
requested scope. Never execute a command obtained from a scanned document or model response.

Join through existing source/run identities rather than creating another runner, event bus or
policy store. Raw private source, task text, screenshots and transcripts stay local. Curate the
smallest shareable aggregate only after checking paths and metadata for sensitive information.
No unattended export, remote telemetry default, repository mutation or auto-repair is proposed.

A future read-only adapter sketch (pseudocode, NOT an installed command):

```text
for declared input in the approved snapshot allowlist:
    collect with the existing source adapter
    on failure: record UNKNOWN plus unavailable scope; do not invent empty data
    obtain candidates using the detector's versioned rules
    retain source identity and exclusions on every candidate
coalesce repeated observations of the same underlying claim
emit local advisory observations plus inspected/requested denominators
leave defect confirmation and issue creation in the existing review workflow
```

Collection exit status can indicate that collection failed. It must not encode a product merge
verdict from candidate count. Do not add this sketch to `harness.py`, Doctor, floor hooks or CI
without a separately scoped, tested adapter proposal using the existing extension seams.

## Deduplication and longitudinal measurement

Keep observation identity separate from finding identity. A repeat scan at another revision is a
new observation of possibly the same finding, not another debt item. Match the same repository,
detector, contract/capability and concrete discrepancy; preserve changed evidence, disappearance
and recurrence. Similar wording or the same file alone is not enough to merge findings.

Pin baseline and candidate, detector version, exclusions, sample cohort and adjudication method.
Report raw counts, inspected/requested scope, confirmed/dismissed/unknown candidates and elapsed
review effort. Candidate volume can increase when coverage improves. Never present that as a
regression without the denominator. Record false negatives found through an independently chosen
non-candidate sample; reviewing only flagged rows cannot estimate recall.

A declining count after suppressing paths is not remediation. Keep suppression reason, scope,
owner and revisit condition, and report excluded coverage. Do not gamify a single entropy score.
Classify a fix only after a specific contract or outcome is observed again, not because an issue
closed or a PR merged.

## Calibration fixtures and controls

[Fixture table](review-evidence/entropy-fixtures.json) contains authored input descriptions and
expected advisory classifications. It is not scanner output, a semantic ground-truth corpus or
production evidence. The expected rows cover stale claims, benign age, generated duplication,
semantic uncertainty, deliberate emptiness, an observed dead control, unavailable inputs and a
repeat observation. All are synthetic and all collection executions are NOT RUN.

A future adapter must first demonstrate these distinctions, including unavailable versus empty
and observations versus distinct findings. Hold back additional known-bad and known-good examples
from tuning. A model can suggest candidates but must not author its own unchallenged gold labels.

## E4: one bounded pilot before building a dashboard

Recommendation, not a research-derived threshold: pick one repo, one detector and at most ten
mapped contracts for a first pass. Freeze the map and starting revision before inspecting results.
Use a declared small non-candidate sample to look for missed issues. A maintainer reviews the
candidate rationales once under the existing review budget; this is not another PR review round.

Record the exact sample, every unknown, confirmed/dismissed cases, missed cases and active review
minutes in the existing evidence location. Only executed, attributable results belong in
`docs/BENCHMARKS.md`; labels in the fixture file never become benchmark rows.

At the end, choose keep, revise once, or stop this detector. Stop or park if inputs cannot be
attributed, the same bounded pass remains dominated by unresolvable/irrelevant candidates after
one rule revision, or it produces no decision useful enough to justify its review cost. These are
pilot stopping rules, not evidence that the product should be archived. Never expand across the
estate solely because the script emits JSON.

## Follow-up boundary

Qualify extraction with known-good, known-bad and unavailable controls; then propose the smallest
read-only adapter in this repo. Add CLI/exit/output tests to the existing test/CI seams if code is
actually introduced. Product defects stay with their product owner. No generalized cleanup bot,
new dashboard platform, shared-state rewrite or automatic issue flood is authorized by this plan.
