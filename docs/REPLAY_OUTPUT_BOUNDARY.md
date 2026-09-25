# Replay report output boundary

Follow-through for #150: validate the requested report directory before either
policy source executes, without changing how policy trees are hashed.

The resolved output cannot equal or descend from either bound process-policy
root or either source's deterministic snapshot root. Both baseline and candidate
are checked. A collision returns CLI input-invalid exit 2 with a path-free
diagnostic and no process invocation, report mutation or snapshot creation.
Existing process-side rejection of a snapshot inside its own policy tree remains
unchanged and covered by the original replay contract test.

Unrelated siblings, including names sharing a string prefix with the policy root,
remain supported. Output aliases and policy-root ancestors are resolved before
comparison. Publication and the reproduction command retain the caller's
original path spelling after validation; existing path-sensitive publication
behavior is unchanged. Recorded-only
comparisons have no process-root restriction. Unsupported policy-directory
symlinks remain unsupported by the existing tree hasher; this guard does not
relax that separate contract.

## Controls

`python -m unittest tests.test_replay_output_boundary -v` covers equal/nested
output, both process roots, pre-existing report preservation, supported alias
forms, reserved snapshot roots/descendants and a real CLI no-launch control.
A sibling-output control runs the structured argv printed by the first report,
proves identical fixed-time manifests, unchanged policy file sets/bytes and no
snapshot residue. A recorded-only positive control prevents over-broad rejection.
Only real symlink controls may skip when host permissions cannot create them.

The existing shared CLI fixture now places its candidate in a separate policies
directory. Its reports remain outside that tree, matching the supported layout;
no existing behavioral assertion or timeout is weakened. The new root test is
included in existing unit discovery and all three existing source-check lists.
Only the CLI and shared fixture hashes change in the existing extraction scope.

This is a resolved-path preflight, not a concurrent-filesystem sandbox, inode or
hard-link isolation, or prevention of writes performed by a policy itself.
It does not restrict all recorded-source directories or change snapshot naming,
process launching, cleanup, policy verdicts, schemas or merge authority.
