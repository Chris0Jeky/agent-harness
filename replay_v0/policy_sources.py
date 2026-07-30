"""Recorded policy decisions and source-result contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any

from replay_v0.corpus import (
    POLICY_DECISION_VERSION,
    ValidationError,
    split_jsonl_records,
    validate_command_events,
    validate_policy_decision,
)

RECORDED_MANIFEST_VERSION = "recorded-policy-manifest.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class _DuplicateJsonKeyError(ValueError):
    """A JSON object repeated a member name and is structurally ambiguous."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKeyError(key)
        value[key] = item
    return value


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
    diagnostics: tuple[str, ...] = ()

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


def _indeterminate(event_id: str, code: str, source_label: str) -> dict[str, str]:
    return {
        "schema_version": POLICY_DECISION_VERSION,
        "event_id": event_id,
        "effect": "indeterminate",
        "reason": f"{source_label} decision unavailable: {code}.",
    }


def _all_indeterminate(
    events: list[dict[str, Any]],
    failure: SourceFailure,
    source_label: str,
    *,
    diagnostics: tuple[str, ...] = (),
) -> PolicySourceResult:
    return PolicySourceResult(
        tuple(
            _indeterminate(event["event_id"], failure.code, source_label)
            for event in events
        ),
        (failure,),
        diagnostics,
    )


def _evaluate_decision_lines(
    events: list[dict[str, Any]],
    lines: list[str],
    *,
    code_prefix: str,
    source_label: str,
    require_order: bool,
    initial_failures: Sequence[SourceFailure] = (),
    diagnostics: tuple[str, ...] = (),
) -> PolicySourceResult:
    """Validate JSONL decisions and restore corpus order without guessing."""

    expected_ids = {event["event_id"] for event in events}
    event_positions = {
        event["event_id"]: position for position, event in enumerate(events)
    }
    by_event_id: dict[str, dict[str, Any]] = {}
    untrustworthy_ids: set[str] = set()
    failures = list(initial_failures)
    last_position = -1

    for line_number, line in enumerate(lines, start=1):
        try:
            raw_value = json.loads(line, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, _DuplicateJsonKeyError):
            failures.append(
                SourceFailure(
                    f"{code_prefix}-json-invalid",
                    f"{source_label} decision line {line_number} is invalid JSON.",
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
                    f"{code_prefix}-schema-invalid",
                    f"{source_label} decision line {line_number} is invalid: {exc}",
                    raw_event_id,
                )
            )
            continue

        event_id = decision["event_id"]
        if event_id not in expected_ids:
            failures.append(
                SourceFailure(
                    f"{code_prefix}-unexpected-event",
                    f"{source_label} decision has no matching corpus event.",
                    event_id,
                )
            )
            continue
        if event_id in by_event_id or event_id in untrustworthy_ids:
            by_event_id.pop(event_id, None)
            untrustworthy_ids.add(event_id)
            failures.append(
                SourceFailure(
                    f"{code_prefix}-duplicate-event",
                    f"{source_label} decision event_id is duplicated.",
                    event_id,
                )
            )
            continue

        position = event_positions[event_id]
        if require_order and position <= last_position:
            failure = SourceFailure(
                f"{code_prefix}-order-invalid",
                f"{source_label} decisions are not in corpus order.",
                event_id,
            )
            return PolicySourceResult(
                tuple(
                    _indeterminate(event["event_id"], failure.code, source_label)
                    for event in events
                ),
                tuple([*failures, failure]),
                diagnostics,
            )
        last_position = position
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
                    f"{code_prefix}-missing-event",
                    f"{source_label} decision is missing for the corpus event.",
                    event_id,
                )
            )
            code = f"{code_prefix}-missing-event"
        else:
            code = f"{code_prefix}-untrustworthy-event"
        ordered.append(_indeterminate(event_id, code, source_label))

    return PolicySourceResult(tuple(ordered), tuple(failures), diagnostics)


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
            manifest_value = json.loads(
                manifest_bytes.decode("utf-8"), object_pairs_hook=_unique_json_object
            )
            manifest = validate_recorded_manifest(manifest_value)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            _DuplicateJsonKeyError,
            ValidationError,
        ) as exc:
            failure = SourceFailure(
                "recording-manifest-invalid",
                f"Recorded manifest is invalid: {exc.__class__.__name__}.",
            )
            return _all_indeterminate(events, failure, "Recorded")

        if manifest.decisions_file != self.decisions_path.name:
            failure = SourceFailure(
                "recording-file-mismatch",
                "Recorded manifest names a different decisions file.",
            )
            return _all_indeterminate(events, failure, "Recorded")

        try:
            decision_bytes = self.decisions_path.read_bytes()
        except OSError as exc:
            failure = SourceFailure(
                "recording-read-failed",
                f"Recorded decisions could not be read: {exc.__class__.__name__}.",
            )
            return _all_indeterminate(events, failure, "Recorded")

        actual_digest = hashlib.sha256(decision_bytes).hexdigest()
        if actual_digest != manifest.decisions_sha256:
            failure = SourceFailure(
                "recording-digest-mismatch",
                "Recorded decisions do not match the manifest SHA-256.",
            )
            return _all_indeterminate(events, failure, "Recorded")

        try:
            lines = split_jsonl_records(decision_bytes.decode("utf-8"))
        except UnicodeDecodeError:
            failure = SourceFailure(
                "recording-utf8-invalid",
                "Recorded decisions are not valid UTF-8.",
            )
            return _all_indeterminate(events, failure, "Recorded")

        if len(lines) != manifest.decision_count:
            failure = SourceFailure(
                "recording-count-mismatch",
                "Recorded decision count does not match the manifest.",
            )
            return _all_indeterminate(events, failure, "Recorded")

        return _evaluate_decision_lines(
            events,
            lines,
            code_prefix="recording",
            source_label="Recorded",
            require_order=False,
        )


