from __future__ import annotations

import sys
import subprocess
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from replay_v0 import policy_sources
from replay_v0.policy_sources import ProcessDecisionSource
from replay_v0.tests.contract.test_process_source import EVENTS, FIXTURE_COMMAND
from replay_v0.tests.contract import test_process_source as fixtures
from replay_v0.hooks import HookSpec, effect_for, run_hook


class ProcessOutputLimitTests(unittest.TestCase):
    def evaluate(self, script):
        with (
            mock.patch.object(
                policy_sources, "_PROCESS_STDOUT_LIMIT_BYTES", 8192, create=True
            ),
            mock.patch.object(
                policy_sources, "_PROCESS_STDERR_LIMIT_BYTES", 4096, create=True
            ),
        ):
            return ProcessDecisionSource(
                [sys.executable, "-I", "-S", "-c", script], timeout_seconds=2.0
            ).evaluate(EVENTS)

    def assert_output_limit(self, result):
        self.assertEqual(
            ["process-output-limit"], [failure.code for failure in result.failures]
        )
        self.assertEqual(
            ["indeterminate", "indeterminate"],
            [decision["effect"] for decision in result.decisions],
        )
        self.assertLessEqual(len("\n".join(result.diagnostics).encode("utf-8")), 4096)

    def test_stdout_and_stderr_capture_limits_fail_closed(self):
        for descriptor in (1, 2):
            with self.subTest(descriptor=descriptor):
                result = self.evaluate(
                    f"import os; os.write({descriptor}, b'x' * 65536)"
                )
                self.assert_output_limit(result)

    def test_continuous_output_is_stopped_before_timeout(self):
        started = time.monotonic()
        result = self.evaluate(
            "import os, time\n"
            "while True:\n"
            "    os.write(2, b'x' * 1024)\n"
            "    time.sleep(0.005)\n"
        )
        self.assert_output_limit(result)
        self.assertLess(time.monotonic() - started, 1.8)

    def test_ordinary_decisions_and_diagnostics_still_succeed(self):
        with (
            mock.patch.object(
                policy_sources, "_PROCESS_STDOUT_LIMIT_BYTES", 8192, create=True
            ),
            mock.patch.object(
                policy_sources, "_PROCESS_STDERR_LIMIT_BYTES", 4096, create=True
            ),
        ):
            result = ProcessDecisionSource([*FIXTURE_COMMAND, "success"]).evaluate(
                EVENTS
            )
        self.assertTrue(result.is_valid)
        self.assertEqual(("synthetic diagnostic",), result.diagnostics)

    def test_overflow_terminates_descendants_in_the_owned_process_family(self):
        with tempfile.TemporaryDirectory() as raw:
            pid_path = Path(raw) / "child.pid"
            with mock.patch.object(policy_sources, "_PROCESS_STDERR_LIMIT_BYTES", 4096):
                result = ProcessDecisionSource(
                    [*FIXTURE_COMMAND, "descendant-output-limit", str(pid_path)],
                    timeout_seconds=3.0,
                ).evaluate(EVENTS)
            oracle = fixtures.ProcessSourceTests()
            child_pid, _state = oracle.require_child_startup(
                pid_path, pid_path.with_suffix(".json")
            )
            oracle.assert_process_stopped(child_pid)
        self.assert_output_limit(result)

    def test_hook_overflow_is_an_indeterminate_output_limit(self):
        with tempfile.TemporaryDirectory() as raw:
            with mock.patch.object(policy_sources, "_PROCESS_STDERR_LIMIT_BYTES", 4096):
                outcome = run_hook(
                    HookSpec(
                        (
                            sys.executable,
                            "-I",
                            "-S",
                            "-c",
                            "import os; os.write(2, b'x'*65536)",
                        ),
                        timeout=2.0,
                    ),
                    {},
                    workspace=Path(raw),
                )
        self.assertEqual("output-limit", outcome.outcome)
        self.assertEqual("indeterminate", effect_for(outcome.outcome, "allow"))

    @unittest.skipIf(sys.platform == "win32", "POSIX process groups only")
    def test_zombie_group_permission_error_keeps_the_output_limit(self):
        with mock.patch.object(
            policy_sources.os, "killpg", side_effect=PermissionError(1, "EPERM")
        ):
            result = self.evaluate("import os; os.write(1, b'x' * 65536)")
        self.assert_output_limit(result)

    def test_capture_uses_temporary_storage_only_for_stdin(self):
        with mock.patch.object(
            policy_sources.tempfile, "TemporaryFile", wraps=tempfile.TemporaryFile
        ) as storage:
            result = self.evaluate("import os; os.write(1, b'x' * 65536)")
        self.assert_output_limit(result)
        self.assertEqual(1, storage.call_count)

    def test_exact_stdout_quota_keeps_valid_decisions(self):
        output = "".join(
            json.dumps(
                {
                    "schema_version": "policy-decision.v1",
                    "event_id": event["event_id"],
                    "effect": "allow",
                    "reason": "ordinary",
                }
            )
            + "\n"
            for event in EVENTS
        )
        with mock.patch.object(
            policy_sources, "_PROCESS_STDOUT_LIMIT_BYTES", len(output.encode("utf-8"))
        ):
            result = ProcessDecisionSource(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    f"import os; os.write(1, {output.encode('utf-8')!r})",
                ]
            ).evaluate(EVENTS)
        self.assertTrue(result.is_valid)

    def test_final_drain_has_a_time_budget_without_waiting_for_eof(self):
        for timed_out, error in (
            (False, policy_sources.ProcessOutputLimitError),
            (True, subprocess.TimeoutExpired),
        ):
            with self.subTest(timed_out=timed_out):
                turns = 0

                def continuously_available(_pipe):
                    nonlocal turns
                    turns += 1
                    return turns < 100

                with (
                    mock.patch.object(
                        policy_sources,
                        "_run_windows_policy_process",
                        return_value=(0, timed_out),
                    ),
                    mock.patch.object(
                        policy_sources,
                        "_run_posix_policy_process",
                        return_value=(0, timed_out),
                    ),
                    mock.patch.object(
                        policy_sources._BoundedOutputPipe,
                        "drain",
                        continuously_available,
                    ),
                    mock.patch.object(
                        policy_sources.time, "monotonic", side_effect=[0.0, 0.5, 1.0]
                    ),
                ):
                    with self.assertRaises(error):
                        policy_sources._run_policy_process(
                            ["fictional-policy"],
                            b"",
                            timeout_seconds=2,
                            cwd=None,
                            environment=None,
                        )
