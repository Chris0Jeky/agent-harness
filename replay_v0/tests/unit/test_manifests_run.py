from __future__ import annotations

import copy
import unittest

from replay_v0.manifests import (
    ManifestError,
    build_run_manifest,
    validate_run_manifest,
)

BASELINE = {
    "kind": "recorded",
    "id": "floor-v1-final",
    "sha256": "1" * 64,
}
CANDIDATE = {
    "kind": "process",
    "id": "candidate-policy",
    "sha256": "2" * 64,
}
CORPUS = {
    "id": "charter-v0.1",
    "manifest_sha256": "3" * 64,
    "event_count": 50,
}
FAIL_ON = ["newly-allowed", "newly-indeterminate"]


class RunIdForgeryTests(unittest.TestCase):
    def test_run_manifest_rejects_forged_run_id(self) -> None:
        manifest = build_run_manifest(
            generated_at="2026-07-30T12:00:00Z",
            baseline=BASELINE,
            candidate=CANDIDATE,
            corpus=CORPUS,
            fail_on=FAIL_ON,
        )
        forged = copy.deepcopy(manifest)
        forged["run_id"] = "0" * 64
        with self.assertRaisesRegex(ManifestError, "run_id does not match"):
            validate_run_manifest(forged)


if __name__ == "__main__":
    unittest.main()
