"""Authoring checks only: these fixtures do not execute a product journey."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from ux_evaluation.common import ContractError
from ux_evaluation.scenarios import bind_pack

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "ux-evaluation" / "workspace-handoff.example.json"
PROFILE = EXAMPLE.with_name("WORKSPACE_HANDOFF_PROFILE.md")
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
        self.assertEqual(result["journey_ids"], ["durable-capture", "stale-scope", "attempt-is-not-outcome",
                                                 "incomplete-observation", "cancellation-at-admission", "evidence-ladder",
                                                 "catch-up-contract", "fix-round-discipline", "admin-agent-acts",
                                                 "adversarial-audit", "two-agent-correction", "archive-not-delete",
                                                 "tldr-undo-cadence"])

    def test_revision_and_permission_negative_controls_are_independent(self) -> None:
        journey = self.load_example()["journeys"][1]
        self.assertEqual([step["id"] for step in journey["steps"]],
                         ["inspect", "stale", "revoked", "recover"])

    def test_incomplete_observation_does_not_authorize_absence(self) -> None:
        journeys = {j["id"]: j for j in self.load_example()["journeys"]}
        self.assertIn("incomplete-observation", journeys)
        journey = journeys["incomplete-observation"]
        self.assertEqual([step["id"] for step in journey["steps"]],
                         ["seed", "limited", "unavailable", "restart", "denied"])
        for step in journey["steps"]:
            self.assertIn("persisted_state", step["evidence_required"])
            self.assertIn("network_summary", step["evidence_required"])

    def test_admission_cancellation_and_lease_controls_are_independent(self) -> None:
        journeys = {j["id"]: j for j in self.load_example()["journeys"]}
        self.assertIn("cancellation-at-admission", journeys)
        journey = journeys["cancellation-at-admission"]
        self.assertEqual([step["id"] for step in journey["steps"]],
                         ["cancel-before", "retired-lease", "expired-during-read", "cancel-after"])
        self.assertEqual(journey["fixture_ref"], FIXTURE)
        self.assertEqual(journey["budget"]["max_judge_calls"], 0)
        self.assertEqual(journey["budget"]["max_retries"], 0)
        self.assertEqual(self.bind(self.load_example())["execution"], "not_run")

    def journey_text(self, journey_id: str) -> str:
        journeys = {j["id"]: j for j in self.load_example()["journeys"]}
        self.assertIn(journey_id, journeys)
        return json.dumps(journeys[journey_id], ensure_ascii=False).lower()

    def profile_text(self) -> str:
        self.assertTrue(PROFILE.is_file(), "The workspace handoff profile is missing")
        return " ".join(PROFILE.read_text(encoding="utf-8").lower().split())

    def test_advisory_journeys_stay_unexecuted_and_within_budget(self) -> None:
        pack = self.load_example()
        for journey in pack["journeys"][5:]:
            self.assertEqual(journey["fixture_ref"], FIXTURE)
            self.assertEqual(journey["budget"]["max_judge_calls"], 0)
            self.assertEqual(journey["budget"]["max_retries"], 0)
        self.assertEqual(self.bind(pack)["execution"], "not_run")
        self.assertIn("advisory and `not_run`; they make no execution claim", " ".join(
            PROFILE.read_text(encoding="utf-8").split()))

    def test_evidence_ladder_names_every_rung_and_receipt_field(self) -> None:
        journeys = {j["id"]: j for j in self.load_example()["journeys"]}
        steps = {step["id"]: step for step in journeys["evidence-ladder"]["steps"]}
        self.assertEqual(list(steps), ["source", "unit", "integrated", "native-runtime", "installed",
                                       "device", "owner-accepted", "revision-change"])
        common = ("subject revision", "exact source revision", "fixture revision or hash", "utc time",
                  "environment", "proof kind", "unavailable observations",
                  "advisory or operational authority")
        executed = ("command and cwd", "pass/fail/skip counts")
        extras = {"installed": ("installed artifact identity",), "device": ("device and platform identity",),
                  "owner-accepted": ("owner-supplied record",)}
        for rung in ("source", "unit", "integrated", "native-runtime", "installed", "device", "owner-accepted"):
            action = steps[rung]["action"].lower()
            required = common + (executed if rung != "owner-accepted" else ()) + extras.get(rung, ())
            for field in required:
                self.assertIn(field, action, f"{rung} rung omits {field}")
        text = self.journey_text("evidence-ladder")
        for claim in ("does not imply", "no rung transfers"):
            self.assertIn(claim, text)
        profile = self.profile_text()
        for rung in ("source, unit, integrated, native runtime, installed, device, owner accepted",
                     "installed artifact identity distinct from the source revision",
                     "never inferred", "never transfers to a different candidate revision",
                     "lower rung never implies a higher one"):
            self.assertIn(rung, profile)

    def test_observation_states_are_folded_into_incomplete_observation(self) -> None:
        ids = [j["id"] for j in self.load_example()["journeys"]]
        self.assertNotIn("observation-states", ids)
        text = self.journey_text("incomplete-observation")
        for claim in ("unknown, never pass and never an empty collection",
                      "distinct state from unavailable and from partial",
                      "no outcome receipt, deletion, delivery claim or authority change",
                      "hides private cached content"):
            self.assertIn(claim, text)
        profile = self.profile_text()
        self.assertIn("complete, partial, unavailable and denied are four distinct states", profile)
        self.assertIn("a partial read never authorises inferred deletion or inferred delivery", profile)
        self.assertEqual(profile.count("four distinct states"), 1)

    def test_catch_up_contract_pins_ordering_overlap_and_deferral(self) -> None:
        journeys = {j["id"]: j for j in self.load_example()["journeys"]}
        self.assertEqual([step["id"] for step in journeys["catch-up-contract"]["steps"]],
                         ["outcome-lookup", "first-run", "overlap-continuation",
                          "timestamp-group", "deferred"])
        text = self.journey_text("catch-up-contract")
        for claim in ("first-run floor", "inclusive overlap", "exclusive", "never splits one timestamp group",
                      "never skipped by a resume position", "failed read does not advance"):
            self.assertIn(claim, text)
        profile = self.profile_text()
        for claim in ("commit-ordered feed", "inclusive overlap", "never splits one timestamp group",
                      "never skipped by a resume position"):
            self.assertIn(claim, profile)

    def test_fix_round_requires_one_scoped_verification(self) -> None:
        journeys = {j["id"]: j for j in self.load_example()["journeys"]}
        self.assertEqual([step["id"] for step in journeys["fix-round-discipline"]["steps"]],
                         ["fix-round", "scoped-verification", "outcome"])
        text = self.journey_text("fix-round-discipline")
        for claim in ("scoped to the fix diff", "expiry does not drop rows", "cursor does not advance on a failed read",
                      "resume position does not skip deferred rows", "exact fix revision"):
            self.assertIn(claim, text)
        self.assertIn("one scoped verification after every fix round", self.profile_text())

    def test_agent_admin_journeys_pin_steps_receipts_and_boundaries(self) -> None:
        journeys = {j["id"]: j for j in self.load_example()["journeys"]}
        expected_steps = {
            "admin-agent-acts": ["triage", "stale-target", "out-of-scope", "partial-batch", "narrated-only"],
            "adversarial-audit": ["independent-identity", "feed-not-report", "partial-coverage", "finding",
                                  "clean-window"],
            "two-agent-correction": ["propose", "self-approval", "stale-approval", "apply", "rejected",
                                     "rarity-budget"],
            "archive-not-delete": ["cleanup-archives", "restore", "hard-delete-refused", "absence-not-deletion",
                                   "retention-visible"],
            "tldr-undo-cadence": ["morning-brief", "evening-wrap", "weekly-review", "undo-conflict",
                                  "undo-by-person", "missed-delivery", "undo-unavailable"],
        }
        for journey_id, step_ids in expected_steps.items():
            self.assertEqual([step["id"] for step in journeys[journey_id]["steps"]], step_ids, journey_id)
        receipts = {
            ("admin-agent-acts", "triage"): ("operation id", "acting agent identity and credential", "role",
                                             "authority scope and policy version", "revision read before acting",
                                             "committed before and after state", "reason",
                                             "undo handle and its availability", "commit time (utc)",
                                             "change-feed reference"),
            ("adversarial-audit", "independent-identity"): ("auditor identity", "window start (inclusive)",
                                                            "end (exclusive)", "coverage state", "items examined",
                                                            "checks run", "findings"),
            ("two-agent-correction", "propose"): ("proposal id and digest", "proposer identity", "approver identity",
                                                  "target revision at approval", "corrected operation id"),
            ("archive-not-delete", "cleanup-archives"): ("act receipt fields", "restore handle",
                                                         "retention or purge time"),
            ("tldr-undo-cadence", "morning-brief"): ("cadence", "first-run floor", "coverage state",
                                                     "receipt and undo link", "items not examined",
                                                     "delivery state"),
        }
        for (journey_id, step_id), fields in receipts.items():
            action = {s["id"]: s for s in journeys[journey_id]["steps"]}[step_id]["action"].lower()
            for field in fields:
                self.assertIn(field, action, f"{journey_id}/{step_id} omits {field}")
        claims = {
            "admin-agent-acts": ("not silently overwritten", "does not borrow",
                                 "narration without a receipt is never counted as an effect",
                                 "never named as the actor of an agent act"),
            "adversarial-audit": ("cannot write", "never the audited agent's summary", "never reported as clean",
                                  "zero examined items is not a clean pass", "cannot apply the correction itself"),
            "two-agent-correction": ("different agent identity from the proposer",
                                     "does not transfer to the new revision", "nothing is applied",
                                     "escalated to sam in the next digest instead of being applied"),
            "archive-not-delete": ("archived, not deleted", "permanent deletion stays a person-only act",
                                   "neither archives it nor reports it deleted", "not applied silently"),
            "tldr-undo-cadence": ("without overlap or gap", "shows a conflict with both states",
                                  "agents never follow undo links", "unknown delivery is not delivered",
                                  "from the last delivered window end", "never presented as available"),
        }
        for journey_id, phrases in claims.items():
            text = self.journey_text(journey_id)
            for phrase in phrases:
                self.assertIn(phrase, text, f"{journey_id} omits {phrase!r}")
            self.assertIn("never the person's", text)
        profile = self.profile_text()
        for claim in ("the approver is a different agent from the proposer",
                      "permanent delete is refused to every agent",
                      "the person is never recorded as the actor of an agent's act",
                      "never fills it from the agent's own account",
                      "advisory and `not_run` like the three above"):
            self.assertIn(claim, profile)

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
