"""Hook adapter: payload shape, outcome classification and recorded output."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from replay_v0 import cli as kernel
from replay_v0.corpus import validate_policy_decisions
from replay_v0.hooks import (
    ASK_EFFECTS,
    PASSTHROUGH_ENV,
    RUNTIMES,
    HookOutcome,
    HookSpec,
    HookSpecError,
    _hook_env,
    build_payload,
    classify,
    decision_record,
    effect_for,
    hook_identity,
    parse_hook_command,
    record_hook,
    run_hook,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "hooks" / "scripted_hook.py"
)


def _event(event_id: str, command: str, cwd: str | None = None) -> dict:
    event = {
        "schema_version": "command-event.v1",
        "event_id": event_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "command": command,
        "source": "synthetic",
    }
    if cwd is not None:
        event["cwd"] = cwd
    return event


class ClassifyTests(unittest.TestCase):
    def test_exit_two_blocks_with_stderr_reason(self) -> None:
        self.assertEqual(
            classify(2, "", "no thanks\n", runtime="claude"), ("deny", "no thanks")
        )

    def test_other_nonzero_exit_is_a_crash(self) -> None:
        outcome, detail = classify(1, "", "trace\nmore", runtime="claude")
        self.assertEqual(outcome, "crash")
        self.assertEqual(detail, "exit 1: trace")

    def test_silent_success_allows(self) -> None:
        self.assertEqual(classify(0, "  \n", "", runtime="claude")[0], "allow")

    def test_permission_decisions(self) -> None:
        for decision in ("allow", "deny", "ask"):
            body = json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": decision,
                        "permissionDecisionReason": "why",
                    }
                }
            )
            self.assertEqual(classify(0, body, "", runtime="claude"), (decision, "why"))

    def test_legacy_decision_field(self) -> None:
        block = json.dumps({"decision": "block", "reason": "old"})
        approve = json.dumps({"decision": "approve"})
        self.assertEqual(classify(0, block, "", runtime="claude"), ("deny", "old"))
        self.assertEqual(classify(0, approve, "", runtime="claude")[0], "allow")

    def test_continue_false_stops(self) -> None:
        body = json.dumps({"continue": False, "stopReason": "halt"})
        self.assertEqual(classify(0, body, "", runtime="claude"), ("stop", "halt"))

    def test_unreadable_replies_are_invalid_output(self) -> None:
        for body in ("not json", '{"decision": "maybe"}', "[1, 2]"):
            self.assertEqual(
                classify(0, body, "", runtime="claude")[0], "invalid-output"
            )

    def test_codex_has_no_ask(self) -> None:
        body = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                }
            }
        )
        self.assertEqual(classify(0, body, "", runtime="codex")[0], "deny")

    def test_replies_the_runtime_would_reject_are_invalid_output(self) -> None:
        missing_event = {"hookSpecificOutput": {"permissionDecision": "deny"}}
        other_event = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "permissionDecision": "deny",
            }
        }
        for value in (missing_event, other_event, {"decision": "deny"}):
            with self.subTest(value=value):
                outcome = classify(0, json.dumps(value), "", runtime="claude")[0]
                self.assertEqual(outcome, "invalid-output")


class EffectTests(unittest.TestCase):
    def test_outcomes_map_onto_the_three_effects(self) -> None:
        self.assertEqual(effect_for("allow", "deny"), "allow")
        self.assertEqual(effect_for("deny", "allow"), "deny")
        self.assertEqual(effect_for("stop", "allow"), "deny")
        self.assertEqual(effect_for("ask", "deny"), "deny")
        self.assertEqual(effect_for("ask", "allow"), "allow")
        for outcome in ("timeout", "crash", "invalid-output", "start-failed"):
            self.assertEqual(effect_for(outcome, "deny"), "indeterminate")

    def test_lone_surrogate_in_a_reason_stays_encodable(self) -> None:
        outcome = HookOutcome("deny", "bad " + chr(0xD83D), 2, 1)
        decision_record("e-2", outcome, "deny")["reason"].encode("utf-8")

    def test_reason_is_single_line_and_bounded(self) -> None:
        outcome = HookOutcome("deny", "line one\nline two " + "x" * 900, 2, 1)
        record = decision_record("e-1", outcome, "deny")
        validate_policy_decisions([record])
        self.assertLessEqual(len(record["reason"]), 500)
        self.assertTrue(record["reason"].startswith("deny: line one line two"))


class CommandParsingTests(unittest.TestCase):
    def test_json_and_word_forms(self) -> None:
        self.assertEqual(parse_hook_command('["hook", "--x"]'), ("hook", "--x"))
        self.assertEqual(parse_hook_command("hook --x 'a b'"), ("hook", "--x", "a b"))

    def test_rejects_empty_and_malformed(self) -> None:
        for value in ("", "[]", "[1]", "[", "hook 'open"):
            with self.assertRaises(HookSpecError):
                parse_hook_command(value)

    def test_missing_script_argument_is_refused(self) -> None:
        # Recording it would turn the interpreter's exit 2 into a deny for all.
        for value in ("python hooks/missing_guard.py", "node missing.js --x"):
            with self.subTest(value=value):
                with self.assertRaises(HookSpecError):
                    parse_hook_command(value)
        for value in (
            "hook --mode=a/b",
            "hook http://localhost:8080/decide",
            'python -c "print(1/2)"',
            "cmd /c hook.cmd",
        ):
            with self.subTest(value=value):
                parse_hook_command(value)

    @unittest.skipUnless(os.name == "nt", "Windows command-line splitting")
    def test_windows_backslash_paths_survive(self) -> None:
        relative = os.path.relpath(FIXTURE).replace("/", "\\")
        argv = parse_hook_command(f'python "{relative}"')
        self.assertEqual(Path(argv[1]), FIXTURE)

    def test_a_path_shaped_executable_becomes_absolute(self) -> None:
        # The hook runs from the workspace, where `./hook` would not exist.
        relative = os.path.relpath(FIXTURE)
        argv = parse_hook_command(json.dumps([relative, "--flag"]))
        self.assertEqual(Path(argv[0]), FIXTURE)
        self.assertEqual(parse_hook_command('["python"]'), ("python",))

    def test_existing_file_arguments_become_absolute(self) -> None:
        argv = parse_hook_command(f'["python", "{FIXTURE.as_posix()}"]')
        self.assertTrue(Path(argv[1]).is_absolute())

    def test_identity_ignores_directory_of_files(self) -> None:
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            for root in (one, two):
                Path(root, "hook.py").write_text("print(1)\n", encoding="utf-8")
            self.assertEqual(
                hook_identity(["python", str(Path(one, "hook.py"))]),
                hook_identity(["python", str(Path(two, "hook.py"))]),
            )


class PayloadTests(unittest.TestCase):
    def test_payload_matches_pretooluse_shape(self) -> None:
        workspace = Path(tempfile.gettempdir()) / "ws"
        payload = build_payload(
            _event("e-1", "git status", "a/../b"),
            runtime="claude",
            workspace=workspace,
            index=3,
        )
        self.assertEqual(payload["hook_event_name"], "PreToolUse")
        self.assertEqual(payload["tool_name"], "Bash")
        self.assertEqual(payload["tool_input"], {"command": "git status"})
        self.assertEqual(Path(payload["cwd"]), workspace / "a" / "b")
        self.assertEqual(payload["tool_use_id"], "replay-000003")


class ProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, command: str, timeout: float = 20.0) -> HookOutcome:
        spec = HookSpec(argv=(sys.executable, str(FIXTURE)), timeout=timeout)
        payload = build_payload(
            _event("e", command), runtime="claude", workspace=self.workspace, index=0
        )
        return run_hook(spec, payload, workspace=self.workspace)

    def test_live_outcomes(self) -> None:
        expected = {
            "exit-two": "deny",
            "json-deny": "deny",
            "json-ask": "ask",
            "json-allow": "allow",
            "legacy-block": "deny",
            "stop": "stop",
            "not-json": "invalid-output",
            "unknown-decision": "invalid-output",
            "crash": "crash",
            "anything-else": "allow",
        }
        for command, outcome in expected.items():
            with self.subTest(command=command):
                self.assertEqual(self._run(command).outcome, outcome)

    def test_timeout_is_its_own_outcome(self) -> None:
        result = self._run("slow", timeout=2.0)
        self.assertEqual(result.outcome, "timeout")
        self.assertIsNone(result.exit_code)

    def test_missing_executable_fails_to_start(self) -> None:
        spec = HookSpec(argv=("definitely-not-a-hook-binary-xyz",), timeout=5.0)
        payload = build_payload(
            _event("e", "x"), runtime="claude", workspace=self.workspace, index=0
        )
        outcome = run_hook(spec, payload, workspace=self.workspace)
        self.assertEqual(outcome.outcome, "start-failed")

    def test_record_writes_a_loadable_recorded_source(self) -> None:
        events = [
            _event("e-1", "json-deny", "project"),
            _event("e-2", "anything"),
            _event("e-3", "crash"),
        ]
        output = self.workspace / "out"
        spec = HookSpec(argv=(sys.executable, str(FIXTURE)), timeout=20.0)
        summary = record_hook(spec, events, output, policy_id="fixture", jobs=2)
        self.assertEqual(summary["outcomes"]["deny"], 1)
        self.assertEqual(summary["outcomes"]["crash"], 1)
        loaded = kernel._load_recorded_source(str(output / "decisions.jsonl"))
        result = loaded.source.evaluate(events)
        self.assertEqual(result.failures, ())
        effects = [decision["effect"] for decision in result.decisions]
        self.assertEqual(effects, ["deny", "allow", "indeterminate"])
        outcome_lines = (output / "outcomes.jsonl").read_text().splitlines()
        self.assertEqual(
            [json.loads(line)["outcome"] for line in outcome_lines],
            ["deny", "allow", "crash"],
        )


class WorkspaceScrubTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name).resolve()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_hook(self, source: str) -> str:
        hook = Path(self._tmp.name) / "echo_hook.py"
        hook.write_text(source, encoding="utf-8", newline="\n")
        return str(hook)

    def _run(self, hook_path: str) -> HookOutcome:
        spec = HookSpec(argv=(sys.executable, hook_path), timeout=20.0)
        payload = build_payload(
            _event("e", "x"), runtime="claude", workspace=self.workspace, index=0
        )
        return run_hook(spec, payload, workspace=self.workspace)

    def test_run_hook_replaces_workspace_path_with_placeholder(self) -> None:
        hook_path = self._write_hook(
            "import os, sys\n" "sys.stderr.write(os.getcwd())\n" "sys.exit(2)\n"
        )
        outcome = self._run(hook_path)
        self.assertEqual(outcome.outcome, "deny")
        self.assertEqual(outcome.exit_code, 2)
        self.assertEqual(outcome.detail, "<workspace>")
        self.assertNotIn(str(self.workspace), outcome.detail)

    def test_run_hook_leaves_a_detail_without_the_workspace_untouched(self) -> None:
        hook_path = self._write_hook(
            "import sys\n" 'sys.stderr.write("blocked-no-path")\n' "sys.exit(2)\n"
        )
        outcome = self._run(hook_path)
        self.assertEqual(outcome.outcome, "deny")
        self.assertEqual(outcome.detail, "blocked-no-path")


class HookEnvTests(unittest.TestCase):
    def test_hook_env_drops_unlisted_names_and_sets_project_dir(self) -> None:
        workspace = Path(tempfile.gettempdir()) / "ws-probe"
        with mock.patch.dict(
            os.environ,
            {"HOOK_LEAK": "secret", "PATH": "/bin", "CUSTOM_X": "1"},
            clear=True,
        ):
            env = _hook_env(workspace)
        self.assertNotIn("HOOK_LEAK", env)
        self.assertNotIn("CUSTOM_X", env)
        self.assertEqual(
            env,
            {
                "PATH": "/bin",
                "CLAUDE_PROJECT_DIR": str(workspace),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )
        allowed = set(PASSTHROUGH_ENV) | {
            "CLAUDE_PROJECT_DIR",
            "PYTHONDONTWRITEBYTECODE",
            "PYTHONIOENCODING",
        }
        self.assertLessEqual(set(env), allowed)

    def test_hook_env_empty_caller_environment_still_sets_project_dir(self) -> None:
        workspace = Path(tempfile.gettempdir()) / "ws-empty"
        with mock.patch.dict(os.environ, {}, clear=True):
            env = _hook_env(workspace)
        self.assertEqual(
            env,
            {
                "CLAUDE_PROJECT_DIR": str(workspace),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_record_manifest_pins_policy_commit_and_decisions_digest(self) -> None:
        events = [_event("e-1", "json-deny", "project"), _event("e-2", "anything")]
        output = self.root / "out"
        spec = HookSpec(argv=(sys.executable, str(FIXTURE)), timeout=20.0)
        record_hook(spec, events, output, policy_id="fixture", jobs=1)
        decisions_bytes = (output / "decisions.jsonl").read_bytes()
        manifest = json.loads(
            (output / "decisions.jsonl.manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["policy_commit"], hook_identity(spec.argv)[:40])
        self.assertEqual(len(manifest["policy_commit"]), 40)
        self.assertEqual(
            manifest["decisions_sha256"], hashlib.sha256(decisions_bytes).hexdigest()
        )
        self.assertEqual(manifest["decisions_file"], "decisions.jsonl")
        self.assertEqual(manifest["decision_count"], 2)

    def test_record_manifest_empty_events_boundary(self) -> None:
        output = self.root / "out-empty"
        spec = HookSpec(argv=(sys.executable, str(FIXTURE)), timeout=20.0)
        summary = record_hook(spec, [], output, policy_id="empty", jobs=1)
        self.assertEqual(summary["events"], 0)
        decisions_bytes = (output / "decisions.jsonl").read_bytes()
        manifest = json.loads(
            (output / "decisions.jsonl.manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["decision_count"], 0)
        self.assertEqual(
            manifest["decisions_sha256"], hashlib.sha256(decisions_bytes).hexdigest()
        )


class SpecRejectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_record_rejects_an_invalid_runtime(self) -> None:
        expected = f"runtime must be one of: {', '.join(RUNTIMES)}"
        for runtime in ("bogus", ""):
            with self.subTest(runtime=runtime):
                spec = HookSpec(argv=("hook",), runtime=runtime)
                with self.assertRaises(HookSpecError) as caught:
                    record_hook(
                        spec,
                        [_event("e-1", "x")],
                        self.root / "out",
                        policy_id="p",
                    )
                self.assertEqual(str(caught.exception), expected)

    def test_record_rejects_an_invalid_ask_effect(self) -> None:
        expected = f"ask effect must be one of: {', '.join(ASK_EFFECTS)}"
        for ask_effect in ("maybe", ""):
            with self.subTest(ask_effect=ask_effect):
                spec = HookSpec(argv=("hook",), ask_effect=ask_effect)
                with self.assertRaises(HookSpecError) as caught:
                    record_hook(
                        spec,
                        [_event("e-1", "x")],
                        self.root / "out",
                        policy_id="p",
                    )
                self.assertEqual(str(caught.exception), expected)


class IdentityTests(unittest.TestCase):
    def test_executable_contributes_its_basename_only(self) -> None:
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first = Path(one, "hookbin")
            second = Path(two, "hookbin")
            first.write_bytes(b"bytes-a")
            second.write_bytes(b"bytes-b")
            self.assertEqual(hook_identity([str(first)]), hook_identity([str(second)]))
            self.assertNotEqual(
                hook_identity([str(first)]),
                hook_identity([str(Path(one, "otherbin"))]),
            )

    def test_argument_files_contribute_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first = Path(one, "hook.py")
            second = Path(two, "hook.py")
            first.write_text("print(1)\n", encoding="utf-8", newline="\n")
            second.write_text("print(2)\n", encoding="utf-8", newline="\n")
            self.assertNotEqual(
                hook_identity(["python", str(first)]),
                hook_identity(["python", str(second)]),
            )


if __name__ == "__main__":
    unittest.main()
