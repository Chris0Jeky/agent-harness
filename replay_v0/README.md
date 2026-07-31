# Replay v0

Replay v0 compares two policy-decision streams for a small, privacy-safe command corpus. It is a
deterministic comparison tool, not a live command interceptor, policy-authoring framework, safety
proof, or benchmark.

The checked-in charter has 50 inert command strings: 20 synthetic catastrophe-boundary cases, 20
synthetic non-executing near-misses, and 10 fully re-authored historical/opaque shapes. The runner
never executes those command strings. Classification comes only from validated baseline and
candidate `PolicyDecision` effects keyed by `event_id`.

## Quick start

Validate the exact-byte corpus manifest:

```text
python -m replay_v0.cli validate --corpus replay_v0/corpora/charter
```

Run the clean reference comparison:

```text
python -m replay_v0.cli replay --baseline recorded:replay_v0/fixtures/legacy-decisions.jsonl --candidate process:python,replay_v0/tests/fixtures/process_policies/reference_candidate.py --corpus replay_v0/corpora/charter/events.jsonl --output .local/replay-proof
```

The command writes `run-manifest.json`, `report.json`, and `report.md`. Exit `0` means the configured
gate passed, `1` means a configured change class was present, `2` means an input or exact-byte
binding was invalid, and `3` means a policy process failed after a reportable comparison could be
formed.

Run the authoritative dependency-free test lane with:

```text
python -m unittest discover -s replay_v0/tests -v
```

After installing the owner-approved development requirements, prove Pytest compatibility with:

```text
python -m pytest -q replay_v0/tests
python -m pytest -q replay_v0/tests/unit replay_v0/tests/contract
```

## Baseline truth

Despite its compatibility filename, `fixtures/legacy-decisions.jsonl` is a synthetic
freeze-candidate expectation for the curated charter. It was not captured by executing the private
legacy dispatcher. The owner-approved `floor-v1-final` tag now exists at
`02bd14cfe094f9b6af85b966de481ff3f45264cf`, but that immutable implementation tag does not turn
this synthetic recording into captured dispatcher output. Its sidecar policy ID and every decision
reason preserve that distinction.

The reference candidate is equally narrow: it maps the 50 reviewed fixture event IDs to expected
effects. It does not parse command text or reproduce the frozen dispatcher.

## Reproducibility and limits

Corpus and recorded-source manifests bind exact bytes with SHA-256. A run ID binds the runner
version, both policy-source identities, the corpus-manifest digest, and gate configuration. Process
startup captures every corpus file and both recorded-source files once, validates those captured
bytes, and retains the same immutable bytes for parsing and evaluation. Replacing a validated path
later therefore cannot change a result under the earlier manifest or policy identity. Process
identity v5 includes the executable bytes and four-octal-digit permission mode, normalized
invocation, entry-policy bytes, the relative names, exact regular-file bytes, and permission modes
for the policy-parent root and entries, configured timeout, fixed environment, and policy-parent
working-directory contract without writing absolute paths to the run manifest. Immediately before
each process runs, the runner copies the bound executable and complete policy-parent tree into a
private temporary snapshot, verifies that the snapshot's entry-policy bytes, executable bytes and
permission mode, and complete tree digest exactly match the identity before and after execution,
and launches only the snapshot paths. Permission differences preserved by the copy therefore
produce distinct identities and run IDs even when names, bytes, and execute bits are unchanged.
Changing or removing an original path after snapshot preparation therefore cannot change what the
process opens. A mismatch or unavailable input produces `indeterminate`; a cleanup failure is also
a source failure. Cleanup may restore write permission only inside the runner-created private
snapshot so copied read-only inputs can be removed; it never changes the original policy tree.
Corpus and run manifests require at least one event, so an empty or truncated corpus cannot
produce a vacuous pass.

The snapshot is reproducibility containment, not an operating-system sandbox. A hostile process
running as the same OS user may still be able to discover or rewrite temporary storage, and policy
behavior after process start remains outside the snapshot guarantee. Pre/post verification catches
ordinary snapshot drift but is not an atomic defence against a same-user mutate-and-restore attack.
A generic executable must be
relocatable enough to run from the snapshot; adjacent loader libraries are copied as unbound
runtime dependencies, and Python uses its host base prefix for its unbound standard library. If the
captured executable cannot start, replay fails closed instead of falling back to the original path.
External installed dependencies, files outside the policy tree, network responses, and host
metadata remain outside the portable identity; callers that depend on them must isolate and record
that environment.

The three report artifacts are fully staged before publication. Replacing an existing report set
uses rollback: a publication error restores the prior complete set instead of leaving a new
manifest beside old results. This is an in-process failure guarantee, not an operating-system crash
transaction; callers still own durable artifact storage.

Reports describe changes between decisions. They never claim that an original command was safe,
unsafe, executed, or reproduced. The checked-in reference and test lane performs no network access
and never imports or runs the legacy dispatcher. A caller-supplied `process:` policy is an
unsandboxed program and may use the network or filesystem unless the caller isolates it.
