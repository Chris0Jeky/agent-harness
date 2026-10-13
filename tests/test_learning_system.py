"""System evaluation: candidate-arm runs against baseline-arm runs."""

import copy
import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock

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
CUTOFF = "2026-09-08T11:05:00Z"
HIST_AT = "2026-09-01T10:20:00Z"
HIST_OBS = "2026-09-08T10:00:00Z"
POST_AT = "2026-09-12T10:20:00Z"
POST_OBS = "2026-09-12T12:00:00Z"


def candidate():
    return copy.deepcopy(lc.read_records(EXAMPLES / "learning-candidate.json")[0])


def genome():
    return copy.deepcopy(lc.read_records(EXAMPLES / "candidate-genome.json")[0])


def run(key, variant, immediate="merged", matured="clean", corrected=False, **extra):
    record = copy.deepcopy(lc.read_records(EXAMPLES / "estate-experience.json")[0])
    record["source"] = {"kind": "muse-job", "key": key}
    record["id"] = lc.experience_id("muse-job", key)
    record["at"] = POST_AT
    record["observed_at"] = POST_OBS
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
        options.setdefault("genome", genome())
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

    def historical_arms(self):
        runs = []
        for i in range(20):
            runs.append(
                run(
                    f"hb{i}",
                    BASE,
                    at=HIST_AT,
                    observed_at=HIST_OBS,
                )
            )
            runs.append(
                run(
                    f"hc{i}",
                    CAND,
                    at=HIST_AT,
                    observed_at=HIST_OBS,
                )
            )
        return runs

    def test_historical_runs_cannot_supply_a_canary_gate(self):
        report = self.compare(self.historical_arms())
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))
        self.assertEqual(report["arms"]["candidate"]["runs"], 0)
        self.assertEqual(report["arms"]["baseline"]["runs"], 0)

    def test_run_starting_before_cutoff_but_observed_after_is_ineligible(self):
        runs = []
        for i in range(20):
            runs.append(run(f"sb{i}", BASE, at=HIST_AT, observed_at=POST_OBS))
            runs.append(run(f"sc{i}", CAND, at=HIST_AT, observed_at=POST_OBS))
        report = self.compare(runs)
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))
        self.assertEqual(report["arms"]["candidate"]["runs"], 0)

    def test_genome_later_than_candidate_sets_the_cutoff(self):
        # candidate.at is 11:00, genome.at is 11:05: a run at 11:02 is too early.
        runs = []
        for i in range(20):
            runs.append(
                run(
                    f"gb{i}",
                    BASE,
                    at="2026-09-08T11:02:00Z",
                    observed_at="2026-09-08T11:03:00Z",
                )
            )
            runs.append(
                run(
                    f"gc{i}",
                    CAND,
                    at="2026-09-08T11:02:00Z",
                    observed_at="2026-09-08T11:03:00Z",
                )
            )
        report = self.compare(runs)
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))

    def test_candidate_later_than_genome_sets_the_cutoff(self):
        cand = candidate()
        cand["at"] = "2026-09-10T11:00:00Z"
        runs = []
        for i in range(20):
            runs.append(
                run(
                    f"cb{i}",
                    BASE,
                    at="2026-09-09T10:00:00Z",
                    observed_at="2026-09-09T12:00:00Z",
                )
            )
            runs.append(
                run(
                    f"cc{i}",
                    CAND,
                    at="2026-09-09T10:00:00Z",
                    observed_at="2026-09-09T12:00:00Z",
                )
            )
        report = ls.compare(runs, cand, BASE, CAND, at=AT, genome=genome())
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))

    def test_absent_genome_uses_the_candidate_cutoff(self):
        cand = candidate()
        cand["genome"] = None
        early = []
        for i in range(20):
            early.append(
                run(
                    f"eb{i}",
                    BASE,
                    at="2026-09-08T10:30:00Z",
                    observed_at="2026-09-08T10:45:00Z",
                )
            )
            early.append(
                run(
                    f"ec{i}",
                    CAND,
                    at="2026-09-08T10:30:00Z",
                    observed_at="2026-09-08T10:45:00Z",
                )
            )
        report = ls.compare(early, cand, BASE, CAND, at=AT, genome=None)
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))
        report = ls.compare(arms(), cand, BASE, CAND, at=AT, genome=None)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["gate"]["gate"], "canary")

    def test_exact_boundary_instants_are_eligible(self):
        runs = []
        for i in range(20):
            runs.append(run(f"xb{i}", BASE, at=CUTOFF, observed_at=CUTOFF))
            runs.append(run(f"xc{i}", CAND, at=CUTOFF, observed_at=CUTOFF))
        report = self.compare(runs)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["gate"]["gate"], "canary")

    def test_timezone_equivalent_boundary_is_eligible(self):
        equiv = "2026-09-08T11:05:00.000000Z"
        runs = []
        for i in range(20):
            runs.append(run(f"zb{i}", BASE, at=equiv, observed_at=equiv))
            runs.append(run(f"zc{i}", CAND, at=equiv, observed_at=equiv))
        report = self.compare(runs)
        self.assertEqual(report["verdict"], "pass")

    def test_mixed_history_passes_only_on_eligible_runs(self):
        report = self.compare(self.historical_arms() + arms())
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["arms"]["candidate"]["runs"], 20)
        self.assertEqual(report["arms"]["baseline"]["runs"], 20)
        short = self.historical_arms() + arms(n=5)
        report = self.compare(short)
        self.assertEqual((report["verdict"], report["gate"]), ("insufficient", None))

    def test_malformed_artifact_time_refuses(self):
        bad = candidate()
        bad["at"] = "soon"
        with self.assertRaises(ls.SystemRefusal):
            ls.compare(arms(), bad, BASE, CAND, at=AT, genome=genome())
        missing = candidate()
        del missing["at"]
        with self.assertRaises(ls.SystemRefusal):
            ls.compare(arms(), missing, BASE, CAND, at=AT, genome=genome())
        bad_genome = genome()
        bad_genome["at"] = "not-a-time"
        with self.assertRaises(ls.SystemRefusal):
            ls.compare(arms(), candidate(), BASE, CAND, at=AT, genome=bad_genome)

    def test_revision_and_cutoff_identity(self):
        report = self.compare(arms())
        self.assertEqual(report["producer"]["model"], ls.TOOL)
        with mock.patch.object(ls, "TOOL", ls.TOOL + "-next"):
            self.assertNotEqual(report["id"], self.compare(arms())["id"])
        other_genome = genome()
        other_genome["at"] = "2026-09-08T11:05:00.000000Z"
        same = self.compare(arms(), genome=other_genome)
        self.assertEqual(report["id"], same["id"])
        later_genome = genome()
        later_genome["at"] = "2026-09-09T11:05:00Z"
        moved = self.compare(arms(), genome=later_genome)
        self.assertNotEqual(report["id"], moved["id"])

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
        result = lc.fold(candidate(), records + [leaving], genome=genome())
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
                "--genome",
                str(EXAMPLES / "candidate-genome.json"),
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