class ProcessDecisionSource:
    """Evaluate a JSONL policy process through a shell-free argv contract."""

    def __init__(self, argv: Sequence[str], *, timeout_seconds: float = 30.0) -> None:
        if isinstance(argv, (str, bytes)) or not argv:
            raise ValueError("process argv must be a non-empty sequence of strings")
        if any(not isinstance(argument, str) for argument in argv) or not argv[0]:
            raise ValueError("process argv must be a non-empty sequence of strings")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("process timeout must be a finite positive number")
        self.argv = tuple(argv)
        self.timeout_seconds = float(timeout_seconds)
        self.cwd: str | None = None
        self.environment: dict[str, str] | None = None

    def with_runtime(
        self,
        *,
        cwd: str | Path,
        environment: Mapping[str, str],
    ) -> ProcessDecisionSource:
        """Bind a deterministic CLI runtime without expanding the process contract."""

        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in environment.items()
        ):
            raise ValueError("process environment must contain only string pairs")
        self.cwd = str(cwd)
        self.environment = dict(environment)
        return self

    def evaluate(self, event_values: list[object]) -> PolicySourceResult:
        events = validate_command_events(event_values)
        input_bytes = "".join(
            f"{json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}\n"
            for event in events
        ).encode("utf-8")

        try:
            completed = subprocess.run(
                list(self.argv),
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
                cwd=self.cwd,
                env=self.environment,
            )
        except subprocess.TimeoutExpired:
            failure = SourceFailure(
                "process-timeout",
                "Policy process exceeded its configured timeout.",
            )
            return _all_indeterminate(events, failure, "Process")
        except OSError as exc:
            failure = SourceFailure(
                "process-start-failed",
                f"Policy process could not start: {exc.__class__.__name__}.",
            )
            return _all_indeterminate(events, failure, "Process")

        diagnostics = tuple(
            completed.stderr.decode("utf-8", errors="replace").splitlines()
        )
        try:
            lines = split_jsonl_records(completed.stdout.decode("utf-8"))
        except UnicodeDecodeError:
            failure = SourceFailure(
                "process-stdout-utf8-invalid",
                "Policy process standard output is not valid UTF-8.",
            )
            return _all_indeterminate(
                events, failure, "Process", diagnostics=diagnostics
            )

        failures: list[SourceFailure] = []
        if completed.returncode != 0:
            failures.append(
                SourceFailure(
                    "process-exit-nonzero",
                    f"Policy process exited with code {completed.returncode}.",
                )
            )

        return _evaluate_decision_lines(
            events,
            lines,
            code_prefix="process",
            source_label="Process",
            require_order=True,
            initial_failures=failures,
            diagnostics=diagnostics,
        )
