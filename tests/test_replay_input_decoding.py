"""Real CLI controls for invalid JSON inputs, distinct from process-output errors."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from replay_v0.tests.contract import test_cli as fixtures

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ("manifest", "sidecar", "events", "cases")


class ReplayInputDecodingTests(unittest.TestCase):
    @contextmanager
    def fixture(self, location, content=None):
        with fixtures.CliTests().fixture("same") as data:
            directory, corpus, recording, candidate = data
            marker = directory / "launched.txt"
            candidate.write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('launched', encoding='utf-8')\n"
                + fixtures.CliTests.policy_script("same"),
                encoding="utf-8",
            )
            paths = {
                "manifest": corpus / "corpus-manifest.json",
                "sidecar": Path(f"{recording}.manifest.json"),
                "events": corpus / "events.jsonl",
                "cases": corpus / "cases.jsonl",
            }
            target = paths[location]
            if content is not None:
                target.write_bytes(content)
                if location in ("events", "cases"):
                    manifest_path = paths["manifest"]
                    manifest = json.loads(manifest_path.read_bytes())
                    for entry in manifest["files"]:
                        if entry["path"] == target.name:
                            entry["sha256"] = hashlib.sha256(content).hexdigest()
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = directory / "reports"
            yield directory, corpus, recording, candidate, marker, output

    def run_cli(self, data, command="replay"):
        _directory, corpus, recording, candidate, _marker, output = data
        args = (
            fixtures.CliTests.replay_args(corpus, recording, candidate, output)
            if command == "replay"
            else ["validate", "--corpus", str(corpus)]
        )
        return subprocess.run(
            [
                sys.executable,
                "-X",
                "int_max_str_digits=640",
                "-m",
                "replay_v0.cli",
                *args,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def assert_input_invalid(self, result, data, expected_message=None):
        directory, _corpus, _recording, _candidate, marker, output = data
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertTrue(
            result.stderr.startswith("replay input invalid:"), result.stderr
        )
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("9" * 20, result.stderr)
        self.assertNotIn(str(directory), result.stderr)
        self.assertLess(len(result.stderr), 300)
        if expected_message is not None:
            self.assertIn(expected_message, result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(output.exists())

    def test_oversized_integer_inputs_exit_two_without_execution(self):
        fields = {
            "manifest": "event_count",
            "sidecar": "decision_count",
            "events": "event_id",
            "cases": "event_id",
        }
        for location in INPUTS:
            content = ('{"' + fields[location] + '":' + "9" * 5000 + "}\n").encode()
            commands = ("replay",) if location == "sidecar" else ("replay", "validate")
            for command in commands:
                with self.subTest(location=location, command=command):
                    with self.fixture(location, content) as data:
                        self.assert_input_invalid(self.run_cli(data, command), data)

    def test_json_syntax_and_utf8_errors_keep_input_invalid_contract(self):
        for location in INPUTS:
            for content in (b'{"unfinished":\n', b"\xff\n"):
                with self.subTest(location=location, content=content):
                    with self.fixture(location, content) as data:
                        self.assert_input_invalid(self.run_cli(data), data)

    def test_duplicate_key_diagnostics_are_preserved(self):
        for location in INPUTS:
            with self.subTest(location=location):
                with self.fixture(location, b'{"same":1,"same":2}\n') as data:
                    self.assert_input_invalid(self.run_cli(data), data, "duplicate")

    def test_recorded_schema_diagnostic_is_not_hidden_by_decoder_translation(self):
        with self.fixture("sidecar") as data:
            sidecar = Path(f"{data[2]}.manifest.json")
            value = json.loads(sidecar.read_bytes())
            value["decision_count"] = -1
            sidecar.write_text(json.dumps(value), encoding="utf-8")
            self.assert_input_invalid(
                self.run_cli(data), data, "RecordedPolicyManifest.decision_count"
            )

    def test_valid_fixture_still_executes_and_publishes_reports(self):
        with self.fixture("manifest") as data:
            result = self.run_cli(data)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stderr)
            self.assertEqual("launched", data[4].read_text("utf-8"))
            self.assertEqual(
                {"report.json", "report.md", "run-manifest.json"},
                {path.name for path in data[5].iterdir()},
            )
            report = json.loads((data[5] / "report.json").read_bytes())
            self.assertEqual("pass", report["gate"]["status"])

    def test_direct_recorded_source_rejects_oversized_manifest_without_traceback(self):
        content = ('{"decision_count":' + "9" * 5000 + "}\n").encode()
        with self.fixture("sidecar", content) as data:
            script = """
import json
import sys
from replay_v0.policy_sources import RecordedDecisionSource
from replay_v0.tests.contract import test_cli as fixtures
result = RecordedDecisionSource(sys.argv[1]).evaluate(fixtures.EVENTS)
print(json.dumps({
    "valid": result.is_valid,
    "effects": [row["effect"] for row in result.decisions],
    "failures": [failure.as_dict() for failure in result.failures],
}))
"""
            result = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "int_max_str_digits=640",
                    "-c",
                    script,
                    str(data[2]),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stderr)
            value = json.loads(result.stdout)
            self.assertFalse(value["valid"])
            self.assertEqual(["indeterminate", "indeterminate"], value["effects"])
            self.assertEqual(
                [
                    {
                        "code": "recording-manifest-invalid",
                        "message": "Recorded manifest is invalid: ValueError.",
                    }
                ],
                value["failures"],
            )
            self.assertNotIn("9" * 20, result.stdout)
            self.assertFalse(data[4].exists())
            self.assertFalse(data[5].exists())


if __name__ == "__main__":
    unittest.main()
