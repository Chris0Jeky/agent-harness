# Mapped authority-document drift probe

First bounded implementation of [E4](https://github.com/Chris0Jeky/agent-harness/pull/291),
with qualification tracked in [#297](https://github.com/Chris0Jeky/agent-harness/issues/297).
This is a read-only advisory script in the existing harness workbench, not a policy resolver,
Doctor check, new runner, or merge gate.

```sh
python scripts/authority_doc_drift.py /path/to/agent-harness
python -m unittest discover -s tests -p test_authority_doc_drift.py -v
```

## Exact mapping and interpretation

The script reads only `.agent-harness/tier.json` and `CLAUDE.md` beneath the supplied local
root. It compares `authority.push` and `authority.merge` against the one explicitly mapped
sentence beginning `This repo is tier ... per ...`. Only free, gated and human-only values
are recognized. It does not interpret arbitrary prose or calculate which authority should win.

Each mapped field is a match, a candidate discrepancy, or unknown. The report always retains
two requested mappings and the inspected/unknown denominator. Missing files, invalid contracts,
multiple matching clauses, renamed wording, and unsupported values do not become zero debt.
Conventional fenced examples are ignored; this is not a complete CommonMark parser. HTML
comments and other Markdown constructs outside that limited mapping require human inspection.

Every report has `authority: advisory`, `merge_verdict: null`, and `revision_verified: false`.
Exit zero means report generation, including unknown inputs or candidates, not correctness or
merge eligibility. CI runs tests of this script; it does not run its candidate count as a gate.
Input SHA-256 values identify bytes, not their author, Git revision or execution authenticity.
Map them to a pinned checkout separately before claiming an attributable repository observation.

The finding key is stable for the same mapping and discrepancy within one repository. Prefix
it with the repository identity before aggregating across repositories. Moving the sentence to
another line changes the input digest and evidence location, not the underlying finding key.
Repeated scans are observations, not additional defects. No event store or aggregation service
is added here.

## Local data and authority boundaries

Input files must be regular, non-symlink UTF-8 files of at most 1 MiB each. Missing/unreadable
inputs remain unknown. Parent-directory symlinks and concurrent filesystem mutation are outside
this local diagnostic's threat model; this is not a filesystem sandbox. No command found in
these files is executed, no network service is contacted, and neither source nor output files
are written automatically. Keep reports local until their paths/identities are reviewed for
publication. The script cannot grant a merge or alter an authority declaration.

## Controls and remaining qualification

Twelve authored tests exercise the named stale sentence, the matching control, absent and
ambiguous wording, fenced examples, malformed/duplicate-key JSON, unknown authority values,
partial coverage, stable finding identity, changed input bytes, and invalid/oversized inputs.
Their execution is synthetic parser/measurement-contract evidence, not a real-repository
precision, recall or reviewer-effort result.

Inspection at `b406374` identified a candidate discrepancy: root prose says merge gated while
the canonical declaration says merge free. That observation selected this bounded mapping;
it is not an automated full-snapshot trial. #297 remains open to run the script on an exact
full snapshot, confirm or reject the candidate, review any correction of stale prose, and
repeat with the known-good and unavailable controls. No stale prose is silently changed by
this implementation. No entry is added to BENCHMARKS before that attributable trial runs.

Do not generalize this two-field mapping into duplicate-abstraction or unfinished-surface
quality scores. Existing review/oracle limits in #290 apply, and B0 (the unavailable original
research brief) remains unresolved. These implementation choices are new recommendations,
not findings attributed to an unseen brief.
