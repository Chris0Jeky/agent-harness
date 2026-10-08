"""Replay evaluator: hold-out selection, oracles, paired comparison and gates.

Runs the synthetic memory-eval suite in schemas/learning/examples/memory-eval;
no live ledger is read.
"""

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
    "learning_eval", ROOT / "scripts" / "learning_eval.py"
)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
lc = ev.contracts

SUITE = ROOT / "schemas" / "learning" / "examples" / "memory-eval"
AT = "2026-09-05T00:00:00Z"
JUDGE = {"kind": "llm_judge", "runtime": "grok", "model": "m", "session": "judge-1"}


def load():
    return {
        "cases": lc.read_records(SUITE / "cases.jsonl"),
        "baseline": lc.read_records(SUITE / "baseline-outputs.json")[0],
        "candidate_outputs": lc.read_records(SUITE / "candidate-outputs.json")[0],
        "candidate": lc.read_records(SUITE / "candidate.json")[0],
        "experiences": lc.read_records(SUITE / "experiences.jsonl"),
    }


def run(inputs=None, **options):
    inputs = inputs or load()
    options.setdefault("at", AT)
    options.setdefault("gate", "retrieval_regression")
    return ev.evaluate(
        inputs["cases"],
        inputs["baseline"],
        inputs["candidate_outputs"],
        inputs["candidate"],
        inputs["experiences"],
        **options,
    )


def labels(variant, verdicts, evaluator=JUDGE):
    return {
        "schema": "eval-labels/v1",
        "at": AT,
        "suite": "memory-eval-example",
        "variant": variant,
        "evaluator": evaluator,
        "labels": verdicts,
    }


class SuiteTests(unittest.TestCase):
    def test_example_suite_covers_every_memory_cell(self):
        cells = {(c["category"], c["layer"]) for c in load()["cases"]}
        for category in (
            "static_state_recall",
            "dynamic_state_tracking",
            "workflow_knowledge",
            "environment_gotchas",
            "false_premise",
        ):
            for layer in ("extraction", "retrieval", "behavioural"):
                self.assertIn((category, layer), cells)

    def test_candidate_beats_baseline_on_the_holdout(self):
        report = run()
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["tier"], "oracle")
        results = report["results"]
        self.assertEqual((results["wins"], results["losses"]), (15, 0))
        self.assertLess(results["sign_test_p"], 0.001)
        self.assertEqual(results["retrieval"]["candidate"]["mrr"], 1.0)
        self.assertEqual(
            set(results["by_layer"]), {"extraction", "retrieval", "behavioural"}
        )
        self.assertEqual(lc.validate_record(report), [])

    def test_training_evidence_and_its_cluster_are_excluded(self):
        report = run()
        counts = report["cases"]
        self.assertEqual(
            (counts["excluded_training"], counts["excluded_cluster"]), (1, 1)
        )
        evidence = set(load()["candidate"]["evidence"])
        self.assertFalse(evidence & set(report["anchors"]))
        evaluated = {r for r in report["results"]["by_category"]}
        self.assertTrue(evaluated)

    def test_the_gate_drops_into_a_promotion_record(self):
        report = run()
        gate = report["gate"]
        self.assertEqual(gate["holdout_digest"], report["holdout_digest"])
        record = {
            "schema": "promotion-record/v1",
            "id": "prom_eval-0001",
            "at": "2026-09-05T00:01:00Z",
            "producer": {
                "lane": "steward",
                "runtime": "tool",
                "model": None,
                "session": "s",
            },
            "candidate": report["candidate"],
            "prev": "prom_eval-0000",
            "from": "evaluating",
            "to": "probation",
            "promotion_class": "P2",
            "effect": "shadow",
            "gates": [gate],
            "reason": "retrieval regression on the sealed hold-out",
        }
        self.assertEqual(lc.validate_record(record), [])

    def test_report_is_deterministic(self):
        self.assertEqual(run(), run())

    def test_dev_runs_never_emit_a_gate(self):
        report = run(split="dev")
        self.assertIsNone(report["gate"])
        self.assertEqual(report["split"], "dev")

    def test_too_few_cases_is_insufficient_not_a_pass(self):
        report = run(policy={"min_cases": 100})
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))

    def test_a_single_loss_fails_the_gate(self):
        inputs = load()
        case = next(c for c in inputs["cases"] if c["id"] == "case_static-tie")
        inputs["candidate_outputs"]["outputs"][case["id"]] = {"text": "master"}
        report = run(inputs)
        self.assertEqual(
            (report["verdict"], report["gate"]["result"]), ("fail", "fail")
        )
        self.assertEqual(report["results"]["losses"], 1)

    def test_missing_candidate_output_counts_as_failure(self):
        inputs = load()
        del inputs["candidate_outputs"]["outputs"]["case_static-tie"]
        self.assertEqual(run(inputs)["results"]["losses"], 1)


