"""Runner output must not alter bound process-policy or reserved snapshot trees."""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from replay_v0 import cli, policy_sources
from replay_v0.tests.contract import test_cli as fixtures

ROOT = Path(__file__).resolve().parents[1]


class ReplayOutputBoundaryTests(unittest.TestCase):
    @contextmanager
    def fixture(self, two_processes=False):
        with fixtures.CliTests().fixture("same") as data:
            directory, corpus, recording, original = data
            roots = [directory / "baseline-policy", directory / "candidate-policy"]
            for root in roots:
                root.mkdir()
                marker = directory / (root.name + ".launched")
                (root / "policy.py").write_text(
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
                    + fixtures.CliTests.policy_script("same"),
                    encoding="utf-8",
                )
            original.unlink()
            snapshots = directory / "snapshots"
            snapshots.mkdir()
            args = fixtures.CliTests.replay_args(
                corpus, recording, roots[1] / "policy.py", directory / "reports"
            )
            if two_processes:
                args[args.index("--baseline") + 1] = (
                    f"process:{sys.executable},{roots[0] / 'policy.py'}"
                )
            with mock.patch.object(
                cli.tempfile, "gettempdir", return_value=str(snapshots)
            ):
                yield directory, roots, args, snapshots

    @staticmethod
    def with_output(args, output):
        result = list(args)
        result[result.index("--output") + 1] = str(output)
        return result

    @staticmethod
    def tree(root):
        result = {}
        for path in root.rglob("*"):
            key = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[key] = ("link", os.readlink(path))
            elif path.is_file():
                result[key] = ("file", path.read_bytes())
            else:
                result[key] = ("directory", None)
        return result

    def assert_rejected(self, data, output):
        directory, _roots, args, _snapshots = data
        before = self.tree(directory)
        stderr = io.StringIO()
        with (
            redirect_stderr(stderr),
            mock.patch.object(
                policy_sources,
                "_run_policy_process",
                wraps=policy_sources._run_policy_process,
            ) as run,
        ):
            code = cli.main(self.with_output(args, output))
        self.assertEqual(2, code, stderr.getvalue())
        run.assert_not_called()
        self.assertTrue(stderr.getvalue().startswith("replay input invalid:"))
        self.assertIn("output", stderr.getvalue())
        self.assertNotIn(str(directory), stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertEqual(before, self.tree(directory))

    def make_link(self, link, target):
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"host cannot create a directory symlink: {exc}")

    def test_candidate_root_and_nested_output_are_rejected_without_mutation(self):
        for nested in (False, True):
            with self.subTest(nested=nested), self.fixture() as data:
                output = data[1][1] / "new/reports" if nested else data[1][1]
                self.assert_rejected(data, output)

    def test_both_process_roots_are_checked_before_either_process_launches(self):
        for index in (0, 1):
            with self.subTest(index=index), self.fixture(True) as data:
                self.assert_rejected(data, data[1][index] / "reports")

    def test_existing_report_bytes_inside_a_policy_tree_are_preserved(self):
        with self.fixture() as data:
            output = data[1][1] / "reports"
            output.mkdir()
            for name in ("report.json", "report.md", "run-manifest.json"):
                (output / name).write_bytes(b"existing report sentinel\n")
            self.assert_rejected(data, output)

    def test_output_alias_into_a_policy_tree_is_rejected(self):
        with self.fixture() as data:
            alias = data[0] / "output-alias"
            self.make_link(alias, data[1][1])
            self.assert_rejected(data, alias / "new/reports")

    def test_aliased_policy_root_is_compared_by_its_resolved_location(self):
        with self.fixture() as data:
            alias = data[0] / "policy-alias"
            self.make_link(alias, data[0])
            data[2][data[2].index("--candidate") + 1] = (
                f"process:{sys.executable},{alias / 'candidate-policy/policy.py'}"
            )
            self.assert_rejected(data, data[1][1])

    def test_snapshot_roots_and_their_descendants_are_reserved_for_both_sources(self):
        for two_processes in (False, True):
            indices = (0, 1) if two_processes else (1,)
            for index in indices:
                for nested in (False, True):
                    with self.subTest(two=two_processes, index=index, nested=nested):
                        with self.fixture(two_processes) as data:
                            loaded = cli._load_process_source(
                                f"{sys.executable},{data[1][index] / 'policy.py'}", 30.0
                            )
                            reserved = data[3] / (
                                "replay-process-inputs-" + loaded.source.snapshot_identity
                            )
                            output = reserved / "reports" if nested else reserved
                            self.assert_rejected(data, output)

    def test_repeated_sibling_output_retains_identity_and_policy_bytes(self):
        with self.fixture(True) as data:
            directory, roots, args, snapshots = data
            # A common string prefix is not a path-component overlap.
            output = directory / "candidate-policy-results"
            before = [self.tree(root) for root in roots]
            reports = []
            with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
                self.assertEqual(0, cli.main(self.with_output(args, output)))
                reports.append((output / "run-manifest.json").read_bytes())
                markdown = (output / "report.md").read_text("utf-8")
                argv_line = next(
                    line for line in markdown.splitlines() if line.startswith("    [")
                )
                reproduction = json.loads(argv_line)
                self.assertEqual([sys.executable, "-m", "replay_v0.cli"], reproduction[:3])
                self.assertEqual(0, cli.main(reproduction[3:]))
                reports.append((output / "run-manifest.json").read_bytes())
            self.assertEqual(reports[0], reports[1])
            self.assertEqual(before, [self.tree(root) for root in roots])
            self.assertEqual([], list(snapshots.iterdir()))
            self.assertTrue((directory / "baseline-policy.launched").is_file())
            self.assertTrue((directory / "candidate-policy.launched").is_file())

    def test_output_alias_outside_policy_tree_remains_supported(self):
        with self.fixture() as data:
            target = data[0] / "actual-reports"
            target.mkdir()
            alias = data[0] / "reports-alias"
            self.make_link(alias, target)
            with mock.patch.object(cli, "_publish_report_set", wraps=cli._publish_report_set) as publish:
                self.assertEqual(0, cli.main(self.with_output(data[2], alias)))
            self.assertEqual(alias, publish.call_args.args[0])
            self.assertTrue((target / "report.json").is_file())
            self.assertFalse(list(data[1][1].glob(".replay-output-*")))

    def test_recorded_only_replay_has_no_process_directory_restriction(self):
        with self.fixture() as data:
            args = list(data[2])
            args[args.index("--candidate") + 1] = args[args.index("--baseline") + 1]
            self.assertEqual(0, cli.main(self.with_output(args, data[0] / "reports")))
            self.assertFalse(list(data[0].glob("*.launched")))

    def test_real_cli_overlap_returns_two_before_candidate_can_run(self):
        with self.fixture() as data:
            directory, roots, args, _snapshots = data
            before = self.tree(directory)
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "replay_v0.cli",
                    *self.with_output(args, roots[1]),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(2, run.returncode, run.stderr)
            self.assertTrue(run.stderr.startswith("replay input invalid:"))
            self.assertEqual("", run.stdout)
            self.assertEqual(before, self.tree(directory))


if __name__ == "__main__":
    unittest.main()
