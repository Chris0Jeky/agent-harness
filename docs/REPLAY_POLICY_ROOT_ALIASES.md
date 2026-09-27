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
remain unchanged. Parent traversal follows the host's path lookup, not a portable
promise that `alias/..` selects the alias target's parent. On POSIX the test proves
that physical traversal. On Windows native lookup can normalize `..` first; the
Windows control proves which file and parent are selected independently of the
loader, then requires input-invalid without execution when that selected tree
contains an unsupported directory link. No custom lexical cancellation is added
to the loader, and the tree-content restrictions are not relaxed.

`tests/test_replay_policy_root_alias.py` covers direct/alias identity and decision
parity, both source positions, exact structured reproduction, file aliases,
retargeting during and after binding, changed inputs, native parent traversal,
report and snapshot overlap, interior directory links, broken/cyclic roots,
asserted resolution-error injection, unchanged original trees and cleanup.
Tests use real synthetic links. The two traversal contracts run on their named
platforms; link controls skip when the host cannot create the required symlink.
Windows may require symlink privilege. No native-model qualification is implied.
