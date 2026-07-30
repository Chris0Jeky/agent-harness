"""Recorded policy decisions and source-result contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from replay_v0.corpus import (
    POLICY_DECISION_VERSION,
    ValidationError,
    validate_command_events,
    validate_policy_decision,
)

RECORDED_MANIFEST_VERSION = "recorded-policy-manifest.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class SourceFailure:
    """One machine-readable reason a policy result is not fully trustworthy."""

    code: str
    message: str
    event_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        value = {"code": self.code, "message": self.message}
        if self.event_id is not None:
            value["event_id"] = self.event_id
        return value


@dataclass(frozen=True)
class PolicySourceResult:
    """Ordered decisions plus validation/evaluation failures."""

    decisions: tuple[dict[str, Any], ...]
    failures: tuple[SourceFailure, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class RecordedPolicyManifest:
    """Validated identity and exact-byte binding for a recorded source."""

    policy_id: str
    policy_commit: str
    decisions_file: str
    decisions_sha256: str
    decision_count: int


def _manifest_path(decisions_path: Path) -> Path:
    return Path(f"{decisions_path}.manifest.json")


def _require_manifest_string(
    value: dict[str, object], field: str, *, pattern: re.Pattern[str] | None = None
) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ValidationError(f"RecordedPolicyManifest.{field}: expected a string")
    if "\r" in candidate or "\n" in candidate:
        raise ValidationError(f"RecordedPolicyManifest.{field}: must be a single line")
    if pattern is not None and not pattern.fullmatch(candidate):
        raise ValidationError(f"RecordedPolicyManifest.{field}: invalid value")
    return candidate


def validate_recorded_manifest(value: object) -> RecordedPolicyManifest:
    """Validate the bounded recorded-policy sidecar schema."""

    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValidationError("RecordedPolicyManifest: expected a JSON object")
    required = (
        "schema_version",
        "policy_id",
        "policy_commit",
        "decisions_file",
        "decisions_sha256",
        "decision_count",
    )
    missing = [field for field in required if field not in value]
    if missing:
        raise ValidationError(
            "RecordedPolicyManifest: missing required field(s): " + ", ".join(missing)
        )
    unexpected = sorted(set(value) - set(required))
    if unexpected:
        raise ValidationError(
            "RecordedPolicyManifest: unexpected field(s): " + ", ".join(unexpected)
        )
    if value["schema_version"] != RECORDED_MANIFEST_VERSION:
        raise ValidationError(
            "RecordedPolicyManifest.schema_version: expected "
            f"{RECORDED_MANIFEST_VERSION!r}"
        )
    decision_count = value["decision_count"]
    if (
        not isinstance(decision_count, int)
        or isinstance(decision_count, bool)
        or decision_count < 0
    ):
        raise ValidationError(
            "RecordedPolicyManifest.decision_count: expected a non-negative integer"
        )
    return RecordedPolicyManifest(
        policy_id=_require_manifest_string(value, "policy_id"),
        policy_commit=_require_manifest_string(
            value, "policy_commit", pattern=_GIT_COMMIT
        ),
        decisions_file=_require_manifest_string(value, "decisions_file"),
        decisions_sha256=_require_manifest_string(
            value, "decisions_sha256", pattern=_SHA256
        ),
        decision_count=decision_count,
    )


def _indeterminate(event_id: str, code: str) -> dict[str, str]:
    return {
        "schema_version": POLICY_DECISION_VERSION,
        "event_id": event_id,
        "effect": "indeterminate",
        "reason": f"Recorded decision unavailable: {code}.",
    }


def _all_indeterminate(
    events: list[dict[str, Any]], failure: SourceFailure
) -> PolicySourceResult:
    return PolicySourceResult(
        tuple(_indeterminate(event["event_id"], failure.code) for event in events),
        (failure,),
    )


class RecordedDecisionSource:
    """Read an exact-byte-bound JSONL decision recording without policy execution."""

    def __init__(
        self, decisions_path: str | Path, manifest_path: str | Path | None = None
    ) -> None:
        self.decisions_path = Path(decisions_path)
        self.manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else _manifest_path(self.decisions_path)
        )

    def evaluate(self, event_values: list[object]) -> PolicySourceResult:
        events = validate_command_events(event_values)

        try:
            manifest_bytes = self.manifest_path.read_bytes()
            manifest_value = json.loads(manifest_bytes.decode("utf-8"))
            manifest = validate_recorded_manifest(manifest_value)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            failure = SourceFailure(
                "recording-manifest-invalid",
                f"Recorded manifest is invalid: {exc.__class__.__name__}.",
            )
            return _all_indeterminate(events, failure)

        if manifest.decisions_file != self.decisions_path.name:
            failure = SourceFailure(
                "recording-file-mismatch",
                "Recorded manifest names a different decisions file.",
            )
            return _all_indeterminate(events, failure)

        try:
            decision_bytes = self.decisions_path.read_bytes()
        except OSError as exc:
            failure = SourceFailure(
                "recording-read-failed",
                f"Recorded decisions could not be read: {exc.__class__.__name__}.",
            )
            return _all_indeterminate(events, failure)

        actual_digest = hashlib.sha256(decision_bytes).hexdigest()
        if actual_digest != manifest.decisions_sha256:
            failure = SourceFailure(
                "recording-digest-mismatch",
                "Recorded decisions do not match the manifest SHA-256.",
            )
            return _all_indeterminate(events, failure)

        try:
            lines = decision_bytes.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            failure = SourceFailure(
                "recording-utf8-invalid",
                "Recorded decisions are not valid UTF-8.",
            )
            return _all_indeterminate(events, failure)

        if len(lines) != manifest.decision_count:
            failure = SourceFailure(
                "recording-count-mismatch",
                "Recorded decision count does not match the manifest.",
            )
            return _all_indeterminate(events, failure)

        expected_ids = {event["event_id"] for event in events}
        by_event_id: dict[str, dict[str, Any]] = {}
        untrustworthy_ids: set[str] = set()
        failures: list[SourceFailure] = []

        for line_number, line in enumerate(lines, start=1):
            try:
                raw_value = json.loads(line)
            except json.JSONDecodeError:
                failures.append(
                    SourceFailure(
                        "recording-json-invalid",
                        f"Recorded decision line {line_number} is invalid JSON.",
                    )
                )
                continue

            raw_event_id = (
                raw_value.get("event_id")
                if isinstance(raw_value, dict)
                and isinstance(raw_value.get("event_id"), str)
                else None
            )
            try:
                decision = validate_policy_decision(raw_value)
            except ValidationError as exc:
                if raw_event_id:
                    untrustworthy_ids.add(raw_event_id)
                    by_event_id.pop(raw_event_id, None)
                failures.append(
                    SourceFailure(
                        "recording-schema-invalid",
                        f"Recorded decision line {line_number} is invalid: {exc}",
                        raw_event_id,
                    )
                )
                continue

            event_id = decision["event_id"]
            if event_id not in expected_ids:
                failures.append(
                    SourceFailure(
                        "recording-unexpected-event",
                        "Recorded decision has no matching corpus event.",
                        event_id,
                    )
                )
                continue
            if event_id in by_event_id or event_id in untrustworthy_ids:
                by_event_id.pop(event_id, None)
                untrustworthy_ids.add(event_id)
                failures.append(
                    SourceFailure(
                        "recording-duplicate-event",
                        "Recorded decision event_id is duplicated.",
                        event_id,
                    )
                )
                continue
            by_event_id[event_id] = decision

        ordered: list[dict[str, Any]] = []
        for event in events:
            event_id = event["event_id"]
            decision = by_event_id.get(event_id)
            if decision is not None and event_id not in untrustworthy_ids:
                ordered.append(decision)
                continue
            if event_id not in untrustworthy_ids:
                failures.append(
                    SourceFailure(
                        "recording-missing-event",
                        "Recorded decision is missing for the corpus event.",
                        event_id,
                    )
                )
                code = "recording-missing-event"
            else:
                code = "recording-untrustworthy-event"
            ordered.append(_indeterminate(event_id, code))

        return PolicySourceResult(tuple(ordered), tuple(failures))
