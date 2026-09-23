"""Contract tests for the offline review-packet advisory reader."""

import copy
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "review_evidence.py"
HEAD = "a" * 40
BASE = "b" * 40


def packet():
    return {
        "document_kind": "authoring_template_not_execution_receipt",
        "template_version": 0,
        "execution_status": "NOT RUN",
        "identity": {"repository": "example/product", "reviewed_head_sha": HEAD},
        "planned_checks": [{"id": "persist", "oracle_class": "behavior"}],
        "observations": [],
    }


def observation(identifier="attempt-1", role="candidate", status="PASS"):
    return {
        "id": identifier,
        "check_id": "persist",
        "role": role,
        "status": status,
        "tested_revision_sha": HEAD,
        "command_or_action": "run existing persistence test",
        "environment": "isolated synthetic database",
        "actual_outcome": "The intended card survives reload.",
        "evidence_ref": "local:run-1/log.txt",
    }


class ReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "review-packet reader is not implemented")
        self.summarize = runpy.run_path(str(SCRIPT))["summarize"]

    def test_empty_template_is_not_acceptance(self):
        p = packet()
        p["identity"]["reviewed_head_sha"] = None
        report = self.summarize(p)
        self.assertEqual("UNKNOWN", report["identity_state"])
        self.assertEqual(1, report["requested_checks"])
        self.assertEqual(0, report["checks_with_candidate_observations"])
        self.assertEqual([], report["observations"])
        self.assertFalse(report["execution_verified"])
        self.assertIsNone(report["merge_verdict"])

    def test_recorded_claim_is_not_execution_verification(self):
        p = packet()
        p["execution_status"] = "RECORDED"
        p["observations"] = [observation()]
        report = self.summarize(p, expected_head=HEAD)
        self.assertEqual("MATCH", report["identity_state"])
        self.assertEqual("RECORDED", report["observations"][0]["evidence_state"])
        self.assertEqual("PASS", report["observations"][0]["reported_status"])
        self.assertFalse(report["execution_verified"])
        self.assertIsNone(report["merge_verdict"])

    def test_wrong_expected_head_is_advisory_not_a_pass(self):
        report = self.summarize(packet(), expected_head=BASE)
        self.assertEqual("MISMATCH", report["identity_state"])
        self.assertIn("reviewed_head_mismatch", report["warnings"])

    def test_missing_head_never_binds_candidate_evidence(self):
        p = packet()
        p["identity"]["reviewed_head_sha"] = None
        p["observations"] = [observation()]
        self.assertEqual("UNBOUND", self.summarize(p)["observations"][0]["evidence_state"])

    def test_other_revision_is_not_relabelled(self):
        p = packet()
        p["observations"] = [observation()]
        p["observations"][0]["tested_revision_sha"] = BASE
        row = self.summarize(p)["observations"][0]
        self.assertEqual("OTHER_REVISION", row["evidence_state"])
        self.assertEqual(BASE, row["tested_revision_sha"])

    def test_controls_may_use_other_revision_but_are_not_candidate_coverage(self):
        p = packet()
        control = observation(role="regression_control")
        control["tested_revision_sha"] = BASE
        control["actual_outcome"] = "The named defect is rejected for its intended reason."
        p["observations"] = [control]
        report = self.summarize(p)
        self.assertEqual(0, report["checks_with_candidate_observations"])
        self.assertEqual("RECORDED", report["observations"][0]["evidence_state"])

    def test_missing_actual_evidence_remains_incomplete(self):
        for field in ("command_or_action", "environment", "actual_outcome", "evidence_ref"):
            with self.subTest(field=field):
                p = packet()
                p["observations"] = [observation()]
                p["observations"][0][field] = " "
                row = self.summarize(p)["observations"][0]
                self.assertEqual("INCOMPLETE", row["evidence_state"])
                self.assertIn(field, row["missing_fields"])

    def test_failed_attempt_is_not_overwritten_by_later_pass(self):
        p = packet()
        p["observations"] = [observation("first", status="FAIL"), observation("second")]
        report = self.summarize(p)
        self.assertEqual(
            ["FAIL", "PASS"], [r["reported_status"] for r in report["observations"]]
        )
        self.assertEqual(1, report["checks_with_candidate_observations"])
        self.assertIn("mixed_candidate_outcomes:persist", report["warnings"])

    def test_blocked_not_run_and_na_are_distinct(self):
        p = packet()
        p["observations"] = [observation(s, status=s) for s in ("BLOCKED", "NOT RUN", "N/A")]
        report = self.summarize(p)
        self.assertEqual(
            ["BLOCKED", "NOT RUN", "N/A"],
            [r["reported_status"] for r in report["observations"]],
        )
        self.assertTrue(
            all(r["evidence_state"] == "NOT_EXECUTED" for r in report["observations"])
        )

    def test_declaration_contradiction_is_visible(self):
        p = packet()
        p["observations"] = [observation()]
        self.assertIn(
            "not_run_declaration_has_outcome_claims", self.summarize(p)["warnings"]
        )

    def test_duplicate_check_or_observation_ids_rejected(self):
        p = packet()
        p["planned_checks"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.summarize(p)
        p = packet()
        p["observations"] = [observation(), observation()]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.summarize(p)

    def test_unknown_check_status_role_or_version_rejected(self):
        mutations = (
            ("check_id", "unknown"),
            ("status", "LGTM"),
            ("role", "judge"),
        )
        for field, value in mutations:
            p = packet()
            p["observations"] = [observation()]
            p["observations"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.summarize(p)
        for version in (True, 1, "0", None):
            p = packet()
            p["template_version"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.summarize(p)

    def test_malformed_shapes_and_short_shas_rejected(self):
        for value in (None, [], "packet", {"template_version": 0}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.summarize(value)
        p = packet()
        p["identity"]["reviewed_head_sha"] = "abc123"
        with self.assertRaises(ValueError):
            self.summarize(p)
        p = packet()
        p["observations"] = ["PASS"]
        with self.assertRaises(ValueError):
            self.summarize(p)

    def test_no_input_mutation_and_repeatable_output(self):
        p = packet()
        p["observations"] = [observation()]
        before = copy.deepcopy(p)
        first = self.summarize(p)
        self.assertEqual(before, p)
        self.assertEqual(first, self.summarize(p))

    def test_llm_claim_cannot_create_a_gate(self):
        p = packet()
        p["planned_checks"][0]["oracle_class"] = "llm"
        p["observations"] = [observation()]
        report = self.summarize(p)
        self.assertIsNone(report["merge_verdict"])
        self.assertFalse(report["execution_verified"])


class ReviewEvidenceCLITests(unittest.TestCase):
    def invoke(self, raw, *args):
        self.assertTrue(SCRIPT.is_file(), "review-packet reader is not implemented")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.json"
            path.write_bytes(raw)
            return subprocess.run(
                [sys.executable, str(SCRIPT), str(path), *args],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

    def test_cli_exit_is_not_a_merge_verdict(self):
        for status in ("PASS", "FAIL", "BLOCKED", "NOT RUN", "N/A"):
            p = packet()
            p["observations"] = [observation(status=status)]
            proc = self.invoke(json.dumps(p).encode(), "--expected-head", BASE)
            self.assertEqual(0, proc.returncode, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertIsNone(report["merge_verdict"])
            self.assertEqual("MISMATCH", report["identity_state"])
            self.assertEqual(64, len(report["input_sha256"]))

    def test_duplicate_keys_nonfinite_bad_utf8_and_oversize_are_errors(self):
        valid = json.dumps(packet())[:-1]
        for raw in (
            (valid + ', "template_version": 0}').encode(),
            (valid + ', "extension": NaN}').encode(),
            (valid + ', "extension": Infinity}').encode(),
            (valid + ', "extension": 1e999}').encode(),
            b"\xff",
            b" " * (1024 * 1024 + 1),
            b"{",
        ):
            with self.subTest(prefix=raw[:20]):
                proc = self.invoke(raw)
                self.assertEqual(2, proc.returncode)
                self.assertEqual("", proc.stdout)
                self.assertNotIn("Traceback", proc.stderr)

    def test_commands_and_artifact_references_are_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "should-not-exist"
            p = packet()
            row = observation()
            row["command_or_action"] = f"touch {sentinel}"
            row["evidence_ref"] = "https://invalid.example/never-fetch"
            p["observations"] = [row]
            proc = self.invoke(json.dumps(p).encode())
            self.assertEqual(
                0, proc.returncode, proc.stderr
            )
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
