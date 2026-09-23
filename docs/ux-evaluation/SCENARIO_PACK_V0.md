# Scenario authoring contract v0

T1 #282. [Schema](scenario-pack.schema.json), [synthetic authoring example](scenario-pack.example.json). JSON is the initial machine-readable format; product packs may use YAML with the same data model. No YAML parser or runner is added by this PR.

## Authoring fields

`schema` is `ux-scenario-pack/0`; `status` is always `draft`. The document is a plan, never a run receipt. `authority: advisory`, `gate_eligible: false` and `local_only: true` are mandatory for this first wave. The subject names the product repository and a full lowercase 40-character Git commit. It does not authorize execution against an arbitrary remote host.

Each journey has a stable ID, goal, named fixture reference, preconditions, ordered steps, rubric dimensions and bounded actions/seconds/judge calls/retries. Each step describes a human-visible action, expected assertions and required evidence kinds. Actions are prose, not shell commands or an interpreted language. The adapter must resolve only reviewed, allowlisted product fixture operations. Do not evaluate strings from a pack, DOM or model response.

The schema rejects unknown object fields, unsupported dimensions, empty steps/evidence and invalid budgets/revisions. It does not prove unique journey/step IDs, fixture existence, provenance, safe paths, assertion completeness or run success. The future semantic binder must reject duplicate IDs, unknown fixtures, unresolved requirements and subject revision mismatch. Do not advertise JSON Schema success as a security boundary or executable qualification.

## Rubric

| Dimension | Question | Necessary evidence; limits |
|---|---|---|
| Effectiveness | Was the intended goal achieved with the correct durable result and no prohibited side effects? | Persisted state and relevant request/UI evidence. Narration alone is insufficient. |
| Usability | Could the user discover, operate and recover without hidden knowledge? | Action history, keyboard/focus observations, errors and recovery attempts. Agent speed is not human usability. |
| Simplicity | Did the journey impose avoidable steps or competing choices? | Task-specific step/decision comparison. Fewer controls alone is not better. |
| Clarity | Are hierarchy, labels, status, consent and consequences understandable? | Actual content at relevant states; comprehension remains a human-study question. |
| Feel | Are feedback, transitions and spatial continuity coherent with the chosen direction? | Temporal evidence plus context; static screenshots cannot establish tactile feedback or actual human preference. |

A finding has severity independent of dimension outcome: **S0** safety/privacy/data loss; **S1** blocked core journey; **S2** substantial recoverable friction; **S3** minor localized defect; **S4** preference. Confidence and evidence sufficiency are separate. Unknown evidence cannot lower a severe concern to a passing score. S4 suggestions do not generate separate issues automatically.

## Future evidence binder acceptance tests

The T5 implementation should first add failing cases for: missing artifact; digest mismatch; absolute or traversal path; symlink escape; duplicate IDs; mixed product revisions; missing persisted-state evidence; static-only feel claim; observer repair hidden from the log; exceeded budget; unrecorded retry; public export containing auth/PII; and a judge response referencing a nonexistent step. Include a valid clean control. Reject before model calls or publication, retaining the reason locally.

Artifact files are under a run-owned directory. The manifest identifies exact bytes and observation method; it does not claim signatures or source attestation. Use relative artifact IDs in issue seeds; publishing a link must not silently upload the raw bundle.

The checked-in example deliberately requires some counters beyond the existing test assertions. Until T5 binds those counters, mark the relevant assertion blocked rather than pretend the current test already covers it. No run timestamp, measured cost or fake evidence digest is included in the authoring example.
