# Process-fixture startup is not containment evidence

Follow-through for [#323](https://github.com/Chris0Jeky/agent-harness/issues/323).
This boundary belongs to the existing Policy Lab and hook tests, not a new
production supervisor, timeout policy or merge gate.

## Boundary

The fixture launch sequence is:

```text
isolated stdlib interpreter -> child initialization -> atomic startup record
    -> existing process timeout/cleanup -> startup and behavioral assertions
```

The interpreter that runs the synthetic policy and its children uses `-I -S`.
The fake `git` and `gh` shims do likewise. These stand-ins need only the standard
library; developer site initialization and Python import paths are not part of
what they are testing. The actual dispatcher invocation and all production
runner code remain unchanged. The Windows policy wrapper is not rewritten.
[Python's command-line reference](https://docs.python.org/3/using/cmdline.html)
documents isolated mode and suppression of automatic `site` initialization.

A parent-written PID proves that a process was created, not that its child code
initialized. A child therefore publishes a separate startup state containing
its PID and actual interpreter startup flags. Write to a temporary sibling and
rename only after the complete record is closed; file existence must not expose
a half-written JSON record. The setpgrp child also publishes its existing
process-group/session identities this way.

Tests require the parent PID and child record to agree before interpreting
termination or escape. Absent, unreadable, malformed or mismatched startup
observations fail with `fixture-startup-unverified`. This is an ordinary failed
test, not a skip, successful negative control, or evidence that a child was
contained. A started child still has to satisfy the original behavioral checks.

## Controls and retained semantics

The oracle controls run the actual process runner against deliberately delayed
synthetic parents and a parent that publishes only its child's PID. They inspect
an inner test result to prove those cases fail explicitly. They do not mock a
successful process verdict. Additional controls check a normal initialized
child, rejected startup flags, an ambient Python import trap, and the actual
startup state reported by both platform-specific probe shims.

The 0.5/1.0-second timeout cases retain their budgets and the existing
indeterminate result requirement. Completed-parent checks, same-group
termination, POSIX setpgrp escape and escaped-child cleanup remain exercised.
No retries, deadline enlargement, source-policy change or workflow job is
introduced. No existing test is newly skipped. Platform-specific controls retain
explicit skips where the operating system lacks the required semantics.
The extraction manifest refreshes only the two changed replay-file digests.

## Running and interpreting the tests

```text
python -m unittest replay_v0.tests.contract.test_process_source -v
python -m unittest tests.test_dispatch_as_hook -v
python -m unittest discover -s replay_v0/tests -v
python -m unittest discover -s tests -p "test_*.py" -v
```

A startup failure under severe scheduling pressure remains a failure to obtain
behavioral evidence. Inspect the startup record and interpreter/environment
before attributing it to containment or weakening a timeout. These synthetic
controls do not qualify a native agent runtime or prove universal process-tree
containment. Keep local interpreter results distinct from the existing hosted
Python/OS matrix, and retain failed attempts rather than retrying until green.
