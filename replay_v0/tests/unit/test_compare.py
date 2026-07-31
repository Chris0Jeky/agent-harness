from __future__ import annotations

import unittest

from replay_v0.compare import ComparisonError, compare_decisions
from replay_v0.reports import (
    DECISION_REPLAY_LIMITATION,
    build_json_report,
    render_markdown_report,
)

EFFECTS = [
    ("unchanged-allow", "allow", "allow", "unchanged"),
    ("unchanged-deny", "deny", "deny", "unchanged"),
    ("newly-allowed", "deny", "allow", "newly-allowed"),
    ("newly-denied", "allow", "deny", "newly-denied"),
    ("newly-indeterminate", "allow", "indeterminate", "newly-indeterminate"),
    (
        "resolved-indeterminate",
        "indeterminate",
        "deny",
        "resolved-indeterminate",
    ),
]


def event(event_id: str) -> dict[str, str]:
    return {
        "schema_version": "command-event.v1",
        "event_id": event_id,
        "timestamp": "2026-07-30T12:00:00Z",
        "command": f"echo fictional {event_id}",
        "source": "synthetic",
    }


def decision(event_id: str, effect: str, policy: str) -> dict[str, str]:
    return {
        "schema_version": "policy-decision.v1",
        "event_id": event_id,
        "effect": effect,
        "reason": f"{policy} returned {effect} for the synthetic fixture.",
    }


def charter_case(event_id: str) -> dict[str, str]:
    return {
        "schema_version": "charter-case.v1",
        "event_id": event_id,
        "case_class": "opaque",
        "case_family": "synthetic-comparison",
        "rationale": "This fixture tests effect comparison only.",
        "provenance": "synthetic",
    }


class ComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events = [event(row[0]) for row in EFFECTS]
        self.baseline = [decision(row[0], row[1], "baseline") for row in EFFECTS]
        self.candidate = [decision(row[0], row[2], "candidate") for row in EFFECTS]
        self.cases = [charter_case(row[0]) for row in EFFECTS]

    def test_all_five_classes_follow_corpus_order_and_preserve_reasons(self) -> None:
        result = compare_decisions(
            self.events,
            list(reversed(self.baseline)),
            list(reversed(self.candidate)),
            case_values=list(reversed(self.cases)),
        )
        self.assertEqual(
            [row[0] for row in EFFECTS],
            [row.event["event_id"] for row in result.results],
        )
        self.assertEqual(
            [row[3] for row in EFFECTS],
            [row.classification for row in result.results],
        )
        self.assertEqual(
            {
                "unchanged": 2,
                "newly-allowed": 1,
                "newly-denied": 1,
                "newly-indeterminate": 1,
                "resolved-indeterminate": 1,
            },
            result.counts,
        )
        self.assertEqual(
            "candidate returned allow for the synthetic fixture.",
            result.results[2].candidate["reason"],
        )
        self.assertEqual("opaque", result.results[0].case["case_class"])

    def test_command_text_and_charter_class_do_not_drive_classification(self) -> None:
        events = [
            {**self.events[0], "command": "git push origin main --force"},
        ]
        cases = [{**self.cases[0], "case_class": "dangerous"}]
        result = compare_decisions(
            events, [self.baseline[0]], [self.candidate[0]], case_values=cases
        )
        self.assertEqual("unchanged", result.results[0].classification)

    def test_missing_or_unexpected_decisions_and_cases_fail(self) -> None:
        with self.assertRaisesRegex(ComparisonError, "missing"):
            compare_decisions(self.events, self.baseline[:-1], self.candidate)
        unexpected = decision("unexpected", "allow", "candidate")
        with self.assertRaisesRegex(ComparisonError, "unexpected"):
            compare_decisions(self.events, self.baseline, [*self.candidate, unexpected])
        with self.assertRaisesRegex(ComparisonError, "charter cases"):
            compare_decisions(
                self.events,
                self.baseline,
                self.candidate,
                case_values=self.cases[:-1],
            )

    def test_json_and_markdown_report_state_limits_and_operational_identity(
        self,
    ) -> None:
        comparison = compare_decisions(
            self.events, self.baseline, self.candidate, case_values=self.cases
        )
        manifest = {
            "run_id": "f" * 64,
            "generated_at": "2026-07-30T12:00:00Z",
            "baseline": {
                "kind": "recorded",
                "id": "floor-v1-final",
                "sha256": "1" * 64,
            },
            "candidate": {
                "kind": "process",
                "id": "candidate-policy",
                "sha256": "2" * 64,
            },
            "corpus": {
                "id": "charter-v0.1",
                "manifest_sha256": "3" * 64,
                "event_count": len(self.events),
            },
            "fail_on": ["newly-allowed", "newly-indeterminate"],
        }
        report = build_json_report(comparison, manifest)
        self.assertEqual("fail", report["gate"]["status"])
        self.assertEqual(
            ["newly-allowed", "newly-indeterminate"],
            report["gate"]["triggered"],
        )
        self.assertEqual(len(self.events), len(report["results"]))
        self.assertIn(DECISION_REPLAY_LIMITATION, report["limitations"])
        self.assertNotIn("reproduction_command", report)

        command = "python -m replay_v0.cli replay --corpus fictional"
        markdown = render_markdown_report(report, reproduction_command=command)
        opening = markdown.split("## Event results", maxsplit=1)[0]
        for expected in (
            "Counts:",
            "Gate: **FAIL**",
            "Baseline: `floor-v1-final`",
            "Candidate: `candidate-policy`",
            "Corpus: `charter-v0.1`",
            "Reproduce:",
        ):
            self.assertIn(expected, opening)
        self.assertIn(command, opening)
        self.assertIn(DECISION_REPLAY_LIMITATION, markdown)


if __name__ == "__main__":
    unittest.main()
