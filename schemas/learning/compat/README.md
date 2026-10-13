# Learning-contract compatibility fixtures

All records are synthetic; accept files cover every record schema.
Reject records carry `_expect`, stripped before validation, to pin the refusal.
A fixture that stops validating as expected is a breaking contract change:
bump the bundle version and announce it on the learning-plane bus.
Never edit a fixture to make a red test green without that bump and announcement.

`FIXTURES.json` pins every ordinary file beneath this directory except itself,
including this README. Its sorted paths and CRLF-normalised SHA-256 values use
exactly the bundle digest rule. `learning_bundle.py check` checks both pins and
requires their versions to agree. Added, changed and removed fixtures require
`build --bump` (or an explicitly higher `build --version N`); ordinary `build`
refuses rather than silently bless a changed corpus. The lock is a reviewed
source pin, not a signature or a substitute for comparing a PR with its base.

The compatibility lock is separate from the exported `BUNDLE.json` file list and
digest. Consumers need not vendor the fixture corpus, and this addition does not
change any record schema. Version 2 introduces the initial compatibility pin.

`verify --vendored DIR` still compares only the manifest-listed files.
`verify --vendored DIR --strict` additionally reports unlisted `.json` entries
in `schemas/learning` and in the parent directories of explicitly mapped schemas.
It ignores the canonical `schemas/learning/BUNDLE.json` and does not scan unrelated
consumer directories. Strict output adds an `extra` array; either extras or byte
drift set `matches` to false and exit 1. The default output remains unchanged.

Recover a missing or conflicted bundle manifest with `build --version N`, choosing
the intended positive version explicitly. A valid existing bundle or fixture-lock
version cannot be decreased. `--version` and `--bump` are mutually exclusive.
A corrupt fixture lock requires a version-advancing refresh. A failure between the
two metadata writes is detected by `check`; recover with the intended explicit
version after inspecting both files. This is not a transactional multi-file write.
