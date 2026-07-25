"""Issue #54: floor tests must not inherit the host's Git configuration.

`dispatch.check` reads the LIVE process environment, so an ambient
`GIT_EXEC_PATH`, `GIT_TRACE_REDACT=0`, `GIT_INDEX_FILE=...secret` or
`GIT_CONFIG_COUNT` turns an ordinary `git log` from allow into deny. Every
floor suite that calls `check()` therefore has to sanitize first — and each one
used to do it differently, from a hand-mirrored name list down to nothing at
all.

`tests/floor_environment.py` is now the single definition, DERIVED from
dispatch's own constants. These tests pin the three properties that keep it
honest:

1. the isolation set really is derived (a name added to any dispatch constant
   flows through with no edit anywhere), and the vendored smoke suite derives
   the same set from the same constants;
2. the inventory of ambient reads in dispatch.py is complete — a new
   `os.environ` read in a new function fails here until it is classified as
   covered or deliberately out of scope;
3. every tests/ suite that calls the real `check()` routes through the shared
   helper, and each covered family really does flip the verdict without it.
"""

import ast
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"
SMOKE_PATH = ROOT / "templates" / "hooks" / "smoke_test.py"
FLOOR_ENVIRONMENT_PATH = ROOT / "tests" / "floor_environment.py"
TESTS_DIR = ROOT / "tests"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch = load_module("dispatch_floor_environment", DISPATCH_PATH)
floor_environment = load_module("floor_environment_self", FLOOR_ENVIRONMENT_PATH)


def stub_resolver(
    args, project_dir, git_globals=None, command_runner=None, deadline=None
):
    """No network during unit tests; treat every remote as private."""
    return False, "unit-test-stub-private"


# Each entry is an inherited environment that dispatch.check reads directly,
# paired with a command whose verdict it flips. Every one was observed to deny
# without the helper (see test_each_family_really_flips_the_verdict), so these
# are live regression barriers rather than assertions about nothing.
HOSTILE_ENVIRONMENTS = (
    ("process-launch", {"GIT_EXEC_PATH": "helper"}, "git log"),
    ("process-launch", {"GIT_PAGER": "helper", "PAGER": "helper"}, "git log"),
    ("process-launch", {"EDITOR": "helper", "GIT_EDITOR": "helper"}, "git commit"),
    (
        "process-launch",
        {"GIT_SSH_COMMAND": "helper", "GIT_PROXY_COMMAND": "helper"},
        "git fetch origin",
    ),
    ("trace-target", {"GIT_TRACE2_ENV_VARS": "GIT_SSH"}, "git status"),
    ("trace-disclosure", {"GIT_TRACE_REDACT": "0"}, "git status"),
    ("index-file", {"GIT_INDEX_FILE": "/tmp/.env"}, "git status"),
    # GIT_INDEX_FILE is evaluated for every segment of every command, so it
    # poisons non-git commands too.
    ("index-file", {"GIT_INDEX_FILE": "/tmp/.env"}, "echo hi"),
    ("config-injection", {"GIT_CONFIG_COUNT": "1"}, "git status"),
    ("repository", {"GIT_DIR": "/elsewhere/.git"}, "git push"),
)


def hermetic(command: str, tier: int = 1):
    return floor_environment.hermetic_check(
        dispatch,
        command,
        {"tier": tier, "flags": {}},
        str(ROOT),
        remote_resolver=stub_resolver,
    )


def bare(command: str, tier: int = 1):
    """`dispatch.check` with NO isolation — the shape this issue removes."""
    return dispatch.check(
        command,
        {"tier": tier, "flags": {}},
        str(ROOT),
        str(ROOT),
        remote_resolver=stub_resolver,
    )


