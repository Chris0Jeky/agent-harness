"""One checked-file inventory feeds all three existing CI commands."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/python_checks.py"


class PythonChecksTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "the shared check launcher is missing")
        spec = importlib.util.spec_from_file_location("python_checks", SCRIPT)
        self.checks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.checks)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "scripts").mkdir()
        (self.root / "replay_v0").mkdir()
        self.files = ["first.py", "scripts/with space.py"]
        for name in self.files:
            (self.root / name).write_text("value = 1\n", encoding="utf-8")
        self.inventory = self.root / "scripts/python_check_files.json"
        self.write_inventory(self.files)

    def write_inventory(self, value):
        self.inventory.write_text(json.dumps(value), encoding="utf-8")

    def test_each_tool_uses_active_interpreter_and_the_same_inventory(self):
        prefixes = {
            "ruff": ["-m", "ruff", "check"],
            "black": ["-m", "black", "--check", "--diff", "replay_v0"],
            "compile": ["-m", "py_compile"],
        }
        for tool, prefix in prefixes.items():
            with self.subTest(tool=tool):
                with mock.patch.object(self.checks.subprocess, "run") as run:
                    run.return_value.returncode = 0
                    self.assertEqual(self.checks.main([tool], root=self.root), 0)
                    run.assert_called_once_with(
                        [sys.executable, *prefix, *self.files],
                        cwd=self.root,
                        check=False,
                    )

    def test_tool_failure_propagates_without_running_other_tools(self):
        with mock.patch.object(self.checks.subprocess, "run") as run:
            run.return_value.returncode = 17
            self.assertEqual(self.checks.main(["ruff"], root=self.root), 17)
            self.assertEqual(run.call_count, 1)

    def test_invalid_inventory_refuses_before_starting_a_tool(self):
        for value in (
            [],
            {},
            None,
            [1],
            ["first.py", "first.py"],
            ["missing.py"],
            ["../outside.py"],
            ["/absolute.py"],
            ["-option.py"],
            ["scripts//with space.py"],
            ["scripts/./with space.py"],
            ["C:/outside.py"],
            ["scripts\\outside.py"],
            ["first.txt"],
        ):
            with self.subTest(inventory=value):
                self.write_inventory(value)
                with mock.patch.object(self.checks.subprocess, "run") as run:
                    with self.assertRaises(ValueError):
                        self.checks.load_files(self.root)
                    run.assert_not_called()

    def test_unreadable_or_malformed_inventory_is_a_classified_cli_error(self):
        for content in ("{", "[]"):
            with self.subTest(content=content):
                self.inventory.write_text(content, encoding="utf-8")
                with mock.patch.object(self.checks.subprocess, "run") as run:
                    with mock.patch.object(self.checks.sys, "stderr") as stderr:
                        self.assertEqual(
                            self.checks.main(["compile"], root=self.root), 2
                        )
                    run.assert_not_called()
                    self.assertIn("python checks:", str(stderr.write.call_args_list))
        self.inventory.unlink()
        with mock.patch.object(self.checks.sys, "stderr"):
            self.assertEqual(self.checks.main(["compile"], root=self.root), 2)

    def test_missing_tool_launch_is_a_classified_error(self):
        with mock.patch.object(
            self.checks.subprocess, "run", side_effect=OSError("missing")
        ):
            with mock.patch.object(self.checks.sys, "stderr"):
                self.assertEqual(self.checks.main(["black"], root=self.root), 2)

    def test_new_inventory_entry_reaches_every_tool_without_workflow_edit(self):
        added = "scripts/new_module.py"
        (self.root / added).write_text("pass\n", encoding="utf-8")
        self.write_inventory([*self.files, added])
        for tool in ("ruff", "black", "compile"):
            with self.subTest(tool=tool):
                with mock.patch.object(self.checks.subprocess, "run") as run:
                    run.return_value.returncode = 0
                    self.assertEqual(self.checks.main([tool], root=self.root), 0)
                    self.assertEqual(run.call_args.args[0][-1], added)

    def test_compile_runs_from_the_repository_not_the_callers_directory(self):
        with mock.patch.object(self.checks, "ROOT", self.root):
            self.assertEqual(self.checks.main(["compile"], root=self.root), 0)
        for name in self.files:
            self.assertTrue(list((self.root / name).parent.glob("__pycache__/*.pyc")))

    def test_repository_inventory_includes_the_launcher_and_its_test(self):
        files = self.checks.load_files(ROOT)
        self.assertIn("scripts/python_checks.py", files)
        self.assertIn("tests/test_python_checks.py", files)
        for name in (
            "harness.py",
            "templates/hooks/dispatch.py",
            "templates/hooks/smoke_test.py",
        ):
            self.assertIn(name, files)

    def test_invalid_tool_does_not_spawn_a_child(self):
        with mock.patch.object(self.checks.subprocess, "run") as run:
            with mock.patch.object(self.checks.sys, "stderr"):
                with self.assertRaises(SystemExit) as failure:
                    self.checks.main(["unknown"], root=self.root)
            self.assertEqual(failure.exception.code, 2)
            run.assert_not_called()

    def test_cli_compiles_the_committed_inventory(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "compile"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class WorkflowInventoryTests(unittest.TestCase):
    def test_verify_steps_delegate_instead_of_copying_file_lists(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text("utf-8")
        for name, tool in (
            ("Run Ruff", "ruff"),
            ("Check Black formatting", "black"),
            ("Compile Python sources", "compile"),
        ):
            with self.subTest(tool=tool):
                self.assertIn(
                    f"      - name: {name}\n        run: python scripts/python_checks.py {tool}\n",
                    text,
                )
        self.assertNotIn("          harness.py tests/test_harness.py", text)


if __name__ == "__main__":
    unittest.main()
