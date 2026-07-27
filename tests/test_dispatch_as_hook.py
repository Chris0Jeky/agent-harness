"""Issue #90: exercise the dispatcher AS A HOOK, not only in-process.

Every existing floor suite calls `check()` in-process with an injected
`command_runner`, so the whole probe layer — process spawning, PATH resolution,
`gh` quota behaviour — was invisible to the tests. That is exactly where #90
lived: `command_output` collapsed a quota-denied `gh`, a failed spawn and an
empty answer into one indistinguishable "", and the sensitive_data push guard
turned that into a mute "could not verify push remote privacy" wall.

This suite spawns the real `dispatch.py` with a real hook payload on stdin and
fake `git`/`gh` executables as the ONLY ones on the child's PATH, so the
assertions cover the lanes an in-process test cannot reach:

* REST (`gh api`) is asked first, pinned to github.com, and a private answer
  ALLOWS the push;
* a public answer still DENIES (the wall is not weakened);
* when BOTH transports are quota-denied the deny reason NAMES the cause;
* when REST fails, or answers a truthy non-verdict like `null`, the GraphQL
  lane still answers — one exhausted quota no longer fail-closes a provably
  private push;
* a credential-bearing stderr never survives into the rendered deny reason.

Hermetic by construction, and proved so rather than assumed: every shim reports
the path it was executed as, and `run_hook` asserts that path is inside the shim
directory on every operating system. The earlier lane only proved this on
Windows (a `.cmd` cannot run any other way), which left ubuntu and macos unable
to tell a shim from the runner's real `git`. What this suite does NOT prove is
which candidate the resolver PREFERS — that is `ProbeBinaryResolutionTests` and
`ShimArgvGateTests`, whose ordering assertions run on every OS.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"
FLOOR_ENVIRONMENT_PATH = ROOT / "tests" / "floor_environment.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch = load_module("dispatch_as_hook", DISPATCH_PATH)
floor_environment = load_module("floor_environment_as_hook", FLOOR_ENVIRONMENT_PATH)

RATE_LIMIT_STDERR = "GraphQL: API rate limit already exceeded for user ID 59696583"
LEAKED_TOKEN = "ghp_AAAABBBBCCCCDDDDEEEEFFFF"

# The stand-in `git`/`gh`. `FAKE_GH_MODE` picks which (stdout, exit, stderr)
# pair the REST and GraphQL visibility probes answer with, so one script covers
# every case without the shims knowing anything about the suite. Each shim
# passes its OWN resolved path as argv[2] so the suite can prove, on every
# operating system, that the image the floor spawned came from the shim
# directory rather than from a real `git`/`gh` further along PATH.
FAKE_PROBES = '''\
"""Stand-in `git` / `gh` for tests/test_dispatch_as_hook.py. No network."""

import os
import sys

RATE_LIMIT = "GraphQL: API rate limit already exceeded for user ID 59696583"
UNEXPECTED = "the GraphQL lane must not be consulted after a REST answer"
# git echoes the whole remote URL, credentials and all, when a probe fails.
CREDENTIAL = (
    "fatal: unable to access "
    "'https://alice:ghp_AAAABBBBCCCCDDDDEEEEFFFF@github.com/acme/widgets.git/'"
)

# mode -> (REST answer, GraphQL answer); an answer is (stdout, exit, stderr).
BEHAVIOUR = {
    "rest-private": (("private", 0, ""), ("", 1, UNEXPECTED)),
    "rest-public": (("public", 0, ""), ("", 1, UNEXPECTED)),
    "both-rate-limited": (("", 1, RATE_LIMIT), ("", 1, RATE_LIMIT)),
    "rest-down": (("", 1, "gh: HTTP 500 from api.github.com"), ("PRIVATE", 0, "")),
    # `--jq .visibility` prints a literal `null` (exit 0) when the field is
    # absent: a truthy non-answer that must still reach the other transport.
    "rest-null": (("null", 0, ""), ("PRIVATE", 0, "")),
    "credential-in-stderr": (("", 128, CREDENTIAL), ("", 128, CREDENTIAL)),
}


def answer(stdout="", code=0, stderr=""):
    if stdout:
        sys.stdout.write(stdout + "\\n")
    if stderr:
        sys.stderr.write(stderr + "\\n")
    raise SystemExit(code)


def main():
    tool = sys.argv[1]
    origin = sys.argv[2]
    args = sys.argv[3:]
    log = os.environ.get("FAKE_PROBE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(origin + "\\t" + " ".join([tool, *args]) + "\\n")
    if tool == "git":
        if args[:1] == ["config"] and args[-1:] == ["push.recurseSubmodules"]:
            answer("no")
        if args[:2] == ["remote", "get-url"]:
            answer("https://github.com/acme/widgets.git")
        answer(code=1, stderr="fake git: unsupported probe")
    if tool == "gh":
        rest, graphql = BEHAVIOUR[os.environ["FAKE_GH_MODE"]]
        if args[:1] == ["api"]:
            answer(*rest)
        if args[:2] == ["repo", "view"]:
            answer(*graphql)
    answer(code=1, stderr="fake probe: unsupported command")


main()
'''


class DispatchAsHookTests(unittest.TestCase):
    """The real dispatcher, spawned the way a runtime spawns it."""

    def write_shims(self, directory: Path) -> None:
        """Fake `git` / `gh`, the only ones on the child's PATH.

        On Windows they are `.cmd` files, so this lane also exercises the
        resolver's PATHEXT route and the shim-argv gate that route requires —
        though what the resolver PREFERS is proven by
        `ProbeBinaryResolutionTests`, not here. Each shim passes its own
        resolved path (`%~f0` / `$0`) so `run_hook` can prove which image ran.
        """
        helper = directory / "fake_probes.py"
        helper.write_text(FAKE_PROBES, encoding="utf-8")
        for tool in ("git", "gh"):
            if os.name == "nt":
                script = directory / f"{tool}.cmd"
                script.write_text(
                    "@echo off\r\n"
                    f'"{sys.executable}" "{helper}" {tool} "%~f0" %*\r\n'
                    "exit /b %ERRORLEVEL%\r\n",
                    encoding="utf-8",
                )
            else:
                script = directory / tool
                script.write_text(
                    "#!/bin/sh\n"
                    f'exec "{sys.executable}" "{helper}" {tool} "$0" "$@"\n',
                    encoding="utf-8",
                )
                script.chmod(0o755)

    def hook_environment(self, shims: Path, project: Path, mode: str, log: Path):
        """The child's environment: no inherited Git launch state, shims only.

        PATH is REPLACED rather than prepended. The resolver prefers a real
        `.EXE` anywhere on PATH over a script shim anywhere on PATH (a `.cmd`
        re-parses argv under `cmd.exe`), so a merely-prepended shim directory
        would lose to the machine's real `git.exe` and the suite would stop
        being hermetic. Everything the shims need is addressed absolutely.

        `floor_environment.should_isolate` is the shared derivation of which
        ambient names flip a floor verdict; reusing it keeps this suite honest
        when dispatch grows another one.
        """
        environment = {
            name: value
            for name, value in os.environ.items()
            if not floor_environment.should_isolate(dispatch, name)
        }
        environment["PATH"] = str(shims)
        environment["CLAUDE_PROJECT_DIR"] = str(project)
        environment["FAKE_GH_MODE"] = mode
        environment["FAKE_PROBE_LOG"] = str(log)
        return environment

    def run_hook(self, command: str, mode: str):
        workspace = Path(tempfile.mkdtemp(prefix="floor-as-hook-"))
        self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
        project = workspace / "project"
        (project / ".agent-harness").mkdir(parents=True)
        (project / ".agent-harness" / "tier.json").write_text(
            json.dumps({"tier": 3, "flags": {"sensitive_data": True}}),
            encoding="utf-8",
        )
        shims = workspace / "bin"
        shims.mkdir()
        self.write_shims(shims)
        log = workspace / "probes.log"
        payload = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(project),
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(DISPATCH_PATH),
                "--event",
                "pre",
                "--runtime",
                "claude",
            ],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project),
            env=self.hook_environment(shims, project, mode, log),
        )
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        probes = []
        for line in lines:
            origin, _tab, spelling = line.partition("\t")
            # OS-independent hermeticity proof. A Windows-only assertion (only a
            # `.cmd` could have run) left the ubuntu and macos jobs unable to
            # tell a shim from the runner's real `git`, because CPython resolves
            # argv[0] from the passed env's PATH there. Every shim reports the
            # path it was executed as instead.
            self.assertEqual(
                os.path.normcase(os.path.dirname(origin)),
                os.path.normcase(str(shims)),
                f"probe ran from outside the shim directory: {origin}",
            )
            probes.append(spelling)
        return completed, probes

    def assertAllowed(self, completed) -> None:
        """An allow is exit 0 with NO stdout — the runtime reads silence."""
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "", completed.stdout)

    def denyReason(self, completed) -> str:
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.strip(), "expected a decision on stdout")
        hook = json.loads(completed.stdout)["hookSpecificOutput"]
        self.assertEqual(hook["permissionDecision"], "deny", completed.stdout)
        return hook["permissionDecisionReason"]

    def test_rest_private_answer_allows_the_push(self):
        completed, probes = self.run_hook("git push origin main", "rest-private")
        self.assertAllowed(completed)
        self.assertTrue(
            any(
                probe.startswith("gh api")
                and "--hostname github.com" in probe
                and "repos/acme/widgets" in probe
                for probe in probes
            ),
            probes,
        )
        # The REST answer is sufficient; the GraphQL lane stays unspent.
        self.assertFalse([probe for probe in probes if probe.startswith("gh repo")])

    def test_a_null_rest_answer_falls_through_to_graphql(self):
        """`null` is truthy after `.upper()`; only a VERDICT ends the search."""
        completed, probes = self.run_hook("git push origin main", "rest-null")
        self.assertAllowed(completed)
        self.assertTrue(any(probe.startswith("gh api") for probe in probes), probes)
        self.assertTrue(any(probe.startswith("gh repo view") for probe in probes))

    def test_a_credential_bearing_stderr_never_reaches_the_reason(self):
        """The deny reason is rendered and stored; git echoes tokens on failure."""
        completed, _probes = self.run_hook(
            "git push origin main", "credential-in-stderr"
        )
        reason = self.denyReason(completed)
        self.assertIn("could not verify push remote privacy", reason)
        self.assertNotIn(LEAKED_TOKEN, reason)
        self.assertNotIn("ghp_", reason)
        self.assertNotIn("alice", reason)

    def test_rest_public_answer_still_denies(self):
        completed, _probes = self.run_hook("git push origin main", "rest-public")
        self.assertIn("refusing a push to public remote", self.denyReason(completed))

    def test_a_rate_limited_probe_denies_and_names_the_cause(self):
        """The #90 regression: a fail-closed wall must not be mute."""
        completed, probes = self.run_hook("git push origin main", "both-rate-limited")
        reason = self.denyReason(completed)
        self.assertIn("could not verify push remote privacy", reason)
        self.assertIn("rate limit", reason)
        # Both transports were genuinely tried before fail-closing.
        self.assertTrue(any(probe.startswith("gh api") for probe in probes), probes)
        self.assertTrue(any(probe.startswith("gh repo view") for probe in probes))

    def test_graphql_answers_when_rest_is_down(self):
        """Lane redundancy: one exhausted transport is no longer a wall."""
        completed, probes = self.run_hook("git push origin main", "rest-down")
        self.assertAllowed(completed)
        self.assertTrue(any(probe.startswith("gh repo view") for probe in probes))


