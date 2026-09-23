"""Strict semantic binding for the existing ux-scenario-pack/0 authoring format."""
from __future__ import annotations

import re
from typing import Any

from .common import array, canonical, digest, integer, object_keys, require, strings, text

DIMENSIONS = {"effectiveness", "usability", "simplicity", "clarity", "feel"}
EVIDENCE_KINDS = {"action_log", "screenshot", "trace", "video", "network_summary", "persisted_state"}


def identifier(value: Any) -> None:
    require(type(value) is str and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", value) is not None,
            "identifier")


def subject(value: Any) -> None:
    object_keys(value, {"repository", "source_revision"})
    repo, revision = value["repository"], value["source_revision"]
    require(type(repo) is str and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) is not None
            and len(repo) <= 200, "repository")
    require(type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "revision")


def validate_pack(pack: Any) -> None:
    canonical(pack)
    object_keys(pack, {"schema", "pack_id", "status", "authority", "gate_eligible",
                       "local_only", "subject", "journeys"})
    require(pack["schema"] == "ux-scenario-pack/0" and pack["status"] == "draft", "pack_version")
    require(pack["authority"] == "advisory" and pack["gate_eligible"] is False
            and pack["local_only"] is True, "authority")
    identifier(pack["pack_id"])
    subject(pack["subject"])
    array(pack["journeys"], 1, 20)
    journey_ids = set()
    for journey in pack["journeys"]:
        object_keys(journey, {"id", "goal", "fixture_ref", "preconditions", "steps",
                              "rubric_dimensions", "budget"})
        identifier(journey["id"])
        require(journey["id"] not in journey_ids, "duplicate_journey")
        journey_ids.add(journey["id"])
        text(journey["goal"])
        text(journey["fixture_ref"])
        strings(journey["preconditions"])
        strings(journey["rubric_dimensions"], maximum=5)
        require(set(journey["rubric_dimensions"]) <= DIMENSIONS, "rubric_dimension")
        object_keys(journey["budget"], {"max_actions", "max_seconds", "max_judge_calls", "max_retries"})
        for key, low, high in (("max_actions", 1, 100), ("max_seconds", 1, 1800),
                               ("max_judge_calls", 0, 5), ("max_retries", 0, 2)):
            integer(journey["budget"][key], low, high)
        array(journey["steps"], 1, 30)
        step_ids = set()
        for step in journey["steps"]:
            object_keys(step, {"id", "action", "assertions", "evidence_required"})
            identifier(step["id"])
            require(step["id"] not in step_ids, "duplicate_step")
            step_ids.add(step["id"])
            text(step["action"])
            strings(step["assertions"])
            strings(step["evidence_required"], maximum=len(EVIDENCE_KINDS))
            require(set(step["evidence_required"]) <= EVIDENCE_KINDS, "evidence_kind")


def bind_pack(pack: Any, *, expected_repository: str, expected_revision: str,
              allowed_fixtures: list[str]) -> dict[str, Any]:
    """Validate declarations, not a checkout, callable fixture, or actual observation."""
    validate_pack(pack)
    expected = {"repository": expected_repository, "source_revision": expected_revision}
    subject(expected)
    require(pack["subject"] == expected, "subject_mismatch")
    strings(allowed_fixtures, minimum=0, maximum=100)
    require(all(j["fixture_ref"] in allowed_fixtures for j in pack["journeys"]), "unknown_fixture")
    return {
        "schema": "ux-scenario-binding/0", "authority": "advisory", "gate_eligible": False,
        "execution": "not_run", "subject": expected, "pack_sha256": digest(pack),
        "journey_ids": [j["id"] for j in pack["journeys"]],
        "assurance": "Declared fixture allowlist and expected identity; no checkout or runtime attestation.",
    }