class RefusalTests(unittest.TestCase):
    def assertRefused(self, fragment, inputs=None, **options):
        with self.assertRaises(ev.EvalRefusal) as caught:
            run(inputs, **options)
        self.assertIn(fragment, str(caught.exception))

    def test_unresolvable_training_evidence_refuses(self):
        inputs = load()
        inputs["experiences"] = inputs["experiences"][2:]
        self.assertRefused("exclusion unprovable", inputs)

    def test_a_named_genome_must_be_supplied(self):
        inputs = load()
        inputs["candidate"]["genome"] = "gen_missing-0001"
        self.assertRefused("pass exactly that genome", inputs)

    def test_genome_training_evidence_is_excluded_too(self):
        inputs = load()
        target = next(
            c for c in inputs["cases"] if c["id"] == "case_workflow-knowledge-extract"
        )
        genome = {
            "schema": "candidate-genome/v1",
            "id": "gen_memory-eval-0001",
            "at": "2026-09-03T09:05:00Z",
            "producer": inputs["candidate"]["producer"],
            "parent": {"example-config": "c" * 40},
            "parent_genome": None,
            "changes": {
                "memory": [{"repo": "example-config", "path": "m.md", "op": "add"}]
            },
            "candidates": [inputs["candidate"]["id"]],
            "training_evidence": {"experiences": [target["experience"]]},
        }
        inputs["candidate"]["genome"] = genome["id"]
        report = run(inputs, genome=genome)
        self.assertNotIn(target["experience"], report["anchors"])
        self.assertEqual(report["cases"]["excluded_training"], 2)

    def test_a_case_cannot_move_across_the_split(self):
        inputs = load()
        anchored = next(c for c in inputs["cases"] if c["experience"])
        anchored["split_key"] = "moved"
        self.assertRefused("cannot move across the split", inputs)

    def test_an_inconsistent_experience_ledger_refuses(self):
        inputs = load()
        moved = copy.deepcopy(inputs["experiences"][0])
        moved.update(observed_at="2026-09-03T00:00:00Z", split_key="elsewhere")
        inputs["experiences"].append(moved)
        self.assertRefused("inconsistent", inputs)

    def test_duplicate_case_ids_refuse(self):
        inputs = load()
        inputs["cases"].append(copy.deepcopy(inputs["cases"][0]))
        self.assertRefused("duplicate case id", inputs)

    def test_mixed_suites_and_mismatched_outputs_refuse(self):
        inputs = load()
        inputs["cases"][0] = dict(inputs["cases"][0], suite="another-suite")
        self.assertRefused("one suite per run", inputs)
        inputs = load()
        inputs["baseline"]["variant"] = "candidate"
        self.assertRefused("baseline outputs", inputs)

    def test_judge_cases_need_labels_from_someone_other_than_the_learner(self):
        inputs = load()
        case = next(c for c in inputs["cases"] if c["id"] == "case_static-tie")
        case["oracle"] = {"kind": "judge"}
        self.assertRefused("without a baseline label", inputs)
        learner = dict(JUDGE, session=inputs["candidate"]["producer"]["session"])
        self.assertRefused(
            "learner's own session",
            inputs,
            labels=[
                labels("baseline", {case["id"]: "pass"}, learner),
                labels("candidate", {case["id"]: "pass"}, learner),
            ],
        )

    def test_any_label_demotes_the_run_from_oracle(self):
        inputs = load()
        case = next(c for c in inputs["cases"] if c["id"] == "case_static-tie")
        case["oracle"] = {"kind": "judge"}
        report = run(
            inputs,
            labels=[
                labels("baseline", {case["id"]: "pass"}),
                labels("candidate", {case["id"]: "pass"}),
            ],
        )
        self.assertEqual(report["tier"], "llm_judge")
        self.assertEqual(report["gate"]["evaluator"]["kind"], "llm_judge")


