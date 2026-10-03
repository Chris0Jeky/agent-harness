"""Authoring checks only: these fixtures do not execute a product journey."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from ux_evaluation.common import ContractError
from ux_evaluation.scenarios import bind_pack

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "ux-evaluation" / "workspace-handoff.example.json"
REPOSITORY = "example/workspace"
REVISION = "1" * 40  # Deliberately synthetic, not a checkout or attestation.
FIXTURE = "authoring-only: isolated workspace handoff simulator (not implemented)"


class WorkspaceHandoffProfileTests(unittest.TestCase):
    def load_example(self) -> dict:
        self.assertTrue(EXAMPLE.is_file(), "The workspace handoff example is missing")
        return json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def bind(self, pack: dict, **overrides) -> dict:
        arguments = {"expected_repository": REPOSITORY, "expected_revision": REVISION,
                     "allowed_fixtures": [FIXTURE]}
        arguments.update(overrides)
        return bind_pack(pack, **arguments)

    def test_example_binds_as_advisory_not_run(self) -> None:
        result = self.bind(self.load_example())
        self.assertEqual(result["execution"], "not_run")
        self.assertEqual(result["authority"], "advisory")
        self.assertFalse(result["gate_eligible"])
        self.assertEqual(result["journey_ids"], ["durable-capture", "stale-scope", "attempt-is-not-outcome"])

    def test_revision_and_permission_negative_controls_are_independent(self) -> None:
        journey = self.load_example()["journeys"][1]
        self.assertEqual([step["id"] for step in journey["steps"]],
                         ["inspect", "stale", "revoked", "recover"])

    def test_expected_revision_must_match_even_for_a_fictional_example(self) -> None:
        with self.assertRaisesRegex(ContractError, "subject_mismatch"):
            self.bind(self.load_example(), expected_revision="2" * 40)

    def test_fixture_requires_explicit_authoring_allowlist(self) -> None:
        with self.assertRaisesRegex(ContractError, "unknown_fixture"):
            self.bind(self.load_example(), allowed_fixtures=[])

    def test_duplicate_steps_are_rejected(self) -> None:
        pack = copy.deepcopy(self.load_example())
        pack["journeys"][0]["steps"].append(pack["journeys"][0]["steps"][0])
        with self.assertRaisesRegex(ContractError, "duplicate_step"):
            self.bind(pack)

    def test_example_cannot_self_promote_to_a_gate(self) -> None:
        pack = self.load_example()
        pack["gate_eligible"] = True
        with self.assertRaisesRegex(ContractError, "authority"):
            self.bind(pack)


if __name__ == "__main__":
    unittest.main()
