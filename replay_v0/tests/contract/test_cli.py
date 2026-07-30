from __future__ import annotations

from contextlib import contextmanager, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from replay_v0.cli import _load_process_source, main
from replay_v0.manifests import (
    build_corpus_manifest,
    build_run_manifest,
    manifest_json_bytes,
)

EVENTS = [
    {
        "schema_version": "command-event.v1",
        "event_id": "force-main",
        "timestamp": "2026-07-30T12:00:00Z",
        "command": "git push origin main --force",
        "source": "synthetic",
    },
    {
        "schema_version": "command-event.v1",
        "event_id": "status",
        "timestamp": "2026-07-30T12:01:00Z",
        "command": "git status --short",
        "source": "synthetic",
    },
]
CASES = [
    {
        "schema_version": "charter-case.v1",
        "event_id": "force-main",
        "case_class": "dangerous",
        "case_family": "shared-history-rewrite",
        "rationale": "A force push can rewrite shared history.",
        "provenance": "synthetic",
    },
    {
        "schema_version": "charter-case.v1",
        "event_id": "status",
        "case_class": "benign",
        "case_family": "read-only-git",
        "rationale": "Status reads repository state.",
        "provenance": "synthetic",
    },
]
BASELINE = [
    {
        "schema_version": "policy-decision.v1",
        "event_id": "force-main",
        "effect": "deny",
        "reason": "The fixture baseline denied a force push.",
    },
    {
        "schema_version": "policy-decision.v1",
        "event_id": "status",
        "effect": "allow",
        "reason": "The fixture baseline allowed status.",
    },
]


def jsonl_bytes(values) -> bytes:
    return "".join(
        f"{json.dumps(value, sort_keys=True, separators=(',', ':'))}\n"
        for value in values
    ).encode("utf-8")


