"""Floor v1.5.4 regressions for agent-harness#12 (F3 + F5).

F3: --abort/--quit sequencer flows never consult an editor, so an inherited
GIT_EDITOR must not deny the estate's always-safe recovery commands.
F5: the vendored smoke suite must refuse fixture roots that inherit a host
tier declaration (or sit inside the floor's temp allowance).
"""

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"
SMOKE_PATH = ROOT / "templates" / "hooks" / "smoke_test.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GitEditorTerminalFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dispatch = load_module("terminal_flow_dispatch", DISPATCH_PATH)

    def test_abort_and_quit_flows_do_not_reach_the_editor(self) -> None:
        cases = [
            ("merge", ["--abort"]),
            ("merge", ["--quit"]),
            ("rebase", ["--abort"]),
            # Prefix abbreviation: the helper treats any --ab… prefix of
            # --abort as terminal (fail-safe — git itself errors on an
            # ambiguous abbreviation, so no editor launches either way).
            ("rebase", ["--ab"]),
            ("cherry-pick", ["--abort"]),
            ("cherry-pick", ["--quit"]),
            ("revert", ["--abort"]),
            ("am", ["--abort"]),
            ("am", ["--quit"]),
        ]
        for subcommand, args in cases:
            with self.subTest(subcommand=subcommand, args=args):
                self.assertFalse(
                    self.dispatch.git_editor_is_reachable(subcommand, args)
                )

    def test_editor_flows_stay_reachable(self) -> None:
        cases = [
            ("merge", ["main"]),
            ("merge", ["--continue"]),  # --continue can open the msg editor
            ("rebase", ["--continue"]),
            ("rebase", ["main"]),
            ("commit", []),
            ("cherry-pick", ["HEAD~1"]),
            # After a bare -- everything is positional: an --abort-shaped
            # positional must NOT count as terminal (git errors on the
            # dash-leading refname; staying reachable keeps the deny).
            ("merge", ["--", "--abort"]),
            # Git's named end-of-options marker has the same effect.
            ("merge", ["--end-of-options", "--abort"]),
            ("merge", ["--end-of-options", "--quit"]),
        ]
        for subcommand, args in cases:
            with self.subTest(subcommand=subcommand, args=args):
                self.assertTrue(self.dispatch.git_editor_is_reachable(subcommand, args))

    def test_option_values_named_like_terminal_flows_stay_reachable(self) -> None:
        cases = [
            ("merge", ["-m", "--abort", "--edit", "--no-ff", "side"]),
            ("merge", ["-m--abort", "--edit", "--no-ff", "side"]),
            ("merge", ["--message", "--quit", "--edit", "side"]),
            ("merge", ["--message=--abort", "--edit", "side"]),
            ("merge", ["-s", "--abort", "--edit", "side"]),
            ("merge", ["-X--quit", "--edit", "side"]),
            ("merge", ["-S--abort", "--edit", "side"]),
            ("merge", ["--gpg-sign=--quit", "--edit", "side"]),
            ("rebase", ["--onto", "--abort", "main"]),
            ("rebase", ["-x--quit", "main"]),
            ("cherry-pick", ["-m", "--abort", "--edit", "HEAD"]),
            ("revert", ["--mainline", "--quit", "--edit", "HEAD"]),
            ("am", ["--quoted-cr", "--abort", "--interactive", "patch"]),
            ("am", ["-C--quit", "--interactive", "patch"]),
        ]
        for subcommand, args in cases:
            with self.subTest(subcommand=subcommand, args=args):
                self.assertTrue(self.dispatch.git_editor_is_reachable(subcommand, args))

    def test_terminal_flows_after_option_values_stay_unreachable(self) -> None:
        cases = [
            ("merge", ["-m", "message", "--abort"]),
            ("merge", ["-mmessage", "--quit"]),
            ("merge", ["--message=message", "--abort"]),
            ("merge", ["-S", "--abort"]),
            ("merge", ["--gpg-sign", "--quit"]),
            ("rebase", ["--onto", "main", "--abort"]),
            ("rebase", ["-xtrue", "--quit"]),
            ("cherry-pick", ["-m", "1", "--abort"]),
            ("revert", ["--mainline=1", "--quit"]),
            ("am", ["--quoted-cr", "nowarn", "--abort"]),
            ("am", ["-C1", "--quit"]),
        ]
        for subcommand, args in cases:
            with self.subTest(subcommand=subcommand, args=args):
                self.assertFalse(
                    self.dispatch.git_editor_is_reachable(subcommand, args)
                )

    def test_sequencer_value_option_arity(self) -> None:
        required_options = {
            "merge": {
                "short": ["-m", "-F", "-s", "-X"],
                "long": [
                    "--cleanup",
                    "--strategy",
                    "--strategy-option",
                    "--message",
                    "--file",
                    "--into-name",
                ],
            },
            "rebase": {
                "short": ["-C", "-x", "-s", "-X"],
                "long": [
                    "--onto",
                    "--whitespace",
                    "--empty",
                    "--exec",
                    "--strategy",
                    "--strategy-option",
                ],
            },
            "cherry-pick": {
                "short": ["-m", "-X"],
                "long": [
                    "--cleanup",
                    "--mainline",
                    "--strategy",
                    "--strategy-option",
                    "--empty",
                ],
            },
            "revert": {
                "short": ["-m", "-X"],
                "long": [
                    "--cleanup",
                    "--mainline",
                    "--strategy",
                    "--strategy-option",
                ],
            },
            "am": {
                "short": ["-C", "-p"],
                "long": [
                    "--quoted-cr",
                    "--whitespace",
                    "--directory",
                    "--exclude",
                    "--include",
                    "--patch-format",
                    "--resolvemsg",
                    "--empty",
                ],
            },
        }
        terminal = self.dispatch.git_sequencer_flow_is_terminal
        for subcommand, options in required_options.items():
            for option in options["short"]:
                with self.subTest(
                    subcommand=subcommand, option=option, form="separate"
                ):
                    self.assertFalse(terminal(subcommand, [option, "--abort"]))
                    self.assertTrue(terminal(subcommand, [option, "value", "--abort"]))
                with self.subTest(
                    subcommand=subcommand, option=option, form="attached"
                ):
                    self.assertFalse(terminal(subcommand, [option + "--quit"]))
                    self.assertTrue(terminal(subcommand, [option + "value", "--quit"]))
            for option in options["long"]:
                with self.subTest(
                    subcommand=subcommand, option=option, form="separate"
                ):
                    self.assertFalse(terminal(subcommand, [option, "--abort"]))
                    self.assertTrue(terminal(subcommand, [option, "value", "--abort"]))
                with self.subTest(
                    subcommand=subcommand, option=option, form="attached"
                ):
                    self.assertFalse(terminal(subcommand, [option + "=--quit"]))
                    self.assertTrue(terminal(subcommand, [option + "=value", "--quit"]))

    def test_sequencer_optional_values_only_consume_attached_text(self) -> None:
        optional_long = {
            "merge": ["--log", "--gpg-sign"],
            "rebase": ["--gpg-sign", "--rebase-merges"],
            "cherry-pick": ["--gpg-sign"],
            "revert": ["--gpg-sign"],
            "am": ["--gpg-sign", "--show-current-patch"],
        }
        terminal = self.dispatch.git_sequencer_flow_is_terminal
        for subcommand, options in optional_long.items():
            with self.subTest(subcommand=subcommand, option="-S", form="separate"):
                self.assertTrue(terminal(subcommand, ["-S", "--abort"]))
            with self.subTest(subcommand=subcommand, option="-S", form="attached"):
                self.assertFalse(terminal(subcommand, ["-S--abort"]))
                self.assertTrue(terminal(subcommand, ["-Skey", "--quit"]))
            for option in options:
                with self.subTest(
                    subcommand=subcommand, option=option, form="separate"
                ):
                    self.assertTrue(terminal(subcommand, [option, "--abort"]))
                with self.subTest(
                    subcommand=subcommand, option=option, form="attached"
                ):
                    self.assertFalse(terminal(subcommand, [option + "=--abort"]))
                    self.assertTrue(terminal(subcommand, [option + "=value", "--quit"]))

    def test_abort_does_not_leak_into_non_sequencer_subcommands(self) -> None:
        # config/add have no --abort; the terminal check must not change them.
        self.assertFalse(self.dispatch.git_editor_is_reachable("config", ["--list"]))
        self.assertTrue(self.dispatch.git_editor_is_reachable("config", ["--edit"]))

    def test_sequence_editor_unreachable_on_interactive_abort(self) -> None:
        reachable = self.dispatch.inherited_git_process_environment_is_reachable
        self.assertFalse(
            reachable("GIT_SEQUENCE_EDITOR", "rebase", ["-i", "--abort"], [])
        )
        self.assertTrue(reachable("GIT_SEQUENCE_EDITOR", "rebase", ["-i", "main"], []))

    def test_check_allows_recovery_with_inherited_git_editor(self) -> None:
        tier = {"tier": 4, "flags": {"sensitive_data": True}}
        # check() scans live os.environ for the WHOLE process-launch set
        # (e.g. GIT_EXEC_PATH is reachable for any subcommand), so sanitize
        # every name in it — not just the editor trio — or a host/CI
        # exporting one of them turns these allow assertions falsely red.
        sanitized = set(self.dispatch._GIT_PROCESS_COMMAND_ENVIRONMENT) | {
            "GIT_SEQUENCE_EDITOR"
        }
        saved = {name: os.environ.get(name) for name in sanitized}
        for name in sanitized:
            os.environ.pop(name, None)
        os.environ["GIT_EDITOR"] = "true"
        try:
            with tempfile.TemporaryDirectory() as project:
                for command in (
                    "git merge --abort",
                    "git rebase --abort",
                    "git cherry-pick --abort",
                ):
                    with self.subTest(command=command):
                        decision, _ = self.dispatch.check(
                            command, tier, project, project
                        )
                        self.assertEqual(decision, "allow")
                # A flow that genuinely reaches the editor stays denied.
                decision, _ = self.dispatch.check(
                    "git merge main", tier, project, project
                )
                self.assertEqual(decision, "deny")
                # --abort is the separate value of -m here. The later --edit
                # still reaches the inherited editor, so the check must deny.
                decision, _ = self.dispatch.check(
                    "git merge -m --abort --edit --no-ff side",
                    tier,
                    project,
                    project,
                )
                self.assertEqual(decision, "deny")
                # --abort is a ref operand after Git's named option
                # terminator, so the preceding --edit still reaches the
                # inherited editor and must remain denied.
                decision, _ = self.dispatch.check(
                    "git merge --edit --no-ff --end-of-options --abort",
                    tier,
                    project,
                    project,
                )
                self.assertEqual(decision, "deny")
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


class SmokeNeutralFixtureRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.smoke = load_module("neutral_root_smoke", SMOKE_PATH)
        cls.dispatch = cls.smoke.load_dispatch_module()

    def _require_neutral_home(self) -> None:
        if self.dispatch.declared_project_dirs(os.path.expanduser("~")):
            self.skipTest("user home inherits a tier declaration")

    def test_candidate_under_declared_authority_is_rejected(self) -> None:
        self._require_neutral_home()
        # Home-anchored (non-temp) so the authority walk, not the temp
        # allowance, is what rejects the nested candidate.
        base = os.path.join(
            os.path.expanduser("~"), ".agent-harness-smoke-authority-test"
        )
        declared = os.path.join(base, "host")
        nested = os.path.join(declared, "hooks-clone")
        clean = os.path.join(base, "clean")
        os.makedirs(os.path.join(declared, ".claude"), exist_ok=True)
        os.makedirs(nested, exist_ok=True)
        os.makedirs(clean, exist_ok=True)
        tier_path = os.path.join(declared, ".claude", "tier.json")
        try:
            with open(tier_path, "w", encoding="utf-8") as handle:
                json.dump({"tier": 4, "flags": {"sensitive_data": True}}, handle)
            selected = self.smoke.neutral_fixture_root(candidates=[nested, clean])
            self.assertEqual(os.path.dirname(selected), clean)
            self.assertTrue(
                os.path.basename(selected).startswith(".agent-harness-smoke-")
            )
        finally:
            if "selected" in locals() and os.path.isdir(selected):
                shutil.rmtree(selected)
            os.remove(tier_path)
            for path in (
                os.path.join(declared, ".claude"),
                nested,
                declared,
                clean,
                base,
            ):
                if os.path.isdir(path) and not os.listdir(path):
                    os.rmdir(path)

    def test_temp_resident_candidate_is_rejected(self) -> None:
        self._require_neutral_home()
        home_candidate = os.path.join(
            os.path.expanduser("~"), ".agent-harness-smoke-fixtures-test"
        )
        os.makedirs(home_candidate, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp_candidate:
            try:
                selected = self.smoke.neutral_fixture_root(
                    candidates=[temp_candidate, home_candidate]
                )
                self.assertEqual(os.path.dirname(selected), home_candidate)
            finally:
                if "selected" in locals() and os.path.isdir(selected):
                    shutil.rmtree(selected)
                if os.path.isdir(home_candidate) and not os.listdir(home_candidate):
                    os.rmdir(home_candidate)

    def test_no_clean_candidate_refuses_to_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_only:
            with self.assertRaises(SystemExit):
                self.smoke.neutral_fixture_root(candidates=[temp_only])

    def test_main_removes_run_owned_fixture_root_on_exit(self) -> None:
        self._require_neutral_home()
        parent = os.path.join(
            os.path.expanduser("~"), ".agent-harness-smoke-cleanup-test"
        )
        os.makedirs(parent, exist_ok=True)
        selected = self.smoke.neutral_fixture_root(candidates=[parent])
        self.smoke._FIXTURE_ROOT = selected
        try:
            with mock.patch.object(self.smoke, "run_smoke", side_effect=SystemExit(7)):
                with self.assertRaisesRegex(SystemExit, "7"):
                    self.smoke.main()
            self.assertFalse(os.path.exists(selected))
            self.assertIsNone(self.smoke._FIXTURE_ROOT)
        finally:
            if os.path.isdir(selected):
                shutil.rmtree(selected)
            self.smoke._FIXTURE_ROOT = None
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)


if __name__ == "__main__":
    unittest.main()
