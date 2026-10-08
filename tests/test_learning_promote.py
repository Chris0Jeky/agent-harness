"""Promotion-record generation: gate results in, the next legal record out."""

import copy
import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "learning_promote", ROOT / "scripts" / "learning_promote.py"
)
lp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)
lc = lp.contracts

EXAMPLES = ROOT / "schemas" / "learning" / "examples"
PRODUCER = {"lane": "steward", "runtime": "tool", "model": None, "session": "gen-1"}
ORACLE = {"kind": "oracle", "runtime": "tool", "model": None, "session": "eval-1"}
OWNER = {"kind": "owner", "runtime": "owner", "model": None, "session": "owner-1"}


def candidate(**changes):
    record = copy.deepcopy(lc.read_records(EXAMPLES / "learning-candidate.json")[0])
    record.update(changes)
    return record


def gate(name, at, result="pass", evaluator=ORACLE):
    item = {"gate": name, "result": result, "evaluator": evaluator, "at": at}
    if name in ("offline_eval", "replay", "retrieval_regression"):
        item.update(holdout_digest="f" * 64, training_excluded=True, anchors=[])
    if name == "owner":
        item["ref"] = "decision:test-1"
    return item


def advance(cand, records, gates, at):
    record = lp.next_record(cand, records, gates, PRODUCER, at)
    return records + [record], record


