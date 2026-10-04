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

The first five authored journeys cover durable capture after a lost response, stale/revoked scope, the separation between attempt results and human completion, incomplete observations and cancellation at admission. The attempt journey includes an identical progress replay and an independently stale, out-of-order report before cancellation, reflecting a native monotonic-report contract while remaining an unexecuted generic case. Retain ordered actions, requests, actual committed state and receipts. Capture UI evidence separately where the user-facing distinction matters. Record unavailable observations as BLOCKED or NOT RUN, not as an expected successful result.

A product implementation must add genuine crash-boundary, duplicate-delivery, out-of-order event, permission revocation and cancellation controls. Isolate revision and permission failures: first test a stale revision with valid scope, then revoked scope with the current revision. Otherwise one working gate can conceal another broken gate. Include a worker that exits successfully without satisfying acceptance criteria. Complete the journey only through the application's current authorized transition. Test fixtures must not borrow personal databases, cloud credentials or real messages.

### Completeness and admission boundaries

A bounded response is not automatically a complete snapshot. Complete, partial, unavailable and
denied are four distinct states: a partial read never authorises inferred deletion or inferred
delivery, unavailable stays unknown (never PASS, never an empty collection) and denied hides private
cached content. The incomplete-observation journey requires a preserved complete checkpoint through
a partial read, an unavailable source and restart, then an independent access-denial control that
cannot be undone by an older reply. An omitted item is not evidence that a reminder was delivered,
a task was deleted or access was revoked. Consume authoritative
outcome receipts where the distinction matters; do not turn a collection cap into an effect.

The admission journey records a precise launch-admission boundary. Persisted cancellation before
that boundary must prevent launch; cancellation after it is an in-flight request. Independently
retire the lease during the last permission read and expire a disclosure grant while that read
is pending. These controls must leave newer ownership intact and must not manufacture process
acknowledgement or effect reconciliation. A scheduler lock does not fence an external writer.

### Evidence ladder, catch-up and fix rounds

Three further journeys are advisory and `not_run`; they make no execution claim.

**Evidence ladder** (`evidence-ladder`): source, unit, integrated, native runtime, installed, device, owner accepted. Each rung is its own receipt. Every rung records the subject revision, exact source revision, fixture revision or hash, UTC time and environment, proof kind, command and cwd, pass/fail/skip counts, unavailable observations and advisory or operational authority. The installed rung adds an installed artifact identity distinct from the source revision. The device rung adds device and platform identity. The owner-accepted rung is an owner-supplied record, never inferred by an agent or implied by a lower rung. A lower rung never implies a higher one, and a higher rung never transfers to a different candidate revision; re-observe each rung against the new revision.

**Catch-up contracts** (`catch-up-contract`): look up outcomes for known IDs directly and read unseen ones from a commit-ordered feed. Apply a first-run floor and report items before it as not examined. Each pass re-reads an inclusive overlap and continues exclusively past it. A page never splits one timestamp group, and a resume position never lands inside one. A deferred item is never skipped by a resume position, and a failed read never advances it.

**Fix-round discipline** (`fix-round-discipline`): run one scoped verification after every fix round. Past fix rounds repeatedly introduced new high-severity defects: an expiry that dropped recoverable rows, a cursor that advanced on a failed read, a resume position that skipped deferred rows. Verify the fix diff and its neighbouring seams against the exact fix revision; a verification of an earlier revision does not cover it.

These are authored acceptance requirements. Passing the profile's declaration tests does not
prove that any product implements them, and no additional simulator or scheduler is introduced.

### Agent-admin workspace journeys

Five more journeys cover agents that do a person's admin inside their task system. They are advisory and `not_run` like the three above, and use a fictional person, Sam, with synthetic items and one synthetic credential per agent. The model: an **admin agent** acts, an **adversarial auditor** checks it, a **correction** needs a second agent's approval and stays rare, agents **archive rather than delete** until undo history exists, and the person reads **digests with undo links** on a morning, evening and weekly cadence.

