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


# A destination each kind may really write (K2: class is the blast radius).
SURFACES = {
    "semantic": {"repo": "claude-config", "path": "projects/example/memory/lesson.md"},
    "consolidation": {
        "repo": "claude-config",
        "path": "projects/example/memory/lesson.md",
    },
    "skill": {"repo": "claude-config", "path": "skills/example-skill/SKILL.md"},
    "recipe": {"repo": "claude-config", "path": "muse/recipes/test-gaps.md"},
    "prompt": {"repo": "claude-config", "path": "muse/coordinator-turn.md"},
    "routing": {"repo": "claude-config", "path": "muse/agent-routes.json"},
    "scheduler": {"repo": "claude-config", "path": "tools/muse_coordinator.py"},
    "harness": {"repo": "claude-config", "path": "tools/example_tool.py"},
    "policy": {"repo": "claude-config", "path": "rules/laws.md"},
    "episodic": None,
}


def candidate(**changes):
    record = copy.deepcopy(lc.read_records(EXAMPLES / "learning-candidate.json")[0])
    if "genome" not in changes:  # genome exclusion has its own tests
        record.pop("genome", None)
    if "kind" in changes and "destination" not in changes:
        changes["destination"] = SURFACES[changes["kind"]]
    record.update(changes)
    return record


def gate(name, at, result="pass", evaluator=ORACLE):
    item = {"gate": name, "result": result, "evaluator": evaluator, "at": at}
    if name in ("offline_eval", "replay", "retrieval_regression"):
        item.update(
            holdout_digest="f" * 64,
            training_excluded=True,
            anchors=[],
            metrics={"cases": 20, "delta": 0.1, "wins": 8, "losses": 0, "anchored": 20},
            salt_draw={"source": "agent-hq@" + "5" * 40, "at": at},
        )
    if name == "owner":
        item["ref"] = "decision:test-1"
    return item


# The owner's approval of lc_example-0001, as a resolver reading agent-hq returns it.
APPROVAL = {
    "schema": "decision-resolution/v1",
    "decision": "test-1",
    "source": "agent-hq@" + "d" * 40,
    "status": "answered",
    "option": "approve",
    "answered_at": "2026-09-01T00:00:00Z",
    "created": "2026-08-30T00:00:00Z",
    "expires": None,
    "subject": {"candidate": "lc_example-0001"},
    "measures": {"exit_bars": {}, "graduation": {}},
}
RESOLVE = lc.resolver_from([APPROVAL])