class ReviewRegressionTests(unittest.TestCase):
    """Defects found by the #497 review lenses; each pins its fix."""

    def assertRefused(self, fragment, inputs=None, **options):
        with self.assertRaises(ev.EvalRefusal) as caught:
            run(inputs, **options)
        self.assertIn(fragment, str(caught.exception))

    def genome(self, inputs, gid, evidence):
        return {
            "schema": "candidate-genome/v1",
            "id": gid,
            "at": "2026-09-03T09:05:00Z",
            "producer": dict(inputs["candidate"]["producer"], session="generator-1"),
            "parent": {"example-config": "c" * 40},
            "parent_genome": None,
            "changes": {
                "memory": [{"repo": "example-config", "path": "m.md", "op": "add"}]
            },
            "candidates": [inputs["candidate"]["id"]],
            "training_evidence": {"experiences": evidence},
        }

    def test_only_the_named_genome_is_accepted(self):
        inputs = load()
        inputs["candidate"]["genome"] = "gen_named-0001"
        other = self.genome(inputs, "gen_other-0001", inputs["candidate"]["evidence"])
        self.assertRefused("pass exactly that genome", inputs, genome=other)

    def test_outputs_from_a_genome_require_that_genome(self):
        inputs = load()
        inputs["candidate_outputs"]["variant_ref"] = "gen:gen_ran-0001"
        self.assertRefused("runs as gen_ran-0001", inputs)

    def test_an_anchor_missing_from_the_ledger_refuses(self):
        inputs = load()
        anchored = next(c for c in inputs["cases"] if c["experience"])
        inputs["experiences"] = [
            e for e in inputs["experiences"] if e["id"] != anchored["experience"]
        ]
        self.assertRefused("not in the ledger", inputs)

    def test_an_invalid_pattern_refuses(self):
        inputs = load()
        case = next(c for c in inputs["cases"] if c["oracle"]["kind"] == "regex")
        case["oracle"]["pattern"] = "(?i"
        self.assertRefused("invalid pattern", inputs)

    def test_labels_never_claim_to_be_an_oracle(self):
        record = labels(
            "baseline", {"case_static-tie": "pass"}, dict(JUDGE, kind="oracle")
        )
        self.assertTrue(lc.validate_record(record))

    def test_labels_from_the_genome_producer_are_the_learners(self):
        inputs = load()
        case = next(c for c in inputs["cases"] if c["id"] == "case_static-tie")
        case["oracle"] = {"kind": "judge"}
        genome = self.genome(inputs, "gen_mine-0001", inputs["candidate"]["evidence"])
        inputs["candidate"]["genome"] = genome["id"]
        mine = dict(JUDGE, session="generator-1")
        self.assertRefused(
            "learner's own session",
            inputs,
            genome=genome,
            labels=[
                labels(v, {case["id"]: "pass"}, mine) for v in ("baseline", "candidate")
            ],
        )

    def test_absent_text_never_passes_a_text_oracle(self):
        for oracle in (
            {"kind": "contains_none", "needles": ["3.9"]},
            {"kind": "regex", "pattern": "^$"},
            {"kind": "exact", "expected": ""},
        ):
            self.assertFalse(
                ev.grade({"id": "case_x", "oracle": oracle}, {"tokens": 1})[0]
            )
        abstain = {"kind": "abstain", "expected_abstain": False}
        self.assertFalse(ev.grade({"id": "case_x", "oracle": abstain}, {})[0])
        self.assertTrue(
            ev.grade({"id": "case_x", "oracle": abstain}, {"abstained": False})[0]
        )

    def test_an_errored_output_fails_a_judge_case(self):
        inputs = load()
        case = next(c for c in inputs["cases"] if c["id"] == "case_static-tie")
        case["oracle"] = {"kind": "judge"}
        inputs["candidate_outputs"]["outputs"][case["id"]] = {"error": "crashed"}
        report = run(
            inputs,
            labels=[labels(v, {case["id"]: "pass"}) for v in ("baseline", "candidate")],
        )
        self.assertEqual(report["results"]["losses"], 1)

    def test_policy_is_bounded_and_recorded_in_the_gate(self):
        self.assertRefused("min_cases is at least 1", policy={"min_cases": 0})
        loose = run(policy={"max_losses": 5})
        self.assertEqual(loose["gate"]["metrics"]["max_losses"], 5)
        self.assertNotEqual(loose["id"], run()["id"])

    def test_the_named_evaluator_does_not_depend_on_order(self):
        inputs = load()
        case = next(c for c in inputs["cases"] if c["id"] == "case_static-tie")
        case["oracle"] = {"kind": "judge"}
        a, b = dict(JUDGE, session="judge-A"), dict(JUDGE, session="judge-B")
        one = [
            labels("baseline", {case["id"]: "pass"}, a),
            labels("candidate", {case["id"]: "pass"}, b),
        ]
        self.assertEqual(
            run(copy.deepcopy(inputs), labels=one)["evaluator"]["session"], "judge-A"
        )
        self.assertEqual(
            run(inputs, labels=list(reversed(one)))["evaluator"]["session"], "judge-A"
        )

    def test_run_records_keep_their_gate_consistent(self):
        report = run()
        for change in (
            {"tier": "llm_judge"},
            {"gate_name": "offline_eval"},
            {"gate": None},
        ):
            self.assertTrue(
                lc.validate_record(dict(copy.deepcopy(report), **change)), change
            )

    def test_maximum_bounds_fractions(self):
        case = copy.deepcopy(load()["cases"][0])
        case["oracle"]["min_recall"] = 1.5
        self.assertTrue(any("above 1" in e for e in lc.validate_record(case)))

    def test_clones_of_one_case_count_once(self):
        inputs = load()
        base = next(c for c in inputs["cases"] if c["id"] == "case_static-tie")
        inputs["cases"] = [
            dict(copy.deepcopy(base), id=f"case_clone-{i:06d}") for i in range(10)
        ]
        for key in ("baseline", "candidate_outputs"):
            inputs[key]["outputs"] = {
                c["id"]: {"text": "main"} for c in inputs["cases"]
            }
        report = run(inputs)
        self.assertEqual(report["cases"]["distinct_inputs"], 1)
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))

    def test_experience_observations_order_by_instant_not_text(self):
        first = copy.deepcopy(load()["experiences"][0])
        first["observed_at"] = "2026-09-02T00:00:00Z"
        later = copy.deepcopy(first)
        later["observed_at"] = "2026-09-02T00:00:00.5Z"
        later["outcome"]["matured"] = None
        later["outcome"]["immediate"] = "failed"
        by_id, errors = lc.fold_experiences([later, first])
        self.assertEqual(
            (errors, by_id[first["id"]]["outcome"]["immediate"]), ([], "failed")
        )


