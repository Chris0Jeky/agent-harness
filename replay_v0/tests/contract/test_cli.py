from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from replay_v0.cli import main
from replay_v0.manifests import build_corpus_manifest, manifest_json_bytes

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
            self.assertIn(
                "python -m replay_v0.cli replay", report["reproduction_command"]
            )
            self.assertIn(
                report["reproduction_command"],
                (output / "report.md").read_text(encoding="utf-8"),
            )
            self.assertTrue((output / "run-manifest.json").is_file())

    def test_exit_two_rejects_a_digest_mismatch_without_policy_execution(self) -> None:
        with self.fixture("same") as (directory, corpus, recording, candidate):
            (corpus / "events.jsonl").write_bytes(b"changed\n")
            output = directory / "invalid-report"
            exit_code = main(self.replay_args(corpus, recording, candidate, output))
            self.assertEqual(2, exit_code)
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

    def test_fail_on_accepts_only_the_three_supported_classes(self) -> None:
        with self.fixture("same") as (directory, corpus, recording, candidate):
            args = self.replay_args(corpus, recording, candidate, directory / "report")
            args.extend(["--fail-on", "resolved-indeterminate"])
            with self.assertRaises(SystemExit) as raised:
                main(args)
            self.assertEqual(2, raised.exception.code)

    def test_validate_accepts_directory_and_rejects_changed_bytes(self) -> None:
        with self.fixture("same") as (_, corpus, _recording, _candidate):
            self.assertEqual(0, main(["validate", "--corpus", str(corpus)]))
            (corpus / "cases.jsonl").write_bytes(b"changed\n")
            self.assertEqual(2, main(["validate", "--corpus", str(corpus)]))


if __name__ == "__main__":
    unittest.main()
