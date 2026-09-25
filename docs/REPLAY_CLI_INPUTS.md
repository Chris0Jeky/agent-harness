# Replay CLI input identity and timeout limits

Follow-through for #146 and the CLI timeout portion of #145. Decision-output
JSON handling is separate in #334; corpus path containment landed in #333.

## Process labels

The CLI emits `process-<full identity SHA-256>` as each process-policy ID instead
of copying the filename stem. A readable policy with a space, leading underscore,
leading dot, non-ASCII letter or long stem can therefore satisfy the existing
portable manifest-ID grammar without renaming the file.

This reuses the existing v9 identity digest. The supplied filename, bytes,
parent tree, executable, timeout and other bound inputs still contribute to
that digest. Distinct names are not collapsed by lossy sanitization. This is
not a location-independent content ID or authentication of an execution.

**Compatibility:** IDs and derived run IDs change for all process sources,
including previously accepted filenames. The identity SHA-256 calculation,
manifest schema, recorded-source IDs and validation of existing reports are
unchanged. Compare archived and new results using their declared inputs rather
than assuming the old stem-based label remains stable. Commas and multiline
argv values remain outside the existing process-reference grammar (#142).

## CLI wait input

`--timeout` accepts finite seconds in `0 < timeout <= 86400`. The existing
30-second default and fractional positive values remain supported. One day is
an explicit CLI upper bound, not a benchmark or a new cleanup timeout.

Invalid values, including an extreme finite value such as `1e100`, fail argument
parsing with exit 2 before reading a corpus, loading a policy or publishing
reports. The diagnostic states the accepted bound without a Python traceback.
The process runner, constructor API, snapshot behavior and cleanup grace are
unchanged; this does not claim to normalize every platform-wrapper exception.
The remaining #145 cases stay open.

## Verification

`python -m unittest replay_v0.tests.contract.test_cli_inputs -v` exercises real
filename/manifest round trips, repeated fixed-time runs, distinct names and
semantic changes. Timeout controls prove early rejection and include a real CLI
subprocess whose candidate launch marker and report directory remain absent.
The module is included in the existing three-OS source-check lists and in
replay discovery. No new dependency, job, privilege or model-based gate is added.
