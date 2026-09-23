"""Verify local artifact identity and declared coverage without judging product quality."""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
from pathlib import Path
import re
import stat
from typing import Any

from .common import (ContractError, array, canonical, digest, integer, object_keys,
                     read_regular, regular, require, strings, text)
from .scenarios import EVIDENCE_KINDS, bind_pack, identifier, subject

MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
OUTCOMES = ("pass", "fail", "blocked", "not_run", "not_applicable")


def hex_digest(value: Any) -> None:
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "digest")


def portable_path(value: Any) -> list[str]:
    text(value, 240)
    parts = value.split("/")
    for part in parts:
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part) is not None
                and not part.endswith("."), "artifact_path")
        stem = part.split(".")[0].upper()
        require(stem not in {"CON", "PRN", "AUX", "NUL"}
                and re.fullmatch(r"(?:COM|LPT)[1-9]", stem) is None, "artifact_path")
    return parts


def directory(path: Path) -> None:
    try:
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0) & 0x400), "artifact_directory")
    except OSError as exc:
        raise ContractError("artifact_directory") from exc


def safe_root(root: Path) -> Path:
    root = root.absolute()
    require(not str(root).startswith(("//", "\\\\")), "artifact_root")
    # Inspect ancestors without resolve(), which would hide static symlink/reparse aliases.
    for parent in reversed((root, *root.parents)):
        directory(parent)
    return root


def safe_file(root: Path, relative: str) -> Path:
    parts = portable_path(relative)
    parent = root
    for part in parts[:-1]:
        parent = parent / part
        directory(parent)
    path = parent / parts[-1]
    try:
        require(regular(path.lstat()), "artifact_file")
    except OSError as exc:
        raise ContractError("artifact_file") from exc
    return path


def timestamp(value: Any) -> None:
    require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value)
            is not None, "capture_time")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError("capture_time") from exc


