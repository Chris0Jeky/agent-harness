# Doctor controlled-dispatcher implementation packet

Status: DRAFT, production integration incomplete. Tracks #275.

This packet contains a proposed implementation and executable regressions. It
DOES NOT change the repository's active harness.py. A green general CI run on
this packet alone is not evidence that the Doctor bug is fixed. Keep the PR
draft until the patch is applied, reviewed and verified on all supported hosts.

## Proposed boundary

Pass the inspected Claude home's dispatcher identity into the floorless settings
scan. Reuse claude_command_points_to_dispatcher for exact token/path comparison;
do not classify any file merely because its name contains dispatch.py.

Preserve the established logical home references (~, HOME and Windows USERPROFILE
forms), requiring the complete .claude/hooks/dispatch.py token. Do not expand
arbitrary variables or infer session/environment values. Windows home syntax has
Windows case semantics; ordinary absolute paths use the existing host-aware
comparison. Comments and non-command handler shapes do not register a floor.
Home, project and local sources retain their scan order.

This remains static reference recognition, not proof that a shell invokes a
handler, that a home variable has a particular runtime value, or that settings
are trusted/active. It does not change the legacy dispatcher, floor policy,
permissions, native-agent qualification, or installation state.

## Reproduction and local evidence

The seven new test methods were run against unchanged harness.py first:
26 failing subcases, 0.114 seconds. After the proposed patch, all seven methods
passed. A combined run of 114 existing Doctor/floorless/Claude-command tests
and these seven new methods passed all 121 tests in 2.349 seconds on Linux,
Python 3.13.5. Existing home-relative and uppercase USERPROFILE controls remain
intact. Fixtures use disposable repositories and settings, not user settings.

The local workspace came from the supplied e150fbd archive. The relevant
harness.py bytes independently match current main's Git blob; this is not a
claim that the whole archive equals current main. No pinned local Black/Ruff
or native Windows/macOS qualification is claimed.

## Apply and integrate

From a clean branch, first compare `git hash-object harness.py` with the
preimage in receipt.json. Stop and reconcile if it differs. Then run:

```sh
git apply --check docs/implementation/doctor-floor-registration/harness.patch
git apply docs/implementation/doctor-floor-registration/harness.patch
python -m unittest discover -s docs/implementation/doctor-floor-registration -p 'test_*.py' -v
python -m unittest tests.test_harness -v
```

Verify the resulting harness.py hash against receipt.json. Move the test into
root discovery as tests/test_doctor_floor_registration.py, add it to the existing
Verify Ruff/Black/compile lists, run the pinned formatter/linter, and run full
root/replay/smoke verification. Record any formatting-induced hash change rather
than silently relabelling this receipt. Remove this transport patch after the
implementation lands and retain an accurate review/verification record.

Final acceptance requires an actual production diff, current-head supported-host
CI and review, with #275 kept open until then. Do not execute the patch as a
pre-test CI mutation or claim its local pass applies to unpatched published code.
