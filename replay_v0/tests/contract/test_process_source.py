from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import replay_v0.policy_sources as policy_sources
from replay_v0.corpus import ValidationError
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

FIXTURE_COMMAND = (sys.executable, "-I", "-S", str(FIXTURE))


class ProcessSourceTests(unittest.TestCase):
    def evaluate(self, mode: str, *, timeout_seconds: float = 5.0):
        source = ProcessDecisionSource(
            [*FIXTURE_COMMAND, mode], timeout_seconds=timeout_seconds
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
            "replay_v0.policy_sources._run_policy_process",
            wraps=policy_sources._run_policy_process,
        ) as run:
            result = self.evaluate("success")
        self.assertTrue(result.is_valid)
        self.assertIsInstance(run.call_args.args[0], list)
        self.assertEqual(
            [sys.executable, "-I", "-S", str(FIXTURE)], run.call_args.args[0][:4]
        )
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_nested_fixtures_ignore_ambient_python_imports(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            sentinel = directory / "ambient-import-ran"
            (directory / "json.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('unexpected', encoding='ascii')\n"
                "raise RuntimeError('ambient module entered synthetic fixture')\n",
                encoding="utf-8",
            )
            cases = [
                "test_completed_parent_terminates_descendants_in_the_root_process_group",
            ]
            if os.name != "nt" and hasattr(os, "setpgrp"):
                cases.append(
                    "test_completed_parent_does_not_contain_a_setpgrp_descendant"
                )
            run_process = policy_sources._run_policy_process

            def fixture_environment(argv, input_bytes, **kwargs):
                # Keep the host (including the Windows wrapper) uncontaminated.
                # Only the synthetic policy and its children receive this trap.
                self.assertNotEqual(str(directory), os.environ.get("PYTHONPATH"))
                kwargs["environment"] = {
                    **os.environ,
                    **(kwargs.get("environment") or {}),
                    "PYTHONPATH": str(directory),
                }
                return run_process(argv, input_bytes, **kwargs)

            with mock.patch.object(
                policy_sources, "_run_policy_process", side_effect=fixture_environment
            ):
                for name in cases:
                    with self.subTest(case=name):
                        outcome = unittest.TestResult()
                        ProcessSourceTests(name).run(outcome)
                        self.assertEqual([], outcome.failures + outcome.errors)
            self.assertFalse(sentinel.exists())

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

    def test_timeout_keeps_the_stderr_written_before_the_deadline(self) -> None:
        # Issue #141 / review of #392: a timed-out source is still exit 3, and
        # its stderr is the only clue to why.
        result = self.evaluate("stderr-timeout", timeout_seconds=3.0)
        self.assertEqual(["process-timeout"], self.failure_codes(result))
        self.assertEqual(("synthetic stderr before the deadline",), result.diagnostics)

    def test_timeout_terminates_descendants_in_the_root_process_group(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            pid_path = Path(raw_directory) / "child.pid"
            source = ProcessDecisionSource(
                [*FIXTURE_COMMAND, "descendant-timeout", str(pid_path)],
                timeout_seconds=0.5,
            )
            started = time.monotonic()
            result = source.evaluate(EVENTS)
            elapsed = time.monotonic() - started
            child_pid, _state = self.require_child_startup(
                pid_path, pid_path.with_suffix(".json")
            )

        self.assertLess(elapsed, 2.5)
        self.assertEqual(["process-timeout"], self.failure_codes(result))
        self.assert_process_stopped(child_pid)

    def test_completed_parent_terminates_descendants_in_the_root_process_group(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            pid_path = Path(raw_directory) / "child.pid"
            source = ProcessDecisionSource(
                [*FIXTURE_COMMAND, "descendant-exit", str(pid_path)],
                timeout_seconds=2.0,
            )
            started = time.monotonic()
            result = source.evaluate(EVENTS)
            elapsed = time.monotonic() - started
            child_pid, _state = self.require_child_startup(
                pid_path, pid_path.with_suffix(".json")
            )

        self.assertLess(elapsed, 2.0)
        self.assertTrue(result.is_valid)
        self.assertEqual(["deny", "allow"], self.effects(result))
        self.assert_process_stopped(child_pid)

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "setpgrp"),
        "POSIX setpgrp semantics",
    )
    def test_completed_parent_does_not_contain_a_setpgrp_descendant(self) -> None:
        result, elapsed = self.evaluate_setpgrp_escape(
            "setpgrp-exit", timeout_seconds=2.0
        )

        self.assertLess(elapsed, 2.0)
        self.assertTrue(result.is_valid)
        self.assertEqual(["deny", "allow"], self.effects(result))

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "setpgrp"),
        "POSIX setpgrp semantics",
    )
    def test_timeout_does_not_contain_a_setpgrp_descendant(self) -> None:
        result, elapsed = self.evaluate_setpgrp_escape(
            "setpgrp-timeout", timeout_seconds=1.0
        )

        self.assertLess(elapsed, 3.0)
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
            "replay_v0.policy_sources._run_policy_process", return_value=completed
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

    def test_non_lf_record_separator_is_invalid_and_fails_closed(self) -> None:
        decisions = [
            {
                "schema_version": "policy-decision.v1",
                "event_id": event["event_id"],
                "effect": effect,
                "reason": "Synthetic separator test.",
            }
            for event, effect in zip(EVENTS, ("deny", "allow"), strict=True)
        ]
        stdout = "\v".join(
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            for value in decisions
        ).encode("utf-8")
        completed = subprocess.CompletedProcess(
            args=[sys.executable], returncode=0, stdout=stdout, stderr=b""
        )
        source = ProcessDecisionSource([sys.executable])
        with mock.patch(
            "replay_v0.policy_sources._run_policy_process", return_value=completed
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

    def test_unicode_line_separator_inside_reason_remains_one_record(self) -> None:
        decision = {
            "schema_version": "policy-decision.v1",
            "event_id": EVENTS[0]["event_id"],
            "effect": "deny",
            "reason": "first\u2028second",
        }
        completed = subprocess.CompletedProcess(
            args=[sys.executable],
            returncode=0,
            stdout=(
                json.dumps(decision, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode("utf-8"),
            stderr=b"",
        )
        source = ProcessDecisionSource([sys.executable])
        with mock.patch(
            "replay_v0.policy_sources._run_policy_process", return_value=completed
        ):
            result = source.evaluate(EVENTS[:1])

        self.assertTrue(result.is_valid)
        self.assertEqual("first\u2028second", result.decisions[0]["reason"])

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

    def test_empty_events_fail_before_snapshot_or_process_execution(self) -> None:
        source = ProcessDecisionSource([sys.executable])
        with mock.patch.object(
            source,
            "_prepare_input_snapshot",
            side_effect=AssertionError("snapshot prepared"),
        ) as prepare_snapshot, mock.patch(
            "replay_v0.policy_sources._run_policy_process",
            side_effect=AssertionError("process executed"),
        ) as process_run:
            with self.assertRaisesRegex(
                ValidationError, "CommandEvent corpus: expected at least one record"
            ):
                source.evaluate([])

        prepare_snapshot.assert_not_called()
        process_run.assert_not_called()

    @staticmethod
    def effects(result) -> list[str]:
        return [decision["effect"] for decision in result.decisions]

    @staticmethod
    def failure_codes(result) -> list[str]:
        return [failure.code for failure in result.failures]

    def evaluate_setpgrp_escape(self, mode: str, *, timeout_seconds: float):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            pid_path = directory / "child.pid"
            state_path = directory / "child.json"
            trigger_path = directory / "write-output.trigger"
            ack_path = directory / "write-output.ack"
            source = ProcessDecisionSource(
                [
                    *FIXTURE_COMMAND,
                    mode,
                    str(pid_path),
                    str(state_path),
                    str(trigger_path),
                    str(ack_path),
                ],
                timeout_seconds=timeout_seconds,
            )
            child_pid: int | None = None
            try:
                started = time.monotonic()
                result = source.evaluate(EVENTS)
                elapsed = time.monotonic() - started
                child_pid, state = self.require_child_startup(pid_path, state_path)
                self.assertEqual(child_pid, state["pid"])
                self.assertEqual(child_pid, state["pgid"])
                self.assertEqual(state["ppid"], state["sid"])
                self.assertNotEqual(child_pid, state["sid"])
                self.assertTrue(self._process_is_running(child_pid))
                trigger_path.write_text("write", encoding="ascii")
                deadline = time.monotonic() + 5
                while not ack_path.is_file():
                    if (
                        not self._process_is_running(child_pid)
                        or time.monotonic() >= deadline
                    ):
                        self.fail(
                            "escaped descendant did not observe closed capture "
                            "after replay returned"
                        )
                    time.sleep(0.01)
                self.assertEqual("capture-closed", ack_path.read_text(encoding="ascii"))
                return result, elapsed
            finally:
                if child_pid is None:
                    try:
                        child_pid = int(pid_path.read_text(encoding="ascii"))
                    except (FileNotFoundError, ValueError):
                        try:
                            child_pid = int(
                                json.loads(state_path.read_text(encoding="ascii"))[
                                    "pid"
                                ]
                            )
                        except (FileNotFoundError, KeyError, ValueError, TypeError):
                            pass
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.assert_process_stopped(child_pid)

    def require_child_startup(self, pid_path: Path, state_path: Path):
        """A parent's Popen PID alone does not show that the child initialized."""
        message = (
            "fixture-startup-unverified: child readiness was not established; "
            "no containment conclusion is available"
        )
        try:
            pid = int(pid_path.read_text(encoding="ascii"))
            state = json.loads(state_path.read_text(encoding="ascii"))
        except (OSError, ValueError):
            self.fail(message)
        self.assertGreater(pid, 0, message)
        self.assertIsInstance(state, dict, message)
        self.assertIs(type(state.get("pid")), int, message)
        self.assertEqual(pid, state["pid"], message)
        self.assertEqual(1, state.get("isolated"), message)
        self.assertIs(state.get("site_loaded"), False, message)
        return pid, state

    def assert_process_stopped(self, pid: int) -> None:
        for _attempt in range(100):
            if not self._process_is_running(pid):
                return
            time.sleep(0.01)
        self.fail(f"descendant process {pid} remained active")

    @staticmethod
    def _process_is_running(pid: int) -> bool:
        if os.name != "nt":
            proc_status = Path("/proc") / str(pid) / "stat"
            try:
                if proc_status.read_text(encoding="ascii").split()[2] in {"X", "Z"}:
                    return False
            except (FileNotFoundError, IndexError, OSError):
                pass
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            return True

        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        process = kernel32.OpenProcess(0x00100000, False, pid)
        if not process:
            return False
        try:
            return kernel32.WaitForSingleObject(process, 0) == 0x00000102
        finally:
            kernel32.CloseHandle(process)


class FixtureStartupOracleTests(unittest.TestCase):
    """Exercise the containment tests' oracle, not a substitute process runner."""

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "setpgrp"), "POSIX setpgrp semantics"
    )
    def test_capture_ack_is_published_only_after_its_contents(self) -> None:
        # Pause the real child immediately after its acknowledgement writer opens
        # the file. Publishing that pathname now lets the parent read empty bytes.
        child_code = next(
            ast.literal_eval(node.value)
            for node in ast.parse(FIXTURE.read_text(encoding="utf-8")).body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "SET_PGRP_CHILD"
                for target in node.targets
            )
        )
        program = """
from pathlib import Path
import sys, time
original_write = Path.write_text
def paused_write(path, text, *args, **kwargs):
    if text not in {"capture-closed", "wrote-after-return"}:
        return original_write(path, text, *args, **kwargs)
    with path.open("w", encoding="ascii") as stream:
        original_write(Path(sys.argv[4]), "opened", encoding="ascii")
        deadline = time.monotonic() + 5
        while not Path(sys.argv[5]).is_file():
            if time.monotonic() >= deadline:
                raise RuntimeError("acknowledgement writer was not released")
            time.sleep(0.01)
        return stream.write(text)
Path.write_text = paused_write
"""
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            state, trigger, ack, opened, release = (
                directory / name
                for name in ("state.json", "trigger", "result.ack", "opened", "release")
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    program + f"\nexec({child_code!r})\n",
                    *map(str, (state, trigger, ack, opened, release)),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            try:
                process.stdout.close()
                trigger.write_text("write", encoding="ascii")
                deadline = time.monotonic() + 5
                while not opened.is_file():
                    self.assertIsNone(process.poll(), "child failed before writing ack")
                    self.assertLess(
                        time.monotonic(), deadline, "ack writer never opened"
                    )
                    time.sleep(0.01)
                self.assertFalse(
                    ack.exists(), "ack pathname exposes incomplete contents"
                )
                release.write_text("release", encoding="ascii")
                while not ack.is_file():
                    self.assertIsNone(
                        process.poll(), "child failed before publishing ack"
                    )
                    self.assertLess(
                        time.monotonic(), deadline, "ack was never published"
                    )
                    time.sleep(0.01)
                self.assertEqual("capture-closed", ack.read_text(encoding="ascii"))
            finally:
                process.kill()
                process.wait(timeout=5)

    def assert_startup_failure(self, test_name: str, code: str) -> None:
        run_process = policy_sources._run_policy_process
        observed_timeouts = []

        def controlled_start(argv, input_bytes, **kwargs):
            # Keep the real process runner and its deadline/cleanup. Only the
            # synthetic fixture is replaced: it cannot publish child readiness.
            observed_timeouts.append(kwargs["timeout_seconds"])
            return run_process(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    code,
                    argv[argv.index(str(FIXTURE)) + 2],
                ],
                input_bytes,
                **kwargs,
            )

        outcome = unittest.TestResult()
        case = ProcessSourceTests(test_name)
        with mock.patch.object(
            policy_sources, "_run_policy_process", side_effect=controlled_start
        ):
            case.run(outcome)
        self.assertEqual(1, outcome.testsRun)
        self.assertEqual([], outcome.errors, "startup must be an explicit failure")
        self.assertEqual(1, len(outcome.failures), "missing startup is not proof")
        self.assertIn("fixture-startup-unverified", outcome.failures[0][1])
        expected = 1.0 if "setpgrp" in test_name else 0.5
        self.assertEqual([expected], observed_timeouts)

    def test_startup_requires_isolated_no_site_child(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            pid_path, state_path = directory / "child.pid", directory / "child.json"
            pid_path.write_text("123", encoding="ascii")
            case = ProcessSourceTests()
            valid = {"pid": 123, "isolated": 1, "site_loaded": False}
            state_path.write_text(json.dumps(valid), encoding="ascii")
            self.assertEqual(
                (123, valid), case.require_child_startup(pid_path, state_path)
            )
            for patch in ({"isolated": 0}, {"site_loaded": True}):
                with self.subTest(patch=patch):
                    state_path.write_text(json.dumps(valid | patch), encoding="ascii")
                    with self.assertRaisesRegex(
                        AssertionError, "fixture-startup-unverified"
                    ):
                        case.require_child_startup(pid_path, state_path)

    def test_delayed_parent_is_not_group_containment_evidence(self) -> None:
        self.assert_startup_failure(
            "test_timeout_terminates_descendants_in_the_root_process_group",
            "import time; time.sleep(10)",
        )

    @unittest.skipUnless(
        os.name != "nt" and hasattr(os, "setpgrp"), "POSIX setpgrp semantics"
    )
    def test_delayed_parent_is_not_escape_evidence(self) -> None:
        self.assert_startup_failure(
            "test_timeout_does_not_contain_a_setpgrp_descendant",
            "import time; time.sleep(10)",
        )

    def test_parent_only_pid_is_not_child_startup_evidence(self) -> None:
        self.assert_startup_failure(
            "test_timeout_terminates_descendants_in_the_root_process_group",
            "import subprocess, sys, time; from pathlib import Path; "
            "child = subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(10)']); "
            "Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii'); "
            "time.sleep(10)",
        )


class WindowsSupervisorStartupTests(unittest.TestCase):
    def test_supervisor_launch_ignores_ambient_python_imports(self) -> None:
        # Capture the real Windows launcher command before WinAPI-dependent work,
        # then exercise its Python startup on every supported test host.
        class CapturedLaunch(Exception):
            pass

        command = []

        def capture(argv, **_kwargs):
            command.extend(argv)
            raise CapturedLaunch

        kernel32 = mock.Mock()
        kernel32.CreateEventW.return_value = 2
        with (
            mock.patch.object(
                policy_sources, "_windows_kernel32", return_value=kernel32
            ),
            mock.patch.object(
                policy_sources, "_create_windows_kill_job", return_value=1
            ),
            mock.patch.object(os, "set_handle_inheritable", create=True),
            mock.patch.object(subprocess, "STARTUPINFO", create=True),
            mock.patch.object(subprocess, "Popen", side_effect=capture),
            self.assertRaises(CapturedLaunch),
        ):
            policy_sources._run_windows_policy_process(
                ["synthetic-policy"],
                stdin_stream=None,
                stdout_stream=None,
                stderr_stream=None,
                output_pipes=(),
                timeout_seconds=2.0,
                cwd=None,
                environment=None,
            )

        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            sentinel = directory / "ambient-import-ran"
            (directory / "json.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('imported', encoding='ascii')\n"
                "raise RuntimeError('ambient json entered supervisor startup')\n",
                encoding="utf-8",
            )
            environment = {**os.environ, "PYTHONPATH": str(directory)}
            control = subprocess.run(
                [sys.executable, "-S", "-c", "import json"],
                cwd=directory,
                env=environment,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertNotEqual(0, control.returncode)
            self.assertTrue(
                sentinel.is_file(), "ambient startup trap was not exercised"
            )
            sentinel.unlink()
            probe = subprocess.run(
                [
                    *command[: command.index("-c") + 1],
                    "import json, sys; print(sys.flags.isolated, 'site' in sys.modules)",
                ],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(0, probe.returncode, probe.stderr)
            self.assertEqual("1 False", probe.stdout.strip())
            self.assertFalse(sentinel.exists())

    @unittest.skipUnless(os.name == "nt", "native Windows supervisor and Job Object")
    def test_native_supervisor_ignores_host_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            sentinel = directory / "ambient-import-ran"
            (directory / "json.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('imported', encoding='ascii')\n"
                "raise RuntimeError('ambient json entered supervisor startup')\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"PYTHONPATH": str(directory)}):
                result = ProcessDecisionSource([*FIXTURE_COMMAND, "success"]).evaluate(
                    EVENTS
                )
            self.assertTrue(result.is_valid, result.failures)
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
