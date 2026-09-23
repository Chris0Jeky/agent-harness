"""Read a review authoring packet offline; never execute or approve its claims.

Exit 0 means a report was produced, including FAIL/BLOCKED/incomplete observations.
Exit 2 means the input could not be read or interpreted. Neither is a merge verdict.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

MAX_BYTES = 1024 * 1024
STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT RUN", "N/A"}
ROLES = {"candidate", "successful_control", "regression_control"}
EVIDENCE_FIELDS = (
    "tested_revision_sha",
    "command_or_action",
    "environment",
    "actual_outcome",
    "evidence_ref",
)


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _identifier(value, label):
    if not _text(value) or len(value) > 128 or not value.isprintable():
        raise ValueError(
            f"{label} must be a nonempty printable ID of at most 128 characters"
        )
    return value


def _revision(value, label):
    if value is not None and (
        not isinstance(value, str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None
    ):
        raise ValueError(f"{label} must be null or a full lowercase Git object ID")
    return value


def _array(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def summarize(packet: dict, expected_head: str | None = None) -> dict:
    """Summarize supplied claims, not execution, artifact authenticity, or CI state.

    Existing packet intent/risk fields are retained by the caller, not copied to the
    report. Unknown extension fields are ignored. Known identity and observation
    fields are checked; no commands or evidence_ref values are dereferenced.
    """
    packet = _object(packet, "packet")
    if packet.get("document_kind") != "authoring_template_not_execution_receipt":
        raise ValueError("unsupported document_kind")
    version = packet.get("template_version")
    if type(version) is not int or version != 0:
        raise ValueError("unsupported template_version")
    identity = _object(packet.get("identity"), "identity")
    reviewed = _revision(identity.get("reviewed_head_sha"), "reviewed_head_sha")
    expected = _revision(expected_head, "expected_head")
    if reviewed is None or expected is None:
        identity_state = "UNKNOWN"
    else:
        identity_state = "MATCH" if reviewed == expected else "MISMATCH"
    warnings = []
    if identity_state == "MISMATCH":
        warnings.append("reviewed_head_mismatch")
    checks = {}
    for check in _array(packet.get("planned_checks"), "planned_checks"):
        check = _object(check, "planned check")
        key = _identifier(check.get("id"), "check id")
        if key in checks:
            raise ValueError("duplicate check id")
        checks[key] = check
    if not checks:
        warnings.append("no_planned_checks")
    seen = set()
    candidate_checks = set()
    outcomes = {}
    rows = []
    for observation in _array(packet.get("observations"), "observations"):
        observation = _object(observation, "observation")
        oid = _identifier(observation.get("id"), "observation id")
        if oid in seen:
            raise ValueError("duplicate observation id")
        seen.add(oid)
        key = _identifier(observation.get("check_id"), "observation check_id")
        if key not in checks:
            raise ValueError("observation references an unknown check")
        status = observation.get("status")
        role = observation.get("role")
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError("unknown observation status")
        if not isinstance(role, str) or role not in ROLES:
            raise ValueError("unknown observation role")
        revision = _revision(observation.get("tested_revision_sha"), "tested_revision_sha")
        for field in EVIDENCE_FIELDS:
            value = observation.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"observation {field} must be text or null")
        missing = [field for field in EVIDENCE_FIELDS if not _text(observation.get(field))]
        if status in {"BLOCKED", "NOT RUN", "N/A"}:
            state = "NOT_EXECUTED"
            if status in {"BLOCKED", "N/A"} and not _text(observation.get("actual_outcome")):
                warnings.append(f"missing_nonexecution_reason:{oid}")
        elif missing:
            state = "INCOMPLETE"
        elif role == "candidate":
            target = expected or reviewed
            state = (
                "UNBOUND"
                if target is None
                else (
                    "RECORDED" if revision == target else "OTHER_REVISION"
                )
            )
        else:
            state = "RECORDED"
        if role == "candidate":
            candidate_checks.add(key)
            outcomes.setdefault(key, set()).add(status)
        rows.append(
            {
                "id": oid,
                "check_id": key,
                "role": role,
                "reported_status": status,
                "tested_revision_sha": revision,
                "evidence_state": state,
                "missing_fields": missing,
            }
        )
    for key in sorted(outcomes):
        if {"PASS", "FAIL"}.issubset(outcomes[key]):
            warnings.append(f"mixed_candidate_outcomes:{key}")
    if packet.get("execution_status") == "NOT RUN" and any(
        row["reported_status"] in {"PASS", "FAIL"} for row in rows
    ):
        warnings.append("not_run_declaration_has_outcome_claims")
    return {
        "document_kind": "advisory_review_packet_summary",
        "reader_version": 1,
        "execution_verified": False,
        "merge_verdict": None,
        "reviewed_head_sha": reviewed,
        "expected_head_sha": expected,
        "identity_state": identity_state,
        "requested_checks": len(checks),
        "checks_with_candidate_observations": len(candidate_checks),
        "checks_without_candidate_observations": sorted(set(checks) - candidate_checks),
        "observations": rows,
        "warnings": warnings,
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non-finite JSON number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(
            "non-finite JSON number"
        )
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument(
        "--expected-head",
        help="full source PR head ID; merge revisions are reported separately",
    )
    args = parser.parse_args(argv)
    try:
        if not args.packet.is_file():
            raise ValueError("packet must be a regular file")
        with args.packet.open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("packet exceeds 1 MiB")
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
        report = summarize(data, expected_head=args.expected_head)
        report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, RecursionError) as error:
        # Report a type, not source snippets, paths, or possibly private JSON text.
        print(f"review-evidence: invalid input ({type(error).__name__})", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
