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

`tests/test_floor_environment.py` fails if dispatch grows an ambient read
outside that inventory, or if a tests/ suite calls `check()` without this
helper.
"""

import contextlib
import os

# Ambient names dispatch reads that are not members of a named constant.
_EXTRA_ISOLATED_NAMES = frozenset({"GIT_INDEX_FILE"})

# Prefix families: dispatch matches these by shape, not by membership.
_ISOLATED_PREFIXES = ("GIT_CONFIG",)


def isolated_environment_names(dispatch) -> frozenset:
    """The exact-match half of the isolation set, derived from `dispatch`."""
    return frozenset(
        set(dispatch._GIT_PROCESS_COMMAND_ENVIRONMENT)
        | set(dispatch._GIT_REPOSITORY_ENVIRONMENT)
        | set(dispatch._GIT_TRACE_ENVIRONMENT)
        | set(_EXTRA_ISOLATED_NAMES)
    )


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
