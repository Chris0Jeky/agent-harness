"""Floor v1.5.3 regressions for agent-harness#12 (F3 + F5).

F3: --abort/--quit sequencer flows never consult an editor, so an inherited
GIT_EDITOR must not deny the estate's always-safe recovery commands.
F5: the vendored smoke suite must refuse fixture roots that inherit a host
tier declaration (or sit inside the floor's temp allowance).
"""

import importlib.util
import json
import os
import tempfile
import unittest
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
            ("rebase", ["--ab"]),  # unambiguous git long-option abbreviation
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
        ]
        for subcommand, args in cases:
            with self.subTest(subcommand=subcommand, args=args):
                self.assertTrue(
                    self.dispatch.git_editor_is_reachable(subcommand, args)
                )

    def test_abort_does_not_leak_into_non_sequencer_subcommands(self) -> None:
        # config/add have no --abort; the terminal check must not change them.
        self.assertFalse(self.dispatch.git_editor_is_reachable("config", ["--list"]))
        self.assertTrue(self.dispatch.git_editor_is_reachable("config", ["--edit"]))

    def test_sequence_editor_unreachable_on_interactive_abort(self) -> None:
        reachable = self.dispatch.inherited_git_process_environment_is_reachable
        self.assertFalse(reachable("GIT_SEQUENCE_EDITOR", "rebase", ["-i", "--abort"], []))
        self.assertTrue(reachable("GIT_SEQUENCE_EDITOR", "rebase", ["-i", "main"], []))

    def test_check_allows_recovery_with_inherited_git_editor(self) -> None:
        tier = {"tier": 4, "flags": {"sensitive_data": True}}
        saved = {
            name: os.environ.get(name) for name in ("GIT_EDITOR", "EDITOR", "VISUAL")
        }
        os.environ["GIT_EDITOR"] = "true"
        os.environ.pop("EDITOR", None)
        os.environ.pop("VISUAL", None)
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
            selected = self.smoke.neutral_fixture_root(
                candidates=[nested, clean]
            )
            self.assertEqual(selected, clean)
        finally:
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
        with tempfile.TemporaryDirectory() as temp_candidate:
            try:
                selected = self.smoke.neutral_fixture_root(
                    candidates=[temp_candidate, home_candidate]
                )
                self.assertEqual(selected, home_candidate)
            finally:
                if os.path.isdir(home_candidate) and not os.listdir(home_candidate):
                    os.rmdir(home_candidate)

    def test_no_clean_candidate_refuses_to_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_only:
            with self.assertRaises(SystemExit):
                self.smoke.neutral_fixture_root(candidates=[temp_only])


if __name__ == "__main__":
    unittest.main()