def verify_observation(*, pack: Any, manifest: Any, run_root: Path,
                       expected_repository: str, expected_revision: str,
                       allowed_fixtures: list[str]) -> dict[str, Any]:
    binding = bind_pack(pack, expected_repository=expected_repository,
                        expected_revision=expected_revision, allowed_fixtures=allowed_fixtures)
    canonical(manifest)
    object_keys(manifest, {"schema", "run_id", "authority", "gate_eligible", "subject", "pack_sha256",
                           "journey_id", "status", "observer", "artifacts", "steps"})
    require(manifest["schema"] == "ux-observation/0", "observation_version")
    require(manifest["authority"] == "advisory" and manifest["gate_eligible"] is False, "authority")
    identifier(manifest["run_id"])
    subject(manifest["subject"])
    require(manifest["subject"] == binding["subject"], "subject_mismatch")
    hex_digest(manifest["pack_sha256"])
    require(manifest["pack_sha256"] == binding["pack_sha256"], "pack_mismatch")
    identifier(manifest["journey_id"])
    journeys = {j["id"]: j for j in pack["journeys"]}
    require(manifest["journey_id"] in journeys, "unknown_journey")
    journey = journeys[manifest["journey_id"]]
    require(type(manifest["status"]) is str and manifest["status"] in
            {"complete", "partial", "blocked_environment"}, "observation_status")
    observer = manifest["observer"]
    object_keys(observer, {"controller", "controller_version", "environment", "fixture_ref",
                           "local_only", "synthetic", "actions", "elapsed_ms", "retries"})
    for key in ("controller", "controller_version", "environment", "fixture_ref"):
        text(observer[key])
    require(observer["local_only"] is True and observer["synthetic"] is True, "observer_scope")
    require(observer["fixture_ref"] == journey["fixture_ref"], "fixture_mismatch")
    integer(observer["actions"], 0, journey["budget"]["max_actions"])
    integer(observer["elapsed_ms"], 0, journey["budget"]["max_seconds"] * 1000)
    integer(observer["retries"], 0, journey["budget"]["max_retries"])
    require(observer["retries"] <= observer["actions"], "observer_counts")

    artifacts = manifest["artifacts"]
    array(artifacts, 0, 128)
    by_id, paths, hashes = {}, set(), set()
    total_bytes = 0
    for artifact in artifacts:
        object_keys(artifact, {"id", "path", "kind", "sha256", "size_bytes", "captured_at"})
        identifier(artifact["id"])
        portable_path(artifact["path"])
        require(type(artifact["kind"]) is str and artifact["kind"] in EVIDENCE_KINDS, "evidence_kind")
        hex_digest(artifact["sha256"])
        integer(artifact["size_bytes"], 1, MAX_ARTIFACT_BYTES)
        timestamp(artifact["captured_at"])
        require(artifact["id"] not in by_id, "duplicate_artifact")
        require(artifact["path"].casefold() not in paths, "duplicate_path")
        require(artifact["sha256"] not in hashes, "duplicate_bytes")
        by_id[artifact["id"]] = artifact
        paths.add(artifact["path"].casefold())
        hashes.add(artifact["sha256"])
        total_bytes += artifact["size_bytes"]
    require(total_bytes <= MAX_TOTAL_BYTES, "artifact_total_size")

    steps = manifest["steps"]
    array(steps, len(journey["steps"]), len(journey["steps"]))
    counts = dict.fromkeys(OUTCOMES, 0)
    missing, used = [], set()
    observed_steps = 0
    for planned, observed in zip(journey["steps"], steps):
        object_keys(observed, {"id", "outcomes", "artifact_ids"})
        require(observed["id"] == planned["id"], "step_identity_or_order")
        array(observed["outcomes"], len(planned["assertions"]), len(planned["assertions"]))
        has_observed_outcome = False
        for outcome in observed["outcomes"]:
            object_keys(outcome, {"status", "reason"})
            require(type(outcome["status"]) is str and outcome["status"] in OUTCOMES, "assertion_status")
            text(outcome["reason"])
            counts[outcome["status"]] += 1
            has_observed_outcome |= outcome["status"] in {"pass", "fail"}
        observed_steps += int(has_observed_outcome)
        strings(observed["artifact_ids"], minimum=0, maximum=128)
        require(set(observed["artifact_ids"]) <= set(by_id), "unknown_artifact")
        used.update(observed["artifact_ids"])
        kinds = {by_id[key]["kind"] for key in observed["artifact_ids"]}
        missing.extend({"step_id": planned["id"], "kind": kind}
                       for kind in sorted(set(planned["evidence_required"]) - kinds))
    require(used == set(by_id), "unreferenced_artifact")
    require(observer["actions"] >= observed_steps, "observer_counts")
    complete = (not missing and not any(counts[key] for key in OUTCOMES[2:])
                and manifest["status"] == "complete")
    require(manifest["status"] != "complete" or complete, "incomplete_evidence")

    # Validate the complete metadata inventory before opening any artifact payload.
    root = safe_root(run_root)
    resolved = {key: safe_file(root, item["path"]) for key, item in by_id.items()}
    for key, artifact in by_id.items():
        raw = read_regular(resolved[key], artifact["size_bytes"])
        require(len(raw) == artifact["size_bytes"]
                and hashlib.sha256(raw).hexdigest() == artifact["sha256"], "artifact_integrity")
    normalized = copy.deepcopy(manifest)
    normalized["artifacts"].sort(key=lambda a: a["id"])
    for step in normalized["steps"]:
        step["artifact_ids"].sort()
    return {
        "schema": "ux-evidence-check/0", "authority": "advisory", "gate_eligible": False,
        "subject": binding["subject"], "pack_sha256": binding["pack_sha256"],
        "observation_sha256": digest(normalized), "run_id": manifest["run_id"],
        "journey_id": journey["id"], "coverage_complete": complete,
        "recorded_status": manifest["status"], "assertion_counts": counts,
        "missing_evidence": missing, "artifact_count": len(artifacts), "artifact_bytes": total_bytes,
        "assurance": "Bytes and declared coverage only; no collector attestation, outcome re-derivation or UX verdict.",
    }
