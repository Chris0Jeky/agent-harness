"""A bounded mapped-document drift probe, not a policy authority."""

import json
from pathlib import Path
import runpy
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "authority_doc_drift.py"
LINE = (
    "This repo is tier 3 (workshop) per `.agent-harness/tier.json`: "
    "push free, merge {}.\n"
)


class AuthorityDocDriftTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "bounded drift probe is not implemented")
        self.measure = runpy.run_path(str(SCRIPT))["measure"]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".agent-harness").mkdir()
        self.contract = self.root / ".agent-harness" / "tier.json"
        self.doc = self.root / "CLAUDE.md"
        self.contract.write_text(
            json.dumps({"authority": {"push": "free", "merge": "free"}}),
            encoding="utf-8",
        )
        self.doc.write_text(LINE.format("gated"), encoding="utf-8")

    def test_named_stale_clause_is_candidate_not_a_gate(self):
        report = self.measure(self.root)
        self.assertEqual(
            {"requested": 2, "inspected": 2, "candidate": 1, "unknown": 0},
            report["counts"],
        )
        self.assertEqual("candidate", report["observations"][1]["status"])
        self.assertIsNone(report["merge_verdict"])
        self.assertEqual("gated", report["observations"][1]["documented"])
        self.assertEqual("free", report["observations"][1]["declared"])
        self.assertEqual(1, report["line"])

    def test_matching_control_is_not_candidate(self):
        self.doc.write_text(LINE.format("free"), encoding="utf-8")
        self.assertEqual(0, self.measure(self.root)["counts"]["candidate"])

    def test_missing_doc_is_unknown_not_zero_debt(self):
        self.doc.unlink()
        report = self.measure(self.root)
        self.assertEqual(2, report["counts"]["unknown"])
        self.assertEqual(0, report["counts"]["inspected"])
        self.assertIsNone(report["inputs"]["CLAUDE.md"])

    def test_missing_or_renamed_clause_is_unknown(self):
        self.doc.write_text(
            "New wording; no supported mapped clause.\n", encoding="utf-8"
        )
        self.assertEqual(2, self.measure(self.root)["counts"]["unknown"])

    def test_ambiguous_clauses_are_unknown(self):
        self.doc.write_text(
            LINE.format("gated") + LINE.format("free"), encoding="utf-8"
        )
        self.assertEqual(
            "ambiguous_or_unmapped_clause", self.measure(self.root)["reason"]
        )

    def test_code_fenced_example_is_not_live_prose(self):
        self.doc.write_text(
            "```markdown\n" + LINE.format("gated") + "```\n" + LINE.format("free"),
            encoding="utf-8",
        )
        report = self.measure(self.root)
        self.assertEqual(0, report["counts"]["candidate"])
        self.assertEqual(4, report["line"])

    def test_partial_contract_preserves_denominator(self):
        self.contract.write_text('{"authority":{"push":"free"}}', encoding="utf-8")
        self.assertEqual(
            {"requested": 2, "inspected": 1, "candidate": 0, "unknown": 1},
            self.measure(self.root)["counts"],
        )

    def test_unknown_authority_value_is_not_interpreted(self):
        self.contract.write_text(
            '{"authority":{"push":true,"merge":"custom"}}', encoding="utf-8"
        )
        self.assertEqual(2, self.measure(self.root)["counts"]["unknown"])

    def test_duplicate_keys_and_malformed_contract_are_unknown(self):
        for data in (
            '{"authority":{"push":"free","push":"gated","merge":"free"}}',
            "[]",
            "{",
            '{"authority":[]}',
        ):
            self.contract.write_text(data, encoding="utf-8")
            with self.subTest(data=data):
                self.assertEqual(2, self.measure(self.root)["counts"]["unknown"])

    def test_bytes_are_identified_without_revision_attestation(self):
        report = self.measure(self.root)
        self.assertEqual(64, len(report["inputs"]["CLAUDE.md"]))
        self.assertFalse(report["revision_verified"])
        self.assertEqual(report, self.measure(self.root))

    def test_input_digests_change_but_finding_identity_is_stable(self):
        first = self.measure(self.root)
        self.doc.write_text("# Heading\n" + LINE.format("gated"), encoding="utf-8")
        second = self.measure(self.root)
        self.assertNotEqual(first["inputs"], second["inputs"])
        self.assertEqual(
            first["observations"][1]["finding_key"],
            second["observations"][1]["finding_key"],
        )

    def test_bad_utf8_and_oversize_inputs_are_unknown(self):
        for data in (b"\xff", b" " * (1024 * 1024 + 1)):
            self.doc.write_bytes(data)
            self.assertEqual(2, self.measure(self.root)["counts"]["unknown"])


if __name__ == "__main__":
    unittest.main()
