# Replay process policy-root aliases

A process policy may be reached through a directory symlink when the host can
resolve it. The loader resolves the **parent directory once**, then binds the
policy file and parent-tree digest through that resolved directory. Snapshot
preparation copies this bound directory, not a later destination of the alias.
The final filename remains the caller's filename, including when that file is
itself a supported file symlink. Directory links inside the bound tree, broken
links and cycles remain unsupported.

## Identity and invocation

Direct and directory-aliased references have the same existing v9 identity when
they select the same filename, tree bytes and modes, executable, arguments,
environment contract, timeout and snapshot parent. No identity-version change
is required: the alias is a locator, not an additional semantic input. The
original spelling remains in structured reproduction. JSON reports and process
identity fields do not expose the resolved directory.

A retargeted alias does not change an already loaded source's bound parent. A
new load observes its current destination and derives identity from that tree.
Changes to the original bound tree are still detected when the private snapshot
is verified. This is not a concurrent-filesystem sandbox or an open-directory
handle guarantee. Runtime cwd is the validated private policy snapshot, as for
a direct source; resolving a parent does not switch to a symlinked file's parent.

## Boundaries and verification

Report output inside the bound policy root or a reserved snapshot remains input
invalid before either policy launches. Snapshot recursion protection and cleanup
remain unchanged. Parent traversal after an alias follows filesystem lookup;
lexically cancelling `alias/..` can select the wrong tree and is not used.

`tests/test_replay_policy_root_alias.py` covers direct/alias identity and decision
parity, both source positions, exact structured reproduction, file aliases,
retargeting during and after binding, changed inputs, parent traversal, report
and snapshot overlap, interior directory links, broken/cyclic roots, bounded
resolution errors, unchanged original trees and cleanup. Tests create real
synthetic links and skip only when host symlink creation is unavailable.
Windows may require symlink privilege. No native-model qualification is implied.