class OracleTests(unittest.TestCase):
    def grade(self, oracle, output):
        return ev.grade({"id": "case_x", "oracle": oracle}, output)[0]

    def test_each_deterministic_oracle(self):
        self.assertTrue(self.grade({"kind": "exact", "expected": "a"}, {"text": " a "}))
        self.assertFalse(self.grade({"kind": "exact", "expected": "a"}, {"text": "A"}))
        self.assertTrue(
            self.grade({"kind": "contains_all", "needles": ["X", "y"]}, {"text": "x Y"})
        )
        self.assertFalse(
            self.grade({"kind": "contains_none", "needles": ["old"]}, {"text": "OLD"})
        )
        self.assertTrue(
            self.grade({"kind": "regex", "pattern": "^v[0-9]"}, {"text": "v2"})
        )
        self.assertTrue(
            self.grade(
                {"kind": "abstain", "expected_abstain": True}, {"abstained": True}
            )
        )
        self.assertFalse(
            self.grade({"kind": "abstain", "expected_abstain": True}, {"text": "sure"})
        )
        self.assertTrue(
            self.grade({"kind": "numeric", "at_least": 1, "at_most": 2}, {"value": 2})
        )
        self.assertFalse(self.grade({"kind": "numeric", "at_least": 1}, {}))

    def test_set_and_ranked_oracles(self):
        set_oracle = {
            "kind": "set_match",
            "expected_items": ["a", "b"],
            "min_precision": 0.6,
        }
        self.assertTrue(self.grade(set_oracle, {"items": ["a", "b", "c"]}))
        self.assertFalse(self.grade(set_oracle, {"items": ["a", "b", "c", "d"]}))
        ranked = {"kind": "ranked_recall", "expected_items": ["m"], "k": 1}
        self.assertTrue(self.grade(ranked, {"items": ["m", "x"]}))
        self.assertFalse(self.grade(ranked, {"items": ["x", "m"]}))

    def test_set_match_forbids_items(self):
        keeps = {
            "kind": "set_match",
            "expected_items": ["a.py#L0"],
            "forbidden_items": ["b.py#L1"],
        }
        self.assertTrue(self.grade(keeps, {"items": ["a.py#L0", "c.py#L2"]}))
        self.assertFalse(self.grade(keeps, {"items": ["a.py#L0", "b.py#L1"]}))
        drops = {"kind": "set_match", "forbidden_items": ["b.py#L1"]}
        self.assertTrue(self.grade(drops, {"items": []}))
        self.assertFalse(self.grade(drops, {}))
        self.assertFalse(self.grade(drops, {"items": ["b.py#L1"]}))
        case = copy.deepcopy(load()["cases"][0])
        case["oracle"] = {"kind": "set_match"}
        self.assertTrue(lc.validate_record(case))
        case["oracle"] = drops
        self.assertEqual(lc.validate_record(case), [])

    def test_missing_and_errored_outputs_fail(self):
        self.assertFalse(self.grade({"kind": "exact", "expected": "a"}, None))
        self.assertFalse(
            self.grade(
                {"kind": "exact", "expected": "a"}, {"text": "a", "error": "boom"}
            )
        )

    def test_sign_test(self):
        self.assertEqual(ev.sign_test(0, 0), 1.0)
        self.assertAlmostEqual(ev.sign_test(15, 0), 2 / 2**15)
        self.assertEqual(ev.sign_test(3, 3), 1.0)


