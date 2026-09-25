# BH3 planted-bug fixture

Ten intentionally broken, independent functions and an offline deterministic
scorer. This is a small test fixture, not a model ranking or a reproduction of
an external benchmark. Never use `src/app.py` as production code.

## Run

Use Python 3.11 or later with the repository-approved pytest version. From this
folder, create a virtual environment and install `requirements.txt` using that
same environment's Python. The native Windows entrypoint is also Python; Bash
is not required for scoring or the maintainer controls.

```text
python -m pip install -r requirements.txt
python -I oracle/score.py
python -I oracle/score.py --check
python -m unittest discover -s oracle -p "test_score.py" -v
```

The examples assume `python` is the selected environment's interpreter. POSIX
convenience wrappers `oracle/score.sh` and `oracle/check.sh` honor `BH3_PYTHON`
for the entire operation. They prefer this fixture's `.venv/bin/python`, then
the repository environment, then an installed Python with pytest.

The maintainer controls copy the fixture to temporary directories and use
`git apply` for the checked-in `fixes/golden.patch`. They leave the intentionally
buggy working copy untouched. Git is required for these controls. Running the
agent task tests directly is expected to fail before fixes; that is not the
command that verifies the scorer itself.

## Result contract

`score.py` writes JSON containing `valid`, `passed`, `total`, `per_bug`,
`pytest_exit`, `mode`, and SHA-256 identities for the manifest, task tests,
candidate source and scorer. Score mode exits 0 for a valid measurement, even
when bugs remain. Check mode exits 0 only for a valid all-fixed measurement,
1 for a valid incomplete fix, and 2 for invalid inputs or runner evidence.

A nonempty manifest must contain 1..10 unique bug IDs and unique test names,
matching `planted_total`. A private temporary JUnit report must contain exactly
one ordinary pass/failure result for each declared test and agree with pytest's
exit status. Collection/setup/teardown errors, skips, missing/duplicate results,
input mutation, and runner failure are invalid evidence, not a zero-point run
or an all-fixed result. Console text never awards points. Regex fingerprints
are diagnostic only, not a second judge.

Pytest runs with isolated Python, an explicit minimal configuration, no
conftest files or external plugin autoload, and no inherited pytest selection
options. A 30-second runner timeout is a fixture limit, not a production-agent
budget. The case-folding test explicitly exercises the listing fallback so a
case-insensitive filesystem does not hide BUG-05.

## Verification and limits

The non-blocking `BH3 fixture` workflow checks the scorer on the existing three
supported operating systems using approved development-tool pins. It does not
change the production CI gates or introduce an LLM judge. The intentionally
buggy app is compiled and exercised, but not linted into a repaired baseline.

Baseline: 0/10. The known golden patch: 10/10. Maintainer controls also exercise
spoofed console output, empty/mismatched/duplicate manifests, missing/skipped
tests, teardown errors, ambient pytest options and shell interpreter selection.
These outcomes qualify the fixture and scorer, not any model. The runner is
not a sandbox: candidate Python executes with the caller's privileges, and
same-user hostile code can interfere with files or processes. Inputs and
oracle/control files must be held fixed by the evaluator; hashing is evidence,
not access control. Use an appropriate sandbox before evaluating untrusted code.

Golden fixes and bug descriptions are public here. Any future blinded trial
must separately withhold answers and record its actual task packaging. No
model calls, paid runs, human preference sample, or workstation qualification
are claimed. BH1/BH2 source verification remains separate in issues #326/#327;
BH4/BH5 remain owner-budgeted/advisory in #329/#330. This delivers BH3 (#328),
under epic #325 and parent #299, without changing the sister UX track #281.
