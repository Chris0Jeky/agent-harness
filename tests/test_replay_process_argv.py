"""Structured process argv preserves comma-bearing values without a shell."""

from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from replay_v0 import cli, policy_sources
from replay_v0.tests.contract import test_cli as fixtures

ROOT = Path(__file__).resolve().parents[1]


def reference(argv):
    return "process-json:" + json.dumps(argv, ensure_ascii=True)


class ReplayProcessArgvTests(unittest.TestCase):
    def test_json_and_legacy_share_identity_for_identical_decoded_arguments(self):
        with fixtures.CliTests().fixture("same") as data:
            argv = [sys.executable, "-B", str(data[3])]
            legacy = cli._load_policy_source("process:" + ",".join(argv), 30.0)
            try:
                structured = cli._load_policy_source(reference(argv), 30.0)
            except cli.ReplayInputError as exc:
                self.fail(f"valid structured argv was rejected: {exc}")
            self.assertEqual("process", structured.kind)
            self.assertEqual(legacy.identity, structured.identity)
            self.assertEqual(legacy.source.argv, structured.source.argv)
            self.assertEqual(legacy.source.cwd, structured.source.cwd)
            self.assertEqual(legacy.source.environment, structured.source.environment)

    def test_commas_in_executable_policy_and_nonfinal_arguments_are_preserved(self):
        with fixtures.CliTests().fixture("same") as data:
            directory, _corpus, _recording, candidate = data
            executable = directory / ("python,fixture" + Path(sys.executable).suffix)
            shutil.copy2(sys.executable, executable)
            policy_root = directory / "policy,folder"
            policy_root.mkdir()
            policy = policy_root / "candidate,entry.py"
            candidate.rename(policy)
            argument = 'literal,argument;$(not-run)&%HOME% "quote" \\path'
            argv = [str(executable), argument, str(policy)]
            try:
                loaded = cli._load_policy_source(reference(argv), 30.0)
            except cli.ReplayInputError as exc:
                self.fail(f"comma-bearing argv was rejected: {exc}")
            self.assertEqual(
                (str(executable.resolve()), argument, policy.name), loaded.source.argv
            )
            changed = cli._load_policy_source(
                reference([str(executable), argument + "x", str(policy)]), 30.0
            )
            self.assertNotEqual(loaded.identity, changed.identity)

    def test_json_spacing_and_unicode_escapes_do_not_change_identity(self):
        with fixtures.CliTests().fixture("same") as data:
            argv = [sys.executable, "comma,\u2603", str(data[3])]
            try:
                compact = cli._load_policy_source(reference(argv), 30.0)
                pretty = cli._load_policy_source(
                    "process-json:" + json.dumps(argv, ensure_ascii=False, indent=2),
                    30.0,
                )
            except cli.ReplayInputError as exc:
                self.fail(f"valid JSON representation was rejected: {exc}")
            self.assertEqual(compact.identity, pretty.identity)
            self.assertEqual(compact.source.argv, pretty.source.argv)

    def test_legacy_bracketed_executable_is_not_reinterpreted_as_json(self):
        with fixtures.CliTests().fixture("same") as data:
            executable = data[0] / ("[python" + Path(sys.executable).suffix)
            shutil.copy2(sys.executable, executable)
            with mock.patch.dict(os.environ, {"PATH": str(data[0])}):
                loaded = cli._load_policy_source(
                    f"process:{executable.name},{data[3]}", 30.0
                )
            self.assertEqual(str(executable.resolve()), loaded.source.argv[0])

    def test_malformed_json_is_input_invalid_without_execution_or_input_echo(self):
        invalid = [
            "",
            "[",
            '["python", "policy.py",]',
            '["python", "policy.py"] trailing',
            '"python,policy.py"',
            '{"argv":["python","policy.py"]}',
            "null",
            "[]",
            '["python"]',
            '[null,"policy.py"]',
            '["python",false,"policy.py"]',
            '["python",1,"policy.py"]',
            '["python",NaN,"policy.py"]',
            '["python",[],"policy.py"]',
            '["python",{},"policy.py"]',
            '["","policy.py"]',
            '["python",""]',
            '["python","","policy.py"]',
            '["python","\\u0000","policy.py"]',
            '["python","\\r","policy.py"]',
            '["python","\\n","policy.py"]',
            '["python","\\ud800","policy.py"]',
            "[" * 1500 + "0" + "]" * 1500,
            '["python",' + "9" * 5000 + ',"policy.py"]',
        ]
        with fixtures.CliTests().fixture("same") as data:
            directory, corpus, recording, candidate = data
            output = directory / "must-not-exist"
            for payload in invalid:
                with self.subTest(payload=payload[:60]):
                    args = fixtures.CliTests.replay_args(
                        corpus, recording, candidate, output
                    )
                    args[args.index("--candidate") + 1] = "process-json:" + payload
                    stderr = io.StringIO()
                    with (
                        redirect_stderr(stderr),
                        mock.patch.object(
                            policy_sources,
                            "_run_policy_process",
                            wraps=policy_sources._run_policy_process,
                        ) as run,
                    ):
                        result = cli.main(args)
                    self.assertEqual(2, result, stderr.getvalue())
                    run.assert_not_called()
                    self.assertFalse(output.exists())
                    self.assertTrue(
                        stderr.getvalue().startswith("replay input invalid:")
                    )
                    self.assertNotIn("Traceback", stderr.getvalue())
                    self.assertNotIn(str(directory), stderr.getvalue())
                    self.assertNotIn("9" * 20, stderr.getvalue())
                    self.assertLess(len(stderr.getvalue()), 300)

    def test_real_cli_preserves_commas_and_printed_reproduction(self):
        with fixtures.CliTests().fixture("same") as data:
            directory, corpus, recording, candidate = data
            policy_root = directory / "policies,with commas"
            policy_root.mkdir()
            policy = policy_root / "candidate,entry.py"
            candidate.rename(policy)
            literal = 'comma,value; $(not-run) & %HOME% "quoted" \\path'
            wrapper = (
                "import sys;"
                f"assert sys.argv[1] == {literal!r};"
                "exec(compile(open(sys.argv[-1],encoding='utf-8').read(),"
                "sys.argv[-1],'exec'))"
            )
            source = reference([sys.executable, "-c", wrapper, literal, str(policy)])
            output = directory / "reports,with commas"
            args = fixtures.CliTests.replay_args(corpus, recording, policy, output)
            args[args.index("--candidate") + 1] = source
            before = {p.name: p.read_bytes() for p in policy_root.iterdir()}
            environment = dict(os.environ, SOURCE_DATE_EPOCH="0")
            first = subprocess.run(
                [sys.executable, "-m", "replay_v0.cli", *args],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(0, first.returncode, first.stderr)
            artifacts = {p.name: p.read_bytes() for p in output.iterdir()}
            self.assertEqual(
                {"report.json", "report.md", "run-manifest.json"}, set(artifacts)
            )
            markdown = artifacts["report.md"].decode("utf-8")
            reproduction = json.loads(
                next(line for line in markdown.splitlines() if line.startswith("    ["))
            )
            self.assertEqual(
                source, reproduction[reproduction.index("--candidate") + 1]
            )
            second = subprocess.run(
                reproduction,
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(
                artifacts, {p.name: p.read_bytes() for p in output.iterdir()}
            )
            self.assertEqual(
                before, {p.name: p.read_bytes() for p in policy_root.iterdir()}
            )

    def test_json_is_supported_for_both_process_sources(self):
        with fixtures.CliTests().fixture("same") as data:
            directory, corpus, recording, candidate = data
            policy_root = directory / "json-policy-sources"
            policy_root.mkdir()
            policy = policy_root / "entry,point.py"
            candidate.rename(policy)
            args = fixtures.CliTests.replay_args(
                corpus, recording, policy, directory / "reports"
            )
            source = reference([sys.executable, str(policy)])
            args[args.index("--baseline") + 1] = source
            args[args.index("--candidate") + 1] = source
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = cli.main(args)
            self.assertEqual(0, result, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
