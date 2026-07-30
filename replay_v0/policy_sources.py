"""Recorded policy decisions and source-result contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

from replay_v0.corpus import (
    POLICY_DECISION_VERSION,
    ValidationError,
    split_jsonl_records,
    validate_command_events,
    validate_policy_decision,
)
from replay_v0.digests import executable_bits, sha256_file, sha256_tree

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


def _cleanup_snapshot_root(root: Path) -> SourceFailure | None:
    try:
        shutil.rmtree(root)
    except FileNotFoundError:
        return None
    except OSError:
        return SourceFailure(
            "process-snapshot-cleanup-failed",
            "The private policy process snapshot could not be removed.",
        )
    return None


@dataclass(frozen=True)
class _ProcessInputSnapshot:
    """Private execution paths that contain the exact bound process inputs."""

    root: Path
    argv: tuple[str, ...]
    cwd: str
    executable_sha256: str
    executable_bits: str
    policy_sha256: str
    policy_tree_sha256: str

    def verification_failure(self) -> SourceFailure | None:
        executable = Path(self.argv[0])
        policy_tree = Path(self.cwd)
        policy = policy_tree / self.argv[-1]
        try:
            actual_executable = sha256_file(executable)
            actual_executable_bits = executable_bits(executable)
            actual_policy = sha256_file(policy)
            actual_tree = sha256_tree(policy_tree)
        except OSError:
            return SourceFailure(
                "process-snapshot-changed",
                "The private policy process snapshot became unavailable.",
            )
        if (
            actual_executable != self.executable_sha256
            or actual_executable_bits != self.executable_bits
            or actual_policy != self.policy_sha256
            or actual_tree != self.policy_tree_sha256
        ):
            return SourceFailure(
                "process-snapshot-changed",
                "The private policy process snapshot changed after capture.",
            )
        return None

    def cleanup(self) -> SourceFailure | None:
        return _cleanup_snapshot_root(self.root)


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
        self.executable_binding: tuple[Path, str, str] | None = None
        self.policy_tree_binding: tuple[Path, str, str] | None = None

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

    def with_input_binding(
        self,
        *,
        executable_path: str | Path,
        executable_sha256: str,
        executable_bits: str,
        policy_tree_path: str | Path,
        policy_sha256: str,
        policy_tree_sha256: str,
    ) -> ProcessDecisionSource:
        """Bind the executable and policy tree copied into a validated snapshot."""

        if (
            not _SHA256.fullmatch(executable_sha256)
            or not _SHA256.fullmatch(policy_sha256)
            or not _SHA256.fullmatch(policy_tree_sha256)
        ):
            raise ValueError("process input bindings require lowercase SHA-256 digests")
        if not re.fullmatch(r"[01]{3}", executable_bits):
            raise ValueError("process executable binding requires three execute bits")
        self.executable_binding = (
            Path(executable_path),
            executable_sha256,
            executable_bits,
        )
        self.policy_tree_binding = (
            Path(policy_tree_path),
            policy_sha256,
            policy_tree_sha256,
        )
        return self

    @staticmethod
    def _snapshot_failure(
        events: list[dict[str, Any]],
        *,
        code: str,
        message: str,
        snapshot_root: Path | None = None,
    ) -> PolicySourceResult:
        failure = SourceFailure(code, message)
        result = _all_indeterminate(events, failure, "Process")
        if snapshot_root is None:
            return result
        cleanup_failure = _cleanup_snapshot_root(snapshot_root)
        if cleanup_failure is None:
            return result
        return PolicySourceResult(
            result.decisions,
            result.failures + (cleanup_failure,),
            result.diagnostics,
        )

    def _prepare_input_snapshot(
        self, events: list[dict[str, Any]]
    ) -> _ProcessInputSnapshot | PolicySourceResult | None:
        if self.executable_binding is None and self.policy_tree_binding is None:
            return None
        if (
            self.executable_binding is None
            or self.policy_tree_binding is None
            or self.cwd is None
            or len(self.argv) < 2
            or Path(self.argv[-1]).name != self.argv[-1]
        ):
            return self._snapshot_failure(
                events,
                code="process-input-binding-invalid",
                message="Policy process input bindings are incomplete.",
            )

        executable_path, expected_executable, expected_executable_bits = (
            self.executable_binding
        )
        policy_tree_path, expected_policy, expected_tree = self.policy_tree_binding
        try:
            snapshot_root = Path(tempfile.mkdtemp(prefix="replay-process-inputs-"))
        except OSError:
            return self._snapshot_failure(
                events,
                code="process-snapshot-unavailable",
                message="A private policy process snapshot could not be created.",
            )

        snapshot_executable = snapshot_root / "executable" / executable_path.name
        snapshot_policy_tree = snapshot_root / "policy"
        snapshot_policy = snapshot_policy_tree / self.argv[-1]
        try:
            snapshot_executable.parent.mkdir()
            shutil.copy2(executable_path, snapshot_executable)
            for companion in executable_path.parent.iterdir():
                companion_name = companion.name.lower()
                if (
                    companion != executable_path
                    and companion.is_file()
                    and (
                        companion.suffix.lower() in {".dll", ".dylib", ".so"}
                        or ".so." in companion_name
                    )
                ):
                    shutil.copy2(
                        companion,
                        snapshot_executable.parent / companion.name,
                    )
            shutil.copytree(policy_tree_path, snapshot_policy_tree)
            actual_executable = sha256_file(snapshot_executable)
            actual_executable_bits = executable_bits(snapshot_executable)
            actual_policy = sha256_file(snapshot_policy)
            actual_tree = sha256_tree(snapshot_policy_tree)
        except (OSError, shutil.Error):
            return self._snapshot_failure(
                events,
                code="process-input-changed",
                message=(
                    "Bound policy process inputs became unavailable while their "
                    "private snapshot was created."
                ),
                snapshot_root=snapshot_root,
            )
        if (
            not snapshot_policy.is_file()
            or actual_executable != expected_executable
            or actual_executable_bits != expected_executable_bits
            or actual_policy != expected_policy
            or actual_tree != expected_tree
        ):
            return self._snapshot_failure(
                events,
                code="process-input-changed",
                message=(
                    "Bound policy process inputs changed before their private "
                    "snapshot was complete."
                ),
                snapshot_root=snapshot_root,
            )

        return _ProcessInputSnapshot(
            root=snapshot_root,
            argv=(
                str(snapshot_executable),
                *self.argv[1:-1],
                self.argv[-1],
            ),
            cwd=str(snapshot_policy_tree),
            executable_sha256=expected_executable,
            executable_bits=expected_executable_bits,
            policy_sha256=expected_policy,
            policy_tree_sha256=expected_tree,
        )

    def _evaluate_runtime(
        self,
        events: list[dict[str, Any]],
        *,
        argv: Sequence[str],
        cwd: str | None,
    ) -> PolicySourceResult:
        input_bytes = "".join(
            f"{json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}\n"
            for event in events
        ).encode("utf-8")
        try:
            completed = subprocess.run(
                list(argv),
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
                cwd=cwd,
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

    def evaluate(self, event_values: list[object]) -> PolicySourceResult:
        events = validate_command_events(event_values)
        snapshot_or_failure = self._prepare_input_snapshot(events)
        if isinstance(snapshot_or_failure, PolicySourceResult):
            return snapshot_or_failure
        snapshot = snapshot_or_failure
        argv = self.argv if snapshot is None else snapshot.argv
        cwd = self.cwd if snapshot is None else snapshot.cwd
        snapshot_failure = None if snapshot is None else snapshot.verification_failure()
        if snapshot_failure is not None:
            result = _all_indeterminate(events, snapshot_failure, "Process")
        else:
            try:
                result = self._evaluate_runtime(events, argv=argv, cwd=cwd)
            except BaseException:
                if snapshot is not None:
                    snapshot.cleanup()
                raise
        if snapshot is None:
            return result
        post_execution_failure = (
            None if snapshot_failure is not None else snapshot.verification_failure()
        )
        if post_execution_failure is not None:
            invalidated = _all_indeterminate(
                events,
                post_execution_failure,
                "Process",
                diagnostics=result.diagnostics,
            )
            result = PolicySourceResult(
                invalidated.decisions,
                result.failures + invalidated.failures,
                invalidated.diagnostics,
            )
        cleanup_failure = snapshot.cleanup()
        if cleanup_failure is None:
            return result
        return PolicySourceResult(
            result.decisions,
            result.failures + (cleanup_failure,),
            result.diagnostics,
        )
