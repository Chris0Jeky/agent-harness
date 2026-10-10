"""Variant archive: genome tree, Pareto frontier, crowding-ranked parents."""

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
    "learning_archive", ROOT / "scripts" / "learning_archive.py"
)
la = importlib.util.module_from_spec(spec)
spec.loader.exec_module(la)
lc = la.contracts

EXAMPLE = ROOT / "schemas" / "learning" / "examples" / "candidate-genome.json"


def genome(key, parent=None, **objectives):
    record = copy.deepcopy(lc.read_records(EXAMPLE)[0])
    record.update(id=f"gen_{key}-0001", parent_genome=parent and f"gen_{parent}-0001")
    record["objectives"] = objectives
    return record


def ids(*keys):
    return [f"gen_{k}-0001" for k in keys]


class DataTests(unittest.TestCase):
    def test_objectives_match_the_genome_schema(self):
        schema = lc._document("candidate-genome.schema.json")
        names = schema["properties"]["objectives"]["propertyNames"]["enum"]
        self.assertEqual(set(la.directions()), set(names))
        self.assertTrue(set(la.directions().values()) <= {"max", "min"})


class FrontierTests(unittest.TestCase):
    def test_directions_decide_domination(self):
        cheap = genome("cheap", correctness=0.8, cost=1.0)
        dear = genome("dear", correctness=0.8, cost=2.0)
        self.assertTrue(la.dominates(cheap, dear, ["correctness", "cost"]))
        self.assertFalse(la.dominates(dear, cheap, ["correctness", "cost"]))
        self.assertFalse(
            la.dominates(cheap, copy.deepcopy(cheap), ["correctness", "cost"])
        )

    def test_frontier_keeps_tradeoffs_and_drops_the_dominated(self):
        genomes = [
            genome("accurate", correctness=0.9, cost=2.0),
            genome("cheap", correctness=0.8, cost=1.0),
            genome("worse", correctness=0.7, cost=3.0),
            genome("twin", correctness=0.9, cost=2.0),
        ]
        report = la.archive(genomes, ["correctness", "cost"])
        self.assertEqual(report["frontier"], ids("accurate", "cheap", "twin"))
        flags = {g["id"]: g["frontier"] for g in report["genomes"]}
        self.assertFalse(flags["gen_worse-0001"])

    def test_unmeasured_genomes_stay_in_the_archive_off_the_frontier(self):
        genomes = [
            genome("full", correctness=0.5, cost=1.0),
            genome("partial", correctness=0.99),
        ]
        report = la.archive(genomes, ["correctness", "cost"])
        self.assertEqual(report["frontier"], ids("full"))
        self.assertEqual(report["unmeasured"], ids("partial"))
        self.assertEqual(report["best"]["correctness"], "gen_partial-0001")
        self.assertEqual(len(report["genomes"]), 2)

    def test_parents_come_from_the_frontier_extremes_first(self):
        genomes = [
            genome(k, correctness=c, cost=x)
            for k, c, x in (
                ("a", 0.5, 1.0),
                ("b", 0.6, 2.0),
                ("c", 0.7, 3.0),
                ("d", 0.9, 9.0),
                ("e", 0.65, 2.6),
            )
        ]
        report = la.archive(genomes, ["correctness", "cost"], parents=2)
        self.assertEqual(report["parents"], ids("a", "d"))
        self.assertEqual(len(report["frontier"]), 5)
        crowd = la.crowding(genomes, ["correctness", "cost"])
        self.assertGreater(crowd["gen_b-0001"], 0)

    def test_a_constant_objective_does_not_crown_genomes_by_name(self):
        # "a" and "z" sort first and last by id but sit inside the frontier.
        points = (("k", 0.5, 1.0), ("a", 0.6, 2.0), ("m", 0.7, 2.2), ("z", 0.8, 6.0))
        genomes = [
            genome(key, correctness=c, cost=x, reverts=0)
            for key, c, x in points + (("p", 0.9, 9.0),)
        ]
        objectives = ["correctness", "cost", "reverts"]
        crowd = la.crowding(genomes, objectives)
        infinite = sorted(k for k, v in crowd.items() if v == float("inf"))
        self.assertEqual(infinite, ids("k", "p"))
        # z's neighbours are farthest apart once each objective is normalised.
        self.assertGreater(crowd["gen_z-0001"], crowd["gen_m-0001"])
        self.assertGreater(crowd["gen_m-0001"], crowd["gen_a-0001"])
        report = la.archive(genomes, objectives, parents=3)
        self.assertEqual(report["parents"], ids("k", "p", "z"))

    def test_non_finite_objectives_are_problems(self):
        bad = genome("bad", correctness=float("nan"))
        report = la.archive([bad, genome("ok", correctness=0.1)], ["correctness"])
        self.assertEqual(report["frontier"], ids("ok"))
        self.assertEqual(len(report["problems"]), 1)

    def test_unknown_objectives_refuse(self):
        with self.assertRaises(ValueError):
            la.archive([], ["vibes"])


