# Corpus path boundary

## Scope

Issue #147 requires corpus entries to remain beneath the resolved corpus
base, before any bytes from an outside target are read. The related NUL-path
case in #145 must return input-invalid exit 2 before loading policy sources or
publishing a report. This is a manifest input boundary, not a filesystem
sandbox or a change to process-policy tree handling.

## Resolution and evidence flow

`validate relative path -> resolve base and target -> require containment and
ordinary file -> capture exact bytes -> verify digest -> validate corpus ->
load policy sources`.

Both manifest construction and loading share `_resolve_corpus_file` in
`replay_v0/manifests.py`. Relative path validation rejects NUL first. Resolution
uses strict paths and compares path components, not string prefixes. A target
outside the resolved base is rejected before hashing or byte capture. Internal
file/directory aliases and an aliased base are allowed when the final ordinary
file remains inside that base; the original relative manifest names and exact
byte hashes are preserved.

Resolution errors are translated to `ManifestError`. Diagnostics identify the
manifest's relative entry without exposing the resolved outside target. The
existing CLI exception boundary emits `replay input invalid:` and returns 2.
There is no new report, retry, process launch, or permission grant on failure.

## Controls

The existing manifest test module covers external file and directory links,
a similarly prefixed sibling directory, ordinary in-tree bytes, internal
aliases, an aliased base, directory rejection, and NUL rejection. Read spies
prove that the loader reads only its manifest when the single entry escapes;
the builder's hasher is not called. A mocked resolution result exercises the
containment decision even on hosts without symlink creation privileges.

Separate CLI tests pin external-link and NUL failures to exit 2, the diagnostic
class, no traceback or outside-target disclosure, no policy-source load, and
no report directory. Only real symlink cases may skip when the host cannot
create the required link; the NUL CLI case is independent and never depends
on that host capability.

```text
python -m unittest replay_v0.tests.unit.test_manifests replay_v0.tests.contract.test_cli -v
python -m pytest -q replay_v0/tests
```

The change refreshes only the two existing source/test digest entries in the
35-file extraction manifest. It does not expand the approved extraction set or
change its approval metadata. Preserve unrelated newer-main digests when
publishing a change developed from an older archive.

## Limits and follow-through

This proves lexical and resolved-path containment at the read boundary. It
does not prove inode isolation for every alias, prevent concurrent directory
replacement, or replace caller-controlled storage isolation. File-descriptor
based race hardening is a separate design decision, not claimed here.

Only #145's NUL-path case is covered. Its numeric decoding, extreme timeout,
and process-wrapper classification cases remain separate work; the issue must
not be closed solely because this boundary lands. No dispatcher, native-agent
qualification, production timeout, charter, or CI gate is changed.
