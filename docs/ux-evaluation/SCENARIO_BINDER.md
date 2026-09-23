# Offline scenario binder

Implementation slice for T1 #282 and T5 #286, following [architecture PR #289](https://github.com/Chris0Jeky/agent-harness/pull/289). This command validates authoring declarations; it does not execute the Taskdeck journey, prove a fixture exists, attest a checkout or grant permissions.

## Run from the harness checkout

```console
python -m ux_evaluation bind --pack docs/ux-evaluation/scenario-pack.example.json --expected-repository Chris0Jeky/Taskdeck --expected-revision 622d9d820f48e68ac7fa77d94c9ca2536155ddf8 --fixture-ref "Taskdeck frontend/taskdeck-web/tests/e2e/workspace-overhaul.spec.ts: setup / keeps Home capture and saved thinking across all experience combinations"
```

The expected identity and repeated `--fixture-ref` arguments are supplied by the coordinator after inspecting the actual product/fixture. They are declarations, not discovered or authenticated facts. A caller can lie about them; the binder does not prevent that. It performs no Git, browser, model, network, installation, server reset or publishing operation. Missing fixture allowance fails closed. No YAML parser or dependency is added; the Taskdeck YAML authoring pack needs an explicitly reviewed JSON serialization before use.

Exit 0 means the declarations are structurally valid and internally match the supplied identity/allowlist. Exit 2 means an invalid input or command. Neither is a product-quality verdict. Output is stdout JSON `ux-scenario-binding/0` with canonical pack SHA-256, expected subject, ordered journey IDs, `authority: advisory`, `gate_eligible: false`, and `execution: not_run`. Error diagnostics do not echo source content or input paths. Normal argparse usage errors describe invalid command arguments.

## Checks implemented

The existing authoring format remains `ux-scenario-pack/0`: exact object fields; unique journey IDs and per-journey step IDs; nonempty unique string lists; known rubric/evidence dimensions; integer-only bounded budgets; exact lower-case full Git revision; explicit advisory/local-only booleans. Boolean-as-integer aliases are refused. Semantic duplicate step IDs cannot pass by changing their action text.

The reader bounds raw/canonical UTF-8 to 256 KiB, depth to 32 and nodes to 20,000; rejects duplicate JSON keys, invalid Unicode, nonfinite numbers and excessive integers. Final input symlinks, hardlinks, special files and Windows reparse files are refused. Filesystem checks detect common static aliases and observable concurrent mutation; this is not a concurrent-writer sandbox. The caller chooses a trusted input parent directory. Artifact directory containment belongs to the subsequent evidence verifier.

Canonical identity ignores object-key order and JSON whitespace but preserves all array order. This is deliberate: it is a precise document identity, not equivalence of differently ordered authoring declarations. The API never changes its input.

## Verification and remaining scope

`python -m unittest discover -s tests -p 'test_ux_scenarios.py' -v` covers valid binding, canonical identity, no input mutation, mismatched subjects, unknown fixtures, malformed object/list/budget/ID input, bounded JSON and the real CLI/error-output boundary. Twelve cases failed before the implementation existed, then passed locally. Full repository Windows/Linux qualification belongs to the exact PR-head CI receipt, not that local subset.

Taskdeck counters, actual fixture execution, observation capture, independent UX judgment, calibrated severity, owner taste and P5 native activation remain open. No LLM merge gate, hidden counter instrumentation or browser success is inferred from this first executable slice. Packaging remains in claude-config; this module owns deterministic validation only.
