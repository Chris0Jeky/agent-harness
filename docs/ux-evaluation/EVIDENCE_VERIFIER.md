# Frozen observation verifier

Executable continuation of [scenario binder #292](https://github.com/Chris0Jeky/agent-harness/pull/292), T2 #283 / T4 #285 / T5 #286. No browser runner, judge, publisher, attestation service or product counter instrumentation is added.

## Invocation

From the harness checkout:

```console
python -m ux_evaluation verify --pack /local/run/pack.json --manifest /local/run/observation.json --run-root /local/run --expected-repository example/product --expected-revision 1111111111111111111111111111111111111111 --fixture-ref "tests/journey.spec.ts: synthetic fixture"
```

Paths and identities above are illustrative caller inputs, not existing product evidence. Supply an actual frozen local bundle and independently inspect the expected subject/fixture. The command creates no files and prints a bounded JSON summary only. Exit 0 means matching bytes and complete declared coverage; 2 means invalid metadata, files or identity; 3 means a valid explicitly partial/blocked record. None means good UX or permission to merge. A complete record can contain a failed product assertion and still exit 0.

## Observation v0

`ux-observation/0` is separate from the unchanged authoring `ux-scenario-pack/0`. The precise runnable synthetic constructor is `tests/test_ux_evidence.py`; it creates two real temporary files and their matching metadata without a browser. It is test evidence, not a Taskdeck run.

| Object | Exact fields and semantics |
|---|---|
| Observation | schema, run_id, authority=advisory, gate_eligible=false, subject, pack_sha256, journey_id, status, observer, artifacts, steps |
| Subject | repository and source_revision; must match both the scenario and caller-supplied expected identity |
| Status | complete, partial or blocked_environment; complete is refused when coverage or observations are missing |
| Observer | controller, controller_version, environment, fixture_ref, local_only=true, synthetic=true, actions, elapsed_ms, retries |
| Artifact | id, path, kind, sha256, size_bytes, captured_at; UTC second-resolution timestamp YYYY-MM-DDTHH:MM:SSZ |
| Step | id, outcomes and artifact_ids; exactly the scenario's ordered steps, including not-run steps |
| Outcome | status and nonempty reason; positional match to the scenario's ordered assertions, never a changed expectation |

Allowed assertion statuses are pass, fail, blocked, not_run and not_applicable. In this conservative v0, the last three retain incomplete coverage; a not-applicable decision cannot silently satisfy a planned assertion. Observer counters are bounded by the scenario budget and checked for basic consistency, but remain declarations, not measured by this tool. Each step with a recorded pass/fail needs at least one declared action in the run total.

Every referenced artifact must exist; unreferenced inventory entries, unknown IDs, duplicate IDs, case-insensitive path aliases and duplicate content hashes are refused. Reuse one artifact ID across steps rather than duplicating the same bytes under different kinds. All metadata is checked before any artifact payload is opened. Missing required evidence kinds are listed on partial records. Complete records cannot omit them. Corrupt or absent declared files are invalid even when the run is marked partial.

## File boundary

Artifacts use portable ASCII relative names: slash-separated alphanumeric-leading components with letters, digits, hyphen, underscore and dot; no trailing dot. Absolute/traversal/backslash paths, empty components, Windows device names, alternate streams, short-name aliases and tilde forms are refused. Names are bounded to 240 characters. Copy deliberately named exports into a run-owned directory; do not repoint the manifest at an arbitrary product tree.

The verifier rejects static symlinks/reparse directories throughout the supplied root and artifact path, and nonregular/hardlinked final files. It compares stat identity around handle-bound bounded reads, byte size and SHA-256. Inventory caps: 128 artifacts, 32 MiB per artifact, 128 MiB total. JSON input retains the binder's 256 KiB/depth/node limits. No archives are extracted or active content executed. Large traces need a deliberately bounded export while the original stays local.

This is not a sandbox against a malicious concurrent filesystem writer, an NFS/mapped-drive detector or a verifier of collector honesty. Use a trusted local root with no concurrent writers. Hashes prove exact bytes, not authenticity. A file labelled screenshot/trace is not decoded here; artifact modality, timestamps, action logs, assertion truth and before/after counters are declared. The next product observer must collect them through the actual runtime. A forged self-consistent bundle can pass these structural checks.

## Stable output and review

Output `ux-evidence-check/0` retains product/pack/normalized-observation identities, run/journey IDs, counts by assertion status, missing evidence and artifact count/size, plus mandatory assurance limitations. Artifact inventory/reference order is normalized; step/assertion order remains significant. It copies no raw evidence, reason text, observer environment or filesystem paths into the summary. It never emits a quality score or a merge/release verdict.

Raw files stay local. A successful byte check is not redaction, licensing, human consent or publication approval. The judge receives separately reviewed evidence and may abstain; it does not change the deterministic assertion outcomes. Original-brief reconciliation, T3 economics, native P5 activation and actual Taskdeck zero-effect counters remain separate work.

## Verification

Fifteen cases first failed because the verifier was absent. Sixteen final evidence tests plus twelve scenario tests pass locally; the extra case separates hardlink testing from symlink privileges. Native CLI cases cover exit 0/2/3 and error redaction. Filesystem tests create actual symlinks/hardlinks when supported. Exact-head Windows/Linux full-suite CI is separate from this local subset. No LLM is called by these tests or promoted into CI.
