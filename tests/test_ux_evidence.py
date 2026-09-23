"""Artifact bytes and declared coverage, never simulated browser acceptance."""
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_ux_scenarios import FIXTURE, REPOSITORY, REVISION, ROOT, pack
from ux_evaluation.common import ContractError, digest


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module("ux_evaluation.evidence")
        except ModuleNotFoundError:
            self.fail("Offline evidence verification is not implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.pack = pack()
        self.files = {"actions.txt": b"Synthetic action log", "state.json": b'{"draft":"kept"}'}
        artifacts = []
        for index, (name, raw) in enumerate(self.files.items()):
            (self.root / name).write_bytes(raw)
            artifacts.append({"id": f"artifact-{index}", "path": name,
                              "kind": ("action_log", "persisted_state")[index],
                              "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                              "captured_at": "2026-09-23T00:00:00Z"})
        self.manifest = {
            "schema": "ux-observation/0", "run_id": "synthetic-run", "authority": "advisory",
            "gate_eligible": False, "subject": copy.deepcopy(self.pack["subject"]),
            "pack_sha256": digest(self.pack), "journey_id": "keep-draft", "status": "complete",
            "observer": {"controller": "synthetic-test", "controller_version": "0",
                         "environment": "unit-fixture", "fixture_ref": FIXTURE,
                         "local_only": True, "synthetic": True,
                         "actions": 1, "elapsed_ms": 10, "retries": 0},
            "artifacts": artifacts,
            "steps": [{"id": "switch", "outcomes": [{"status": "pass", "reason": "Synthetic control"}],
                       "artifact_ids": ["artifact-0", "artifact-1"]}]}

    def verify(self, **overrides):
        args = dict(pack=self.pack, manifest=self.manifest, run_root=self.root,
                    expected_repository=REPOSITORY, expected_revision=REVISION,
                    allowed_fixtures=[FIXTURE])
        args.update(overrides)
        return self.api.verify_observation(**args)

    def test_valid_bytes_and_coverage_have_no_quality_verdict(self):
        before = copy.deepcopy(self.manifest)
        result = self.verify()
        self.assertIs(result["coverage_complete"], True)
        self.assertEqual(result["artifact_count"], 2)
        self.assertEqual(result["assertion_counts"]["pass"], 1)
        self.assertIs(result["gate_eligible"], False)
        self.assertEqual(result["authority"], "advisory")
        self.assertNotIn("verdict", result)
        self.assertNotIn("quality_score", result)
        self.assertEqual(self.manifest, before)

    def test_failed_product_assertion_can_be_complete_evidence(self):
        self.manifest["steps"][0]["outcomes"][0]["status"] = "fail"
        result = self.verify()
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["assertion_counts"]["fail"], 1)
        self.assertNotIn("passed", result)

    def test_missing_evidence_is_partial_not_false_complete(self):
        self.manifest["artifacts"] = self.manifest["artifacts"][:1]
        self.manifest["steps"][0]["artifact_ids"] = ["artifact-0"]
        with self.assertRaises(ContractError):
            self.verify()
        self.manifest["status"] = "partial"
        result = self.verify()
        self.assertFalse(result["coverage_complete"])
        self.assertIn({"step_id": "switch", "kind": "persisted_state"}, result["missing_evidence"])

    def test_unobserved_assertions_cannot_claim_complete(self):
        for status in ("blocked", "not_run", "not_applicable"):
            self.manifest["steps"][0]["outcomes"][0]["status"] = status
            self.manifest["status"] = "complete"
            with self.subTest(status=status), self.assertRaises(ContractError):
                self.verify()
            self.manifest["status"] = "partial"
            self.assertFalse(self.verify()["coverage_complete"])

    def test_tampered_missing_or_wrong_sized_artifact_refused_even_for_partial(self):
        path = self.root / "actions.txt"
        for raw in (b"different content", b""):
            path.write_bytes(raw)
            with self.assertRaises(ContractError):
                self.verify()
        path.unlink()
        self.manifest["status"] = "partial"
        with self.assertRaises(ContractError):
            self.verify()

    def test_identity_and_fixture_mismatches_refused(self):
        before = copy.deepcopy(self.manifest)
        mutations = (lambda m: m.update(pack_sha256="0" * 64),
                     lambda m: m["subject"].update(source_revision="2" * 40),
                     lambda m: m.update(journey_id="missing"),
                     lambda m: m["observer"].update(fixture_ref="other"),
                     lambda m: m.update(gate_eligible=0),
                     lambda m: m["observer"].update(local_only=1),
                     lambda m: m["observer"].update(synthetic=False))
        for mutation in mutations:
            self.manifest = copy.deepcopy(before)
            mutation(self.manifest)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                self.verify()
        self.manifest = before
        with self.assertRaises(ContractError):
            self.verify(expected_revision="2" * 40)

    def test_invalid_portable_paths_refused_before_read(self):
        for name in ("../secret", "/tmp/file", "a/../b", "C:/a", "a\\b", "a//b", "./a",
                     "a.", "a ", "CON.txt", "x/NUL", "COM1.log", "x:stream", "~a", "a\x00b"):
            self.manifest["artifacts"][0]["path"] = name
            with self.subTest(name=name), patch.object(self.api, "read_regular") as reader:
                with self.assertRaises(ContractError):
                    self.verify()
                reader.assert_not_called()

    def test_case_aliases_and_duplicate_artifact_ids_refused(self):
        original = copy.deepcopy(self.manifest)
        for changes in ({"id": "artifact-0"}, {"path": "ACTIONS.TXT"}):
            self.manifest = copy.deepcopy(original)
            self.manifest["artifacts"][1].update(changes)
            with self.assertRaises(ContractError):
                self.verify()

    def test_bad_step_references_and_assertion_counts_refused(self):
        original = copy.deepcopy(self.manifest)
        mutations = (lambda m: m["steps"][0].update(id="unknown"),
                     lambda m: m["steps"].append(copy.deepcopy(m["steps"][0])),
                     lambda m: m["steps"][0].update(artifact_ids=["missing"]),
                     lambda m: m["steps"][0].update(artifact_ids=["artifact-0", "artifact-0"]),
                     lambda m: m["steps"][0].update(outcomes=[]),
                     lambda m: m["steps"][0]["outcomes"][0].update(status="approved"),
                     lambda m: m["steps"][0]["outcomes"][0].update(reason=""))
        for mutation in mutations:
            self.manifest = copy.deepcopy(original)
            mutation(self.manifest)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                self.verify()

    def test_unreferenced_artifact_and_relabelled_duplicate_bytes_refused(self):
        self.manifest["steps"][0]["artifact_ids"] = ["artifact-0"]
        self.manifest["status"] = "partial"
        with self.assertRaises(ContractError):
            self.verify()
        self.manifest["steps"][0]["artifact_ids"] = ["artifact-0", "artifact-1"]
        raw = self.files["actions.txt"]
        (self.root / "state.json").write_bytes(raw)
        self.manifest["artifacts"][1].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        with self.assertRaises(ContractError):
            self.verify()

    def test_limits_and_unknown_fields_refused(self):
        original = copy.deepcopy(self.manifest)
        mutations = (lambda m: m.update(secret="not expected"),
                     lambda m: m["observer"].update(actions=True),
                     lambda m: m["observer"].update(actions=41),
                     lambda m: m["observer"].update(actions=0),
                     lambda m: m["observer"].update(elapsed_ms=600001),
                     lambda m: m["observer"].update(retries=1),
                     lambda m: m["artifacts"][0].update(size_bytes=True),
                     lambda m: m["artifacts"][0].update(size_bytes=self.api.MAX_ARTIFACT_BYTES + 1),
                     lambda m: m["artifacts"][0].update(captured_at="yesterday"),
                     lambda m: m["artifacts"][0].update(sha256="A" * 64))
        for mutation in mutations:
            self.manifest = copy.deepcopy(original)
            mutation(self.manifest)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                self.verify()

    def test_hardlink_refused_without_requiring_symlink_privilege(self):
        path = self.root / "actions.txt"
        original = self.root / "original.txt"
        path.rename(original)
        try:
            os.link(original, path)
        except OSError:
            self.skipTest("Hardlink creation unavailable on this filesystem")
        with self.assertRaises(ContractError):
            self.verify()

    def test_file_symlink_and_directory_alias_refused(self):
        path = self.root / "actions.txt"
        original = self.root / "original.txt"
        path.rename(original)
        try:
            path.symlink_to(original)
        except OSError:
            self.skipTest("Symlink creation unavailable on this host")
        with self.assertRaises(ContractError):
            self.verify()
        path.unlink()
        original.rename(path)
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.manifest["artifacts"][0]["path"] = "alias/actions.txt"
        with self.assertRaises(ContractError):
            self.verify()
        self.manifest["artifacts"][0]["path"] = "actions.txt"
        with self.assertRaises(ContractError):
            self.verify(run_root=alias)

    def test_metadata_preflight_precedes_artifact_reads(self):
        self.manifest["artifacts"][1]["path"] = "../later-bad-path"
        with patch.object(self.api, "read_regular") as reader:
            with self.assertRaises(ContractError):
                self.verify()
            reader.assert_not_called()

    def test_reordered_artifact_inventory_retains_identity(self):
        before = self.verify()
        self.manifest["artifacts"].reverse()
        self.manifest["steps"][0]["artifact_ids"].reverse()
        self.assertEqual(before, self.verify())

    def test_cli_verification_and_error_redaction(self):
        pack_path = self.root / "pack.json"
        manifest_path = self.root / "observation.json"
        pack_path.write_text(json.dumps(self.pack), encoding="utf-8")
        manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        args = [sys.executable, "-m", "ux_evaluation", "verify", "--pack", str(pack_path),
                "--manifest", str(manifest_path), "--run-root", str(self.root),
                "--expected-repository", REPOSITORY, "--expected-revision", REVISION,
                "--fixture-ref", FIXTURE]
        done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)["coverage_complete"])
        self.manifest["status"] = "partial"
        manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertFalse(json.loads(done.stdout)["coverage_complete"])
        (self.root / "actions.txt").write_bytes(b"PRIVATE_BROKEN_ARTIFACT")
        done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertNotIn("PRIVATE_BROKEN_ARTIFACT", done.stderr)
        self.assertNotIn(str(self.root), done.stderr)


if __name__ == "__main__":
    unittest.main()
