# Replay JSON argv Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement and verify this bounded fix.

**Goal:** Resolve #142 without changing the existing bare comma-separated process reference.

**Architecture:** Add the explicit `process-json:` source prefix. Decode its payload as one JSON array of argv strings, then route both encodings through the same executable, policy, identity and snapshot validation. Never invoke a shell or infer an encoding from a filename.

**Tech Stack:** Python 3.11+, standard library only, unittest, existing nine-job CI.

**Spec:** GitHub issue #142, replay_v0/README.md process source contract.

## Global constraints

Keep the final argv element as the policy file; preserve current process identity for equivalent decoded arguments. Reject NUL, CR/LF, unpaired surrogates, malformed JSON and non-string/empty array entries. Do not change policy verdicts, environment binding, isolation, authority, timeouts or manifest schemas. Existing `process:` bytes retain their grammar, including brackets and quotes as literal characters. No external or paid model calls.

## Review focus

Commas in the executable path, policy path and non-final arguments must survive decoding. Quoted JSON and escaped backslashes must round-trip without shell interpretation. Invalid JSON must never fall back to comma parsing. Printed reproduction must retain its structured argv exactly. Ordinary legacy invocations must retain their identity and behavior.

## One implementation slice

- [x] Add root-discovered tests for JSON grammar, controls, malformed encodings, identity parity and real CLI/reproduction with comma-bearing paths/arguments.
- [x] Run the controls against unchanged production and retain the expected failures.
- [x] Implement decoding in replay_v0/cli.py and share existing loading/validation.
- [x] Update replay_v0/README.md, extraction hashes for changed exported files, and all existing CI source-check lists for the new root test.
- [ ] Run focused tests, root discovery, replay suites, smoke and source checks; record unavailable local tools honestly.
- [ ] Publish a draft PR and require all nine exact-head Actions jobs plus review before any merge.
