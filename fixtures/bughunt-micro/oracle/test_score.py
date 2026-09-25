"""Maintainer controls for the scorer, not agent task tests or model judgments."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScoreContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="bh3-control-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "fixture with spaces"
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns("__pycache__"))
        self.env = {
            **os.environ,
            "BH3_PYTHON": sys.executable,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
        self.env.pop("PYTEST_ADDOPTS", None)
        self.env.pop("PYTEST_PLUGINS", None)

    def manifest(self):
        return json.loads((self.root / "bugs/MANIFEST.json").read_text("utf-8"))

    def write_manifest(self, manifest):
        (self.root / "bugs/MANIFEST.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def score(self, *, check=True):
        argv = [sys.executable, "-I", str(self.root / "oracle/score.py")]
        if check:
            argv.append("--check")
        result = subprocess.run(
            argv,
            cwd=self.root.parent,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload, _ = json.JSONDecoder().raw_decode(result.stdout)
        return result.returncode, payload

    def golden(self):
        subprocess.run(
            ["git", "apply", "--check", "fixes/golden.patch"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "apply", "fixes/golden.patch"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )

    def assert_invalid(self):
        code, result = self.score()
        self.assertEqual(2, code, result)
        self.assertEqual("invalid", result["mode"])
        self.assertFalse(result["valid"])
        self.assertEqual(0, result["passed"])

    def test_baseline_is_a_valid_zero_score_not_a_runner_failure(self):
        code, result = self.score()
        self.assertEqual((1, 0, 10), (code, result["passed"], result["total"]))
        self.assertEqual("bugs_present", result["mode"])

    def test_golden_is_ten_of_ten(self):
        self.golden()
        code, result = self.score()
        self.assertEqual((0, 10, 10), (code, result["passed"], result["total"]))
        self.assertEqual(0, result["pytest_exit"])

    def test_collection_exception_cannot_spoof_passes(self):
        fake = "\n".join(f"::{bug['test']} PASSED" for bug in self.manifest()["bugs"])
        (self.root / "src/app.py").write_text(
            f"raise RuntimeError({fake!r})\n", encoding="utf-8"
        )
        self.assert_invalid()

    def test_empty_manifest_cannot_pass_vacuously(self):
        manifest = self.manifest()
        manifest.update(planted_total=0, bugs=[])
        self.write_manifest(manifest)
        self.assert_invalid()

    def test_manifest_count_must_match_unique_tests(self):
        manifest = self.manifest()
        manifest["planted_total"] = 9
        self.write_manifest(manifest)
        self.assert_invalid()

    def test_duplicate_ids_or_test_names_are_invalid(self):
        original = self.manifest()
        for field in ("id", "test"):
            with self.subTest(field=field):
                manifest = json.loads(json.dumps(original))
                manifest["bugs"][1][field] = manifest["bugs"][0][field]
                self.write_manifest(manifest)
                self.assert_invalid()

    def test_missing_test_is_not_a_valid_partial_score(self):
        path = self.root / "tests/test_oracle.py"
        path.write_text(
            path.read_text("utf-8").replace("def test_BUG01_", "def removed_BUG01_"),
            encoding="utf-8",
        )
        self.assert_invalid()

    def test_skipped_test_is_not_evidence(self):
        path = self.root / "tests/test_oracle.py"
        path.write_text(
            path.read_text("utf-8").replace(
                "def test_BUG01_",
                '@pytest.mark.skip(reason="control")\ndef test_BUG01_',
            ),
            encoding="utf-8",
        )
        self.assert_invalid()

    def test_teardown_failure_cannot_hide_behind_ten_passes(self):
        self.golden()
        path = self.root / "tests/test_oracle.py"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                '\n@pytest.fixture(scope="session", autouse=True)\n'
                "def broken_teardown():\n"
                "    yield\n"
                '    raise RuntimeError("controlled teardown failure")\n'
            )
        self.assert_invalid()

    @unittest.skipIf(os.name == "nt", "POSIX convenience wrapper")
    def test_score_wrapper_preserves_partial_score_mode(self):
        result = subprocess.run(
            [str(self.root / "oracle/score.sh")],
            cwd=self.root.parent,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        self.assertEqual((0, 0, 10), (result.returncode, data["passed"], data["total"]))
        self.assertTrue(data["valid"])

    @unittest.skipIf(os.name == "nt", "POSIX convenience wrapper")
    def test_check_wrapper_uses_the_selected_interpreter_for_every_step(self):
        trap = self.root / "trap"
        trap.mkdir()
        python3 = trap / "python3"
        python3.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        python3.chmod(0o755)
        self.env["PATH"] = str(trap) + os.pathsep + os.environ["PATH"]
        result = subprocess.run(
            [str(self.root / "oracle/check.sh")],
            cwd=self.root.parent,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_case_fallback_bug_is_visible_on_case_insensitive_hosts(self):
        code = (
            "import runpy, tempfile; from pathlib import Path; "
            "from unittest import TestCase, mock; "
            f"tests = runpy.run_path({str(self.root / 'tests/test_oracle.py')!r}); "
            "case = TestCase()\n"
            "with tempfile.TemporaryDirectory() as directory:\n"
            "    with mock.patch.object(Path, 'exists', return_value=True):\n"
            "        with case.assertRaises(FileNotFoundError):\n"
            "            tests['test_BUG05_case_insensitive_config'](Path(directory))\n"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_ambient_pytest_options_cannot_disable_assertions_or_select_tests(self):
        self.env["PYTEST_ADDOPTS"] = "--assert=plain -k nonexistent"
        code, result = self.score(check=False)
        self.assertEqual((0, 0, 10), (code, result["passed"], result["total"]))
        self.assertEqual(1, result["pytest_exit"])
        self.assertTrue(result.get("valid", False))


if __name__ == "__main__":
    unittest.main()
