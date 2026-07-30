from __future__ import annotations

import json
from pathlib import Path
import unittest

from replay_v0.corpus import (
    ValidationError,
    validate_charter_case,
    validate_charter_cases,
    validate_command_event,
    validate_command_events,
    validate_policy_decision,
)

VALID_EVENT = {
    "schema_version": "command-event.v1",
    "event_id": "git-force-main-001",
    "timestamp": "2026-07-30T12:00:00Z",
    "command": "git push origin main --force",
    "cwd": "/fictional/shop-api",
    "source": "synthetic",
}

VALID_DECISION = {
    "schema_version": "policy-decision.v1",
    "event_id": "git-force-main-001",
    "effect": "deny",
    "reason": "The recorded baseline denied this event.",
}

VALID_CASE = {
    "schema_version": "charter-case.v1",
    "event_id": "git-force-main-001",
    "case_class": "dangerous",
    "case_family": "shared-history-rewrite",
    "rationale": "A force push can rewrite shared history.",
    "provenance": "synthetic",
}


class SchemaContractTests(unittest.TestCase):
    def assert_validation_error(self, expected: str, callback) -> None:
        with self.assertRaisesRegex(ValidationError, f"^{expected}$"):
            callback()

    def test_valid_records_round_trip_without_mutation(self) -> None:
        for value, validator in (
            (VALID_EVENT, validate_command_event),
            (VALID_DECISION, validate_policy_decision),
            (VALID_CASE, validate_charter_case),
        ):
            result = validator(value)
            self.assertEqual(value, result)
            self.assertIsNot(value, result)

    def test_command_event_cwd_is_optional(self) -> None:
        event = {key: value for key, value in VALID_EVENT.items() if key != "cwd"}
        self.assertNotIn("cwd", validate_command_event(event))

    def test_missing_identity_fields_fail_in_contract_order(self) -> None:
        event = {
            key: value
            for key, value in VALID_EVENT.items()
            if key not in {"schema_version", "event_id", "timestamp"}
        }
        self.assert_validation_error(
            r"CommandEvent: missing required field\(s\): "
            r"schema_version, event_id, timestamp",
            lambda: validate_command_event(event),
        )

    def test_extra_event_fields_fail_deterministically(self) -> None:
        event = {**VALID_EVENT, "adapter": "legacy", "confidence": 1}
        self.assert_validation_error(
            r"CommandEvent: unexpected field\(s\): adapter, confidence",
            lambda: validate_command_event(event),
        )

    def test_timestamp_requires_valid_rfc3339_utc(self) -> None:
        for timestamp, expected in (
            (
                "2026-07-30T13:00:00+01:00",
                "CommandEvent.timestamp: expected an RFC 3339 UTC timestamp ending in Z",
            ),
            (
                "2026-02-30T12:00:00Z",
                "CommandEvent.timestamp: expected a valid calendar timestamp",
            ),
        ):
            with self.subTest(timestamp=timestamp):
                event = {**VALID_EVENT, "timestamp": timestamp}
                self.assert_validation_error(
                    expected, lambda: validate_command_event(event)
                )

    def test_event_source_is_closed(self) -> None:
        event = {**VALID_EVENT, "source": "transcript"}
        self.assert_validation_error(
            "CommandEvent.source: expected one of: "
            "generated-variant, historical-redacted, synthetic",
            lambda: validate_command_event(event),
        )

    def test_policy_effect_is_closed(self) -> None:
        decision = {**VALID_DECISION, "effect": "warn"}
        self.assert_validation_error(
            "PolicyDecision.effect: expected one of: allow, deny, indeterminate",
            lambda: validate_policy_decision(decision),
        )

    def test_policy_reason_is_single_line_and_bounded(self) -> None:
        for reason, expected in (
            (
                "line one\nline two",
                "PolicyDecision.reason: must be a single line",
            ),
            (
                "x" * 501,
                "PolicyDecision.reason: must be at most 500 characters",
            ),
        ):
            with self.subTest(expected=expected):
                decision = {**VALID_DECISION, "reason": reason}
                self.assert_validation_error(
                    expected, lambda: validate_policy_decision(decision)
                )

    def test_charter_class_is_closed(self) -> None:
        case = {**VALID_CASE, "case_class": "safe"}
        self.assert_validation_error(
            "CharterCase.case_class: expected one of: benign, dangerous, opaque",
            lambda: validate_charter_case(case),
        )

    def test_duplicate_event_ids_fail_for_ordered_collections(self) -> None:
        self.assert_validation_error(
            "CommandEvent corpus: duplicate event_id 'git-force-main-001'",
            lambda: validate_command_events([VALID_EVENT, VALID_EVENT]),
        )
        self.assert_validation_error(
            "CharterCase corpus: duplicate event_id 'git-force-main-001'",
            lambda: validate_charter_cases([VALID_CASE, VALID_CASE]),
        )

    def test_event_and_case_corpora_must_not_be_empty(self) -> None:
        self.assert_validation_error(
            "CommandEvent corpus: expected at least one record",
            lambda: validate_command_events([]),
        )
        self.assert_validation_error(
            "CharterCase corpus: expected at least one record",
            lambda: validate_charter_cases([]),
        )
        self.assertEqual([VALID_EVENT], validate_command_events([VALID_EVENT]))
        self.assertEqual([VALID_CASE], validate_charter_cases([VALID_CASE]))

    def test_schema_documents_are_strict_and_loadable(self) -> None:
        schema_dir = Path(__file__).parents[2] / "schemas"
        expected = {
            "command-event.v1.schema.json",
            "policy-decision.v1.schema.json",
            "charter-case.v1.schema.json",
        }
        self.assertEqual(expected, {path.name for path in schema_dir.glob("*.json")})
        for path in schema_dir.glob("*.json"):
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual("object", schema["type"])
                self.assertIs(False, schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
