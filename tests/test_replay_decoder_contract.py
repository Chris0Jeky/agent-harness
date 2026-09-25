"""Integration controls for replay's JSON decoder exception boundary."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from replay_v0.tests.contract import test_cli as cli_fixtures

ROOT = Path(__file__).resolve().parents[1]


class ReplayDecoderContractTests(unittest.TestCase):
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
