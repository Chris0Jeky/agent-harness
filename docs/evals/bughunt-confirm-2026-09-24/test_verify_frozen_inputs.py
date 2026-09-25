"""Synthetic controls only; none of these tests authenticate the missing pack."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("verify_frozen_inputs.py")
spec = importlib.util.spec_from_file_location("verify_frozen_inputs", MODULE_PATH)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class FrozenInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = b'{"synthetic": true}\n'
        self.expected = {"benchmark.json": hashlib.sha256(self.data).hexdigest()}

    def test_missing_inputs_are_not_a_match(self):
        result = verifier.verify(self.root, self.expected)
        self.assertFalse(result["matches_receipt"])
        self.assertEqual("missing", result["files"][0]["status"])

    def test_synthetic_matching_bytes_do_not_verify_claims(self):
        (self.root / "benchmark.json").write_bytes(self.data)
        result = verifier.verify(self.root, self.expected)
        self.assertTrue(result["matches_receipt"])
        self.assertFalse(result["benchmark_claims_verified"])
        self.assertFalse(result["generator_verified"])
        self.assertEqual("blocked", result["acceptance"])
        self.assertEqual("match", result["files"][0]["status"])

    def test_changed_bytes_fail_without_disclosing_contents(self):
        (self.root / "benchmark.json").write_bytes(b"private synthetic sentinel")
        result = verifier.verify(self.root, self.expected)
        self.assertFalse(result["matches_receipt"])
        self.assertEqual("mismatch", result["files"][0]["status"])
        self.assertNotIn("private synthetic sentinel", str(result))
        self.assertNotIn(str(self.root), str(result))

    def test_every_required_input_is_checked(self):
        (self.root / "benchmark.json").write_bytes(self.data)
        expected = {**self.expected, "KEY_RUNS.json": "0" * 64}
        result = verifier.verify(self.root, expected)
        self.assertFalse(result["matches_receipt"])
        self.assertEqual(["match", "missing"], [r["status"] for r in result["files"]])

    def test_directory_input_is_rejected(self):
        (self.root / "benchmark.json").mkdir()
        result = verifier.verify(self.root, self.expected)
        self.assertEqual("not_regular_file", result["files"][0]["status"])

    def test_symlink_input_is_rejected_without_hashing_target(self):
        target = self.root / "target.json"
        target.write_bytes(self.data)
        try:
            (self.root / "benchmark.json").symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"host cannot create the required symlink: {exc}")
        result = verifier.verify(self.root, self.expected)
        self.assertFalse(result["matches_receipt"])
        self.assertEqual("not_regular_file", result["files"][0]["status"])
        self.assertIsNone(result["files"][0]["observed_sha256"])

    def test_cli_missing_sources_exits_two_and_stays_blocked(self):
        run = subprocess.run(
            [sys.executable, "-I", str(MODULE_PATH), "--inputs", str(self.root)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        result = json.loads(run.stdout)
        self.assertEqual(2, run.returncode)
        self.assertFalse(result["matches_receipt"])
        self.assertEqual("blocked", result["acceptance"])
        self.assertEqual(2, len(result["files"]))
        self.assertEqual("", run.stderr)

    def test_empty_expectations_never_pass_vacuously(self):
        with self.assertRaises(ValueError):
            verifier.verify(self.root, {})


if __name__ == "__main__":
    unittest.main()