def advance(cand, records, gates, at):
    record = lp.next_record(cand, records, gates, PRODUCER, at, resolve=RESOLVE)
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

    def test_the_maturity_clock_produces_the_shadow_maturity_gate(self):
        cand, records = candidate(), []
        records, _ = advance(cand, records, [], "2026-09-08T11:10:00Z")
        records, _ = advance(
            cand,
            records,
            [gate("offline_eval", "2026-09-08T12:00:00Z")],
            "2026-09-08T12:01:00Z",
        )
        records, r = advance(
            cand,
            records,
            [gate("canary", "2026-09-09T12:00:00Z")],
            "2026-09-09T12:01:00Z",
        )
        self.assertEqual(r["to"], "probation")
        with self.assertRaises(lp.PromotionRefusal):
            lp.clock_maturity_gate(cand, records, "2026-09-15T12:00:00Z")  # 6 days
        clock = lp.clock_maturity_gate(cand, records, "2026-09-16T12:05:00Z")
        self.assertEqual((clock["result"], clock["ref"]), ("pass", f"prom:{r['id']}"))
        records, r = advance(cand, records, [clock], "2026-09-16T12:06:00Z")
        self.assertEqual(r["to"], "active")
        failed = lp.clock_maturity_gate(
            cand, records[:-1], "2026-09-16T12:05:00Z", regressed=True
        )
        self.assertEqual(failed["result"], "fail")

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
        self.assertIn("awaits a counted pass of offline_eval", str(caught.exception))

    def test_a_failure_while_still_a_candidate_rejects(self):
        cand = candidate(kind="semantic", promotion_class="P1", protected=True)
        refusal = [
            gate("owner", "2026-09-08T11:05:00Z", result="fail", evaluator=OWNER)
        ]
        _, r = advance(cand, [], refusal, "2026-09-08T11:10:00Z")
        self.assertEqual((r["from"], r["to"]), ("candidate", "rejected"))

    def test_an_uncounted_extra_gate_cannot_vouch_for_a_judge(self):
        cand = candidate()  # P4: offline_eval is its only evaluation gate
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        judge = {"kind": "llm_judge", "runtime": "grok", "model": "m", "session": "j"}
        learner = dict(ORACLE, session=cand["producer"]["session"])
        mixed = [
            gate("offline_eval", "2026-09-08T12:00:00Z", evaluator=judge),
            gate("tests", "2026-09-08T12:00:00Z", evaluator=learner),
        ]
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.next_record(cand, records, mixed, PRODUCER, "2026-09-08T12:01:00Z")
        self.assertIn("not only an LLM judge", str(caught.exception))

    def test_the_fold_has_the_last_word(self):
        cand = candidate()
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        early = [
            gate("offline_eval", "2026-09-08T11:00:00Z")
        ]  # before evaluating began
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.next_record(cand, records, early, PRODUCER, "2026-09-08T12:01:00Z")
        self.assertIn("fold refuses", str(caught.exception))

    def test_gates_that_would_not_count_never_move_a_candidate(self):
        cand = candidate()
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        learner = dict(ORACLE, session=cand["producer"]["session"])
        judge = {"kind": "llm_judge", "runtime": "grok", "model": "m", "session": "j"}
        for evaluator, words in (
            (learner, "counted pass"),
            (judge, "not only an LLM judge"),
        ):
            with self.assertRaises(lp.PromotionRefusal) as caught:
                lp.next_record(
                    cand,
                    records,
                    [gate("offline_eval", "2026-09-08T12:00:00Z", evaluator=evaluator)],
                    PRODUCER,
                    "2026-09-08T12:01:00Z",
                )
            self.assertIn(words, str(caught.exception))
        records, _ = advance(
            cand,
            records,
            [gate("offline_eval", "2026-09-08T12:00:00Z")],
            "2026-09-08T12:01:00Z",
        )
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.next_record(
                cand,
                records,
                [gate("canary", "2026-09-09T12:00:00Z", evaluator=learner)],
                PRODUCER,
                "2026-09-09T12:01:00Z",
            )
        self.assertIn("counted canary result", str(caught.exception))

    def test_future_records_are_refused(self):
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.next_record(candidate(), [], [], PRODUCER, "2999-01-01T00:00:00Z")
        self.assertIn("not a past contract instant", str(caught.exception))

    def test_malformed_gates_are_refusals(self):
        for bad in ({}, None, {"gate": "offline_eval"}):
            with self.assertRaises(lp.PromotionRefusal):
                lp.next_record(candidate(), [], [bad], PRODUCER, "2026-09-08T11:10:00Z")

    def test_a_live_candidate_is_never_moved_by_the_generator(self):
        cand = candidate(kind="episodic", promotion_class="P0", destination=None)
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        records[0]["effect"] = "live"  # P0 is the one class live without authority
        self.assertEqual(lc.fold(cand, records).effect, "live")
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.next_record(cand, records, [], PRODUCER, "2026-09-09T12:01:00Z")
        self.assertIn("owner's records", str(caught.exception))

    def test_gate_order_does_not_change_the_record(self):
        cand = candidate(kind="policy", promotion_class="P8")
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        records, _ = advance(
            cand,
            records,
            [gate("tests", "2026-09-08T12:00:00Z")],
            "2026-09-08T12:01:00Z",
        )
        pair = [
            gate("maturity", "2026-09-15T12:05:00Z"),
            gate("owner", "2026-09-15T12:05:00Z", evaluator=OWNER),
        ]
        one = lp.next_record(
            cand, records, pair, PRODUCER, "2026-09-15T12:06:00Z", resolve=RESOLVE
        )
        two = lp.next_record(
            cand,
            records,
            list(reversed(pair)),
            PRODUCER,
            "2026-09-15T12:06:00Z",
            resolve=RESOLVE,
        )
        self.assertEqual(one, two)

    def test_conditional_gates_shape_the_path(self):
        skill = candidate(kind="skill", promotion_class="P3", consequential=True)
        records, _ = advance(skill, [], [], "2026-09-08T11:10:00Z")
        _, r = advance(
            skill,
            records,
            [gate("offline_eval", "2026-09-08T12:00:00Z")],
            "2026-09-08T12:01:00Z",
        )
        self.assertEqual(r["to"], "canary")
        memory = candidate(kind="semantic", promotion_class="P1", protected=True)
        records, _ = advance(memory, [], [], "2026-09-08T11:10:00Z")
        checks = [
            gate("provenance", "2026-09-08T12:00:00Z"),
            gate("contradiction", "2026-09-08T12:00:00Z"),
        ]
        records, _ = advance(memory, records, checks, "2026-09-08T12:01:00Z")
        # Protected memory waits for the owner only to go live; in shadow it activates.
        _, r = advance(
            memory,
            records,
            [gate("maturity", "2026-09-15T12:05:00Z")],
            "2026-09-15T12:06:00Z",
        )
        self.assertEqual((r["to"], r["effect"]), ("active", "shadow"))

    def test_p8_needs_the_owner_on_the_activating_record(self):
        cand = candidate(kind="policy", promotion_class="P8")
        records, _ = advance(cand, [], [], "2026-09-08T11:10:00Z")
        # The owner approved while evaluating: that pass exists but is not on
        # the activating record, so P8 still refuses.
        records, _ = advance(
            cand,
            records,
            [
                gate("tests", "2026-09-08T12:00:00Z"),
                gate("owner", "2026-09-08T12:00:00Z", evaluator=OWNER),
            ],
            "2026-09-08T12:01:00Z",
        )
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.next_record(
                cand,
                records,
                [gate("maturity", "2026-09-15T12:05:00Z")],
                PRODUCER,
                "2026-09-15T12:06:00Z",
                resolve=RESOLVE,
            )
        self.assertIn("never automatic", str(caught.exception))
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

    def eval_report(self):
        spec_ = importlib.util.spec_from_file_location(
            "learning_eval", ROOT / "scripts" / "learning_eval.py"
        )
        ev = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(ev)
        suite = EXAMPLES / "memory-eval"
        cand = lc.read_records(suite / "candidate.json")[0]
        report = ev.evaluate(
            lc.read_records(suite / "cases.jsonl"),
            lc.read_records(suite / "baseline-outputs.json")[0],
            lc.read_records(suite / "candidate-outputs.json")[0],
            cand,
            lc.read_records(suite / "experiences.jsonl"),
            gate="retrieval_regression",
            at="2026-09-05T00:00:00Z",
            salt_draw={"source": "agent-hq@" + "7" * 40, "at": "2026-09-04T00:00:00Z"},
        )
        return cand, report

    def test_a_run_report_is_bound_to_its_candidate(self):
        cand, report = self.eval_report()
        self.assertEqual(lp.gate_results([report], cand), [report["gate"]])
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.gate_results([report], candidate())
        self.assertIn("judged lc_memory-eval-0001", str(caught.exception))
        named = dict(cand, genome="gen_other-0001")
        with self.assertRaises(lp.PromotionRefusal) as caught:
            lp.gate_results([report], named)
        self.assertIn("not gen_other-0001", str(caught.exception))

    def test_an_eval_run_gate_moves_its_candidate(self):
        cand, report = self.eval_report()
        records, _ = advance(cand, [], [], "2026-09-04T10:00:00Z")
        _, r = advance(cand, records, [report], "2026-09-05T00:01:00Z")
        self.assertEqual((r["from"], r["to"]), ("evaluating", "probation"))

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
            self.assertIn("awaits a counted pass of offline_eval", err.getvalue())


if __name__ == "__main__":
    unittest.main()
