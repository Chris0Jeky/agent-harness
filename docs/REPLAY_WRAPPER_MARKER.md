# Replay supervisor marker scope

Bounded follow-through for issue #145's reserved-marker classification case.

Only the Windows supervisor defines `replay-wrapper-exec-failed:` with exit
127 as its executable-start failure signal. POSIX policies emitting the same
stderr prefix and exit code now follow the ordinary nonzero-process contract:
valid decisions remain present, and `process-exit-nonzero` prevents a clean
result. The marker is not interpreted as proof that a POSIX process never ran.

Windows marker handling is unchanged. In particular, this does not authenticate
stderr or remove the existing collision when a Windows policy itself writes the
reserved marker and exits 127. It does not change process creation, Job Objects,
process groups, timeouts, cleanup grace, snapshot identity or report privacy.
Timeout failure still takes precedence. Ordinary diagnostics and other exit
codes retain their existing behavior on both platforms.

`python -m unittest replay_v0.tests.contract.test_wrapper_marker -v` exercises
both platform branches with controlled supervisor returns and real temporary
streams, then launches a real host process with two valid decisions and the
reserved stderr marker. POSIX retains the decisions with nonzero failure;
Windows retains its existing all-indeterminate start-failure classification.
Mocked platform branches are not native Windows execution evidence. The
existing supported-host CI runs the real-host control on each operating system.

The source digest is refreshed in the unchanged 35-file extraction scope.
The new regression module is covered by replay discovery and the existing
three-host source-check lists; no new job, dependency, permission or model gate
is introduced. This completes only the marker case, not every issue #145 edge.