class CliTests(unittest.TestCase):
    @contextmanager
    def fixture(self, mode: str):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            corpus = directory / "corpus"
            corpus.mkdir()
            (corpus / "events.jsonl").write_bytes(jsonl_bytes(EVENTS))
            (corpus / "cases.jsonl").write_bytes(jsonl_bytes(CASES))
            corpus_manifest = build_corpus_manifest(
                corpus_id="charter-v0.1",
                event_count=len(EVENTS),
                base_directory=corpus,
                files=["events.jsonl", "cases.jsonl"],
            )
            (corpus / "corpus-manifest.json").write_bytes(
                manifest_json_bytes(corpus_manifest)
            )

            recording = directory / "baseline.jsonl"
            decision_bytes = jsonl_bytes(BASELINE)
            recording.write_bytes(decision_bytes)
            sidecar = {
                "schema_version": "recorded-policy-manifest.v1",
                "policy_id": "floor-v1-final",
                "policy_commit": "0" * 40,
                "decisions_file": recording.name,
                "decisions_sha256": hashlib.sha256(decision_bytes).hexdigest(),
                "decision_count": len(BASELINE),
            }
            Path(f"{recording}.manifest.json").write_bytes(manifest_json_bytes(sidecar))

            candidate = directory / f"candidate_{mode}.py"
            candidate.write_text(
                self.policy_script(mode), encoding="utf-8", newline="\n"
            )
            yield directory, corpus, recording, candidate

    @staticmethod
    def policy_script(mode: str) -> str:
        return f"""import json
import sys

events = [json.loads(line) for line in sys.stdin if line.strip()]
for index, event in enumerate(events):
    effect = "deny" if "--force" in event["command"] else "allow"
    if {mode!r} == "regression" and index == 0:
        effect = "allow"
    print(json.dumps({{
        "schema_version": "policy-decision.v1",
        "event_id": event["event_id"],
        "effect": effect,
        "reason": "Synthetic CLI candidate returned " + effect + ".",
    }}, sort_keys=True, separators=(",", ":")))
    if {mode!r} == "failure" and index == 0:
        raise SystemExit(9)
"""

    @staticmethod
    def replay_args(corpus: Path, recording: Path, candidate: Path, output: Path):
        return [
            "replay",
            "--baseline",
            f"recorded:{recording}",
            "--candidate",
            f"process:{sys.executable},{candidate}",
            "--corpus",
            str(corpus / "events.jsonl"),
            "--output",
            str(output),
        ]

    def test_exit_zero_writes_all_reports_for_a_clean_comparison(self) -> None:
        with self.fixture("same") as (directory, corpus, recording, candidate):
            output = directory / "clean-report"
            with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
                exit_code = main(self.replay_args(corpus, recording, candidate, output))
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(0, exit_code)
            self.assertEqual("pass", report["gate"]["status"])
            self.assertEqual("1970-01-01T00:00:00Z", report["generated_at"])
            self.assertEqual(2, report["counts"]["unchanged"])
            self.assertNotIn("reproduction_command", report)
            self.assertTrue((output / "report.md").is_file())
            self.assertTrue((output / "run-manifest.json").is_file())

    def test_exit_one_writes_reports_before_returning_regression(self) -> None:
        with self.fixture("regression") as (
            directory,
            corpus,
            recording,
            candidate,
        ):
            output = directory / "regression-report"
            exit_code = main(self.replay_args(corpus, recording, candidate, output))
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(1, exit_code)
            self.assertEqual("fail", report["gate"]["status"])
            self.assertEqual(["newly-allowed"], report["gate"]["triggered"])
            self.assertNotIn("reproduction_command", report)
            markdown = (output / "report.md").read_text(encoding="utf-8")
            self.assertIn("python -m replay_v0.cli replay", markdown)
            self.assertIn(str(output), markdown)
            self.assertTrue((output / "run-manifest.json").is_file())

    def test_exit_two_rejects_a_digest_mismatch_without_policy_execution(self) -> None:
        with self.fixture("same") as (directory, corpus, recording, candidate):
            (corpus / "events.jsonl").write_bytes(b"changed\n")
            output = directory / "invalid-report"
            exit_code = main(self.replay_args(corpus, recording, candidate, output))
            self.assertEqual(2, exit_code)
            self.assertFalse(output.exists())

    def test_exit_two_rejects_an_empty_corpus_before_loading_policies(self) -> None:
        with self.fixture("same") as (directory, corpus, recording, candidate):
            (corpus / "events.jsonl").write_bytes(b"")
            (corpus / "cases.jsonl").write_bytes(b"")
            empty_sha256 = hashlib.sha256(b"").hexdigest()
            manifest = {
                "schema_version": "corpus-manifest.v1",
                "corpus_id": "empty-v0",
                "event_count": 0,
                "files": [
                    {"path": "events.jsonl", "sha256": empty_sha256},
                    {"path": "cases.jsonl", "sha256": empty_sha256},
                ],
            }
            (corpus / "corpus-manifest.json").write_bytes(
                manifest_json_bytes(manifest)
            )
            output = directory / "empty-report"
            with mock.patch(
                "replay_v0.cli._load_policy_source",
                side_effect=AssertionError("policy source loaded"),
            ) as load_policy:
                exit_code = main(
                    self.replay_args(corpus, recording, candidate, output)
                )

            self.assertEqual(2, exit_code)
            load_policy.assert_not_called()
            self.assertFalse(output.exists())

    def test_invalid_recording_is_rejected_before_process_execution(self) -> None:
        with self.fixture("same") as (directory, corpus, recording, candidate):
            invalid = [{**BASELINE[0], "effect": "warn"}, BASELINE[1]]
            decision_bytes = jsonl_bytes(invalid)
            recording.write_bytes(decision_bytes)
            sidecar_path = Path(f"{recording}.manifest.json")
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            sidecar["decisions_sha256"] = hashlib.sha256(decision_bytes).hexdigest()
            sidecar_path.write_bytes(manifest_json_bytes(sidecar))
            output = directory / "invalid-recording-report"
            with mock.patch(
                "replay_v0.cli.ProcessDecisionSource.evaluate",
                side_effect=AssertionError("process policy executed"),
            ):
                exit_code = main(self.replay_args(corpus, recording, candidate, output))
            self.assertEqual(2, exit_code)
            self.assertFalse(output.exists())

    def test_exit_three_writes_reports_for_process_failure(self) -> None:
        with self.fixture("failure") as (
            directory,
            corpus,
            recording,
            candidate,
        ):
            output = directory / "failure-report"
            exit_code = main(self.replay_args(corpus, recording, candidate, output))
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(3, exit_code)
            self.assertEqual("error", report["gate"]["status"])
            self.assertEqual(
                ["process-exit-nonzero", "process-missing-event"],
                [failure["code"] for failure in report["source_failures"]["candidate"]],
            )
            self.assertTrue((output / "report.md").is_file())
            self.assertTrue((output / "run-manifest.json").is_file())

    def test_output_publication_failure_restores_the_previous_report_set(self) -> None:
        with self.fixture("same") as (directory, corpus, recording, candidate):
            output = directory / "existing-report"
            output.mkdir()
            previous = {
                "run-manifest.json": b'{"old":"manifest"}\n',
                "report.json": b'{"old":"report"}\n',
                "report.md": b"old report\n",
            }
            for name, content in previous.items():
                (output / name).write_bytes(content)

            original_replace = Path.replace

            def reject_locked_report(path, target):
                if path == output / "report.json":
                    raise PermissionError("synthetic locked report")
                return original_replace(path, target)

            stderr = io.StringIO()
            with mock.patch.object(
                Path, "replace", autospec=True, side_effect=reject_locked_report
            ), redirect_stderr(stderr):
                exit_code = main(self.replay_args(corpus, recording, candidate, output))

            self.assertEqual(3, exit_code)
            self.assertIn("replay output failed", stderr.getvalue())
            self.assertEqual(
                previous,
                {name: (output / name).read_bytes() for name in previous},
            )
            self.assertFalse(list(directory.glob(".replay-output-*")))

    def test_timeout_changes_process_identity_and_run_id(self) -> None:
        with self.fixture("same") as (directory, corpus, recording, candidate):
            normal_output = directory / "normal-report"
            normal_exit = main(
                self.replay_args(corpus, recording, candidate, normal_output)
            )
            timeout_output = directory / "timeout-report"
            timeout_args = self.replay_args(
                corpus, recording, candidate, timeout_output
            )
            timeout_args.extend(["--timeout", "0.000001"])
            timeout_exit = main(timeout_args)

            normal_report = json.loads(
                (normal_output / "report.json").read_text(encoding="utf-8")
            )
            timeout_report = json.loads(
                (timeout_output / "report.json").read_text(encoding="utf-8")
            )

        self.assertEqual(0, normal_exit)
        self.assertEqual(3, timeout_exit)
        self.assertEqual("pass", normal_report["gate"]["status"])
        self.assertEqual("error", timeout_report["gate"]["status"])
        self.assertNotEqual(normal_report["run_id"], timeout_report["run_id"])

    def test_fail_on_accepts_only_the_three_supported_classes(self) -> None:
        with self.fixture("same") as (directory, corpus, recording, candidate):
            args = self.replay_args(corpus, recording, candidate, directory / "report")
            args.extend(["--fail-on", "resolved-indeterminate"])
            with self.assertRaises(SystemExit) as raised:
                main(args)
            self.assertEqual(2, raised.exception.code)

    def test_process_executable_and_invocation_are_bound_without_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            policy = directory / "candidate.py"
            policy.write_text("pass\n", encoding="utf-8", newline="\n")
            first_executable = directory / "first.exe"
            second_executable = directory / "second.exe"
            first_executable.write_bytes(b"first synthetic executable")
            second_executable.write_bytes(b"second synthetic executable")
            first = _load_process_source(f"{first_executable},{policy}", 1.0)
            second = _load_process_source(f"{second_executable},{policy}", 1.0)
            with_flag = _load_process_source(
                f"{first_executable},--isolated,{policy}", 1.0
            )
            with_longer_timeout = _load_process_source(
                f"{first_executable},{policy}", 2.0
            )

        self.assertNotEqual(first.identity["sha256"], second.identity["sha256"])
        self.assertNotEqual(first.identity["sha256"], with_flag.identity["sha256"])
        self.assertNotEqual(
            first.identity["sha256"], with_longer_timeout.identity["sha256"]
        )
        self.assertEqual({"kind", "id", "sha256"}, set(first.identity))
        self.assertNotIn(raw_directory, json.dumps(first.identity))

        common = {
            "generated_at": "2026-07-30T12:00:00Z",
            "baseline": {
                "kind": "recorded",
                "id": "baseline",
                "sha256": "1" * 64,
            },
            "corpus": {
                "id": "charter-v0.1",
                "manifest_sha256": "2" * 64,
                "event_count": 1,
            },
            "fail_on": ["newly-allowed"],
        }
        first_manifest = build_run_manifest(candidate=first.identity, **common)
        second_manifest = build_run_manifest(candidate=second.identity, **common)
        longer_timeout_manifest = build_run_manifest(
            candidate=with_longer_timeout.identity, **common
        )
        self.assertNotEqual(first_manifest["run_id"], second_manifest["run_id"])
        self.assertNotEqual(first_manifest["run_id"], longer_timeout_manifest["run_id"])

    def test_process_policy_parent_tree_changes_identity_and_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            policy = directory / "policy.py"
            helper = directory / "rules.py"
            policy.write_text(
                "import json\n"
                "import sys\n"
                "from rules import EFFECT\n"
                "for event in map(json.loads, sys.stdin):\n"
                '    print(json.dumps({"schema_version": "policy-decision.v1", '
                '"event_id": event["event_id"], "effect": EFFECT, '
                '"reason": "Sibling rule."}))\n',
                encoding="utf-8",
                newline="\n",
            )
            helper.write_text('EFFECT = "deny"\n', encoding="utf-8", newline="\n")
            denied = _load_process_source(f"{sys.executable},{policy}", 5.0)
            denied_result = denied.source.evaluate(EVENTS)

            helper.write_text('EFFECT = "allow"\n', encoding="utf-8", newline="\n")
            allowed = _load_process_source(f"{sys.executable},{policy}", 5.0)
            allowed_result = allowed.source.evaluate(EVENTS)

        self.assertEqual(
            ["deny", "deny"], [row["effect"] for row in denied_result.decisions]
        )
        self.assertEqual(
            ["allow", "allow"], [row["effect"] for row in allowed_result.decisions]
        )
        self.assertNotEqual(denied.identity["sha256"], allowed.identity["sha256"])

        common = {
            "generated_at": "2026-07-30T12:00:00Z",
            "baseline": {
                "kind": "recorded",
                "id": "baseline",
                "sha256": "1" * 64,
            },
            "corpus": {
                "id": "charter-v0.1",
                "manifest_sha256": "2" * 64,
                "event_count": len(EVENTS),
            },
            "fail_on": ["newly-allowed"],
        }
        denied_manifest = build_run_manifest(candidate=denied.identity, **common)
        allowed_manifest = build_run_manifest(candidate=allowed.identity, **common)
        self.assertNotEqual(denied_manifest["run_id"], allowed_manifest["run_id"])

    @unittest.skipIf(os.name == "nt", "Windows has no portable POSIX execute bits")
    def test_process_helper_executable_bits_change_identity_and_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            policy = directory / "policy.py"
            helper = directory / "helper"
            policy.write_text("pass\n", encoding="utf-8", newline="\n")
            helper.write_bytes(b"#!/bin/sh\nexit 0\n")
            os.chmod(helper, 0o644)
            non_executable = _load_process_source(f"{sys.executable},{policy}", 5.0)

            os.chmod(helper, 0o755)
            executable = _load_process_source(f"{sys.executable},{policy}", 5.0)

        self.assertNotEqual(
            non_executable.identity["sha256"], executable.identity["sha256"]
        )
        common = {
            "generated_at": "2026-07-30T12:00:00Z",
            "baseline": {
                "kind": "recorded",
                "id": "baseline",
                "sha256": "1" * 64,
            },
            "corpus": {
                "id": "charter-v0.1",
                "manifest_sha256": "2" * 64,
                "event_count": len(EVENTS),
            },
            "fail_on": ["newly-allowed"],
        }
        non_executable_manifest = build_run_manifest(
            candidate=non_executable.identity, **common
        )
        executable_manifest = build_run_manifest(
            candidate=executable.identity, **common
        )
        self.assertNotEqual(
            non_executable_manifest["run_id"], executable_manifest["run_id"]
        )

    @unittest.skipIf(os.name == "nt", "Windows has no portable POSIX execute bits")
    def test_process_executable_bits_change_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            executable_directory = directory / "bin"
            policy_directory = directory / "policy"
            executable_directory.mkdir()
            policy_directory.mkdir()
            executable = executable_directory / "python-copy"
            policy = policy_directory / "policy.py"
            shutil.copy2(sys.executable, executable)
            policy.write_text("pass\n", encoding="utf-8", newline="\n")
            os.chmod(executable, 0o755)
            executable_identity = _load_process_source(
                f"{executable},{policy}", 5.0
            ).identity

            os.chmod(executable, 0o644)
            non_executable_identity = _load_process_source(
                f"{executable},{policy}", 5.0
            ).identity

        self.assertNotEqual(
            executable_identity["sha256"], non_executable_identity["sha256"]
        )

    @unittest.skipIf(os.name == "nt", "Windows has no portable POSIX execute bits")
    def test_process_helper_mode_is_revalidated_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            policy = directory / "policy.py"
            helper = directory / "helper"
            policy.write_text("pass\n", encoding="utf-8", newline="\n")
            helper.write_bytes(b"#!/bin/sh\nexit 0\n")
            os.chmod(helper, 0o644)
            loaded = _load_process_source(f"{sys.executable},{policy}", 5.0)

            os.chmod(helper, 0o755)
            with mock.patch("replay_v0.policy_sources.subprocess.run") as process_run:
                result = loaded.source.evaluate(EVENTS)

        process_run.assert_not_called()
        self.assertEqual(
            ["process-input-changed"],
            [failure.code for failure in result.failures],
        )
        self.assertEqual(
            ["indeterminate", "indeterminate"],
            [decision["effect"] for decision in result.decisions],
        )

    def test_process_policy_tree_is_revalidated_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            policy = directory / "policy.py"
            helper = directory / "rules.py"
            policy.write_text(
                "import json\n"
                "import sys\n"
                "from rules import EFFECT\n"
                "for event in map(json.loads, sys.stdin):\n"
                '    print(json.dumps({"schema_version": "policy-decision.v1", '
                '"event_id": event["event_id"], "effect": EFFECT, '
                '"reason": "Sibling rule."}))\n',
                encoding="utf-8",
                newline="\n",
            )
            helper.write_text('EFFECT = "deny"\n', encoding="utf-8", newline="\n")
            loaded = _load_process_source(f"{sys.executable},{policy}", 5.0)

            helper.write_text('EFFECT = "allow"\n', encoding="utf-8", newline="\n")
            result = loaded.source.evaluate(EVENTS)

        self.assertEqual(
            ["process-input-changed"],
            [failure.code for failure in result.failures],
        )
        self.assertEqual(
            ["indeterminate", "indeterminate"],
            [decision["effect"] for decision in result.decisions],
        )

    def test_process_policy_symlink_keeps_supplied_parent_and_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            target_parent = directory / "target"
            supplied_parent = directory / "supplied"
            target_parent.mkdir()
            supplied_parent.mkdir()
            target = target_parent / "real.py"
            target.write_text("pass\n", encoding="utf-8", newline="\n")
            supplied = supplied_parent / "selected.py"
            try:
                supplied.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            loaded = _load_process_source(f"{sys.executable},{supplied}", 1.0)

        self.assertEqual(str(supplied_parent.absolute()), loaded.source.cwd)
        self.assertEqual("selected.py", loaded.source.argv[-1])

    def test_process_policy_runtime_uses_lexical_path_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            target_parent = directory / "target"
            supplied_parent = directory / "supplied"
            target_parent.mkdir()
            supplied_parent.mkdir()
            target = target_parent / "real.py"
            supplied = supplied_parent / "selected.py"
            target.write_text("pass\n", encoding="utf-8", newline="\n")
            supplied.write_text("pass\n", encoding="utf-8", newline="\n")
            original_resolve = Path.resolve

            def redirected_resolve(path, *args, **kwargs):
                if path == supplied:
                    return target
                return original_resolve(path, *args, **kwargs)

            with mock.patch.object(
                Path, "resolve", autospec=True, side_effect=redirected_resolve
            ):
                loaded = _load_process_source(f"{sys.executable},{supplied}", 1.0)

        self.assertEqual(str(supplied_parent.absolute()), loaded.source.cwd)
        self.assertEqual("selected.py", loaded.source.argv[-1])

    def test_validate_accepts_directory_and_rejects_changed_bytes(self) -> None:
        with self.fixture("same") as (_, corpus, _recording, _candidate):
            self.assertEqual(0, main(["validate", "--corpus", str(corpus)]))
            self.assertEqual(
                0,
                main(["validate", "--corpus", str(corpus / "corpus-manifest.json")]),
            )
            self.assertEqual(
                0, main(["validate", "--corpus", str(corpus / "events.jsonl")])
            )
            self.assertEqual(
                2, main(["validate", "--corpus", str(corpus / "cases.jsonl")])
            )
            self.assertEqual(
                2, main(["validate", "--corpus", str(corpus / "missing.jsonl")])
            )
            (corpus / "cases.jsonl").write_bytes(b"changed\n")
            self.assertEqual(2, main(["validate", "--corpus", str(corpus)]))

    def test_validate_rejects_non_lf_jsonl_with_matching_manifest(self) -> None:
        with self.fixture("same") as (_, corpus, _recording, _candidate):
            event_bytes = "\v".join(
                json.dumps(value, sort_keys=True, separators=(",", ":"))
                for value in EVENTS
            ).encode("utf-8")
            (corpus / "events.jsonl").write_bytes(event_bytes)
            corpus_manifest = build_corpus_manifest(
                corpus_id="charter-v0.1",
                event_count=len(EVENTS),
                base_directory=corpus,
                files=["events.jsonl", "cases.jsonl"],
            )
            (corpus / "corpus-manifest.json").write_bytes(
                manifest_json_bytes(corpus_manifest)
            )

            self.assertEqual(2, main(["validate", "--corpus", str(corpus)]))


if __name__ == "__main__":
    unittest.main()