class ProbeBinaryResolutionTests(unittest.TestCase):
    """`resolve_probe_binary` searches PATH and nothing else."""

    def setUp(self) -> None:
        dispatch._PROBE_BINARY_CACHE.clear()
        self.addCleanup(dispatch._PROBE_BINARY_CACHE.clear)
        self.directory = Path(tempfile.mkdtemp(prefix="floor-probe-bin-"))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)

    def write_executable(self, directory: Path, name: str) -> Path:
        path = directory / (f"{name}.cmd" if os.name == "nt" else name)
        path.write_text("@echo off\r\n" if os.name == "nt" else "#!/bin/sh\n")
        if os.name != "nt":
            path.chmod(0o755)
        return path

    def test_a_binary_on_path_resolves_to_its_full_path(self):
        """Windows resolves through PATHEXT, whose own casing comes back."""
        expected = self.write_executable(self.directory, "floor-probe-tool")
        with patch.dict(os.environ, {"PATH": str(self.directory)}, clear=False):
            resolved = dispatch.resolve_probe_binary("floor-probe-tool")
        self.assertIsNotNone(resolved)
        self.assertEqual(os.path.normcase(resolved), os.path.normcase(str(expected)))

    def test_a_binary_only_in_the_cwd_is_not_resolved(self):
        """CreateProcess searches the cwd; a planted `gh` must not win."""
        self.write_executable(self.directory, "floor-probe-planted")
        empty = Path(tempfile.mkdtemp(prefix="floor-probe-empty-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        with patch.dict(os.environ, {"PATH": str(empty)}, clear=False):
            saved = os.getcwd()
            os.chdir(self.directory)
            try:
                self.assertIsNone(
                    dispatch.resolve_probe_binary("floor-probe-planted"),
                )
            finally:
                os.chdir(saved)

    def test_an_explicit_path_is_used_verbatim(self):
        target = self.write_executable(self.directory, "floor-probe-explicit")
        self.assertEqual(dispatch.resolve_probe_binary(str(target)), str(target))
        self.assertIsNone(
            dispatch.resolve_probe_binary(str(self.directory / "absent-probe"))
        )

    def test_a_missing_binary_resolves_to_none(self):
        with patch.dict(os.environ, {"PATH": str(self.directory)}, clear=False):
            self.assertIsNone(dispatch.resolve_probe_binary("floor-probe-absent"))

    def test_a_relative_path_entry_is_never_searched(self):
        """`PATH=.` (and the empty entry Windows reads as ".") is the cwd."""
        with patch.dict(
            os.environ,
            {"PATH": os.pathsep.join(["", ".", "relative/bin", str(self.directory)])},
            clear=False,
        ):
            self.assertEqual(dispatch.probe_path_directories(), [str(self.directory)])

    def test_every_image_is_tried_before_any_script_shim(self):
        """The ordering rule, asserted without a Windows filesystem.

        A `.CMD` runs under `cmd.exe`, which re-parses the command line, so a
        directory early on PATH must not be able to promote a shim over a real
        image sitting further along it.
        """
        order = dispatch.probe_binary_search_order(
            "gh",
            [os.path.join("A", "bin"), os.path.join("B", "bin")],
            [".COM", ".EXE", ".BAT", ".CMD"],
        )
        images = [
            index
            for index, path in enumerate(order)
            if path.lower().endswith((".exe", ".com"))
        ]
        shims = [
            index
            for index, path in enumerate(order)
            if path.lower().endswith((".bat", ".cmd"))
        ]
        self.assertTrue(images and shims)
        self.assertLess(max(images), min(shims))
        # PATH order still decides inside a pass.
        self.assertLess(
            order.index(os.path.join("A", "bin", "gh.EXE")),
            order.index(os.path.join("B", "bin", "gh.EXE")),
        )

    def test_a_name_that_carries_its_own_extension_stays_in_its_own_pass(self):
        order = dispatch.probe_binary_search_order(
            "gh.cmd", [os.path.join("A", "bin")], [".EXE", ".CMD"]
        )
        self.assertEqual(order[0], os.path.join("A", "bin", "gh.cmd.EXE"))
        self.assertIn(os.path.join("A", "bin", "gh.cmd"), order[1:])

    def test_a_posix_search_is_plain_path_order(self):
        self.assertEqual(
            dispatch.probe_binary_search_order("gh", ["/a/bin", "/b/bin"], []),
            [os.path.join("/a/bin", "gh"), os.path.join("/b/bin", "gh")],
        )

    @unittest.skipUnless(os.name == "nt", "PATHEXT resolution is Windows-only")
    def test_a_planted_cmd_never_beats_a_real_exe(self):
        """The CRITICAL lane: a `.cmd` alongside a `.exe` must not be chosen."""
        (self.directory / "floor-probe-pair.cmd").write_text("@echo off\r\n")
        real = self.directory / "floor-probe-pair.exe"
        real.write_text("MZ")
        with patch.dict(os.environ, {"PATH": str(self.directory)}, clear=False):
            self.assertEqual(
                os.path.normcase(dispatch.resolve_probe_binary("floor-probe-pair")),
                os.path.normcase(str(real)),
            )

    @unittest.skipUnless(os.name == "nt", "PATHEXT resolution is Windows-only")
    def test_an_exe_later_on_path_still_beats_an_earlier_cmd(self):
        later = Path(tempfile.mkdtemp(prefix="floor-probe-later-"))
        self.addCleanup(shutil.rmtree, later, ignore_errors=True)
        (self.directory / "floor-probe-split.cmd").write_text("@echo off\r\n")
        real = later / "floor-probe-split.exe"
        real.write_text("MZ")
        path = os.pathsep.join([str(self.directory), str(later)])
        with patch.dict(os.environ, {"PATH": path}, clear=False):
            self.assertEqual(
                os.path.normcase(dispatch.resolve_probe_binary("floor-probe-split")),
                os.path.normcase(str(real)),
            )


class ShimArgvGateTests(unittest.TestCase):
    """A script shim may only be spawned with argv `cmd.exe` cannot re-read."""

    def setUp(self) -> None:
        dispatch._PROBE_BINARY_CACHE.clear()
        self.addCleanup(dispatch._PROBE_BINARY_CACHE.clear)

    def test_the_probes_the_floor_actually_asks_are_accepted(self):
        for argv in (
            [r"C:\tools\gh.cmd", "api", "--hostname", "github.com"],
            [r"C:\tools\gh.cmd", "repos/acme/widgets", "--jq", ".visibility"],
            ["/usr/bin/git", "remote", "get-url", "--push", "--all", "origin"],
            ["/usr/bin/git", "config", "--get", "--default", "no", "push.recurse"],
            [r"C:\Program Files\GitHub CLI\gh.cmd", "api"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(dispatch.probe_argv_shim_hazard(argv), "")

    def test_an_ordinary_windows_install_path_is_not_a_hazard(self):
        """argv[0] is the machine's layout, not the repository's text.

        An allowlist on argv[0] refused every one of these, and on such a box
        every visibility probe is refused and every sensitive_data push denies:
        issue #90's wall, made permanent by the fix for it.
        """
        for image in (
            r"C:\Program Files (x86)\GitHub CLI\gh.cmd",
            "C:\\Users\\Jekyt\u00e9\\bin\\gh.cmd",
            "C:\\Users\\\u5f20\u4f1f\\scoop\\shims\\gh.cmd",
            r"C:\tools[stable]\gh.cmd",
            r"C:\Users\dev'name\bin\gh.cmd",
            r"C:\opt\{shims}\gh.cmd",
            r"C:\opt\a+b\gh.cmd",
            r"C:\opt\a#b$c\gh.cmd",
        ):
            with self.subTest(image=image):
                self.assertEqual(
                    dispatch.probe_argv_shim_hazard([image, "api", "repos/acme/w"]), ""
                )

    def test_a_delimiter_is_a_hazard_only_while_argv0_is_unquoted(self):
        """Measured against a real `.cmd` spawn, not reasoned about.

        cmd.exe splits an UNQUOTED command name on `,`, `;`, `=` and `(`, so
        `C:\\dev\\a,b\\gh.cmd` runs `C:\\dev\\a` and the probe answers about
        nothing. subprocess quotes argv[0] only when it holds whitespace, which
        is exactly why `Program Files (x86)` works and `tools(x86)` does not.
        """
        for image in (
            r"C:\dev\a,b\gh.cmd",
            r"C:\dev\a;b\gh.cmd",
            r"C:\dev\a=b\gh.cmd",
            r"C:\tools(x86)\gh.cmd",
        ):
            with self.subTest(image=image):
                self.assertEqual(
                    dispatch.probe_argv_shim_hazard([image, "api"]),
                    "its resolved path holds an unquoted cmd.exe delimiter",
                )
        for image in (
            r"C:\dev\a, b\gh.cmd",
            r"C:\Program Files (x86)\gh.cmd",
        ):
            with self.subTest(image=image):
                self.assertTrue(dispatch.probe_image_is_quoted(image))
                self.assertEqual(dispatch.probe_argv_shim_hazard([image, "api"]), "")

    def test_every_cmd_metacharacter_is_refused(self):
        for token in (
            "repos/a&mkdir,PWNED",
            "a|b",
            "a>b",
            "a<b",
            "a^b",
            'a"b',
            "%COMSPEC%",
            "a!b",
            "a(b)",
            "a b",
            "a\nb",
            "a;b",
            "a,b",
        ):
            with self.subTest(token=token):
                self.assertEqual(
                    dispatch.probe_argv_shim_hazard(["gh.cmd", "api", token]),
                    "unsafe arguments",
                )

    def test_an_image_path_metacharacter_is_refused_with_its_own_cause(self):
        """The denylist on argv[0]: only what reaches `cmd.exe` unquoted."""
        for image in (
            r"C:\a&b\gh.cmd",
            r"C:\a|b\gh.cmd",
            r"C:\a<b\gh.cmd",
            r"C:\a>b\gh.cmd",
            r"C:\a^b\gh.cmd",
            'C:\\a"b\\gh.cmd',
            r"C:\%TEMP%\gh.cmd",
            r"C:\a!b\gh.cmd",
            "C:\\a\rb\\gh.cmd",
            "C:\\a\nb\\gh.cmd",
        ):
            with self.subTest(image=image):
                self.assertEqual(
                    dispatch.probe_argv_shim_hazard([image, "api"]),
                    "its resolved path holds a cmd.exe metacharacter",
                )
        self.assertEqual(dispatch.probe_argv_shim_hazard([]), "empty command")

    @unittest.skipUnless(os.name == "nt", "only Windows re-parses a shim's argv")
    def test_a_shim_extension_is_classified_as_re_parsing(self):
        self.assertTrue(dispatch.probe_image_reparses(r"C:\tools\gh.cmd"))
        self.assertTrue(dispatch.probe_image_reparses(r"C:\tools\gh.bat"))
        self.assertFalse(dispatch.probe_image_reparses(r"C:\tools\gh.exe"))
        self.assertFalse(dispatch.probe_image_reparses(r"C:\tools\gh.COM"))

    @unittest.skipUnless(os.name == "nt", "only Windows re-parses a shim's argv")
    def test_a_shim_only_path_executes_nothing_for_a_hostile_argument(self):
        """The CRITICAL reproduction: injected text must not reach `cmd.exe`."""
        workspace = Path(tempfile.mkdtemp(prefix="floor-probe-shim-"))
        self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
        shims = workspace / "bin"
        work = workspace / "work"
        shims.mkdir()
        work.mkdir()
        (shims / "gh.cmd").write_text("@echo off\r\necho PRIVATE\r\n")
        notes: list[str] = []
        with patch.dict(os.environ, {"PATH": str(shims)}, clear=False):
            output = dispatch.command_output(
                ["gh", "api", "repos/a&mkdir,PWNED"], str(work), diagnostics=notes
            )
        self.assertEqual(output, "")
        self.assertFalse((work / "PWNED").exists(), "the injected command was executed")
        self.assertEqual(len(notes), 1)
        self.assertIn("only a script shim on PATH", notes[0])

    @unittest.skipUnless(os.name == "nt", "only Windows re-parses a shim's argv")
    def test_a_shim_only_path_still_answers_a_clean_probe(self):
        """Issue #90's whole point: a box whose `gh` IS a `.cmd` keeps working."""
        shims = Path(tempfile.mkdtemp(prefix="floor-probe-clean-"))
        self.addCleanup(shutil.rmtree, shims, ignore_errors=True)
        (shims / "gh.cmd").write_text("@echo off\r\necho private\r\n")
        notes: list[str] = []
        with patch.dict(os.environ, {"PATH": str(shims)}, clear=False):
            output = dispatch.command_output(
                ["gh", "api", "repos/acme/widgets", "--jq", ".visibility"],
                str(shims),
                diagnostics=notes,
            )
        self.assertEqual(output, "private")
        self.assertEqual(notes, [])

    def probe_from_directory(self, name: str):
        """Plant a working `gh.cmd` in `name` and probe with PATH set to it."""
        root = Path(tempfile.mkdtemp(prefix="floor-probe-image-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        shims = root / name
        shims.mkdir(parents=True)
        (shims / "gh.cmd").write_text("@echo off\r\necho PRIVATE\r\n")
        dispatch._PROBE_BINARY_CACHE.clear()
        notes: list[str] = []
        with patch.dict(os.environ, {"PATH": str(shims)}, clear=False):
            output = dispatch.command_output(
                ["gh", "api", "repos/acme/widgets", "--jq", ".visibility"],
                str(root),
                diagnostics=notes,
            )
        return output, notes

    @unittest.skipUnless(os.name == "nt", "only Windows re-parses a shim's argv")
    def test_an_ordinary_windows_install_directory_still_probes(self):
        """The paths a real Windows box hands the resolver, end to end.

        These are not exotic: `Program Files (x86)` is where an MSI puts `gh`,
        and the shim directory the suite itself uses lives under the user's
        profile — so an accented or CJK user name breaks the tests too.
        """
        for name in (
            "Program Files (x86)",
            "Jekyt\u00e9",
            "\u5f20\u4f1f",
            "tools[stable]",
            "plus+dir",
            "brace{x}",
        ):
            with self.subTest(name=name):
                output, notes = self.probe_from_directory(name)
                self.assertEqual(output, "PRIVATE", notes)
                self.assertEqual(notes, [])

    @unittest.skipUnless(os.name == "nt", "only Windows re-parses a shim's argv")
    def test_a_metacharacter_in_the_image_path_names_argv0_as_the_cause(self):
        """The diagnostic must not blame arguments that were clean."""
        for name in ("a&b", "pct%dir", "with,comma", "paren(x86)"):
            with self.subTest(name=name):
                output, notes = self.probe_from_directory(name)
                self.assertEqual(output, "")
                self.assertEqual(len(notes), 1)
                self.assertIn("only a script shim on PATH", notes[0])
                self.assertIn("its resolved path holds", notes[0])
                self.assertNotIn("unsafe arguments", notes[0])

    @unittest.skipUnless(os.name == "nt", "only Windows re-parses a shim's argv")
    def test_a_refused_image_path_never_executes_a_neighbouring_program(self):
        """`C:\\dev\\a,b\\gh.cmd` unquoted would have cmd.exe run `C:\\dev\\a`."""
        root = Path(tempfile.mkdtemp(prefix="floor-probe-split-name-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        shims = root / "a,b"
        shims.mkdir()
        (shims / "gh.cmd").write_text("@echo off\r\necho PRIVATE\r\n")
        # The image the unquoted split would resolve to instead.
        (root / "a.cmd").write_text("@echo off\r\ntype nul > \"%~dp0SPLIT\"\r\n")
        dispatch._PROBE_BINARY_CACHE.clear()
        notes: list[str] = []
        with patch.dict(os.environ, {"PATH": str(shims)}, clear=False):
            output = dispatch.command_output(
                ["gh", "api", "repos/acme/widgets"], str(root), diagnostics=notes
            )
        self.assertEqual(output, "")
        self.assertFalse((root / "SPLIT").exists(), "the split command ran")
        self.assertIn("unquoted cmd.exe delimiter", notes[0])


class ProbeDiagnosticsTests(unittest.TestCase):
    """Every `command_output` failure mode names itself."""

    def setUp(self) -> None:
        dispatch._PROBE_BINARY_CACHE.clear()
        self.addCleanup(dispatch._PROBE_BINARY_CACHE.clear)

    def test_a_missing_binary_is_named(self):
        notes: list[str] = []
        self.assertEqual(
            dispatch.command_output(
                ["floor-probe-absent-binary"], "", diagnostics=notes
            ),
            "",
        )
        self.assertEqual(len(notes), 1)
        self.assertIn("not found on PATH", notes[0])

    def test_a_nonzero_exit_carries_its_stderr(self):
        notes: list[str] = []
        output = dispatch.command_output(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('quota exhausted\\n'); sys.exit(3)",
            ],
            "",
            diagnostics=notes,
        )
        self.assertEqual(output, "")
        self.assertIn("exit 3", notes[0])
        self.assertIn("quota exhausted", notes[0])

    def test_a_spawn_failure_is_named_not_silent(self):
        """The `fork: Resource temporarily unavailable` class of failure."""
        directory = Path(tempfile.mkdtemp(prefix="floor-probe-spawn-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        not_a_program = directory / "not-a-program.json"
        not_a_program.write_text("{}\n", encoding="utf-8")
        notes: list[str] = []
        self.assertEqual(
            dispatch.command_output([str(not_a_program)], "", diagnostics=notes), ""
        )
        self.assertEqual(len(notes), 1)
        self.assertIn("spawn failed", notes[0])

    def test_an_empty_success_is_named(self):
        notes: list[str] = []
        self.assertEqual(
            dispatch.command_output([sys.executable, "-c", ""], "", diagnostics=notes),
            "",
        )
        self.assertIn("exit 0 with empty output", notes[0])

    def test_a_successful_probe_notes_nothing(self):
        notes: list[str] = []
        self.assertEqual(
            dispatch.command_output(
                [sys.executable, "-c", "print('private')"], "", diagnostics=notes
            ),
            "private",
        )
        self.assertEqual(notes, [])

    def test_diagnostics_are_optional(self):
        """Without a list the behaviour is byte-for-byte the old contract."""
        self.assertEqual(dispatch.command_output(["floor-probe-absent-binary"], ""), "")

    def test_the_detail_suffix_is_capped(self):
        detail = dispatch.detail_with_diagnostics("acme/widgets", ["x" * 500])
        self.assertLessEqual(len(detail), 300)
        self.assertTrue(detail.startswith("acme/widgets"))
        self.assertEqual(
            dispatch.detail_with_diagnostics("acme/widgets", []), "acme/widgets"
        )

    def test_a_credential_bearing_stderr_is_redacted_before_it_is_recorded(self):
        """A diagnostic is an EMISSION: it lands in the deny reason verbatim."""
        leak = f"fatal: unable to access 'https://alice:{LEAKED_TOKEN}@github.com/o/r'"
        notes: list[str] = []
        output = dispatch.command_output(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write(sys.argv[1] + chr(10)); sys.exit(128)",
                leak,
            ],
            "",
            diagnostics=notes,
        )
        self.assertEqual(output, "")
        self.assertNotIn(LEAKED_TOKEN, notes[0])
        self.assertNotIn("alice", notes[0])
        self.assertIn("exit 128", notes[0])

    def test_every_known_secret_shape_is_masked(self):
        for stderr in (
            f"remote: https://alice:{LEAKED_TOKEN}@github.com/o/r",
            f"error: No such remote 'git+ssh://alice:{LEAKED_TOKEN}@example.com/a/b'",
            f"gh: bad credentials for {LEAKED_TOKEN}",
            "gh: token github_pat_11ABCDEFG0aBcDeFgHiJkLmNoPqRsTuVwXyZ rejected",
            "x-oauth-token: 0123456789abcdef0123456789abcdef01234567",
        ):
            with self.subTest(stderr=stderr):
                head = dispatch.probe_stderr_head(stderr)
                self.assertNotIn(LEAKED_TOKEN, head)
                self.assertNotIn("github_pat_11", head)
                self.assertNotIn("0123456789abcdef", head)
                self.assertNotIn("alice:", head)

    def test_a_recognisable_cause_is_named_ahead_of_the_tail(self):
        for stderr, cause in (
            (
                "GraphQL: API rate limit already exceeded for user ID 59696583",
                "rate limit",
            ),
            ("gh: Bad credentials (HTTP 401)", "authentication"),
            ("gh: Not Found (HTTP 404)", "not found"),
            ("dial tcp: could not resolve host: api.github.com", "network"),
        ):
            with self.subTest(stderr=stderr):
                self.assertTrue(dispatch.probe_stderr_head(stderr).startswith(cause))

    def test_a_cause_survives_the_shape_blind_redaction(self):
        """Classification reads the RAW line; redaction ran first and ate it.

        `[A-Za-z0-9+/_]{24,}` matched the whole snake_cased error code, so
        `rate_limit_exceeded_for_installation` became `***` before anything
        looked for the words "rate limit" — the wall went mute again, which is
        the failure this branch exists to remove.
        """
        head = dispatch.probe_stderr_head(
            "error: rate_limit_exceeded_for_installation"
        )
        self.assertTrue(head.startswith("rate limit"), head)

    def test_an_ordinary_path_survives_readable(self):
        """A `/` no longer glues path segments into one redactable run."""
        head = dispatch.probe_stderr_head(
            "fatal: not a git repository: "
            "/home/runner/work/agent_harness_checkout/subproject/.git"
        )
        self.assertIn("/home/runner/work/agent_harness_checkout/subproject/.git", head)
        self.assertNotIn("***", head)

    def test_a_credential_bearing_url_is_still_masked(self):
        """The redaction that matters did not move: only its ORDER did."""
        head = dispatch.probe_stderr_head(
            f"fatal: unable to access 'https://alice:{LEAKED_TOKEN}"
            "@github.com/acme/widgets.git/'"
        )
        self.assertNotIn(LEAKED_TOKEN, head)
        self.assertNotIn("ghp_", head)
        self.assertNotIn("alice", head)
        self.assertIn("***", head)

    def test_a_rate_limited_403_is_not_classified_as_an_auth_failure(self):
        head = dispatch.probe_stderr_head(
            "HTTP 403: API rate limit exceeded for user ID 1 (https://api.github.com)"
        )
        self.assertTrue(head.startswith("rate limit"))

    def test_a_head_is_still_capped(self):
        self.assertLessEqual(
            len(dispatch.probe_stderr_head("rate limit " + "x" * 500)), 160
        )
        self.assertEqual(dispatch.probe_stderr_head(""), "no stderr")
        self.assertEqual(dispatch.probe_stderr_head(None), "no stderr")

    def test_only_the_last_three_notes_are_reported(self):
        detail = dispatch.detail_with_diagnostics(
            "acme/widgets", ["first", "second", "third", "fourth"]
        )
        self.assertNotIn("first", detail)
        for note in ("second", "third", "fourth"):
            self.assertIn(note, detail)


class RecordingRunner:
    """A two-argument `command_runner`, the injection contract every probe uses."""

    def __init__(self, responses: dict, default: str = ""):
        self.responses = responses
        self.default = default
        self.calls: list[str] = []
        self.observer = None

    def __call__(self, argv, cwd):
        command = " ".join(argv)
        self.calls.append(command)
        if self.observer is not None:
            # A probe costs wall-clock time; a budget test needs to see it.
            self.observer()
        for needle, output in self.responses.items():
            if needle in command:
                return output
        return self.default

    def matching(self, needle: str) -> list[str]:
        return [call for call in self.calls if needle in call]


class SyntheticClock:
    """A stand-in for `dispatch.time` — only `monotonic`, advanced per probe.

    `dispatch` reads nothing else from `time`, so replacing the module attribute
    keeps the budget arithmetic deterministic without touching the real clock.
    """

    def __init__(self, cost: float, start: float = 1000.0):
        self.now = start
        self.cost = cost

    def monotonic(self) -> float:
        return self.now

    def spend(self) -> None:
        self.now += self.cost


class RestFirstVisibilityTests(unittest.TestCase):
    """REST is the primary transport; GraphQL is the fallback."""

    RESOLUTION = {
        "git config": "no",
        "git remote get-url": "https://github.com/acme/widgets.git",
    }

    def status(self, runner: RecordingRunner):
        return dispatch.public_remote_status(
            ["origin", "main"], "/project", None, runner
        )

    def test_rest_is_asked_before_graphql(self):
        runner = RecordingRunner({**self.RESOLUTION, "gh api": "private"})
        self.assertEqual(self.status(runner), (False, "approved private destinations"))
        self.assertEqual(len(runner.matching("gh api")), 1)
        self.assertEqual(runner.matching("gh repo view"), [])

    def test_the_rest_lane_pins_the_host(self):
        """`gh api` otherwise resolves against GH_HOST; the destination is not."""
        runner = RecordingRunner({**self.RESOLUTION, "gh api": "private"})
        self.status(runner)
        self.assertEqual(
            runner.matching("gh api"),
            ["gh api --hostname github.com repos/acme/widgets --jq .visibility"],
        )

    def test_the_graphql_lane_pins_the_host_too(self):
        """The fallback answers whenever REST is mute, so it is the SAME hazard.

        `gh repo view OWNER/REPO` resolves against GH_HOST, which the probe
        environment does not clear. Pointed at a GitHub Enterprise instance an
        unpinned fallback can report PRIVATE about a different repository that
        shares the slug, and the floor then ALLOWS a sensitive_data push to a
        public github.com remote — fail-open, the class this branch repaired.
        """
        runner = RecordingRunner({**self.RESOLUTION, "gh repo view": "PRIVATE"})
        self.assertEqual(self.status(runner), (False, "approved private destinations"))
        self.assertEqual(
            runner.matching("gh repo view"),
            [
                "gh repo view github.com/acme/widgets "
                "--json visibility --jq .visibility"
            ],
        )

    def test_a_public_rest_answer_is_still_public(self):
        runner = RecordingRunner({**self.RESOLUTION, "gh api": "public"})
        self.assertEqual(self.status(runner), (True, "acme/widgets"))
        self.assertEqual(runner.matching("gh repo view"), [])

    def test_graphql_serves_an_empty_rest_answer(self):
        runner = RecordingRunner({**self.RESOLUTION, "gh repo view": "PRIVATE"})
        self.assertEqual(self.status(runner), (False, "approved private destinations"))
        self.assertEqual(len(runner.matching("gh api")), 1)
        self.assertEqual(len(runner.matching("gh repo view")), 1)

    def test_a_null_rest_answer_still_reaches_graphql(self):
        """`null` is a non-answer `gh` prints at exit 0 — and it is truthy."""
        runner = RecordingRunner(
            {
                **self.RESOLUTION,
                "gh api": "null",
                "gh repo view": "PRIVATE",
            }
        )
        self.assertEqual(self.status(runner), (False, "approved private destinations"))
        self.assertEqual(len(runner.matching("gh repo view")), 1)

    def test_a_null_rest_answer_that_stays_unverified_names_itself(self):
        runner = RecordingRunner({**self.RESOLUTION, "gh api": "null"})
        verdict, detail = self.status(runner)
        self.assertIsNone(verdict)
        self.assertIn("unrecognized visibility", detail)
        self.assertIn("NULL", detail)

    def test_an_unrecognised_rest_answer_never_stands_in_for_a_verdict(self):
        """A non-verdict must not be treated as private by omission."""
        runner = RecordingRunner({**self.RESOLUTION, "gh api": "not-a-visibility"})
        self.assertIsNone(self.status(runner)[0])
        self.assertEqual(len(runner.matching("gh repo view")), 1)

    def test_both_transports_empty_stays_fail_closed(self):
        runner = RecordingRunner(dict(self.RESOLUTION))
        self.assertEqual(self.status(runner), (None, "acme/widgets"))
        self.assertEqual(len(runner.matching("gh repo view")), 1)

    def test_an_injected_runner_is_never_handed_diagnostics(self):
        """The replay/test contract: injected runners take exactly two args."""
        runner = RecordingRunner({**self.RESOLUTION, "gh api": "private"})
        self.assertEqual(self.status(runner), (False, "approved private destinations"))


THREE_PRIVATE_PUSHURLS = "\n".join(
    f"https://github.com/acme/{name}.git" for name in ("one", "two", "three")
)


class MuteTransportBudgetTests(unittest.TestCase):
    """A mute transport is asked ONCE per call, not once per remote.

    Both transports draw on one 3.5s budget. Asking a dead lane again for every
    pushurl spends the budget that would have bought the answer, so a fan-out of
    private remotes went from a verified `False` to an unverified `None` — a NEW
    denial, manufactured in exactly the exhausted-transport scenario issue #90
    is about. Measured with a mute REST lane, 3 pushurls and 0.5s per probe:
    main `False` (5 probes), preferring REST `None` (7), remembering the mute
    lane `False` (6). The one remaining probe is irreducible — REST has to be
    asked once before anything can know it is mute.
    """

    RESOLUTION = {
        "git config": "no",
        "git remote get-url": THREE_PRIVATE_PUSHURLS,
    }

    def status(self, runner, deadline=None):
        return dispatch.public_remote_status(
            ["origin", "main"], "/project", None, runner, deadline
        )

    def test_a_mute_rest_lane_is_asked_once_for_three_remotes(self):
        runner = RecordingRunner({**self.RESOLUTION, "gh repo view": "PRIVATE"})
        self.assertEqual(self.status(runner), (False, "approved private destinations"))
        self.assertEqual(len(runner.matching("gh api")), 1)
        self.assertEqual(len(runner.matching("gh repo view")), 3)

    def test_a_mute_rest_lane_no_longer_flips_the_verdict_under_budget(self):
        """The measured regression, on a synthetic clock: main said `False`."""
        runner = RecordingRunner({**self.RESOLUTION, "gh repo view": "PRIVATE"})
        clock = SyntheticClock(cost=0.5)
        runner.observer = clock.spend
        with patch.object(dispatch, "time", clock):
            verdict = self.status(
                runner, clock.monotonic() + dispatch._REMOTE_RESOLUTION_BUDGET_SECONDS
            )
        self.assertEqual(verdict, (False, "approved private destinations"))
        self.assertEqual(len(runner.calls), 6)

    def test_both_lanes_mute_still_fail_closes(self):
        """Skipping a dead lane must never invent a verdict it did not get."""
        runner = RecordingRunner(dict(self.RESOLUTION))
        self.assertIsNone(self.status(runner)[0])

    def test_a_rest_answer_never_spends_the_graphql_lane(self):
        runner = RecordingRunner({**self.RESOLUTION, "gh api": "private"})
        self.assertEqual(self.status(runner), (False, "approved private destinations"))
        self.assertEqual(len(runner.matching("gh api")), 3)
        self.assertEqual(runner.matching("gh repo view"), [])


class RestPathMappingTests(unittest.TestCase):
    """`slug -> repos/<owner>/<repo>`; anything else asks no REST question."""

    def test_a_bare_pair_passes_through(self):
        self.assertEqual(dispatch.github_rest_repo_path("acme/widgets"), "acme/widgets")

    def test_a_host_pinned_slug_loses_the_host(self):
        for slug in (
            "github.com/acme/widgets",
            "GitHub.com/acme/widgets",
            "https://github.com/acme/widgets",
            "/acme/widgets/",
        ):
            with self.subTest(slug=slug):
                self.assertEqual(dispatch.github_rest_repo_path(slug), "acme/widgets")

    def test_the_slug_a_real_remote_produces_maps_cleanly(self):
        for remote in (
            "https://github.com/acme/widgets.git",
            "git@github.com:acme/widgets.git",
            "ssh://git@github.com/acme/widgets",
        ):
            with self.subTest(remote=remote):
                self.assertEqual(
                    dispatch.github_rest_repo_path(dispatch.github_repo_slug(remote)),
                    "acme/widgets",
                )

    def test_anything_that_is_not_a_pair_is_refused(self):
        """The result is interpolated into argv, so this is an ALLOWLIST.

        `../x` would become `repos/../x` — a traversal of the REST route — and
        `a&b/c` would put a `cmd.exe` separator on a command line.
        """
        for slug in (
            "",
            "acme",
            "acme/widgets/extra",
            "acme/wid gets",
            "acme/wid?gets",
            "../x",
            "..",
            "./x",
            "a&b/c",
            "a/b&mkdir,PWNED",
            "a|b/c",
            "a/b;c",
            "a/../b",
            "acme/wid\ngets",
            "%TEMP%/x",
        ):
            with self.subTest(slug=slug):
                self.assertEqual(dispatch.github_rest_repo_path(slug), "")


class OfflineReplayContractTests(unittest.TestCase):
    """`scripts/replay_corpus.py` rebinds the module global; nothing may key on it.

    `make_module_offline` sets `module.command_output = stub_command_runner` and
    rewrites every `command_runner` default to the same two-argument stub. An
    identity test against the GLOBAL therefore answered True for that stub and
    handed it a `diagnostics=` keyword it never declares — a TypeError, which
    `check()` contracts to DENY. The floor's own declared measurement instrument
    could not run against the floor.
    """

    def setUp(self) -> None:
        def stub_command_runner(argv, cwd, timeout=3):
            return ""

        self.stub = stub_command_runner
        self.original = dispatch.command_output
        self.patched = []
        for name in dir(dispatch):
            function = getattr(dispatch, name, None)
            if not isinstance(function, types.FunctionType):
                continue
            defaults = function.__defaults__
            if not defaults:
                continue
            code = function.__code__
            names = code.co_varnames[: code.co_argcount]
            first = code.co_argcount - len(defaults)
            replaced = list(defaults)
            changed = False
            for offset, value in enumerate(defaults):
                if names[first + offset] == "command_runner" and value is self.original:
                    replaced[offset] = stub_command_runner
                    changed = True
            if changed:
                self.patched.append((function, defaults))
                function.__defaults__ = tuple(replaced)
        dispatch.command_output = stub_command_runner
        self.addCleanup(self.restore)
        self.assertTrue(self.patched, "no command_runner default was rebindable")

    def restore(self) -> None:
        dispatch.command_output = self.original
        for function, defaults in self.patched:
            function.__defaults__ = defaults

    def test_public_remote_status_runs_against_the_rebound_stub(self):
        self.assertEqual(
            dispatch.public_remote_status(
                ["--no-recurse-submodules", "origin", "main"], "/project"
            ),
            (None, "unresolved push remote"),
        )

    def test_configured_bare_push_is_dangerous_runs_against_the_rebound_stub(self):
        self.assertFalse(dispatch.configured_bare_push_is_dangerous("/project"))

    def test_check_runs_against_the_rebound_stub(self):
        """`check()` reaches `public_remote_status` through its own default."""
        decision, reason = floor_environment.hermetic_check(
            dispatch,
            "git push origin main",
            {"tier": 3, "flags": {"sensitive_data": True}},
            str(ROOT),
        )
        self.assertEqual(decision, "deny")
        self.assertIn("could not verify push remote privacy", reason)


if __name__ == "__main__":
    unittest.main()