class GeneratorTests(unittest.TestCase):
    def test_walks_a_p4_candidate_to_active_in_shadow(self):
        cand, records = candidate(), []
        records, r = advance(cand, records, [], "2026-09-08T11:10:00Z")
        self.assertEqual((r["from"], r["to"]), ("candidate", "evaluating"))
        evaluation = [gate("offline_eval", "2026-09-08T12:00:00Z")]
        records, r = advance(cand, records, evaluation, "2026-09-08T12:01:00Z")
        self.assertEqual(r["to"], "canary")
        records, r = advance(
            cand,
            records,
            [gate("canary", "2026-09-09T12:00:00Z")],
            "2026-09-09T12:01:00Z",
        )
        self.assertEqual(r["to"], "probation")
        records, r = advance(
            cand,
            records,
            [gate("maturity", "2026-09-16T12:05:00Z")],
            "2026-09-16T12:06:00Z",
        )
        self.assertEqual(r["to"], "active")
        result = lc.fold(cand, records)
        self.assertEqual(
            (result.state, result.effect, result.errors), ("active", "shadow", [])
        )
        self.assertTrue(all(rec["effect"] == "shadow" for rec in records))

    def test_classes_without_canary_go_straight_to_probation(self):
        cand = candidate(kind="skill", promotion_class="P3")
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        _, r = advance(
            cand,
            records,
            [gate("offline_eval", "2026-09-08T12:00:00Z")],
            "2026-09-08T12:01:00Z",
        )
        self.assertEqual(r["to"], "probation")

    def test_p0_activates_directly(self):
        cand = candidate(kind="episodic", promotion_class="P0", destination=None)
        _, r = advance(cand, [], [], "2026-09-08T11:10:00Z")
        self.assertEqual(r["to"], "active")

    def test_a_failed_gate_rejects(self):
        cand, records = candidate(), []
        records, _ = advance(cand, records, [], "2026-09-08T11:10:00Z")
        failed = [gate("offline_eval", "2026-09-08T12:00:00Z", result="fail")]
        _, r = advance(cand, records, failed, "2026-09-08T12:01:00Z")
        self.assertEqual(r["to"], "rejected")

    def test_missing_gates_are_refused_by_name(self):
        cand = candidate()
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.next_record(cand, records, [], PRODUCER, "2026-09-08T12:01:00Z")
        self.assertIn("awaits offline_eval", str(caught.exception))

    def test_the_fold_has_the_last_word(self):
        cand = candidate()
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        early = [
            gate("offline_eval", "2026-09-08T11:00:00Z")
        ]  # before evaluating began
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.next_record(cand, records, early, PRODUCER, "2026-09-08T12:01:00Z")
        self.assertIn("fold refuses", str(caught.exception))
        learner = dict(ORACLE, session=cand["producer"]["session"])
        records = [records[0]]
        records, _ = advance(
            cand,
            records,
            [gate("offline_eval", "2026-09-08T12:00:00Z")],
            "2026-09-08T12:01:00Z",
        )
        records, _ = advance(
            cand,
            records,
            [gate("canary", "2026-09-09T12:00:00Z", evaluator=learner)],
            "2026-09-09T12:01:00Z",
        )
        with self.assertRaises(lp.PromotionRefusal):
            lp.next_record(
                cand,
                records,
                [gate("maturity", "2026-09-16T12:05:00Z")],
                PRODUCER,
                "2026-09-16T12:06:00Z",
            )

    def test_p8_needs_the_owner_on_the_activating_record(self):
        cand = candidate(kind="policy", promotion_class="P8")
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        records, _ = advance(
            cand,
            records,
            [gate("tests", "2026-09-08T12:00:00Z")],
            "2026-09-08T12:01:00Z",
        )
        with self.assertRaises(lp.PromotionRefusal):
            lp.next_record(
                cand,
                records,
                [gate("maturity", "2026-09-15T12:05:00Z")],
                PRODUCER,
                "2026-09-15T12:06:00Z",
            )
        owner = [
            gate("maturity", "2026-09-15T12:05:00Z"),
            gate("owner", "2026-09-15T12:05:00Z", evaluator=OWNER),
        ]
        _, r = advance(cand, records, owner, "2026-09-15T12:06:00Z")
        self.assertEqual(r["to"], "active")

    def test_steward_moves_are_never_generated(self):
        cand = candidate(kind="episodic", promotion_class="P0", destination=None)
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.next_record(cand, records, [], PRODUCER, "2026-09-09T00:00:00Z")
        self.assertIn("steward", str(caught.exception))

    def test_retries_are_byte_identical(self):
        cand = candidate()
        first = lp.next_record(cand, [], [], PRODUCER, "2026-09-08T11:10:00Z")
        again = lp.next_record(cand, [], [], PRODUCER, "2026-09-08T11:10:00Z")
        self.assertEqual(first, again)
        self.assertEqual(lc.fold(cand, [first, again]).errors, [])

    def test_a_broken_chain_is_refused(self):
        cand = candidate()
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        twin = dict(records[0], id="prom_other-0001", to="rejected")
        with self.assertRaises(lp.PromotionRefusal):
            lp.next_record(cand, records + [twin], [], PRODUCER, "2026-09-08T12:00:00Z")

    def test_eval_runs_without_a_gate_are_refused(self):
        with self.assertRaises(lp.PromotionRefusal):
            lp.gate_results([{"gate": "offline_eval"}])


class CommandLineTests(unittest.TestCase):
    def test_cli_prints_a_record_and_refuses_with_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, err = io.StringIO(), io.StringIO()
            argv = [
                "--candidate",
                str(EXAMPLES / "learning-candidate.json"),
                "--lane",
                "steward",
                "--session",
                "gen-1",
                "--at",
                "2026-09-08T11:10:00Z",
            ]
            with redirect_stdout(out), redirect_stderr(err):
                code = lp.main(argv)
            self.assertEqual(code, 0)
            record = json.loads(out.getvalue())
            self.assertEqual(
                (record["to"], lc.validate_record(record)), ("evaluating", [])
            )
            path = Path(tmp) / "records.jsonl"
            path.write_text(json.dumps(record) + "\n", "utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = lp.main(argv[:2] + ["--records", str(path)] + argv[2:])
            self.assertEqual(code, 2)
            self.assertIn("awaits offline_eval", err.getvalue())


if __name__ == "__main__":
    unittest.main()
