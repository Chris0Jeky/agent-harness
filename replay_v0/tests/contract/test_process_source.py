from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from replay_v0.policy_sources import ProcessDecisionSource

EVENTS = [
    {
        "schema_version": "command-event.v1",
        "event_id": "git-force-main-001",
        "timestamp": "2026-07-30T12:00:00Z",
        "command": "git push origin main --force",
        "cwd": "/fictional/shop-api",
        "source": "synthetic",
    },
    {
        "schema_version": "command-event.v1",
        "event_id": "git-status-001",
        "timestamp": "2026-07-30T12:01:00Z",
        "command": "git status --short",
        "cwd": "/fictional/shop-api",
        "source": "synthetic",
    },
]

FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "process_policies" / "fixture_policy.py"
)


class ProcessSourceTests(unittest.TestCase):
    def evaluate(self, mode: str, *, timeout_seconds: float = 5.0):
        source = ProcessDecisionSource(
            [sys.executable, str(FIXTURE), mode], timeout_seconds=timeout_seconds
        )
        return source.evaluate(EVENTS)

    def test_success_is_ordered_and_keeps_stderr_diagnostic(self) -> None:
        result = self.evaluate("success")
        self.assertTrue(result.is_valid)
        self.assertEqual(["deny", "allow"], self.effects(result))
        self.assertEqual(
            ["git-force-main-001", "git-status-001"],
            [decision["event_id"] for decision in result.decisions],
        )
        self.assertEqual(("synthetic diagnostic",), result.diagnostics)

    def test_invocation_is_an_argv_list_without_a_shell(self) -> None:
        with mock.patch(
            "replay_v0.policy_sources.subprocess.run", wraps=subprocess.run
        ) as run:
            result = self.evaluate("success")
        self.assertTrue(result.is_valid)
        self.assertIsInstance(run.call_args.args[0], list)
        self.assertIs(run.call_args.kwargs["shell"], False)

    def test_nonzero_exit_keeps_valid_output_and_fills_missing_decision(self) -> None:
        result = self.evaluate("nonzero")
        self.assertEqual(["deny", "indeterminate"], self.effects(result))
        self.assertEqual(
            ["process-exit-nonzero", "process-missing-event"],
            self.failure_codes(result),
        )

    def test_timeout_makes_all_decisions_indeterminate(self) -> None:
        result = self.evaluate("timeout", timeout_seconds=0.05)
        self.assertEqual(["indeterminate", "indeterminate"], self.effects(result))
        self.assertEqual(["process-timeout"], self.failure_codes(result))

    def test_malformed_output_does_not_hide_later_valid_decision(self) -> None:
        result = self.evaluate("malformed")
        self.assertEqual(["indeterminate", "allow"], self.effects(result))
        self.assertEqual(
            ["process-json-invalid", "process-missing-event"],
            self.failure_codes(result),
        )

    def test_duplicate_json_key_is_invalid_and_fails_closed(self) -> None:
        line = (
            '{"schema_version":"policy-decision.v1",'
            '"event_id":"git-force-main-001","effect":"allow",'
            '"effect":"deny","reason":"ambiguous"}\n'
        )
        completed = subprocess.CompletedProcess(
            args=[sys.executable], returncode=0, stdout=line.encode(), stderr=b""
        )
        source = ProcessDecisionSource([sys.executable])
        with mock.patch(
            "replay_v0.policy_sources.subprocess.run", return_value=completed
        ):
            result = source.evaluate(EVENTS)

        self.assertEqual(["indeterminate", "indeterminate"], self.effects(result))
        self.assertEqual(
            [
                "process-json-invalid",
                "process-missing-event",
                "process-missing-event",
            ],
            self.failure_codes(result),
        )

    def test_duplicate_event_is_untrustworthy(self) -> None:
        result = self.evaluate("duplicate")
        self.assertEqual(["indeterminate", "allow"], self.effects(result))
        self.assertEqual(["process-duplicate-event"], self.failure_codes(result))

    def test_partial_output_fills_missing_decision(self) -> None:
        result = self.evaluate("partial")
        self.assertEqual(["deny", "indeterminate"], self.effects(result))
        self.assertEqual(["process-missing-event"], self.failure_codes(result))

    def test_reordered_output_fails_closed(self) -> None:
        result = self.evaluate("reversed")
        self.assertEqual(["indeterminate", "indeterminate"], self.effects(result))
        self.assertEqual(["process-order-invalid"], self.failure_codes(result))

    def test_rejects_shell_command_strings_and_invalid_timeouts(self) -> None:
        with self.assertRaises(ValueError):
            ProcessDecisionSource(f"{sys.executable} {FIXTURE} success")
        with self.assertRaises(ValueError):
            ProcessDecisionSource([sys.executable], timeout_seconds=0)

    @staticmethod
    def effects(result) -> list[str]:
        return [decision["effect"] for decision in result.decisions]

    @staticmethod
    def failure_codes(result) -> list[str]:
        return [failure.code for failure in result.failures]


if __name__ == "__main__":
    unittest.main()
