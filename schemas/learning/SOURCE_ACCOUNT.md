# Optional experience account attribution

The `estate-experience/v1` source contract permits optional `source.account`:
a string of 1-64 characters, omitted when unknown. This is producer-supplied
attribution, not an authorization or account-partition boundary.

Source identity remains `kind` plus `key`. The deterministic experience ID and
default split key exclude `account`; later observations may supply or correct
attribution without creating a new experience. Producers must keep native source
keys distinct when sessions differ, including across accounts.

The outcome stream projects only `kind` and `key` into `outcome-event/v1.run`.
Consumers can obtain account attribution by joining the event's `experience`
back to the experience ledger. An account-only observation does not create a
new outcome-event version, and an attributed run retains the same event IDs,
version chain and posterior as its otherwise identical legacy record.

Legacy records without `account` remain valid. Present null, empty, non-string
and overlong values are invalid; source fields other than `kind`, `key` and
`account` remain rejected. No account is inferred, and no credential or account
configuration is collected by this change.

Consumers must update their vendored schema and validator bundle before emitting
the new optional field. The schema name stays `estate-experience/v1`; the bundle
version and digest identify the updated accepted contract. See
[SPECS section 15](../../SPECS.md) for the surrounding
record, storage and lifecycle contract.
