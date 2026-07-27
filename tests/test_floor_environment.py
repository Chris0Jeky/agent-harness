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
   `os.environ`, `os.path.expanduser` or `tempfile.gettempdir` read in a new
   function fails here until it is classified as covered or deliberately out of
   scope. "Complete" is scoped to `AmbientReadInventoryTests.AMBIENT_READS`: an
   ambient read spelled some other way is still invisible, so widen that set
   rather than trusting the claim;
3. every tests/ suite that calls the real `check()` routes through the shared
   helper, and each covered family really does flip the verdict without it.
"""

import ast
import atexit
import importlib.util
import os
import shutil
import subprocess
import tempfile
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


# A directory with no repository-local Git config, used as project_dir instead
# of ROOT. Once the helper clears GIT_DIR, a refspec-less `git push` falls
# through to `configured_bare_push_is_dangerous`, which really does run
# `git config --get-regexp ^remote\..*\.(push|mirror|receivepack)$`. The helper
# neutralizes that subprocess's user and system config; the repository-local
# layer is the caller's cwd, so a contributor with `remote.origin.push = +...`
# in their own agent-harness checkout would otherwise watch this suite deny for
# reasons that have nothing to do with environment isolation. Earlier revisions
# of this file stubbed the resolver out instead, which only RELOCATED the host
# dependency into a mock. The resolver's own force/delete/mirror/receivepack
# behaviour is exercised against real fixture repositories in
# tests/test_push_config_force.py, which is where it belongs.
CONFIG_FREE_DIR = tempfile.mkdtemp(prefix="floor-env-project-")
atexit.register(shutil.rmtree, CONFIG_FREE_DIR, ignore_errors=True)


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


def hermetic(command: str, tier: int = 1, project_dir: str = CONFIG_FREE_DIR):
    return floor_environment.hermetic_check(
        dispatch,
        command,
        {"tier": tier, "flags": {}},
        project_dir,
        remote_resolver=stub_resolver,
    )


def bare(command: str, tier: int = 1, project_dir: str = CONFIG_FREE_DIR):
    """`dispatch.check` with NO isolation — the shape this issue removes."""
    return dispatch.check(
        command,
        {"tier": tier, "flags": {}},
        project_dir,
        project_dir,
        remote_resolver=stub_resolver,
    )


class DerivedIsolationSetTests(unittest.TestCase):
    """The set must be derived from dispatch, never mirrored."""

    def test_every_family_constant_is_classified(self):
        """A NEW `_GIT_*_ENVIRONMENT` family must be classified, not ignored.

        The per-name derivation below only proves the families we already know
        about flow through. Reflecting over dispatch closes the level above it:
        a family added tomorrow fails here until someone decides, in writing,
        whether the helper has to clear it.
        """
        self.assertEqual(
            sorted(floor_environment.environment_family_constants(dispatch)),
            sorted(
                set(floor_environment._ISOLATED_CONSTANTS)
                | set(floor_environment._UNISOLATED_CONSTANTS)
            ),
            "dispatch.py grew or lost a _GIT_*_ENVIRONMENT family; add it to "
            "_ISOLATED_CONSTANTS in tests/floor_environment.py if check() reads "
            "it off os.environ, or to _UNISOLATED_CONSTANTS with the reason",
        )
        self.assertEqual(
            set(floor_environment._ISOLATED_CONSTANTS)
            & set(floor_environment._UNISOLATED_CONSTANTS),
            set(),
        )

    def test_every_family_constant_is_a_name_set(self):
        """A family with an unexpected shape must fail, not disappear.

        `environment_family_constants` used to filter on `isinstance(..., (set,
        frozenset))`, so a family added as a tuple, list or dict would drop out
        of the classification comparison above and be silently unisolated —
        the alarm would stay green precisely when it had something to say.
        Type is asserted here instead of being used to select.
        """
        for constant in sorted(
            floor_environment.environment_family_constants(dispatch)
        ):
            with self.subTest(constant=constant):
                self.assertIsInstance(
                    getattr(dispatch, constant),
                    (set, frozenset),
                    f"{constant} is not a name set; the helper derives its "
                    "isolation set by unioning these, so a different shape "
                    "needs a deliberate decision here",
                )

    def test_every_named_constant_is_covered(self):
        for constant in sorted(
            floor_environment.environment_family_constants(dispatch)
            - {
                # The two command-text-only families intentionally carry names
                # (HOME, USERPROFILE, ...) the helper must NOT clear.
                "_GIT_REPOSITORY_CONTEXT_ENVIRONMENT",
                "_GIT_REPOSITORY_COMMAND_ENVIRONMENT",
            }
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
        # The names MUST be exported first. Asserting absence from a clean
        # host's environment is vacuous: it holds however broken the sanitizer
        # is, so it would certify a coverage that does not exist.
        names = ("GIT_CONFIG_COUNT", "GIT_TRACE_REDACT", "GIT_INDEX_FILE")
        with patch.dict(os.environ, {name: "sentinel" for name in names}):
            for name in names:
                with self.subTest(name=name):
                    self.assertIn(name, os.environ)
                    self.assertTrue(smoke.is_inherited_git_helper(name))
                    self.assertNotIn(name, smoke.clean_dispatch_environment())
            # ...and it must remove ONLY those, or the smoke run would lose the
            # PATH / SystemRoot it needs to launch a subprocess at all.
            cleaned = smoke.clean_dispatch_environment()
            self.assertEqual(
                sorted(set(os.environ) - set(cleaned)),
                sorted(
                    name for name in os.environ if smoke.is_inherited_git_helper(name)
                ),
            )


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
        "resolve_probe_binary": (
            "NOT covered: reads PATH / PATHEXT to resolve `git` and `gh` for the "
            "remote-privacy probes. Clearing PATH would leave the probes unable "
            "to run at all, which is the failure this resolution exists to name; "
            "a test that cares pins its own PATH (tests/test_dispatch_as_hook.py "
            "is the worked example)"
        ),
        "command_output": (
            "NOT covered: passes the host environment through to a read-only "
            "probe subprocess, with the non-interactive overrides in "
            "_PROBE_ENVIRONMENT layered on top. The Git launch variables the "
            "helper clears are cleared in the parent, so the child inherits the "
            "cleared set; `neutral_git_command_runner` covers the config sources"
        ),
        "environment_value": (
            "NOT covered: expands whatever $VAR / %VAR% the command text names, "
            "so the set is chosen by the command under test, not by the host"
        ),
        "main": "NOT covered: CLAUDE_PROJECT_DIR, which check() never reads",
        # HOME / TMPDIR family. These DO reach check() and DO flip
        # path-containment verdicts, but the helper deliberately leaves them
        # alone: clearing HOME would break `~` resolution for the test process
        # itself, and pinning TMPDIR would silently redefine the floor's temp
        # allowance for every suite. A test whose verdict depends on either one
        # must pin its own paths — templates/hooks/smoke_test.py's
        # `isolated_dispatch_temp` is the worked example.
        "canonical_path": (
            "NOT covered: expanduser/expandvars on a path the CALLER supplies; "
            "pin the path, not the environment"
        ),
        "is_within_path_lexical": "NOT covered: same, on caller-supplied paths",
        "is_safe_containment_root": (
            "NOT covered: compares the candidate root against ~; a test that "
            "cares must not point project_dir at the home directory"
        ),
        "is_within_temp": (
            "NOT covered: reads TMPDIR/TEMP/TMP via tempfile.gettempdir() and ~ "
            "via expanduser, so the temp allowance follows the host; a suite "
            "asserting containment must pin its own paths"
        ),
        "expand_environment_references": (
            "NOT covered: expanduser on text the command under test supplies"
        ),
        "check_delete_targets": (
            "NOT covered: compares a resolved delete target against ~; the "
            "target comes from the command, not the host"
        ),
    }

    # Not only `os.environ`: `tempfile.gettempdir()` reads TMPDIR/TEMP/TMP and
    # `os.path.expanduser` reads HOME/USERPROFILE, and both feed
    # `is_within_temp`, which decides the floor's temp allowance and therefore
    # flips path-containment verdicts. A scanner that watched only os.environ
    # would have let a host dependency in through either one while this file
    # claimed the inventory was complete.
    AMBIENT_READS = frozenset(
        {
            "os.environ",
            "os.getenv",
            "os.path.expanduser",
            "os.path.expandvars",
            "os.getlogin",
            "tempfile.gettempdir",
            "tempfile.gettempdirb",
            "pathlib.Path.home",
            "Path.home",
        }
    )

    @staticmethod
    def dotted_name(node):
        """`os.path.expanduser` for the Attribute chain, or None."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        parts.append(node.id)
        return ".".join(reversed(parts))

    def ambient_reads(self):
        tree = ast.parse(DISPATCH_PATH.read_text(encoding="utf-8"))
        reads = {}
        stack = []

        def walk(node):
            pushed = False
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stack.append(node.name)
                pushed = True
            if isinstance(node, ast.Attribute) and (
                self.dotted_name(node) in self.AMBIENT_READS
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
            "dispatch.py grew or lost an ambient read (see AMBIENT_READS); "
            "classify it in INVENTORY and, if check() can see it and the "
            "helper can safely clear it, add it to tests/floor_environment.py",
        )


