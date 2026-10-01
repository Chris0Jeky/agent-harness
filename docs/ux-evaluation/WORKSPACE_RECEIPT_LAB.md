# Workspace receipt lab

Status: executable **reference model**, not an application adapter, queue runner or production persistence library. Tracks #416; complements the authoring profile in #410. All data and identities are fictional.

## Question and result boundary

Can one owner transaction reject obsolete worker results while recording an accepted result, its receipt and an outbound obligation together? `scripts/workspace_receipt_lab.py` supplies a deliberately small SQLite fixture for that question. Existing `scripts/merge_gate_model.py` is a separate policy model and is unchanged.

Run from this repository:

```sh
python -m unittest discover -s tests -p 'test_workspace_receipt_lab.py' -v
```

The test suite starts with a fresh temporary file. It never reads a product database, network, credentials or provider. Opening a non-lab database is refused, and creating a fixture never overwrites an existing path. The application ID is only an accidental-misuse guard, not a security boundary against an adversary who can edit a database.

## Modeled contract

The fixture has one work row per `(scope, work)`. A claim names a worker, expiry and increasing fence. A result command binds scope, work, stable actor, operation key, expected target revision, epoch, policy version, fence and a result digest. Command hashing is explicitly this fixture's sorted JSON encoding, not a general JSON canonicalization standard.

The SQLite owner serializes a write with `BEGIN IMMEDIATE`. Before a new effect it checks current scope, revocation, epoch, policy, lifecycle, holder, fence, expiry and target revision. A current-authorized replay of the same operation and hash returns the saved receipt even after the old lease expires. Reusing a key with different command content conflicts. Scope is part of both the operation-key uniqueness boundary and receipt identity.

Result count/revision, receipt and outbox obligation are in one transaction. `human_state` stays `open`. Neither a recorded result nor a staged event completes a human commitment. The model has no dispatcher; `outbox=1` means one persisted obligation, not one delivery.

| Failure or interleaving | Required outcome |
|---|---|
| Failure before commit | No result, receipt or outbox row survives |
| Lost acknowledgement after commit | Retry recovers one receipt and creates no second effect |
| Outbox insert fails | Result and receipt roll back too |
| Same key from two connections | Both callers can recover the same receipt; one effect |
| Different keys targeting the same revision | One accepts; the other conflicts |
| Expired/replaced lease | Obsolete writer is refused at the committing owner |
| Same holder, wrong fence | Refused independently of the holder test |
| Same fence, wrong holder | Refused independently of the fence test |
| Revoked scope, including replay | No result or receipt disclosure through accept |
| Stale revision/policy/epoch | Refused independently for each dimension |
| Cancelled work plus late success | Work remains cancelled; no accepted result |

The explicit before/after-commit exceptions model process-level interruption boundaries. The trigger-induced insert failure models an atomicity failure path, not actual ENOSPC or a power cut.

## What the lab does not prove

Identity and time are supplied by trusted fixture callers. There is no HTTP authentication, token validation, session authorization, clock-skew detector, lease heartbeat, worker process containment, real prompt injection test, physical storage crash test, restore procedure or distributed coordinator. Test code changes fixture facts directly to model revocation/cancellation. Those edits are not exposed as product controls.

SQLite has a single writer even in WAL mode; WAL is not a cross-host shared-disk protocol. See the official [isolation documentation](https://www.sqlite.org/isolation.html) and [WAL documentation](https://www.sqlite.org/wal.html). This model demonstrates local transaction behavior with independent connections, not distributed consensus.

An epoch check rejects an old epoch **at the owner receiving the command**. It cannot stop two independently restored databases from both accepting effects. Production restore needs a writer-identity change, old credential revocation and receiver-enforced fencing or explicit old-host isolation before dispatch resumes. Restoring a counter from the same backup is not a split-brain solution.

An external service may perform an effect and lose its response. A local transaction cannot undo that uncertainty. Unless the remote service supports a qualified operation key or receipt lookup, such work must enter reconciliation rather than automatic retry. Do not advertise exactly-once external execution based on this lab.

The record stores only result digests, but scope and actor identifiers can still be sensitive in a real product. Production must additionally scope reads, define retention, test deletion/tombstones and keep secrets and raw transcripts out of telemetry.

## Consumer adoption

Translate one case at a time into a consumer-owned test against its real service/repository and real authorization context. Preserve independent negative controls, especially scope, fence, holder, epoch and revision. Qualify provider retry/lookup semantics separately. Record exact source and test identities and any unavailable case. A model pass never grants an agent authority, creates a merge gate or marks a live journey complete.
