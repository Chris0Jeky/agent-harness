"""Integration controls for replay's JSON decoder exception boundary."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from replay_v0 import cli
from replay_v0.tests.contract import test_cli as cli_fixtures
from replay_v0.tests.unit import test_recorded_source as recorded_fixtures
from replay_v0.policy_sources import RecordedDecisionSource

ROOT = Path(__file__).resolve().parents[1]


class ReplayDecoderContractTests(unittest.TestCase):
    def test_jsonl_recursion_failure_is_bounded(self):
        error = RecursionError("decoder nesting limit")
        with mock.patch.object(json, "loads", side_effect=error):
            with self.assertRaisesRegex(
                cli.ReplayInputError, "events.jsonl line 1 is not valid JSON"
            ) as caught:
                cli._read_jsonl_bytes(b"[\n", "events.jsonl")
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(
            [{"a": 1}], cli._read_jsonl_bytes(b'{"a": 1}\n', "events.jsonl")
        )

    def test_recorded_source_loader_recursion_failure_is_bounded(self):
        fixtures = recorded_fixtures.RecordedSourceTests()
        with fixtures.recording(recorded_fixtures.DECISIONS) as path:
            error = RecursionError("decoder nesting limit")
            with mock.patch.object(json, "loads", side_effect=error):
                with self.assertRaisesRegex(
                    cli.ReplayInputError,
                    "recorded source or sidecar is not readable JSON",
                ) as caught:
                    cli._load_recorded_source(str(path))
            self.assertIs(caught.exception.__cause__, error)

    def test_recorded_manifest_recursion_failure_is_indeterminate(self):
        fixtures = recorded_fixtures.RecordedSourceTests()
        with fixtures.recording(recorded_fixtures.DECISIONS) as path:
            with mock.patch.object(json, "loads", side_effect=RecursionError):
                result = RecordedDecisionSource(path).evaluate(recorded_fixtures.EVENTS)
        self.assertFalse(result.is_valid)
        self.assertEqual(["indeterminate", "indeterminate"], fixtures.effects(result))
        self.assertEqual(["recording-manifest-invalid"], fixtures.failure_codes(result))
        self.assertEqual(
            "Recorded manifest is invalid: RecursionError.", result.failures[0].message
        )

    def test_recorded_decision_recursion_failure_keeps_later_valid_decision(self):
        fixtures = recorded_fixtures.RecordedSourceTests()
        payload = "[" * 10000
        real_loads = json.loads

        def decode(value, *args, **kwargs):
            # Decoder recursion behavior varies across Python versions.
            if value == payload:
                raise RecursionError("decoder nesting limit")
            return real_loads(value, *args, **kwargs)

        with fixtures.recording([payload, recorded_fixtures.DECISIONS[1]]) as path:
            with mock.patch.object(json, "loads", side_effect=decode):
                result = RecordedDecisionSource(path).evaluate(recorded_fixtures.EVENTS)
        self.assertFalse(result.is_valid)
        self.assertEqual(["indeterminate", "allow"], fixtures.effects(result))
        self.assertEqual(
            ["recording-json-invalid", "recording-missing-event"],
            fixtures.failure_codes(result),
        )
        self.assertEqual(
            "Recorded decision line 1 is invalid JSON.", result.failures[0].message
        )
        self.assertNotIn(payload, str(result))

    def test_process_integer_limit_failure_publishes_reports_and_exits_three(self):
        fixtures = cli_fixtures.CliTests()
        with fixtures.fixture("same") as (directory, corpus, recording, candidate):
            marker = directory / "launches.txt"
            candidate.write_text(
                "from pathlib import Path\n"
                f"with Path({str(marker)!r}).open('a', encoding='utf-8') as log:\n"
                "    log.write('launch\\n')\n"
                "print('9' * 5000)\n"
                f"print({json.dumps(cli_fixtures.BASELINE[1])!r})\n",
                encoding="utf-8",
            )
            output = directory / "decoder-report"
            # Tighten only this child interpreter's limit. Do not disable/raise
            # production limits or depend on the host's ambient setting.
            completed = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "int_max_str_digits=640",
                    "-m",
                    "replay_v0.cli",
                    *fixtures.replay_args(corpus, recording, candidate, output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(3, completed.returncode, completed.stderr)
            self.assertEqual("", completed.stderr)
            self.assertEqual("launch\n", marker.read_text("utf-8"))
            self.assertEqual(
                {"report.json", "report.md", "run-manifest.json"},
                {path.name for path in output.iterdir()},
            )
            report = json.loads((output / "report.json").read_text("utf-8"))
            self.assertEqual("error", report["gate"]["status"])
            failures = report["source_failures"]["candidate"]
            self.assertEqual(
                ["process-json-invalid", "process-missing-event"],
                [failure["code"] for failure in failures],
            )
            self.assertIn("decision line 1 is invalid JSON", failures[0]["message"])
            self.assertNotIn("9999999999", json.dumps(report))
            self.assertEqual(1, report["counts"]["unchanged"])
            self.assertEqual(1, report["counts"]["newly-indeterminate"])

    def test_recorded_integer_limit_failure_keeps_later_valid_decision(self):
        script = """
import json
from replay_v0.tests.unit import test_recorded_source as fixtures
from replay_v0.policy_sources import RecordedDecisionSource
with fixtures.RecordedSourceTests().recording(["9" * 5000, fixtures.DECISIONS[1]]) as path:
    result = RecordedDecisionSource(path).evaluate(fixtures.EVENTS)
print(json.dumps({
    "valid": result.is_valid,
    "effects": [row["effect"] for row in result.decisions],
    "codes": [failure.code for failure in result.failures],
    "messages": [failure.message for failure in result.failures],
}))
"""
        completed = subprocess.run(
            [sys.executable, "-X", "int_max_str_digits=640", "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("", completed.stderr)
        result = json.loads(completed.stdout)
        self.assertFalse(result["valid"])
        self.assertEqual(["indeterminate", "allow"], result["effects"])
        self.assertEqual(
            ["recording-json-invalid", "recording-missing-event"], result["codes"]
        )
        self.assertIn("decision line 1 is invalid JSON", result["messages"][0])
        self.assertNotIn("9999999999", completed.stdout)


if __name__ == "__main__":
    unittest.main()
