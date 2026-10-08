"""Synthetic outcome history: one stream, replacement reducers and durable cursors."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "learning_outcomes", ROOT / "scripts" / "learning_outcomes.py"
)
outcomes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(outcomes)
lc = outcomes.contracts


def experience(key="run-1", day=1, immediate="published", matured=None):
    return {
        "schema": "estate-experience/v1",
        "id": lc.experience_id("muse-job", key),
        "at": "2026-09-01T00:00:00Z",
        "observed_at": f"2026-09-{day:02d}T00:00:00Z",
        "producer": {
            "lane": "synthetic",
            "runtime": "muse",
            "model": "synthetic-model",
            "session": "synthetic-session",
        },
        "source": {"kind": "muse-job", "key": key},
        "repo": "example",
        "task_kind": "review",
        "recipe": "test-gaps",
        "outcome": {
            "immediate": immediate,
            "matured": matured,
            "regression": matured == "reverted" if matured else None,
        },
    }


def feedback(kind, signal, key=None):
    item = {"kind": kind, "signal": signal, "ref": "decision:synthetic"}
    if key is not None:
        item["key"] = key
    return item


def history():
    published = experience()
    merged = experience(day=8, immediate="merged", matured="clean")
    reverted = experience(day=9, immediate="merged", matured="reverted")
    reverted["feedback"] = [
        feedback("owner_correction", "corrected", "missed-regression")
    ]
    reverted["failure_keys"] = ["missed-regression"]
    unchanged = copy.deepcopy(reverted)
    unchanged["observed_at"] = "2026-09-10T00:00:00Z"
    return [published, merged, reverted, unchanged]


class OutcomeTests(unittest.TestCase):
    def project(self, records):
        events, problems = outcomes.events_from_experiences(records)
        self.assertEqual(problems, [])
        for event in events:
            self.assertEqual(lc.validate_record(event), [], event)
        return events

    def test_versions_chain_and_unchanged_observation(self):
        records = history()
        events = self.project(records)
        self.assertEqual([event["version"] for event in events], [1, 2, 3])
        self.assertEqual(
            [event["supersedes"] for event in events],
            [None, events[0]["id"], events[1]["id"]],
        )
        self.assertEqual([event["success"] for event in events], [True, True, False])
        self.assertEqual(events[-1]["observed_at"], records[2]["observed_at"])
        self.assertEqual(events[0]["run"], records[0]["source"])
        self.assertEqual(events[0]["runtime"], "muse")
        self.assertEqual(events[0]["model"], "synthetic-model")
        self.assertEqual(events[0]["recipe"], "test-gaps")
        self.assertIsNone(events[0]["variant"])
        # The event snapshots do not retain references into the source records.
        records[0]["outcome"]["immediate"] = "failed"
        records[0]["source"]["key"] = "edited"
        records[0]["producer"]["model"] = "edited"
        self.assertEqual(events[0]["outcome"]["immediate"], "published")
        self.assertEqual(events[0]["run"]["key"], "run-1")
        self.assertEqual(events[0]["producer"]["model"], "synthetic-model")

    def test_late_regression_revises_all_consumers_and_cursor(self):
        records = history()
        other = experience("other-run")
        other["repo"] = "another-repo"
        other["feedback"] = [
            feedback("owner_correction", "corrected", "missed-regression")
        ]
        other["failure_keys"] = ["missed-regression"]
        before = self.project([other, *records[:2]])
        initial = {"observed_at": None, "id": None}
        _, cursor = outcomes.read_since(before, initial)
        self.assertEqual(outcomes.posterior(before, "example", "test-gaps"), (2, 1))
        for field in ("corrections", "failure_keys"):
            self.assertEqual(outcomes.recurrences(before, field), set())
        after = self.project([other, *records])
        self.assertEqual(outcomes.posterior(after, "example", "test-gaps"), (1, 2))
        self.assertIn("muse-job|run-1", outcomes.lesson_eligible(after))
        for field in ("corrections", "failure_keys"):
            self.assertEqual(outcomes.recurrences(after, field), {"missed-regression"})
        arrived, advanced = outcomes.read_since(after, cursor)
        self.assertEqual([event["version"] for event in arrived], [3])
        self.assertEqual(outcomes.read_since(after, cursor), (arrived, advanced))
        self.assertEqual(outcomes.read_since(after, advanced), ([], advanced))
        self.assertEqual(outcomes.latest(reversed(after))["muse-job|run-1"], arrived[0])

    def test_only_clean_merges_count_and_triage_signals_are_counted_once(self):
        merged = experience(immediate="merged")
        merged["feedback"] = [
            feedback("triage_verdict", "confirmed"),
            feedback("triage_verdict", "confirmed"),
            feedback("triage_verdict", "refuted"),
            feedback("triage_verdict", "unclassified"),
            feedback("review_verdict", "confirmed"),
        ]
        events = self.project([merged])
        self.assertEqual(events[0]["verdicts"], {"confirmed": 2, "refuted": 1})
        self.assertEqual(outcomes.posterior(events, "example", "test-gaps"), (3, 2))
        self.assertEqual(outcomes.lesson_eligible(events), set())
        clean = copy.deepcopy(merged)
        clean["observed_at"] = "2026-09-08T00:00:00Z"
        clean["outcome"]["matured"] = "clean"
        events = self.project([merged, clean])
        self.assertEqual(outcomes.posterior(events, "example", "test-gaps"), (4, 2))
        self.assertEqual(outcomes.posterior(events, "example", "another"), (1, 1))
        self.assertEqual(outcomes.posterior(events, "another", "test-gaps"), (1, 1))
        self.assertEqual(outcomes.lesson_eligible(events), {"muse-job|run-1"})

    def test_identity_drift_is_skipped_and_reported_like_the_fold(self):
        for field in ("split_key", "variant", "source"):
            with self.subTest(field=field):
                first = experience()
                first["variant"] = "baseline:synthetic"
                changed = copy.deepcopy(first)
                changed["observed_at"] = "2026-09-08T00:00:00Z"
                changed["outcome"]["immediate"] = "failed"
                changed[field] = {
                    "split_key": "different-split",
                    "variant": "gen:other",
                    "source": {"kind": "muse-job", "key": "different-source"},
                }[field]
                valid_later = experience(day=9, immediate="merged", matured="clean")
                valid_later["variant"] = first["variant"]
                records = [first, changed, valid_later]
                events, problems = outcomes.events_from_experiences(records)
                _, fold_problems = lc.fold_experiences(records)
                self.assertEqual(problems, fold_problems)
                self.assertTrue(problems)
                self.assertEqual([event["version"] for event in events], [1, 2])
                self.assertEqual(events[-1]["outcome"]["matured"], "clean")
                self.assertEqual(events[-1]["variant"], first["variant"])

    def test_event_semantics_reject_hand_edits(self):
        event = self.project(history())[1]
        changes = [
            {"id": "oev_" + "0" * 16},
            {"experience": "exp_" + "0" * 16},
            {"success": False},
            {"supersedes": None},
            {"supersedes": "oev_" + "0" * 16},  # not this run's previous version
            {"observed_at": "2026-08-01T00:00:00Z"},
            {"observed_at": "2026-02-30T00:00:00Z"},
            {"unexpected": True},
        ]
        for change in changes:
            with self.subTest(change=change):
                edited = copy.deepcopy(event)
                edited.update(change)
                self.assertTrue(lc.validate_record(edited))
        first = self.project(history())[0]
        first["supersedes"] = event["id"]
        self.assertTrue(lc.validate_record(first))
        schema = lc._document("outcome-event.schema.json")
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        for field in schema["required"]:
            edited = copy.deepcopy(event)
            del edited[field]
            self.assertTrue(lc.validate_record(edited), field)

    def test_each_feedback_projection_change_emits_a_version(self):
        records = [experience()]
        for day, field, value in (
            (2, "feedback", [feedback("triage_verdict", "confirmed")]),
            (3, "feedback", [feedback("owner_correction", "corrected", "key")]),
            (4, "failure_keys", ["failure"]),
        ):
            record = copy.deepcopy(records[-1])
            record["observed_at"] = f"2026-09-{day:02d}T00:00:00Z"
            record[field] = value
            records.append(record)
        events = self.project(records)
        self.assertEqual([event["version"] for event in events], [1, 2, 3, 4])
        self.assertEqual(events[1]["verdicts"]["confirmed"], 1)
        self.assertEqual(events[2]["corrections"], ["key"])
        self.assertEqual(events[3]["failure_keys"], ["failure"])

    def test_invalid_inputs_are_reported_without_projection(self):
        for record in (42, [], {}, {**experience(), "id": []}):
            with self.subTest(record=record):
                events, problems = outcomes.events_from_experiences([record])
                self.assertEqual(events, [])
                self.assertTrue(problems)
        minimal = experience()
        del minimal["recipe"]
        minimal["producer"]["model"] = None
        event = self.project([minimal])[0]
        self.assertIsNone(event["recipe"])
        self.assertIsNone(event["model"])

    def test_determinism_and_content_only_versioning(self):
        records = history()
        records.append(experience("another-run"))
        first = self.project(records)
        second = self.project(reversed(records))
        self.assertEqual(lc._canonical(first), lc._canonical(second))
        self.assertEqual(lc._canonical(first), lc._canonical(self.project(records)))
        observation = experience()
        observation["feedback"] = [
            feedback("owner_correction", "corrected", "z-key"),
            feedback("owner_correction", "corrected", "a-key"),
            feedback("owner_correction", "corrected", "a-key"),
            feedback("owner_correction", "corrected"),
        ]
        observation["failure_keys"] = ["z-key", "a-key"]
        later = copy.deepcopy(observation)
        later["observed_at"] = "2026-09-02T00:00:00Z"
        later["feedback"].reverse()
        later["failure_keys"].reverse()
        later["producer"]["session"] = "changed-session"
        later["cost"] = {"tokens": None, "seconds": 4}
        events = self.project([observation, later])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["corrections"], ["a-key", "z-key"])
        self.assertEqual(events[0]["failure_keys"], ["a-key", "z-key"])
        self.assertEqual(outcomes.lesson_eligible(events), {"muse-job|run-1"})
        self.assertEqual(outcomes.recurrences(events, "corrections"), set())
        with self.assertRaises(ValueError):
            outcomes.recurrences(events, "outcome")

    def test_cursors_order_instants_and_break_ties_by_id(self):
        early = experience("early")
        early["observed_at"] = "2026-09-01T00:00:00Z"
        late = experience("late")
        late["observed_at"] = "2026-09-01T00:00:00.1Z"
        same_time = experience("same-time")
        events = self.project([late, same_time, early])
        self.assertEqual(events[-1]["run"]["key"], "late")
        self.assertLess(events[0]["id"], events[1]["id"])
        cursor = {"observed_at": events[0]["observed_at"], "id": events[0]["id"]}
        arrived, _ = outcomes.read_since(reversed(events), cursor)
        self.assertEqual(arrived, events[1:])
        empty = {"observed_at": None, "id": None}
        self.assertEqual(outcomes.read_since([], empty), ([], empty))
        for invalid in (
            {"observed_at": None, "id": events[0]["id"]},
            {"observed_at": "bad", "id": events[0]["id"]},
        ):
            with self.assertRaises(ValueError):
                outcomes.read_since(events, invalid)

    def test_cli_success_and_refusal_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "experiences.jsonl"
            target = Path(directory) / "events.jsonl"
            source.write_text(
                "".join(lc._canonical(record) + "\n" for record in history()),
                encoding="utf-8",
            )
            stdout = self.cli("project", str(source))
            self.assertEqual(stdout.returncode, 0, stdout.stderr)
            self.assertEqual(stdout.stderr, "")
            projected = [json.loads(line) for line in stdout.stdout.splitlines()]
            self.assertEqual(projected, self.project(history()))
            written = self.cli("project", str(source), "--out", str(target))
            self.assertEqual(written.returncode, 0, written.stderr)
            self.assertEqual(written.stdout, "")
            self.assertEqual(target.read_bytes(), stdout.stdout.encode("utf-8"))
            result = self.cli(
                "posterior",
                "--events",
                str(target),
                "--repo",
                "example",
                "--recipe",
                "test-gaps",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"alpha": 1, "beta": 2})
            bad = history()
            bad[-1]["split_key"] = "changed"
            source = source.with_suffix(".json")
            source.write_text(json.dumps(bad), encoding="utf-8")
            preserved = target.read_bytes()
            refused = self.cli("project", str(source), "--out", str(target))
            self.assert_refusal(refused)
            self.assertEqual(target.read_bytes(), preserved)
            source.write_text("{broken JSON", encoding="utf-8")
            self.assert_refusal(self.cli("project", str(source)))
            self.assert_refusal(self.cli("project", str(source.with_name("missing"))))
            source.write_text("[42]", encoding="utf-8")
            self.assert_refusal(self.cli("project", str(source)))
            projected[0]["success"] = False
            target_json = target.with_suffix(".json")
            target_json.write_text(json.dumps(projected), encoding="utf-8")
            self.assert_refusal(
                self.cli(
                    "posterior",
                    "--events",
                    str(target_json),
                    "--repo",
                    "example",
                    "--recipe",
                    "test-gaps",
                )
            )

    def cli(self, *arguments):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "learning_outcomes.py"),
                *arguments,
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def assert_refusal(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["status"], "refused")


class StreamTests(unittest.TestCase):
    def test_a_gapped_or_duplicated_stream_is_refused(self):
        events, problems = outcomes.events_from_experiences(history())
        self.assertEqual((problems, outcomes.stream_errors(events)), ([], []))
        gapped = [e for e in events if e["version"] != 2]
        self.assertIn("are not 1..", outcomes.stream_errors(gapped)[0])
        self.assertIn("appears twice", outcomes.stream_errors(events + events[:1])[0])


if __name__ == "__main__":
    unittest.main()
