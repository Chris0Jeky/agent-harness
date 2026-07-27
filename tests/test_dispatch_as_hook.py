"""Issue #90: exercise the dispatcher AS A HOOK, not only in-process.

Every existing floor suite calls `check()` in-process with an injected
`command_runner`, so the whole probe layer — process spawning, PATH resolution,
`gh` quota behaviour — was invisible to the tests. That is exactly where #90
lived: `command_output` collapsed a quota-denied `gh`, a failed spawn and an
empty answer into one indistinguishable "", and the sensitive_data push guard
turned that into a mute "could not verify push remote privacy" wall.

This suite spawns the real `dispatch.py` with a real hook payload on stdin and
fake `git`/`gh` executables shadowing the real ones on PATH, so the assertions
cover the lanes an in-process test cannot reach:

* REST (`gh api`) is asked first and a private answer ALLOWS the push;
* a public answer still DENIES (the wall is not weakened);
* when BOTH transports are quota-denied the deny reason NAMES the cause;
* when REST fails the GraphQL lane still answers, so one exhausted quota no
  longer fail-closes a provably private push.

Hermetic by construction: the shims are the only `git`/`gh` on the child's
PATH, so no network and no real repository is ever touched.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
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

# The stand-in `git`/`gh`. `FAKE_GH_MODE` picks which (stdout, exit, stderr)
# pair the REST and GraphQL visibility probes answer with, so one script covers
# every case without the shims knowing anything about the suite.
FAKE_PROBES = '''\
"""Stand-in `git` / `gh` for tests/test_dispatch_as_hook.py. No network."""

import os
import sys

RATE_LIMIT = "GraphQL: API rate limit already exceeded for user ID 59696583"
UNEXPECTED = "the GraphQL lane must not be consulted after a REST answer"

# mode -> (REST answer, GraphQL answer); an answer is (stdout, exit, stderr).
BEHAVIOUR = {
    "rest-private": (("private", 0, ""), ("", 1, UNEXPECTED)),
    "rest-public": (("public", 0, ""), ("", 1, UNEXPECTED)),
    "both-rate-limited": (("", 1, RATE_LIMIT), ("", 1, RATE_LIMIT)),
    "rest-down": (("", 1, "gh: HTTP 500 from api.github.com"), ("PRIVATE", 0, "")),
}


def answer(stdout="", code=0, stderr=""):
    if stdout:
        sys.stdout.write(stdout + "\\n")
    if stderr:
        sys.stderr.write(stderr + "\\n")
    raise SystemExit(code)


def main():
    tool = sys.argv[1]
    args = sys.argv[2:]
    log = os.environ.get("FAKE_PROBE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join([tool, *args]) + "\\n")
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
        """Fake `git` / `gh` that shadow the real binaries on PATH.

        On Windows they are `.cmd` files, which only run because the probe
        resolver honours PATHEXT and hands subprocess the full extension path —
        so this doubles as the resolver's regression test.
        """
        helper = directory / "fake_probes.py"
        helper.write_text(FAKE_PROBES, encoding="utf-8")
        for tool in ("git", "gh"):
            if os.name == "nt":
                script = directory / f"{tool}.cmd"
                script.write_text(
                    "@echo off\r\n"
                    f'"{sys.executable}" "{helper}" {tool} %*\r\n'
                    "exit /b %ERRORLEVEL%\r\n",
                    encoding="utf-8",
                )
            else:
                script = directory / tool
                script.write_text(
                    "#!/bin/sh\n" f'exec "{sys.executable}" "{helper}" {tool} "$@"\n',
                    encoding="utf-8",
                )
                script.chmod(0o755)

    def hook_environment(self, shims: Path, project: Path, mode: str, log: Path):
        """The child's environment: no inherited Git launch state, shims first.

        `floor_environment.should_isolate` is the shared derivation of which
        ambient names flip a floor verdict; reusing it keeps this suite honest
        when dispatch grows another one.
        """
        environment = {
            name: value
            for name, value in os.environ.items()
            if not floor_environment.should_isolate(dispatch, name)
        }
        environment["PATH"] = str(shims) + os.pathsep + environment.get("PATH", "")
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
        probes = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
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
            any(probe.startswith("gh api repos/acme/widgets") for probe in probes),
            probes,
        )
        # The REST answer is sufficient; the GraphQL lane stays unspent.
        self.assertFalse([probe for probe in probes if probe.startswith("gh repo")])

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

    def __call__(self, argv, cwd):
        command = " ".join(argv)
        self.calls.append(command)
        for needle, output in self.responses.items():
            if needle in command:
                return output
        return self.default

    def matching(self, needle: str) -> list[str]:
        return [call for call in self.calls if needle in call]


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
        runner = RecordingRunner(
            {**self.RESOLUTION, "gh api repos/acme/widgets": "private"}
        )
        self.assertEqual(self.status(runner), (False, "approved private destinations"))
        self.assertEqual(len(runner.matching("gh api repos/acme/widgets")), 1)
        self.assertEqual(runner.matching("gh repo view"), [])

    def test_a_public_rest_answer_is_still_public(self):
        runner = RecordingRunner(
            {**self.RESOLUTION, "gh api repos/acme/widgets": "public"}
        )
        self.assertEqual(self.status(runner), (True, "acme/widgets"))
        self.assertEqual(runner.matching("gh repo view"), [])

    def test_graphql_serves_an_empty_rest_answer(self):
        runner = RecordingRunner({**self.RESOLUTION, "gh repo view": "PRIVATE"})
        self.assertEqual(self.status(runner), (False, "approved private destinations"))
        self.assertEqual(len(runner.matching("gh api repos/acme/widgets")), 1)
        self.assertEqual(len(runner.matching("gh repo view")), 1)

    def test_both_transports_empty_stays_fail_closed(self):
        runner = RecordingRunner(dict(self.RESOLUTION))
        self.assertEqual(self.status(runner), (None, "acme/widgets"))
        self.assertEqual(len(runner.matching("gh repo view")), 1)

    def test_an_injected_runner_is_never_handed_diagnostics(self):
        """The replay/test contract: injected runners take exactly two args."""
        runner = RecordingRunner(
            {**self.RESOLUTION, "gh api repos/acme/widgets": "private"}
        )
        self.assertEqual(self.status(runner), (False, "approved private destinations"))


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
        for slug in (
            "",
            "acme",
            "acme/widgets/extra",
            "acme/wid gets",
            "acme/wid?gets",
        ):
            with self.subTest(slug=slug):
                self.assertEqual(dispatch.github_rest_repo_path(slug), "")


if __name__ == "__main__":
    unittest.main()
