# Mapped authority drift: pinned local trial

Inspection: 2026-09-23. Relates [#297](https://github.com/Chris0Jeky/agent-harness/issues/297)
and implementation [#298](https://github.com/Chris0Jeky/agent-harness/pull/298).
This records a real local CLI trial, not a native agent rollout or merge verdict.

## Scope and implementation boundary

The existing adapter reads only `.agent-harness/tier.json` and the exact mapped
root `CLAUDE.md` clause. Its pipeline remains local bytes, explicit mapping,
requested/inspected/unknown counts, then an advisory report. No new scanner,
parser framework, telemetry collector, workflow or policy authority is added.
The correction is a separately reviewed prose diff, not a probe-side auto-repair.

## Snapshot and executable identity

The supplied archive identifies revision
`4ed6561ceabca623e556e8bca6c0574b9d555c3f`. Reconstructing its Git tree from all
130 tracked files, including Git file modes, produced
`b391e9a5bf0df5b5258e6be95c136de76d3714c5`, exactly matching
[GitHub's pinned commit](https://github.com/Chris0Jeky/agent-harness/commit/4ed6561ceabca623e556e8bca6c0574b9d555c3f).
This checks repository content against that retrieved identity; it is not a
signature verification or a claim about the user's installed configuration.

The executable was the drift probe at
[`5f6b8f8da02ededdccbac0a944e3fded848209c0`](https://github.com/Chris0Jeky/agent-harness/blob/5f6b8f8da02ededdccbac0a944e3fded848209c0/scripts/authority_doc_drift.py),
Git blob `ea81677e96dd519a146ae752c82e0fd699456e7a`.
Its formatting-only changes preserve the original probe's Python AST.
Environment: Linux, Python 3.13.5. Each observation below used a real subprocess:

```text
python /path/to/checker/scripts/authority_doc_drift.py /path/to/snapshot
```

These are caller-selected local paths, not commands extracted from repository
prose. No network request, installation, hook activation or source-file write was
performed by the probe. The original snapshot's 130 tracked-file SHA-256 values
were compared before and after the trial and were unchanged.

## Observations

| Input | Requested | Inspected | Candidates | Unknown | Interpretation |
|---|---:|---:|---:|---:|---|
| Complete pinned snapshot | 2 | 2 | 1 | 0 | Line 18 documents merge `gated`, while the declaration says `free` |
| Separate complete copy, only that clause corrected | 2 | 2 | 0 | 0 | Both mapped fields match |
| Known-good two-file control | 2 | 2 | 0 | 0 | Independent minimal matching input agrees |
| Control with `CLAUDE.md` removed | 2 | 0 | 0 | 2 | Unavailable input remains unknown, not a clean assessment |

All four subprocesses exited 0 with no stderr. Every report retained
`merge_verdict: null`, `revision_verified: false` and advisory authority.
The baseline was repeated and its complete parsed report was identical.
The concrete discrepancy key was `authority-doc-v1:merge:free:gated`.
The probe did not establish the Git revision itself; the snapshot mapping above
was checked separately by the caller.

## Exact input digests

SHA-256 over the bytes supplied to the probe:

| Input | SHA-256 |
|---|---|
| Tier declaration, unchanged in every control | `33ec95e5d08ff5c759f4344ed675e67b9b1329465f250c6841ee591a1bc086d3` |
| Original complete `CLAUDE.md` | `a58ff28f4631211bac7d3c868ee9fc6b7d8c3853a46edf15731ad54c7cac67dd` |
| Corrected complete `CLAUDE.md` | `895e61991acd3dcf66a0bda36256b6c68263b08a9e1864b18fdf46fd649b710f` |
| Minimal known-good clause | `3c47497683b0b27aeff343e5082bad4c2f8f9aff7a357bf2d638a4804bd217eb` |
| Missing document | null, no bytes inspected |

## Review and reconciliation

The canonical declaration was inspected directly before proposing the correction;
it already sets both push and merge to `free`. This PR changes neither declaration
nor permissions, protection settings, review requirements, or CI. Free authority
does not mean that unreviewed or failing work is safe to merge.

GitHub comparison of the archive revision with main
`fcea0eb3fc129d5422250133a50e1d1d47c1dba0` showed only the two #288 documentation
changes, outside this mapping. Before publication, the live root guidance was
retrieved again and still matched original Git blob
`dd4a6c3f633fe78812c16070d0af9e1e8db58ffd`.
The proposed corrected blob is `a007ea1a71786fab81033de858ea283ffac70998`;
its 149-line count remains within the existing 150-line budget.

## Limits and remaining acceptance

This trial covers exactly two explicitly mapped fields in one repository plus
controls. It does not establish estate-wide precision, recall, runtime policy
resolution, useful automation savings, or native Windows/macOS qualification.
The 12 synthetic probe tests also pass, but are separate from this real-input
trial. Both the implementation and this evidence/correction still need their
applicable published-head CI and review before #297 is closed.
No new mapping or quality gate is authorized by these observations.
