# Workspace handoff acceptance profile

This is a reusable **authoring profile**, not a runner, an executed evaluation or a merge gate. It applies when an agent carries human intent into a work application, delegates a bounded job and reports a result.

## Facts that must remain separate

| Fact | Authority | A weaker fact is not enough |
|---|---|---|
| Durable capture accepted | Application persistence and its operation receipt | Adapter queue or HTTP request sent |
| Intent admitted | Existing runtime admission receipt | A prompt containing a job description |
| Attempt progressed or exited | Runtime attempt state and evidence | Agent narration or a provider response |
| Human work completed | Application transition under current authority and acceptance criteria | Exit code zero, merged code or a terminal attempt |

Use scoped identities for operations, intents, attempts and receipts. A source revision is an exact token, not a display timestamp. An expired permission or changed target is a new decision boundary, not permission to impersonate a human.

## Example and binding

`workspace-handoff.example.json` uses the existing `ux-scenario-pack/0` format. Its repository, revision (forty `1` characters) and fixture reference are deliberately fictional. No checkout or simulator is supplied. Replace them with a pinned candidate and an implemented, approved isolated fixture before execution. Do not claim its fixture exists merely because it appears in an allowlist.

The existing `ux_evaluation.scenarios.bind_pack` checks declarations against caller-supplied expected identity and fixture allowlist. The example tests assert `execution=not_run`, advisory authority and gate ineligibility, and reject identity/fixture mistakes and self-promotion to a gate. Binding does not attest a checkout, permission, invocation or observation.

```sh
python -m unittest discover -s tests -p test_workspace_handoff_profile.py -v
```

## Required journey evidence

The three authored journeys cover durable capture after a lost response, stale/revoked scope and the separation between attempt results and human completion. Retain ordered actions, requests, actual committed state and receipts. Capture UI evidence separately where the user-facing distinction matters. Record unavailable observations as BLOCKED or NOT RUN, not as an expected successful result.

A product implementation must add genuine crash-boundary, duplicate-delivery, out-of-order event, permission revocation and cancellation controls. Isolate revision and permission failures: first test a stale revision with valid scope, then revoked scope with the current revision. Otherwise one working gate can conceal another broken gate. Include a worker that exits successfully without satisfying acceptance criteria. Complete the journey only through the application's current authorized transition. Test fixtures must not borrow personal databases, cloud credentials or real messages.

## Qualification boundary

Nothing here changes the enforcement floor, execution framework, scheduling ownership, model routing, telemetry collection or the existing merge boundary. Deterministic product assertions may become qualification evidence only through the normal review process. Model judgment and a well-written scenario stay advisory. Never manufacture screenshots, receipts, observations or PASS results from declared expectations.