class TreeTests(unittest.TestCase):
    def test_the_archive_is_a_tree(self):
        genomes = [
            genome("root", correctness=0.5),
            genome("left", "root", correctness=0.6),
            genome("right", "root", correctness=0.4),
            genome("leaf", "right", correctness=0.9),
        ]
        report = la.archive(genomes, ["correctness"])
        by_id = {g["id"]: g for g in report["genomes"]}
        self.assertEqual(report["roots"], ids("root"))
        self.assertEqual(by_id["gen_root-0001"]["children"], ids("left", "right"))
        self.assertEqual(by_id["gen_leaf-0001"]["depth"], 2)
        self.assertEqual(report["problems"], [])

    def test_orphans_and_cycles_are_problems_not_crashes(self):
        a = genome("a", "b", correctness=0.5)
        b = genome("b", "a", correctness=0.6)
        orphan = genome("orphan", "missing", correctness=0.7)
        report = la.archive([a, b, orphan], ["correctness"])
        self.assertIn("gen_orphan-0001", report["roots"])
        self.assertEqual(sum("cycle" in p for p in report["problems"]), 2)
        below = la.archive([a, b, genome("c", "a", correctness=0.1)], ["correctness"])
        self.assertEqual(sum("cycle" in p for p in below["problems"]), 3)
        self.assertTrue(any("not in the archive" in p for p in report["problems"]))

    def test_invalid_and_conflicting_genomes_are_problems(self):
        good = genome("good", correctness=0.5)
        clash = dict(copy.deepcopy(good), parent={"other-repo": "e" * 40})
        report = la.archive(
            [good, clash, {"schema": "candidate-genome/v1"}], ["correctness"]
        )
        self.assertEqual(len(report["genomes"]), 0)  # both copies of the clash dropped
        self.assertEqual(len(report["problems"]), 2)
        self.assertEqual(
            la.archive([good, copy.deepcopy(good)], ["correctness"])["problems"], []
        )


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = la.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "genomes.jsonl"
            path.write_text(
                "".join(
                    json.dumps(genome(k, correctness=c)) + "\n"
                    for k, c in (("a", 0.1), ("b", 0.2))
                ),
                "utf-8",
            )
            code, out, _ = self.run_cli(str(path), "--objectives", "correctness")
            self.assertEqual((code, json.loads(out)["frontier"]), (0, ids("b")))
            self.assertEqual(self.run_cli(str(path), "--objectives", "vibes")[0], 2)
            orphan = Path(tmp) / "orphan.json"
            orphan.write_text(
                json.dumps(genome("o", "missing", correctness=0.1)), "utf-8"
            )
            self.assertEqual(
                self.run_cli(str(orphan), "--objectives", "correctness")[0], 1
            )


if __name__ == "__main__":
    unittest.main()
