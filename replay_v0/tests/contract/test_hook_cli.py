"""End to end: two versions of the example hook compared over the charter corpus."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from replay_v0.app import main

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "replay_v0" / "corpora" / "charter"
GUARDS = REPO / "examples" / "toy-guard"


def _hook(name: str) -> str:
    return json.dumps([sys.executable, str(GUARDS / name)])


class HookOptionTests(unittest.TestCase):
    def _record(self, *extra: str, output: str) -> int:
        return main(
            [
                "record",
                "--hook",
                _hook("guard_v1.py"),
                "--corpus",
                str(CORPUS),
                "--output",
                output,
                *extra,
            ]
        )

    def test_out_of_range_timeouts_and_jobs_are_refused(self) -> None:
        # The kernel's --timeout refuses these; the hook runner must too, or a
        # zero timeout records every event as a timeout and still exits 0.
        cases = (
            ("--hook-timeout", "0"),
            ("--hook-timeout", "-1"),
            ("--hook-timeout", "nan"),
            ("--hook-timeout", "inf"),
            ("--jobs", "0"),
            ("--jobs", "65"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for flag, value in cases:
                with self.subTest(flag=flag, value=value):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as caught:
                            self._record(flag, value, output=tmp)
                    self.assertEqual(caught.exception.code, 2)

    def test_a_missing_redact_terms_file_is_input_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "import",
                        "--output",
                        str(Path(tmp) / "corpus"),
                        "--redact-terms",
                        str(Path(tmp) / "absent.txt"),
                    ]
                )
        self.assertEqual(code, 2)
        self.assertIn("--redact-terms is not a readable file", stderr.getvalue())

    def test_a_filesystem_failure_is_a_clean_exit_three(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "replay_v0.app.record_hook", side_effect=PermissionError("denied")
            ), contextlib.redirect_stderr(stderr):
                code = self._record(output=tmp)
        self.assertEqual(code, 3)
        self.assertIn("PermissionError: denied", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


class HookDiffTests(unittest.TestCase):
    def test_toy_guard_upgrade_reports_its_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "hooks",
                        "--baseline",
                        _hook("guard_v1.py"),
                        "--candidate",
                        _hook("guard_v2.py"),
                        "--corpus",
                        str(CORPUS),
                        "--output",
                        str(output),
                        "--jobs",
                        "4",
                    ]
                )
            self.assertEqual(code, 1)
            summary = json.loads((output / "summary.json").read_text("utf-8"))
            self.assertEqual(summary["counts"]["newly-allowed"], 4)
            self.assertEqual(summary["counts"]["newly-denied"], 1)
            self.assertEqual(summary["counts"]["newly-indeterminate"], 0)
            self.assertEqual(
                summary["by_case_class"]["dangerous"].get("newly-allowed"), 1
            )
            self.assertEqual(summary["outcomes"]["candidate"]["crash"], 0)
            for name in ("report.json", "report.md", "run-manifest.json"):
                self.assertTrue((output / "report" / name).is_file(), name)
            markdown = (output / "summary.md").read_text("utf-8")
            self.assertIn("no corpus command was executed", markdown)

    def test_same_hook_twice_passes_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "hooks",
                        "--baseline",
                        _hook("guard_v1.py"),
                        "--candidate",
                        _hook("guard_v1.py"),
                        "--corpus",
                        str(CORPUS),
                        "--output",
                        str(Path(tmp) / "run"),
                    ]
                )
            self.assertEqual(code, 0)

    def test_bad_hook_command_is_input_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stderr(io.StringIO()):
                code = main(
                    [
                        "record",
                        "--hook",
                        "[",
                        "--corpus",
                        str(CORPUS),
                        "--output",
                        tmp,
                    ]
                )
            self.assertEqual(code, 2)

    def test_hooks_replaces_stale_report_and_summaries(self) -> None:
        sentinel = "stale-sentinel-9f3c4a"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            (output / "report").mkdir(parents=True)
            (output / "report" / "report.json").write_text(sentinel, encoding="utf-8")
            (output / "summary.json").write_text(
                json.dumps({"stale": sentinel}), encoding="utf-8"
            )
            (output / "summary.md").write_text(sentinel, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "hooks",
                        "--baseline",
                        _hook("guard_v1.py"),
                        "--candidate",
                        _hook("guard_v2.py"),
                        "--corpus",
                        str(CORPUS),
                        "--output",
                        str(output),
                        "--jobs",
                        "4",
                    ]
                )
            self.assertEqual(code, 1)
            raw = (output / "summary.json").read_text(encoding="utf-8")
            self.assertNotIn(sentinel, raw)
            summary = json.loads(raw)
            self.assertEqual(summary["counts"]["newly-allowed"], 4)
            self.assertEqual(summary["counts"]["newly-denied"], 1)
            self.assertEqual(summary["counts"]["newly-indeterminate"], 0)
            markdown = (output / "summary.md").read_text(encoding="utf-8")
            self.assertIn("# Hook decision diff", markdown)
            self.assertNotIn(sentinel, markdown)
            report_raw = (output / "report" / "report.json").read_text(encoding="utf-8")
            self.assertNotIn(sentinel, report_raw)

    def test_record_workspace_pointing_at_file_is_input_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_file = Path(tmp) / "workspace-file"
            workspace_file.write_text("not a directory", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main(
                    [
                        "record",
                        "--hook",
                        _hook("guard_v1.py"),
                        "--corpus",
                        str(CORPUS),
                        "--output",
                        str(Path(tmp) / "out"),
                        "--workspace",
                        str(workspace_file),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn(
                f"workspace template is not a directory: {workspace_file}",
                err.getvalue(),
            )

    def test_hooks_workspace_pointing_at_file_is_input_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_file = Path(tmp) / "workspace-file"
            workspace_file.write_text("not a directory", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main(
                    [
                        "hooks",
                        "--baseline",
                        _hook("guard_v1.py"),
                        "--candidate",
                        _hook("guard_v1.py"),
                        "--corpus",
                        str(CORPUS),
                        "--output",
                        str(Path(tmp) / "run"),
                        "--workspace",
                        str(workspace_file),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn(
                f"workspace template is not a directory: {workspace_file}",
                err.getvalue(),
            )


if __name__ == "__main__":
    unittest.main()