class ProceduralTests(unittest.TestCase):
    """A proposed skill replayed on historical tasks it was not generated from."""

    def suite(self):
        inputs = load()
        procedural = []
        for n in range(10):
            case = copy.deepcopy(
                next(c for c in inputs["cases"] if c["id"] == "case_static-tie")
            )
            case.update(
                id=f"case_proc-{n:04d}",
                layer="procedural",
                category="task",
                input_ref=f"synthetic:procedure/{n}",
                oracle={
                    "kind": "procedure",
                    "max_turns": 12,
                    "require_recovery": n == 0,
                },
            )
            procedural.append(case)
        inputs["cases"] = procedural
        inputs["baseline"]["outputs"] = {
            c["id"]: {
                "completed": n % 2 == 0,
                "turns": 15,
                "recovered": False,
                "tokens": 9000,
            }
            for n, c in enumerate(procedural)
        }
        inputs["candidate_outputs"]["outputs"] = {
            c["id"]: {"completed": True, "turns": 8, "recovered": True, "tokens": 6000}
            for c in procedural
        }
        return inputs

    def test_the_skill_is_judged_on_completion_turns_recovery_and_cost(self):
        report = run(self.suite(), gate="offline_eval")
        self.assertEqual(report["verdict"], "pass")
        block = report["results"]["procedural"]
        self.assertEqual(block["n"], 10)
        self.assertEqual(block["baseline"]["completion_rate"], 0.5)
        self.assertEqual(block["candidate"]["completion_rate"], 1.0)
        self.assertEqual(
            (block["baseline"]["turns_mean"], block["candidate"]["turns_mean"]), (15, 8)
        )
        self.assertEqual(block["candidate"]["recovery_rate"], 1.0)
        self.assertEqual(block["candidate"]["tokens_mean"], 6000)
        # Baseline completions ran over max_turns, so none of them pass.
        self.assertEqual(report["results"]["baseline"]["passed"], 0)

    def test_procedure_oracle(self):
        def grade(output, **oracle):
            case = {"id": "case_x", "oracle": {"kind": "procedure", **oracle}}
            return ev.grade(case, output)[0]

        self.assertTrue(grade({"completed": True}))
        self.assertFalse(grade({"completed": False}))
        self.assertFalse(grade({}))
        self.assertTrue(grade({"completed": True, "turns": 0}, max_turns=3))
        self.assertFalse(grade({"completed": True}, max_turns=3))
        self.assertFalse(grade({"completed": True, "turns": 4}, max_turns=3))
        self.assertFalse(
            grade({"completed": True, "recovered": None}, require_recovery=True)
        )
        self.assertTrue(
            grade({"completed": True, "recovered": True}, require_recovery=True)
        )

    def test_training_tasks_are_excluded_from_a_skills_evaluation(self):
        inputs = self.suite()
        anchored = load()["cases"]
        leak = next(c for c in anchored if c["id"] == "case_leak-training")
        inputs["cases"].append(dict(copy.deepcopy(leak), oracle={"kind": "procedure"}))
        inputs["candidate_outputs"]["outputs"][leak["id"]] = {"completed": True}
        report = run(inputs, gate="offline_eval")
        self.assertEqual(report["cases"]["excluded_training"], 1)

    def test_errored_and_unfinished_runs_do_not_flatter_the_block(self):
        inputs = self.suite()
        first = inputs["cases"][0]["id"]
        inputs["candidate_outputs"]["outputs"][first] = {
            "completed": True,
            "turns": 1,
            "error": "crashed",
        }
        block = run(inputs, gate="offline_eval")["results"]["procedural"]
        self.assertEqual(block["candidate"]["completion_rate"], 0.9)
        self.assertEqual(block["candidate"]["turns_mean"], 8)

    def test_recovery_rate_counts_only_cases_that_needed_recovery(self):
        inputs = self.suite()  # only the first case requires recovery
        for key, output in inputs["candidate_outputs"]["outputs"].items():
            output["recovered"] = key == inputs["cases"][0]["id"]
        block = run(inputs, gate="offline_eval")["results"]["procedural"]
        self.assertEqual(block["candidate"]["recovery_rate"], 1.0)

    def test_no_case_requiring_recovery_means_no_recovery_rate(self):
        inputs = self.suite()
        for case in inputs["cases"]:
            case["oracle"].pop("require_recovery", None)
        block = run(inputs, gate="offline_eval")["results"]["procedural"]
        self.assertIsNone(block["candidate"]["recovery_rate"])

    def test_no_procedural_cases_no_block(self):
        self.assertIsNone(run()["results"]["procedural"])


class CommandLineTests(unittest.TestCase):
    def cli(self, *extra):
        argv = [
            "--cases",
            str(SUITE / "cases.jsonl"),
            "--baseline",
            str(SUITE / "baseline-outputs.json"),
            "--candidate-outputs",
            str(SUITE / "candidate-outputs.json"),
            "--candidate",
            str(SUITE / "candidate.json"),
            "--experiences",
            str(SUITE / "experiences.jsonl"),
            "--gate",
            "retrieval_regression",
            "--at",
            AT,
            *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ev.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        code, out, _ = self.cli()
        self.assertEqual((code, json.loads(out)["verdict"]), (0, "pass"))
        self.assertEqual(self.cli("--min-cases", "100")[0], 3)
        self.assertEqual(self.cli("--at", "yesterday")[0], 2)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"schema": "eval-outputs/v1"}), "utf-8")
            code, _, err = self.cli("--baseline", str(bad))
            self.assertEqual(code, 2)
            self.assertIn("refused", err)


if __name__ == "__main__":
    unittest.main()