| Journey | What a qualifying implementation must show |
|---|---|
| `admin-agent-acts` | Each act has a committed receipt from the change feed; a stale revision is a conflict, never an overwrite; out-of-scope requests are refused without borrowing another identity; a partial batch counts succeeded, failed and not attempted; narration without a receipt is not an effect |
| `adversarial-audit` | The auditor has its own read-only identity and audits the committed change feed over a declared window, not the audited agent's report; partial coverage is never clean; zero examined items is not a pass; the auditor cannot apply its own correction |
| `two-agent-correction` | The proposal binds operation, target revision and a digest of the exact change; the approver is a different agent from the proposer; an approval never transfers to a newer revision; a rejection applies nothing; corrections past the window's budget escalate to the person instead of applying |
| `archive-not-delete` | Cleanup archives with a restore handle; restore keeps fields, links and history; permanent delete is refused to every agent; an item missing from a partial read is unknown, not deleted; a retention purge that would end restorability early is reported |
| `tldr-undo-cadence` | Each digest declares its commit-ordered window, first-run floor, coverage and delivery state; daily windows neither overlap nor gap; every act links its receipt and undo; undo after a later edit is a conflict; undo runs under the person's authority, never an agent's; unknown delivery is not delivered; a superseded undo is never shown as available |

**Receipt fields.** Every agent act records: operation id, acting agent identity and credential, role, authority scope and policy version, target item and the revision read before acting, committed before and after state, reason, undo handle and its availability, application commit time (UTC) and change-feed reference. The person is never recorded as the actor of an agent's act, and an agent never as the actor of the person's undo. Audits add the auditor identity, window bounds, coverage, items examined, checks run and findings. Corrections add proposal id and digest, proposer and approver identities, approval time and the target revision at approval. Archives add the archive location, restore handle and purge time. Digests add cadence, window, first-run floor, coverage, items not examined and delivery state. A receipt with an unavailable field records it as unavailable; it never fills it from the agent's own account.

## Fictional adoption profile

This table assigns conformance questions to generic roles. It records no native adoption; the example pack remains `ux-scenario-pack/0`, advisory and `not_run`. Keep any real repository map and native receipts in the adopter's private evidence record.

| Reference question | Native proof owner | Required observation |
|---|---|---|
| Lost capture response, duplicate key and changed-payload conflict | Work application | One persisted capture and its authoritative receipt through the actual client; independent scope/revision controls |
| Lost admission response and duplicate enqueue | Admission runtime and receiver | Stable intent/attempt mapping, actual admission receipt and one admitted job after reconciliation |
| Duplicate or out-of-order progress | Attempt/report owners | Identical-sequence replay, stale report handling without state regression and durable recovery after restart |
| Incomplete collection and restart | Projection and source owners | Explicit coverage, preserved complete checkpoint, no inferred effects and a separate denied-access/late-response control |
| Cancellation before launch admission | Admission runtime | Cancellation and lease retirement during the final authority read prevent launch; elapsed read time can expire the grant |
| Cancellation and late success | Runtime, receiver and effect owner | Separately observed request, admission stop, process acknowledgement and reconciled effects; unavailable observations stay unknown |
| Successful worker without accepted human outcome | Work application | Attempt result/evidence recorded while human work remains open; completion uses a separate authorized transition |
| Restored owners with copied epoch/fence | Effect receiver | Receiver-enforced fencing or explicit old-writer isolation; the receipt lab's two-owner counterexample proves neither |
| Agent acts, audits, two-agent corrections, archive-not-delete and digests with undo | Work application, admin and auditor agents | The agent-admin receipt fields above, read from the application's committed change feed; the person's undo and permanent delete stay the person's acts |

Cancellation requested does not establish that admission stopped. Admission stopped does not establish process acknowledgement, and process acknowledgement does not establish reconciled effects. Record each observation separately, including `blocked` or `not_run` where appropriate. Repeating the receipt lab's cancelled-work/late-success case is reference coverage, not native adoption evidence.

Each native receipt records the evidence-ladder fields of its rung (see Evidence ladder above). Existing binding validates declarations only; it never invokes a runner, checks permissions or decides merge eligibility. Do not add fixture/identity fields to the strict schema merely to turn a pending proof request into an apparent executed observation.

## Qualification boundary

Nothing here changes the enforcement floor, execution framework, scheduling ownership, model routing, telemetry collection or the existing merge boundary. Deterministic product assertions may become qualification evidence only through the normal review process. Model judgment and a well-written scenario stay advisory. Never manufacture screenshots, receipts, observations or PASS results from declared expectations.
