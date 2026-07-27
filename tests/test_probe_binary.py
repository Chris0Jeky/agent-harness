"""Probe binaries resolve against PATH only — never the cwd (issue #112).

`audit` and `doctor` spawn `git`/`gh` with the working directory set to the
repository under inspection, and Windows' `CreateProcess` searches the calling
process's current directory before PATH. Every test here uses an INJECTED
environment or a temporary directory; none of them changes the host's PATH
beyond a scoped `mock.patch.dict`, and none installs anything outside a
`TemporaryDirectory`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import harness

WINDOWS_PATHEXT = [".COM", ".EXE", ".BAT", ".CMD"]


def plant(directory: Path, name: str) -> Path:
    """Write a file that the resolver would accept as a runnable candidate."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text("planted\n", encoding="utf-8")
    target.chmod(0o755)
    return target


class ProbeBinaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        harness.reset_probe_binary_cache()
        self.addCleanup(harness.reset_probe_binary_cache)
        self.addCleanup(self.temp.cleanup)

    def assertSamePath(self, actual: str | None, expected: Path) -> None:
        """Compare resolutions case-insensitively on Windows.

        A resolved path carries the suffix as PATHEXT spells it (`gh.EXE`),
        not as the file was created; on a case-insensitive filesystem that is
        the same file.
        """
        self.assertIsNotNone(actual)
        left = os.path.normcase(str(actual))
        self.assertEqual(left, os.path.normcase(str(expected)))

    def env(
        self, *directories: str | Path, pathext: str | None = None
    ) -> dict[str, str]:
        """An injected environment holding exactly the directories given."""
        environment = {"PATH": os.pathsep.join(str(entry) for entry in directories)}
        if pathext is not None:
            environment["PATHEXT"] = pathext
        return environment

    # --- the cwd is never searched ------------------------------------------

    def test_a_binary_planted_beside_the_repo_is_not_on_the_search_path(self) -> None:
        repo = self.root / "repo"
        for name in ("gh", "gh.exe", "gh.cmd", "gh.bat"):
            plant(repo, name)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        env = self.env(elsewhere, pathext=os.pathsep.join(WINDOWS_PATHEXT))
        self.assertIsNone(harness.resolve_probe_binary("gh", env))
        spawn_argv, failure = harness.probe_spawn_argv(["gh", "--version"], env)
        self.assertEqual(spawn_argv, [])
        self.assertIn("no executable of that name on PATH", failure)
        self.assertIn("gh", failure)

    def test_relative_path_entries_are_skipped(self) -> None:
        repo = self.root / "repo"
        plant(repo, "gh.exe")
        # Every spelling by which the cwd reaches PATH: the empty entry Windows
        # reads as ".", "." itself, and a bare relative directory name.
        env = self.env("", ".", "repo", "..", pathext=os.pathsep.join(WINDOWS_PATHEXT))
        self.assertEqual(harness.probe_search_directories(env), [])
        self.assertIsNone(harness.resolve_probe_binary("gh", env))

    def test_absolute_entries_survive_the_relative_filter(self) -> None:
        tools = self.root / "tools"
        tools.mkdir()
        env = self.env(".", tools, "also-relative")
        self.assertEqual(harness.probe_search_directories(env), [str(tools)])

    # --- images outrank script shims ----------------------------------------

    def test_every_image_is_tried_before_any_shim(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        order = harness.probe_candidate_paths(
            "gh", [str(first), str(second)], WINDOWS_PATHEXT
        )
        self.assertEqual(
            order,
            [
                os.path.join(str(first), "gh.COM"),
                os.path.join(str(first), "gh.EXE"),
                os.path.join(str(second), "gh.COM"),
                os.path.join(str(second), "gh.EXE"),
                os.path.join(str(first), "gh.BAT"),
                os.path.join(str(first), "gh.CMD"),
                os.path.join(str(second), "gh.BAT"),
                os.path.join(str(second), "gh.CMD"),
            ],
        )

    def test_a_named_shim_suffix_stays_in_the_shim_pass(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        order = harness.probe_candidate_paths(
            "gh.cmd", [str(first), str(second)], WINDOWS_PATHEXT
        )
        verbatim = os.path.join(str(first), "gh.cmd")
        self.assertIn(verbatim, order)
        # Spelling the shim out does not let it jump the image pass.
        self.assertGreater(
            order.index(verbatim), order.index(os.path.join(str(second), "gh.cmd.EXE"))
        )

    def test_a_named_image_suffix_is_tried_verbatim_first(self) -> None:
        first = self.root / "first"
        order = harness.probe_candidate_paths("gh.exe", [str(first)], WINDOWS_PATHEXT)
        self.assertEqual(order[0], os.path.join(str(first), "gh.exe"))

    @unittest.skipUnless(os.name == "nt", "PATHEXT resolution is Windows-only")
    def test_a_real_image_later_on_path_beats_an_earlier_shim(self) -> None:
        shim_dir = self.root / "shim"
        image_dir = self.root / "image"
        plant(shim_dir, "gh.cmd")
        image = plant(image_dir, "gh.exe")
        env = self.env(shim_dir, image_dir, pathext=os.pathsep.join(WINDOWS_PATHEXT))
        self.assertSamePath(harness.resolve_probe_binary("gh", env), image)

    @unittest.skipUnless(os.name == "nt", "PATHEXT resolution is Windows-only")
    def test_a_shim_still_answers_when_it_is_the_only_candidate(self) -> None:
        shim_dir = self.root / "shim"
        shim = plant(shim_dir, "gh.cmd")
        env = self.env(shim_dir, pathext=os.pathsep.join(WINDOWS_PATHEXT))
        self.assertSamePath(harness.resolve_probe_binary("gh", env), shim)

    @unittest.skipUnless(os.name == "nt", "PATHEXT resolution is Windows-only")
    def test_an_empty_pathext_falls_back_to_the_windows_default(self) -> None:
        self.assertEqual(
            harness.probe_search_suffixes({"PATHEXT": ""}),
            harness.DEFAULT_WINDOWS_PATHEXT.split(os.pathsep),
        )

    # --- POSIX behaviour is unchanged ---------------------------------------

    @unittest.skipUnless(os.name == "posix", "POSIX has no PATHEXT")
    def test_posix_resolution_is_plain_path_order(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        expected = plant(first, "gh")
        plant(second, "gh")
        env = self.env(first, second)
        self.assertEqual(harness.probe_search_suffixes(env), [])
        self.assertSamePath(harness.resolve_probe_binary("gh", env), expected)

    @unittest.skipUnless(os.name == "posix", "the executable bit is POSIX-only")
    def test_posix_skips_a_candidate_without_the_executable_bit(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        unreadable = plant(first, "gh")
        unreadable.chmod(0o644)
        expected = plant(second, "gh")
        self.assertSamePath(
            harness.resolve_probe_binary("gh", self.env(first, second)), expected
        )

    @unittest.skipUnless(os.name == "posix", "nothing re-parses argv off Windows")
    def test_no_posix_target_is_treated_as_re_parsing(self) -> None:
        self.assertFalse(harness.probe_image_reparses("/usr/bin/gh"))
        self.assertFalse(harness.probe_image_reparses("/usr/bin/gh.cmd"))

    # --- an explicit path keeps its meaning ---------------------------------

    def test_an_explicit_path_is_not_searched_for(self) -> None:
        tools = self.root / "tools"
        existing = plant(tools, "gh.exe")
        self.assertEqual(harness.resolve_probe_binary(str(existing), {}), str(existing))
        self.assertIsNone(harness.resolve_probe_binary(str(tools / "absent.exe"), {}))

    # --- the cmd.exe re-parsing gate ----------------------------------------

    def test_a_shim_spawn_with_ordinary_arguments_is_allowed(self) -> None:
        self.assertEqual(
            harness.probe_shim_hazard(
                [r"C:\tools\gh.cmd", "api", "repos/owner/repo", "--jq", ".visibility"]
            ),
            "",
        )

    def test_a_shim_spawn_with_a_reparsable_argument_is_refused(self) -> None:
        hazard = harness.probe_shim_hazard(
            [r"C:\tools\gh.cmd", "api", "repos/owner/repo&whoami"]
        )
        self.assertIn("cmd.exe", hazard)
        # The offending token is repository-influenced text and is never echoed.
        self.assertNotIn("whoami", hazard)

    def test_a_metacharacter_in_the_resolved_path_is_refused(self) -> None:
        self.assertIn(
            "metacharacter", harness.probe_shim_hazard([r"C:\to&ols\gh.cmd", "api"])
        )

    def test_an_unquoted_delimiter_in_the_resolved_path_is_refused(self) -> None:
        self.assertIn(
            "delimiter", harness.probe_shim_hazard([r"C:\tools(x86)\gh.cmd", "api"])
        )

    def test_a_quoted_path_may_hold_those_delimiters(self) -> None:
        # subprocess quotes argv[0] when it holds whitespace, and a quoted token
        # keeps its parentheses literal — otherwise `Program Files (x86)` would
        # make every probe on an ordinary Windows box permanently unprovable.
        self.assertEqual(
            harness.probe_shim_hazard([r"C:\Program Files (x86)\gh.cmd", "api"]), ""
        )

    def test_an_empty_command_is_named_rather_than_spawned(self) -> None:
        self.assertEqual(harness.probe_shim_hazard([]), "the command is empty")
        self.assertEqual(harness.probe_spawn_argv([]), ([], "empty probe command"))

    @unittest.skipUnless(os.name == "nt", "only a Windows shim re-parses argv")
    def test_a_shim_only_probe_refuses_hostile_argv_and_allows_safe_argv(self) -> None:
        shim_dir = self.root / "shim"
        shim = plant(shim_dir, "gh.cmd")
        env = self.env(shim_dir, pathext=os.pathsep.join(WINDOWS_PATHEXT))
        spawn_argv, failure = harness.probe_spawn_argv(
            ["gh", "api", "repos/owner/repo|calc"], env
        )
        self.assertEqual(spawn_argv, [])
        self.assertIn("script shim", failure)
        spawn_argv, failure = harness.probe_spawn_argv(
            ["gh", "api", "repos/owner/repo"], env
        )
        self.assertEqual(failure, "")
        self.assertSamePath(spawn_argv[0], shim)
        self.assertEqual(spawn_argv[1:], ["api", "repos/owner/repo"])

    # --- every spawn in harness.py goes through the resolver ----------------

    def test_probe_spawn_argv_rewrites_argv_onto_the_resolved_image(self) -> None:
        tools = self.root / "tools"
        name = "gh.exe" if os.name == "nt" else "gh"
        image = plant(tools, name)
        env = self.env(tools, pathext=os.pathsep.join(WINDOWS_PATHEXT))
        spawn_argv, failure = harness.probe_spawn_argv(["gh", "--version"], env)
        self.assertEqual(failure, "")
        self.assertSamePath(spawn_argv[0], image)
        self.assertEqual(spawn_argv[1:], ["--version"])

    def test_run_refuses_an_unresolvable_probe_instead_of_spawning_it(self) -> None:
        repo = self.root / "repo"
        for name in ("git", "git.exe", "git.cmd"):
            plant(repo, name)
        empty = self.root / "empty"
        empty.mkdir()
        # Scoped, and restored on exit: nothing outside this block sees it.
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            harness.reset_probe_binary_cache()
            result = harness.run(["git", "--version"], repo)
        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.stdout, "")
        self.assertIn("no executable of that name on PATH", result.stderr)

    def test_bounded_command_result_refuses_an_unresolvable_probe(self) -> None:
        repo = self.root / "repo"
        for name in ("gh", "gh.exe", "gh.cmd"):
            plant(repo, name)
        empty = self.root / "empty"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            harness.reset_probe_binary_cache()
            resolved, stdout, failure = harness.bounded_command_result(
                ["gh", "--version"], repo
            )
        self.assertFalse(resolved)
        self.assertEqual(stdout, "")
        self.assertIn("no executable of that name on PATH", failure)

    def test_bounded_command_result_still_runs_a_resolvable_probe(self) -> None:
        resolved, stdout, failure = harness.bounded_command_result(
            [sys.executable, "-c", "print('probe ok')"]
        )
        self.assertTrue(resolved, failure)
        self.assertEqual(stdout, "probe ok")

    @unittest.skipUnless(os.name == "nt", "taskkill is the Windows branch")
    def test_terminate_process_tree_resolves_taskkill(self) -> None:
        if harness.resolve_probe_binary("taskkill") is None:
            self.skipTest("no taskkill on this machine's PATH")

        class FakeProcess:
            pid = 424242
            stdout = None
            stderr = None

            def kill(self) -> None:
                return None

        spawned: list[list[str]] = []

        def record(argv: list[str], **_kwargs: object) -> None:
            spawned.append(argv)

        with mock.patch.object(subprocess, "run", record):
            harness.terminate_process_tree(FakeProcess())
        self.assertEqual(len(spawned), 1)
        self.assertTrue(os.path.isabs(spawned[0][0]))
        self.assertEqual(os.path.basename(spawned[0][0]).lower(), "taskkill.exe")
        self.assertEqual(spawned[0][1:], ["/F", "/T", "/PID", "424242"])


if __name__ == "__main__":
    unittest.main()
