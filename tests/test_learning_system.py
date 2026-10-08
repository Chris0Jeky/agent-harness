"""System evaluation: candidate-arm runs against baseline-arm runs."""

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
    "learning_system", ROOT / "scripts" / "learning_system.py"
)
ls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ls)
lc = ls.contracts

EXAMPLES = ROOT / "schemas" / "learning" / "examples"
BASE, CAND = "baseline:example", "gen:gen_example-0001"
AT = "2026-09-20T00:00:00Z"


def candidate():
    return copy.deepcopy(lc.read_records(EXAMPLES / "learning-candidate.json")[0])


def run(key, variant, immediate="merged", matured="clean", corrected=False, **extra):
    record = copy.deepcopy(lc.read_records(EXAMPLES / "estate-experience.json")[0])
    record["source"] = {"kind": "muse-job", "key": key}
    record["id"] = lc.experience_id("muse-job", key)
    record["variant"] = variant
    record["outcome"] = {
        "immediate": immediate,
        "matured": matured,
        "regression": False,
    }
    record["feedback"] = [
        {"kind": "triage_verdict", "ref": "coordinator-item:f-1", "signal": "confirmed"}
    ]
    if corrected:
        record["feedback"].append(
            {
                "kind": "owner_correction",
                "ref": "claude-session:x",
                "signal": "corrected",
                "key": "k",
            }
        )
    record.update(extra)
    return record


def arms(n=20, cand_reverts=0, base_reverts=0, cand_corrections=0):
    runs = []
    for i in range(n):
        runs.append(
            run(f"b{i}", BASE, matured="reverted" if i < base_reverts else "clean")
        )
        runs.append(
            run(
                f"c{i}",
                CAND,
                matured="reverted" if i < cand_reverts else "clean",
                corrected=i < cand_corrections,
            )
        )
    return runs


class CompareTests(unittest.TestCase):
    def compare(self, runs, **options):
        return ls.compare(runs, candidate(), BASE, CAND, at=AT, **options)

    def test_equal_arms_pass_as_a_canary_gate(self):
        report = self.compare(arms())
        self.assertEqual(
            (report["verdict"], report["gate"]["gate"]), ("pass", "canary")
        )
        self.assertEqual(report["arms"]["candidate"]["precision"], 1.0)
        self.assertEqual(lc.validate_record(report), [])

    def test_more_reverts_fail(self):
        report = self.compare(arms(cand_reverts=2))
        self.assertEqual(report["verdict"], "fail")
        self.assertTrue(any("reverts rose" in r for r in report["reasons"]))
        self.assertEqual(report["gate"]["result"], "fail")
        self.assertEqual(report["arms"]["candidate"]["success_rate"], 0.9)

    def test_more_owner_corrections_fail(self):
        report = self.compare(arms(cand_corrections=1))
        self.assertTrue(any("owner corrections rose" in r for r in report["reasons"]))

    def test_tolerances_are_the_policy(self):
        report = self.compare(
            arms(cand_reverts=1),
            policy={"max_revert_rise": 0.1, "max_success_drop": 0.1},
        )
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["policy"]["max_revert_rise"], 0.1)

    def test_small_arms_are_insufficient(self):
        report = self.compare(arms(n=5))
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))

    def test_training_evidence_and_other_variants_stay_out(self):
        runs = arms()
        evidence = candidate()["evidence"][0]
        trained = run("trained", CAND)
        trained["id"] = evidence  # the candidate learned from this very run
        trained["source"] = {"kind": "x", "key": "y"}
        stray = run("stray", "gen:gen_other-0001")
        with self.assertRaises(ls.SystemRefusal):
            self.compare(
                runs + [trained]
            )  # an id that does not match its source refuses
        report = self.compare(runs + [stray])
        self.assertEqual(report["arms"]["candidate"]["runs"], 20)
        source = lc.read_records(EXAMPLES / "estate-experience.json")[0]
        own = dict(copy.deepcopy(source), variant=CAND)
        report = self.compare(runs + [own])
        self.assertEqual(
            (report["excluded_training"], report["arms"]["candidate"]["runs"]), (1, 20)
        )

    def test_refusals(self):
        with self.assertRaises(ls.SystemRefusal):
            ls.compare(arms(), candidate(), BASE, BASE)
        with self.assertRaises(ls.SystemRefusal):
            self.compare(arms(), policy={"min_runs": 0})

    def test_an_unmatured_arm_is_insufficient_not_a_silent_pass(self):
        runs = arms()
        for record in runs:
            if record["variant"] == CAND:
                record["outcome"]["matured"] = None
        report = self.compare(runs)
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))
        self.assertTrue(any("matured runs" in r for r in report["reasons"]))

    def test_a_run_cannot_leave_its_arm_when_re_observed(self):
        runs = arms()
        later = copy.deepcopy(next(r for r in runs if r["variant"] == CAND))
        later.update(observed_at="2026-09-30T00:00:00Z")
        del later["variant"]
        with self.assertRaises(ls.SystemRefusal) as caught:
            self.compare(runs + [later])
        self.assertIn("variant differs", str(caught.exception))

    def test_the_candidate_variant_is_the_candidates_genome(self):
        with self.assertRaises(ls.SystemRefusal) as caught:
            ls.compare(arms(), candidate(), BASE, "gen:gen_other-0001", at=AT)
        self.assertIn("runs as gen:gen_example-0001", str(caught.exception))

    def test_the_canary_gate_folds_leaving_canary(self):
        gate = self.compare(arms())["gate"]
        records = lc.read_records(EXAMPLES / "promotion-chain.jsonl")[:2]
        leaving = dict(
            copy.deepcopy(records[1]),
            id="prom_example-canary",
            prev=records[1]["id"],
            at="2026-09-20T00:01:00Z",
            **{"from": "canary", "to": "probation"},
        )
        leaving["gates"] = [gate]
        result = lc.fold(candidate(), records + [leaving])
        self.assertEqual((result.state, result.errors), ("probation", []))

    def test_success_is_the_contract_definition(self):
        self.assertFalse(
            lc.experience_succeeded(run("x", BASE, immediate="failed", matured=None))
        )
        self.assertFalse(lc.experience_succeeded(run("y", BASE, matured="reverted")))
        self.assertTrue(
            lc.experience_succeeded(run("z", BASE, immediate="published", matured=None))
        )


class CommandLineTests(unittest.TestCase):
    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in arms()), "utf-8")
            argv = [
                "--experiences",
                str(path),
                "--candidate",
                str(EXAMPLES / "learning-candidate.json"),
                "--baseline-variant",
                BASE,
                "--candidate-variant",
                CAND,
                "--at",
                AT,
            ]
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                self.assertEqual(ls.main(argv), 0)
                self.assertEqual(ls.main(argv + ["--min-runs", "50"]), 3)
                self.assertEqual(ls.main(argv[:-2] + ["--at", "soon"]), 2)


if __name__ == "__main__":
    unittest.main()
