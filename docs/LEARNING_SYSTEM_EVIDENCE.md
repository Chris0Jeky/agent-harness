# System comparisons and canary evidence

`scripts/learning_system.py` produces observational comparisons. Matching a run's
`variant` label to a candidate genome does not prove that the run was assigned to
a canary or executed that genome. The repository does not yet have the trusted
cohort assignment and execution resolver needed to establish those facts.

## Current behavior

Every generated `system-run/v1` report has `evidence_scope: observational` and
`gate: null`. Its arm statistics, policy, verdict and reasons remain useful for
reviewing recorded outcomes. A `pass` means those observations meet the selected
non-regression tolerances; it supplies no canary promotion evidence.

The CLI preserves its comparison exit codes: 0 for an observational pass, 1 for
an observational regression, 2 for refused input and 3 for insufficient runs or
maturity. Callers must read the scope and gate fields rather than treating exit
0 as permission to promote.

The existing chronology filter excludes a run if its claimed start (or terminal
time when no start is present) or observation precedes the later candidate and
genome creation time. Training evidence stays excluded. This filter predates the
observational boundary; it does not verify store import times, canary entry,
immutable execution times, or assignment. It uses the folded latest observation,
whose source timestamps can be changed by re-observation. Its output is still
observational when all timestamps and variant labels match.

## Compatibility boundary in bundle version 5

The portable validator still reads legacy `system-run/v1` reports that omit
`evidence_scope`, including their archived gate claims. Current reports use the
new optional scope field; validation forbids a gate on an observational report.
This preserves archival reading without accepting those claims as new evidence:

- The promotion generator refuses every `system-run/v1` report, whether current
  or legacy, with an explanation that trusted assignment and execution receipts
  are not implemented.
- The generator and lifecycle fold also refuse an extracted `canary` gate whose
  reference is `system-run:...`. Removing the report's scope field or passing
  only its old gate does not make it admissible.
- Assignment-looking joins and arbitrary local labels cannot turn the comparison
  into a canary. Unsupported assignment fields are invalid input.

The report remains a version-1 record because existing archival records retain
their meaning and validity. The exported bundle advances to version 5 to make
the new promotion refusal and optional scope field explicit for consumers. A
consumer must update its validator and promotion generator together; a reader
running an older bundle does not gain this refusal automatically.

This boundary rejects recognized system-comparison claims. It does not
authenticate unrelated, caller-supplied raw gates or records. A writer that
rewrites a gate as a different evidence source is outside this provenance check;
the store and its resolver must authenticate that source. No local string or
manifest is presented as a trusted receipt.

## Remaining work

Issue #520 remains open for immutable cohort assignment and execution receipts.
A future canary evaluator needs a trusted resolver that binds the candidate and
genome commits, assignment time, arm, source identity and actual execution. It
must exclude unassigned runs, reject changed or forged assignments, and enforce
run chronology after assignment. Issue #517 separately tracks store import
timestamps and other trust anchors. The current comparison has no option to
bypass these missing dependencies or restore canary gate emission.
