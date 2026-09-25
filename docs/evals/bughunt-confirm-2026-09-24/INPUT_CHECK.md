# Frozen-input byte check

This is the first executable step of the recovery plan in `README.md`, not a
benchmark verifier. `verify_frozen_inputs.py` compares recovered files with the
two hashes in the historical receipt. It never parses benchmark rows, runs a
generator, computes model/cost claims, or changes this draft's acceptance.

From this directory, with Python 3.11 or later:

```text
python -I verify_frozen_inputs.py --inputs /path/to/recovered/frozen-inputs
python -m unittest discover -s . -p "test_verify_frozen_inputs.py" -v
```

The selected directory must contain ordinary files named `benchmark.json` and
`KEY_RUNS.json`. The command reads in chunks and emits a JSON result to stdout.
Missing, unreadable, non-regular or mismatched inputs produce exit 2. Exit 0
means only that every observed digest matches the historical receipt. The CLI
does not allow replacing those expected hashes with a newer snapshot's hashes.
Tests inject separate, visibly synthetic expectations to exercise the positive
case without pretending to possess the real frozen files.

Every result retains `benchmark_claims_verified: false`,
`generator_verified: false`, and `acceptance: blocked`, even when
`matches_receipt` is true. The receipt itself has not been authenticated against
an independent upstream source, so digest equality establishes consistency with
that receipt, not upstream authenticity. Do not use the command's exit status
as a model-quality decision or PR merge gate.

Inputs are operator-owned and must remain stable during the read. The checker
rejects existing leaf symlinks but is not a concurrent filesystem-race sandbox.
It does not execute source code or install dependencies, and its result omits
file contents and caller-local absolute paths. It does not create an output
file or alter the imported receipt.

## Local control evidence

Linux / Python 3.13.5: eight synthetic controls passed in 0.621s, including a
real CLI subprocess that returns 2 for missing inputs. Python compilation
passed. The initial run failed because the checker module did not yet exist;
that run is not counted as a passing test. These are local controls, not a
supported-host CI claim, pinned formatter/linter pass, recovered-source check,
or benchmark rerun.

Still required: recover/authenticate the actual frozen inputs and generator;
verify row selection, finite values and ratio semantics; regenerate new
provenance-bound claim evidence; reconcile the old labels; and complete review.
The seven historical claim/protocol/receipt files remain byte-preserved.