class BarePushSubprocessIsolationTests(unittest.TestCase):
    """The one code path that shells out must read no host configuration.

    Clearing `GIT_CONFIG*` is worse than doing nothing for this subprocess: a
    host that isolates Git the supported way (`GIT_CONFIG_GLOBAL=<empty>`)
    has its protection REMOVED by the clearing, re-enabling `$HOME/.gitconfig`.
    The helper therefore neutralizes the subprocess's config sources instead of
    unsetting the selectors that name them.
    """

    def hostile_home(self) -> dict:
        """A home directory whose `.gitconfig` would deny a bare push."""
        home = tempfile.mkdtemp(prefix="floor-env-home-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        Path(home, ".gitconfig").write_text(
            '[remote "origin"]\n\treceivepack = evil-helper\n', encoding="utf-8"
        )
        return {
            "HOME": home,
            "USERPROFILE": home,
            "HOMEDRIVE": "",
            "HOMEPATH": "",
            "XDG_CONFIG_HOME": os.path.join(home, "xdg"),
        }

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_the_resolver_really_reads_a_hostile_home(self):
        """The fixture is load-bearing: unneutralized, this config denies."""
        with patch.dict(os.environ, self.hostile_home()):
            for name in list(os.environ):
                if name.upper().startswith("GIT_CONFIG"):
                    del os.environ[name]
            self.assertTrue(
                dispatch.configured_bare_push_is_dangerous(CONFIG_FREE_DIR),
                "the fixture ~/.gitconfig is not reaching git, so the "
                "isolation assertion below would pass vacuously",
            )

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_a_hostile_home_does_not_reach_the_helper_verdict(self):
        with patch.dict(os.environ, self.hostile_home()):
            self.assertEqual(hermetic("git push")[0], "allow")

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_a_host_that_isolates_git_is_not_de_isolated(self):
        """Codex P2: unsetting GIT_CONFIG_GLOBAL re-enables ~/.gitconfig."""
        environment = self.hostile_home()
        environment["GIT_CONFIG_GLOBAL"] = floor_environment.empty_git_config_path()
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        with patch.dict(os.environ, environment):
            # What the host itself sees, with its own isolation intact.
            self.assertFalse(
                dispatch.configured_bare_push_is_dangerous(CONFIG_FREE_DIR)
            )
            # ...and what the suite sees, after the helper removes those names.
            self.assertEqual(hermetic("git push")[0], "allow")

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_repository_local_config_still_decides(self):
        """Neutralizing the host must not blind the resolver to a real repo."""
        repo = tempfile.mkdtemp(prefix="floor-env-repo-")
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        for args in (
            ("init", "-q"),
            ("config", "remote.origin.receivepack", "helper --unsafe"),
        ):
            subprocess.run(
                ["git", *args], cwd=repo, check=True, capture_output=True, text=True
            )
        decision, reason = hermetic("git push", project_dir=repo)
        self.assertEqual(decision, "deny", reason)
        self.assertIn("push-config-force", reason)


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

    # tests/floor_environment.py IS the wrapper, and this module deliberately
    # calls the raw check() to prove the wrapper is load-bearing (see bare()).
    # Those two are the only permitted exceptions.
    RAW_CHECK_ALLOWED = {"floor_environment.py", "test_floor_environment.py"}

    @staticmethod
    def raw_check_calls(tree):
        """Line numbers of every `check(...)` / `<x>.check(...)` call.

        Structural, and deliberately not gated on how the file happens to spell
        its dispatch import. An earlier revision only scanned files containing
        the literal token `"dispatch.py"`, so a suite written with
        `ROOT / 'templates' / 'hooks' / 'dispatch.py'`, with
        `importlib.import_module`, or against an already-loaded dispatch module
        would have re-introduced the host dependency while this test stayed
        green. Scanning every module under tests/ removes the spelling from the
        guard entirely; the direction of the error is a false positive on some
        unrelated `.check()` method, which is loud and easy to allowlist.
        """
        # A module that defines its own `check` (several wrap hermetic_check
        # under that name, at module level or nested inside a test) owns the
        # bare name, so only the attribute form is an offender there.
        defines_check = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "check"
            for node in ast.walk(tree)
        )
        lines = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "check":
                lines.append(node.lineno)
            elif (
                isinstance(func, ast.Name) and func.id == "check" and not defines_check
            ):
                lines.append(node.lineno)
        return lines

    def test_no_suite_calls_the_raw_check(self):
        """A new suite cannot quietly re-introduce a hand-rolled helper."""
        offenders = []
        for path in sorted(TESTS_DIR.glob("*.py")):
            if path.name in self.RAW_CHECK_ALLOWED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders.extend(
                f"{path.name}:{line}" for line in self.raw_check_calls(tree)
            )
        self.assertEqual(
            offenders,
            [],
            "these call the real dispatch.check directly instead of "
            "tests/floor_environment.hermetic_check, so their verdicts depend "
            "on the host's Git configuration",
        )

    def test_the_guard_sees_every_spelling_of_the_raw_call(self):
        """The guard itself needs a test: it is what stops the regression.

        Each of these is a way a future suite could reach the real check()
        while the retired substring gate ('"dispatch.py"' in source) stayed
        silent.
        """
        for source in (
            "d = load(ROOT / 'templates' / 'hooks' / 'dispatch.py')\nd.check('git log')",
            "import dispatch\ndispatch.check('git log')",
            "from dispatch import check\ncheck('git log')",
            "floor = sys.modules['dispatch']\nfloor.check('git log')",
            "self.dispatch.check('git log')",
        ):
            with self.subTest(source=source.splitlines()[-1]):
                self.assertTrue(self.raw_check_calls(ast.parse(source)), source)
        # ...and the wrapper call must NOT be flagged, or every suite fails.
        self.assertEqual(
            self.raw_check_calls(
                ast.parse("floor_environment.hermetic_check(dispatch, 'git log')")
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