class DerivedIsolationSetTests(unittest.TestCase):
    """The set must be derived from dispatch, never mirrored."""

    def test_every_named_constant_is_covered(self):
        for constant in (
            "_GIT_PROCESS_COMMAND_ENVIRONMENT",
            "_GIT_PROCESS_ENVIRONMENT",
            "_GIT_REPOSITORY_ENVIRONMENT",
            "_GIT_TRACE_ENVIRONMENT",
            "_GIT_TRACE_TARGET_ENVIRONMENT",
            "_GIT_TRACE_DISCLOSURE_ENVIRONMENT",
        ):
            with self.subTest(constant=constant):
                names = set(getattr(dispatch, constant))
                self.assertTrue(names, f"{constant} is unexpectedly empty")
                self.assertLessEqual(
                    names, floor_environment.isolated_environment_names(dispatch)
                )

    def test_prefix_and_literal_families_are_covered(self):
        for name in (
            "GIT_INDEX_FILE",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_KEY_0",
            "GIT_CONFIG_VALUE_0",
            "GIT_CONFIG_GLOBAL",
            # dispatch's own predicate exempts NOSYSTEM, but it still reaches
            # the real `git config` subprocesses the push guard spawns, so the
            # helper is deliberately a superset there.
            "GIT_CONFIG_NOSYSTEM",
            # Case folding: the runtime may hand back any spelling on Windows.
            "git_exec_path",
        ):
            with self.subTest(name=name):
                self.assertTrue(floor_environment.should_isolate(dispatch, name))

    def test_unrelated_names_are_left_alone(self):
        for name in ("PATH", "HOME", "USERPROFILE", "CLAUDE_PROJECT_DIR", "WT_PROJECT"):
            with self.subTest(name=name):
                self.assertFalse(floor_environment.should_isolate(dispatch, name))

    def test_smoke_suite_derives_the_same_set(self):
        smoke = load_module("smoke_floor_environment", SMOKE_PATH)
        self.assertEqual(
            set(smoke.GIT_HELPER_ENVIRONMENT),
            set(floor_environment.isolated_environment_names(dispatch)),
        )
        for name in ("GIT_CONFIG_COUNT", "GIT_TRACE_REDACT", "GIT_INDEX_FILE"):
            with self.subTest(name=name):
                self.assertTrue(smoke.is_inherited_git_helper(name))
                self.assertNotIn(name, smoke.clean_dispatch_environment())


class AmbientReadInventoryTests(unittest.TestCase):
    """Drift alarm: a NEW ambient read in dispatch must be classified here."""

    # Qualified function path -> why the shared helper does or does not
    # neutralize it. Qualified, not bare: a read added to a nested helper
    # inside the already-listed `check` would otherwise be attributed to
    # `check` and slip through.
    INVENTORY = {
        "dangerous_git_index_file_mutation": "covered: GIT_INDEX_FILE",
        "has_dangerous_git_trace_environment": "covered: _GIT_TRACE_ENVIRONMENT",
        "has_git_config_environment": "covered: GIT_CONFIG* prefix",
        "has_git_process_environment": "covered: _GIT_PROCESS_COMMAND_ENVIRONMENT",
        "check": "covered: _GIT_REPOSITORY_ENVIRONMENT (bare-push overrides)",
        "environment_value": (
            "NOT covered: expands whatever $VAR / %VAR% the command text names, "
            "so the set is chosen by the command under test, not by the host"
        ),
        "main": "NOT covered: CLAUDE_PROJECT_DIR, which check() never reads",
    }

    def ambient_reads(self):
        tree = ast.parse(DISPATCH_PATH.read_text(encoding="utf-8"))
        reads = {}
        stack = []

        def walk(node):
            pushed = False
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stack.append(node.name)
                pushed = True
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr in {"environ", "getenv"}
            ):
                owner = ".".join(stack) if stack else "<module>"
                reads.setdefault(owner, []).append(node.lineno)
            for child in ast.iter_child_nodes(node):
                walk(child)
            if pushed:
                stack.pop()

        walk(tree)
        return reads

    def test_inventory_matches_dispatch(self):
        reads = self.ambient_reads()
        self.assertEqual(
            sorted(reads),
            sorted(self.INVENTORY),
            "dispatch.py grew or lost an ambient os.environ read; classify it in "
            "INVENTORY and, if check() can see it, add it to "
            "tests/floor_environment.py",
        )


