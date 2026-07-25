"""One hermetic environment helper for every floor test that calls `check()`.

`dispatch.check` consults the LIVE process environment, so a developer's (or a
CI runner's) ambient Git configuration silently changes the verdict a parser
test asserts. Each floor test suite used to hand-roll its own sanitization —
one cleared `GIT_CONFIG*` plus a hand-mirrored helper list, two cleared only
`GIT_CONFIG*`, and two cleared nothing at all — so the same hazard had five
different answers and drifted every time dispatch grew a name.

The isolation set is DERIVED from dispatch's own constants, never mirrored:
adding a name to `_GIT_PROCESS_COMMAND_ENVIRONMENT` (or any other family below)
is picked up here with no edit. The ambient reads it covers, each of which can
flip a plain `git` command from allow to deny:

* `has_git_process_environment`          -> `_GIT_PROCESS_COMMAND_ENVIRONMENT`
* `check` (bare-push repo overrides)     -> `_GIT_REPOSITORY_ENVIRONMENT`
* `has_dangerous_git_trace_environment`  -> `_GIT_TRACE_ENVIRONMENT`
* `dangerous_git_index_file_mutation`    -> `GIT_INDEX_FILE`
* `has_git_config_environment`           -> any `GIT_CONFIG*` name

Deliberately NOT covered, so the claim stays exactly as strong as the code:

* `environment_value` expands whatever `$VAR` / `%VAR%` the command text names.
  That set is unbounded and chosen by the command under test, not by the host,
  so it is the test author's business, not this helper's.
* `main`'s `CLAUDE_PROJECT_DIR`. `check` never reads it.
* Everything a real `git` subprocess reads (`configured_bare_push_is_dangerous`
  shells out). `GIT_CONFIG*` clearing here is a deliberate superset of
  dispatch's `is_git_config_environment_name`, which exempts
  `GIT_CONFIG_NOSYSTEM`, because that name does reach those subprocesses.
  A suite that reaches that subprocess must stub it — see `StubPushConfig`.
* The HOME / TMPDIR family: `tempfile.gettempdir()` and `os.path.expanduser`
  in `is_within_temp`, `is_safe_containment_root`, `canonical_path`. These DO
  flip path-containment verdicts, but clearing HOME would break `~` for the
  test process and pinning TMPDIR would redefine the floor's temp allowance for
  every suite at once. A test whose verdict depends on either must pin its own
  paths (`smoke_test.isolated_dispatch_temp` is the worked example). They are
  in the drift alarm's scanner and inventory, classified out of scope — not
  invisible to it.

`tests/test_floor_environment.py` fails if dispatch grows an ambient read
outside that inventory, if it grows a `_GIT_*_ENVIRONMENT` family constant that
is not classified below, or if a tests/ suite calls `check()` without this
helper.
"""

import contextlib
import os
import re

# Ambient names dispatch reads that are not members of a named constant.
_EXTRA_ISOLATED_NAMES = frozenset({"GIT_INDEX_FILE"})

# Prefix families: dispatch matches these by shape, not by membership.
_ISOLATED_PREFIXES = ("GIT_CONFIG",)

# Every `_GIT_*_ENVIRONMENT` constant dispatch defines must appear in exactly
# one of the two tables below, and `test_every_family_constant_is_classified`
# fails until a NEW one does. Reflecting the names is the drift guard;
# auto-UNIONING them would not be safe, because two of these families are
# matched against assignments in the COMMAND TEXT rather than against the host
# environment and contain names (HOME, USERPROFILE, XDG_CONFIG_HOME) that the
# test process must keep — `dispatch.is_within_temp` and
# `is_safe_containment_root` resolve `~` and would change containment verdicts
# without them.
_ISOLATED_CONSTANTS = (
    "_GIT_PROCESS_COMMAND_ENVIRONMENT",
    "_GIT_REPOSITORY_ENVIRONMENT",
    "_GIT_TRACE_ENVIRONMENT",
)
_UNISOLATED_CONSTANTS = {
    "_GIT_PROCESS_ENVIRONMENT": (
        "subset of _GIT_PROCESS_COMMAND_ENVIRONMENT, already isolated"
    ),
    "_GIT_TRACE_TARGET_ENVIRONMENT": "subset of _GIT_TRACE_ENVIRONMENT",
    "_GIT_TRACE_DISCLOSURE_ENVIRONMENT": "subset of _GIT_TRACE_ENVIRONMENT",
    "_GIT_REPOSITORY_CONTEXT_ENVIRONMENT": (
        "never read off os.environ — check() intersects it with assignments "
        "parsed out of the command text only. It holds HOME / HOMEDRIVE / "
        "HOMEPATH / USERPROFILE / XDG_CONFIG_HOME, which the test process "
        "needs for `~` resolution, so clearing them would corrupt every "
        "path-containment verdict"
    ),
    "_GIT_REPOSITORY_COMMAND_ENVIRONMENT": (
        "union of _GIT_REPOSITORY_ENVIRONMENT and the context family above; "
        "same command-text-only reason"
    ),
}
_FAMILY_CONSTANT = re.compile(r"^_GIT_[A-Z0-9_]*_ENVIRONMENT$")


def environment_family_constants(dispatch) -> frozenset:
    """Every `_GIT_*_ENVIRONMENT` name-set constant dispatch defines."""
    return frozenset(
        name
        for name in dir(dispatch)
        if _FAMILY_CONSTANT.match(name)
        and isinstance(getattr(dispatch, name), (set, frozenset))
    )


def isolated_environment_names(dispatch) -> frozenset:
    """The exact-match half of the isolation set, derived from `dispatch`."""
    names = set(_EXTRA_ISOLATED_NAMES)
    for constant in _ISOLATED_CONSTANTS:
        names |= set(getattr(dispatch, constant))
    return frozenset(names)


def should_isolate(dispatch, name: str) -> bool:
    """Whether `name` can change a `dispatch.check` verdict from the host."""
    upper = name.upper()
    return upper in isolated_environment_names(dispatch) or any(
        upper.startswith(prefix) for prefix in _ISOLATED_PREFIXES
    )


@contextlib.contextmanager
def hermetic_environment(dispatch, overrides=None):
    """Run the body with every host-inherited Git launch variable removed.

    `overrides` are applied AFTER the clearing, so a test that needs one
    specific inherited variable observed (rather than every variable the host
    happens to export) gets exactly that variable and nothing else.
    """
    names = {name for name in os.environ if should_isolate(dispatch, name)}
    names |= set(overrides or {})
    saved = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)
    os.environ.update(overrides or {})
    try:
        yield
    finally:
        for name in names:
            os.environ.pop(name, None)
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


def hermetic_check(
    dispatch,
    command: str,
    tier_cfg: dict,
    project_dir: str,
    command_cwd: str | None = None,
    *,
    overrides=None,
    **kwargs,
):
    """`dispatch.check` with the host's Git launch configuration removed."""
    with hermetic_environment(dispatch, overrides):
        return dispatch.check(
            command,
            tier_cfg,
            project_dir,
            project_dir if command_cwd is None else command_cwd,
            **kwargs,
        )