class HermeticCheckTests(unittest.TestCase):
    def test_hostile_environments_do_not_change_the_verdict(self):
        for family, environment, command in HOSTILE_ENVIRONMENTS:
            with self.subTest(family=family, command=command):
                with patch.dict(os.environ, environment):
                    self.assertEqual(hermetic(command)[0], "allow")

    def test_each_family_really_flips_the_verdict(self):
        """Without the helper every case above denies — so it is load-bearing."""
        with floor_environment.hermetic_environment(dispatch):
            for family, environment, command in HOSTILE_ENVIRONMENTS:
                with self.subTest(family=family, command=command):
                    with patch.dict(os.environ, environment):
                        self.assertEqual(bare(command)[0], "deny")

    def test_overrides_are_applied_after_the_clearing(self):
        with patch.dict(os.environ, {"GIT_EXEC_PATH": "helper"}):
            with floor_environment.hermetic_environment(
                dispatch, {"GIT_EDITOR": "true"}
            ):
                self.assertNotIn("GIT_EXEC_PATH", os.environ)
                self.assertEqual(os.environ["GIT_EDITOR"], "true")

    # NB: never assertEqual on os.environ itself — a failure would print every
    # value, and developer environments hold credentials.
    def assertRestored(self, before):
        self.assertTrue(
            dict(os.environ) == before,
            "hermetic_environment did not restore the process environment",
        )

    def test_the_environment_is_restored_afterwards(self):
        with patch.dict(os.environ, {"GIT_EXEC_PATH": "sentinel"}):
            # An override name the host may itself export tells us nothing
            # about removal, so start from a known-absent one.
            os.environ.pop("GIT_SEQUENCE_EDITOR", None)
            before = dict(os.environ)
            with floor_environment.hermetic_environment(
                dispatch, {"GIT_SEQUENCE_EDITOR": "true"}
            ):
                self.assertEqual(os.environ["GIT_SEQUENCE_EDITOR"], "true")
            self.assertRestored(before)
            self.assertNotIn("GIT_SEQUENCE_EDITOR", set(os.environ))

    def test_the_environment_is_restored_after_an_exception(self):
        with patch.dict(os.environ, {"GIT_EXEC_PATH": "sentinel"}):
            before = dict(os.environ)
            with self.assertRaises(RuntimeError):
                with floor_environment.hermetic_environment(dispatch):
                    raise RuntimeError("boom")
            self.assertRestored(before)


class SiblingSuiteHermeticityTests(unittest.TestCase):
    """Finding 2: the fix must not be hermetic in one file only."""

    # Suites with a module-level check()/decide() over the real dispatch, and a
    # command each asserts as "allow".
    MODULE_LEVEL_HELPERS = (
        ("test_powershell_block_scan", "check", ("git status",)),
        ("test_push_guard_review_gaps", "check", ("git push origin main",)),
        ("test_git_readonly_plumbing", "decide", ("git merge-base main HEAD", 1)),
        ("test_double_quote_escapes", "decide", ('git commit -m "note"',)),
    )

    def load_suite(self, name: str):
        return load_module(f"hermeticity_{name}", TESTS_DIR / f"{name}.py")

    def test_module_level_helpers_are_hermetic(self):
        hostile = {
            "GIT_EXEC_PATH": "helper",
            "GIT_TRACE_REDACT": "0",
            "GIT_INDEX_FILE": "/tmp/.env",
            "GIT_CONFIG_COUNT": "1",
        }
        for name, helper, args in self.MODULE_LEVEL_HELPERS:
            with self.subTest(module=name, command=args[0]):
                suite = self.load_suite(name)
                decide = getattr(suite, helper)
                with patch.dict(os.environ, hostile):
                    verdict = decide(*args)
                self.assertEqual(
                    verdict[0] if isinstance(verdict, tuple) else verdict, "allow"
                )

    # This module deliberately calls the raw check() to prove the helper is
    # load-bearing (see bare()), so it is the one permitted exception.
    RAW_CHECK_ALLOWED = {"test_floor_environment.py"}

    def test_no_suite_calls_the_raw_check(self):
        """A new suite cannot quietly re-introduce a hand-rolled helper.

        A substring scan is not enough: `hermetic_check(...)` and
        `dispatch.check(...)` differ by one character. Match the call shape
        `<anything>.check(...)` in the AST instead, in any file that loads the
        real dispatch.py.
        """
        offenders = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            if path.name in self.RAW_CHECK_ALLOWED:
                continue
            source = path.read_text(encoding="utf-8")
            if '"dispatch.py"' not in source:
                continue
            for node in ast.walk(ast.parse(source)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "check"
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            "these call the real dispatch.check directly instead of "
            "tests/floor_environment.hermetic_check, so their verdicts depend "
            "on the host's Git configuration",
        )


if __name__ == "__main__":
    unittest.main()
