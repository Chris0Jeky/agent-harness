"""Learning-plane contracts: schemas, data files, validator and lifecycle fold.

Synthetic records only (schemas/learning/examples); no live ledger is read.
"""

import copy
import importlib.util
import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "learning_contracts", ROOT / "scripts" / "learning_contracts.py"
)
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

EXAMPLES = ROOT / "schemas" / "learning" / "examples"
ORACLE = {"kind": "oracle", "runtime": "tool", "model": None, "session": "eval-1"}
OWNER = {"kind": "owner", "runtime": "owner", "model": None, "session": "owner-1"}
HOLDOUT = "e" * 64


def example(name):
    return lc.read_records(EXAMPLES / name)


def candidate(**changes):
    record = copy.deepcopy(example("learning-candidate.json")[0])
    record.update(changes)
    return record


def chain():
    return copy.deepcopy(example("promotion-chain.jsonl"))


def gate(name, at, evaluator=ORACLE, result="pass"):
    item = {"gate": name, "result": result, "evaluator": evaluator, "at": at}
    if name in ("offline_eval", "replay"):
        item.update(holdout_digest=HOLDOUT, training_excluded=True)
    return item


def move(n, prev, frm, to, gates=(), at="2026-10-08T12:00:00Z", cls="P4", **extra):
    record = {
        "schema": "promotion-record/v1",
        "id": f"prom_test-{n:04d}",
        "at": at,
        "producer": {
            "lane": "steward",
            "runtime": "claude",
            "model": None,
            "session": "steward-1",
        },
        "candidate": "lc_example-0001",
        "prev": prev,
        "from": frm,
        "to": to,
        "promotion_class": cls,
        "effect": "shadow",
        "gates": list(gates),
        "reason": "test move",
    }
    record.update(extra)
    return record


def walk(*steps, cls="P4"):
    """Chain (from, to, gates, at) steps into linked promotion records."""
    records, prev = [], None
    for n, (frm, to, gates, at) in enumerate(steps, 1):
        records.append(move(n, prev, frm, to, gates, at, cls))
        prev = records[-1]["id"]
    return records


class ContractDataTests(unittest.TestCase):
    """The data files agree with the shared enums, so no rule hides in prose."""

    def setUp(self):
        self.common = lc._document("common.schema.json")["$defs"]
        self.life = lc.lifecycle()
        self.classes = lc.classes()

    def test_every_schema_loads_with_supported_keywords_only(self):
        for name in lc.RECORD_SCHEMAS.values():
            document = lc._document(name)
            self.assertEqual(
                document["title"], document["properties"]["schema"]["const"]
            )

    def test_specs_field_lists_match_the_schemas(self):
        text = (ROOT / "SPECS.md").read_text("utf-8")
        section = text[text.index("## §15 ") :]
        envelope = {"schema", "id", "at", "producer", "ext"}
        for name, path in lc.RECORD_SCHEMAS.items():
            row = next(
                line for line in section.splitlines() if line.startswith(f"| `{name}`")
            )
            listed = set(re.findall(r"`([a-z_]+)`", row.split("|")[2]))
            fields = set(lc._document(path)["properties"]) - envelope
            self.assertEqual(listed, fields, name)

    def test_unsupported_keyword_is_refused_not_skipped(self):
        with self.assertRaises(lc.ContractError):
            lc._audit_keywords({"properties": {"x": {"oneOf": []}}}, "probe")

    def test_lifecycle_states_match_the_state_enum(self):
        self.assertEqual(set(self.life["states"]), set(self.common["state"]["enum"]))
        self.assertEqual(set(self.life["edges"]), set(self.life["states"]))
        for targets in self.life["edges"].values():
            self.assertTrue(set(targets) <= set(self.life["states"]))
        for state in self.life["terminal"]:
            self.assertEqual(self.life["edges"][state], [])

    def test_every_state_is_reachable_and_every_path_can_end(self):
        reach, frontier = {self.life["initial"]}, [self.life["initial"]]
        while frontier:
            for target in self.life["edges"][frontier.pop()]:
                if target not in reach:
                    reach.add(target)
                    frontier.append(target)
        self.assertEqual(reach, set(self.life["states"]))
        for state in self.life["states"]:
            seen, frontier = {state}, [state]
            while frontier:
                for target in self.life["edges"][frontier.pop()]:
                    if target not in seen:
                        seen.add(target)
                        frontier.append(target)
            self.assertTrue(seen & set(self.life["terminal"]), state)

    def test_gate_sources_cover_exactly_the_gate_enum(self):
        self.assertEqual(
            set(self.life["gate_sources"]), set(self.common["gate"]["enum"])
        )

    def test_promotion_classes_cover_every_kind_and_gate(self):
        self.assertEqual(
            set(self.classes["kind_class"]), set(self.common["kind"]["enum"])
        )
        self.assertEqual(
            set(self.classes["classes"]), set(self.common["promotion_class"]["enum"])
        )
        gates = set(self.common["gate"]["enum"])
        for spec_ in self.classes["classes"].values():
            self.assertTrue(set(spec_["activation_gates"]) <= gates)
            for extra in spec_["conditional_gates"].values():
                self.assertTrue(set(extra) <= gates)

    def test_p8_is_never_automatic_and_needs_the_owner(self):
        p8 = self.classes["classes"]["P8"]
        self.assertTrue(p8["owner_on_activation"])
        self.assertIn("owner", p8["activation_gates"])
        self.assertEqual(p8["creation"], "proposal_only")

    def test_only_p0_activates_without_gates(self):
        for name, spec_ in self.classes["classes"].items():
            self.assertEqual(name == "P0", not spec_["activation_gates"], name)


class ExampleTests(unittest.TestCase):
    def test_every_example_is_valid(self):
        paths = sorted(EXAMPLES.iterdir())
        self.assertEqual(len(paths), 5)
        for path in paths:
            for record in lc.read_records(path):
                self.assertEqual(lc.validate_record(record), [], record["id"])

    def test_example_chain_folds_to_active_in_shadow(self):
        result = lc.fold(candidate(), chain())
        self.assertEqual(result.errors, [])
        self.assertEqual((result.state, result.effect), ("active", "shadow"))
        self.assertEqual(len(result.chain), 4)

    def test_record_order_on_input_does_not_matter(self):
        result = lc.fold(candidate(), list(reversed(chain())))
        self.assertEqual((result.state, result.errors), ("active", []))


class RecordRuleTests(unittest.TestCase):
    def assertRejected(self, record, fragment):
        errors = lc.validate_record(record)
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_candidate_without_future_decision_fails_admission(self):
        record = candidate()
        del record["future_decision"]
        self.assertRejected(record, "missing required 'future_decision'")

    def test_future_decision_must_name_a_decision(self):
        self.assertRejected(
            candidate(future_decision="Supercalifragilistic expialidocious"), "concrete"
        )
        record = candidate()
        record["future_decision"] = record["claim"]
        self.assertRejected(record, "restates the claim")

    def test_candidate_needs_evidence(self):
        self.assertRejected(candidate(evidence=[]), "fewer than 1 items")

    def test_class_is_never_lowered_below_the_kind(self):
        self.assertRejected(
            candidate(kind="policy", promotion_class="P4"), "at least P8"
        )
        self.assertEqual(lc.validate_record(candidate(promotion_class="P6")), [])

    def test_only_episodic_has_no_destination(self):
        self.assertRejected(candidate(destination=None), "only an episodic")
        self.assertEqual(
            lc.validate_record(
                candidate(kind="episodic", promotion_class="P4", destination=None)
            ),
            [],
        )

    def test_destination_path_cannot_escape_the_repository(self):
        for path in ("../secrets.txt", "a/../../b", "/etc/x", "~/x", "C:\\x", "a\\b"):
            dest = {"repo": "example-repo", "path": path}
            self.assertRejected(candidate(destination=dest), "destination")

    def test_validity_window_and_timestamps(self):
        self.assertRejected(
            candidate(valid_until="2026-10-01T00:00:00Z"), "after valid_from"
        )
        self.assertRejected(candidate(at="2026-13-01T00:00:00Z"), "real UTC instant")
        self.assertRejected(candidate(at="2026-10-01T00:00:00+01:00"), "does not match")

    def test_experience_id_is_derived_from_its_source(self):
        record = copy.deepcopy(example("estate-experience.json")[0])
        record["source"]["key"] = "another-run"
        self.assertRejected(record, "exp_ + sha256")
        self.assertEqual(
            lc.experience_id("muse-job", "k"), lc.experience_id("muse-job", "k")
        )

    def test_only_a_merged_run_matures(self):
        record = copy.deepcopy(example("estate-experience.json")[0])
        record["outcome"]["immediate"] = "completed"
        self.assertRejected(record, "only a merged run matures")

    def test_booleans_are_not_integers(self):
        record = copy.deepcopy(example("estate-experience.json")[0])
        record["cost"]["tokens"]["input"] = True
        self.assertRejected(record, "expected integer")

    def test_experience_carries_no_free_text_feedback(self):
        record = copy.deepcopy(example("estate-experience.json")[0])
        record["feedback"][0]["text"] = "the owner said this was wrong"
        self.assertRejected(record, "unexpected property")

    def test_memory_use_rules(self):
        record = copy.deepcopy(example("memory-use.json")[0])
        record["memories"][0].update(supplied=False, read=False, cited=True)
        self.assertRejected(record, "cited but never supplied")
        record = copy.deepcopy(example("memory-use.json")[0])
        record["id"] = "mu_0000000000000000"
        self.assertRejected(record, "experience id's suffix")

    def test_illegal_edge(self):
        self.assertRejected(
            move(1, None, "candidate", "probation"), "not a lifecycle edge"
        )
        self.assertRejected(move(1, None, "archived", "active"), "not a lifecycle edge")

    def test_gate_placement_forces_the_path(self):
        record = move(
            1, None, "evaluating", "probation", [gate("canary", "2026-10-08T11:00:00Z")]
        )
        self.assertRejected(record, "canary is not recorded leaving evaluating")

    def test_failed_gate_cannot_move_forward(self):
        failed = gate("offline_eval", "2026-10-08T11:00:00Z", result="fail")
        self.assertRejected(
            move(1, None, "evaluating", "canary", [failed]), "failed gate"
        )
        self.assertEqual(
            lc.validate_record(move(1, None, "evaluating", "rejected", [failed])), []
        )

    def test_offline_eval_must_name_the_sealed_holdout(self):
        bare = {
            "gate": "offline_eval",
            "result": "pass",
            "evaluator": ORACLE,
            "at": "2026-10-08T11:00:00Z",
        }
        self.assertRejected(
            move(1, None, "evaluating", "canary", [bare]), "holdout_digest"
        )
        leaky = dict(bare, holdout_digest=HOLDOUT, training_excluded=False)
        self.assertRejected(
            move(1, None, "evaluating", "canary", [leaky]), "must be true"
        )

    def test_owner_gate_is_judged_only_by_the_owner(self):
        self.assertRejected(
            move(
                1, None, "evaluating", "active", [gate("owner", "2026-10-08T11:00:00Z")]
            ),
            "judged only by the owner",
        )
        impostor = dict(OWNER, runtime="claude")
        self.assertRejected(
            move(
                1,
                None,
                "evaluating",
                "active",
                [gate("owner", "2026-10-08T11:00:00Z", impostor)],
            ),
            "owner kind and owner runtime",
        )

    def test_live_effect_above_p0_needs_authority(self):
        self.assertRejected(
            move(1, None, "candidate", "evaluating", effect="live"), "authority"
        )
        self.assertEqual(
            lc.validate_record(
                move(1, None, "candidate", "active", cls="P0", effect="live")
            ),
            [],
        )
        self.assertEqual(
            lc.validate_record(
                move(
                    1,
                    None,
                    "candidate",
                    "evaluating",
                    effect="live",
                    authority="decision:x-1",
                )
            ),
            [],
        )

    def test_transition_specific_fields(self):
        self.assertRejected(
            move(1, None, "active", "reverted"), "missing required 'revert'"
        )
        self.assertRejected(move(1, None, "candidate", "merged"), "merged_into")
        self.assertRejected(
            move(1, None, "candidate", "rejected", merged_into="lc_other-0001"),
            "only on a move to merged",
        )

    def test_unknown_schema_and_non_object(self):
        self.assertTrue(lc.validate_record({"schema": "learning-candidate/v9"}))
        self.assertTrue(lc.validate_record(["not", "an", "object"]))


class FoldTests(unittest.TestCase):
    """The promotion-gate decision logic: the high-risk core of the contract."""

    def fold_steps(self, cand, *steps, cls=None):
        return lc.fold(cand, walk(*steps, cls=cls or cand["promotion_class"]))

    def test_p4_cannot_skip_canary(self):
        result = self.fold_steps(
            candidate(),
            ("candidate", "evaluating", [], "2026-10-08T11:00:00Z"),
            (
                "evaluating",
                "probation",
                [gate("offline_eval", "2026-10-08T12:00:00Z")],
                "2026-10-08T12:01:00Z",
            ),
            (
                "probation",
                "active",
                [gate("maturity", "2026-10-16T00:00:00Z")],
                "2026-10-16T00:01:00Z",
            ),
        )
        self.assertEqual(result.state, "probation")
        self.assertTrue(
            any("pass of canary" in e for e in result.errors), result.errors
        )

    def test_p0_activates_directly(self):
        cand = candidate(kind="episodic", promotion_class="P0", destination=None)
        result = self.fold_steps(
            cand, ("candidate", "active", [], "2026-10-08T12:00:00Z")
        )
        self.assertEqual((result.state, result.errors), ("active", []))

    def test_p1_direct_activation_without_gates_is_refused(self):
        cand = candidate(kind="semantic", promotion_class="P1")
        result = self.fold_steps(
            cand, ("candidate", "active", [], "2026-10-08T12:00:00Z")
        )
        self.assertEqual(result.state, "candidate")
        self.assertTrue(result.errors)

    def test_protected_semantic_memory_needs_the_owner(self):
        cand = candidate(kind="semantic", promotion_class="P1", protected=True)
        checks = [
            gate("provenance", "2026-10-08T12:00:00Z"),
            gate("contradiction", "2026-10-08T12:00:00Z"),
        ]
        steps = [
            ("candidate", "evaluating", [], "2026-10-08T11:00:00Z"),
            ("evaluating", "active", checks, "2026-10-08T12:01:00Z"),
        ]
        refused = self.fold_steps(cand, *steps)
        self.assertTrue(
            any("pass of owner" in e for e in refused.errors), refused.errors
        )
        steps[1] = (
            "evaluating",
            "active",
            checks + [gate("owner", "2026-10-08T12:00:00Z", OWNER)],
            "2026-10-08T12:01:00Z",
        )
        self.assertEqual(self.fold_steps(cand, *steps).state, "active")

    def test_the_learner_never_evaluates_itself(self):
        cand = candidate(kind="skill", promotion_class="P3")
        learner = dict(ORACLE, session=cand["producer"]["session"])
        for evaluator in (learner, dict(ORACLE, kind="self")):
            result = self.fold_steps(
                cand,
                ("candidate", "evaluating", [], "2026-10-08T11:00:00Z"),
                (
                    "evaluating",
                    "active",
                    [gate("offline_eval", "2026-10-08T12:00:00Z", evaluator)],
                    "2026-10-08T12:01:00Z",
                ),
            )
            self.assertEqual(result.state, "evaluating", evaluator)

    def test_an_llm_judge_alone_cannot_activate(self):
        cand = candidate(kind="skill", promotion_class="P3")
        judge = {
            "kind": "llm_judge",
            "runtime": "grok",
            "model": "m",
            "session": "judge-1",
        }
        result = self.fold_steps(
            cand,
            ("candidate", "evaluating", [], "2026-10-08T11:00:00Z"),
            (
                "evaluating",
                "active",
                [gate("offline_eval", "2026-10-08T12:00:00Z", judge)],
                "2026-10-08T12:01:00Z",
            ),
        )
        self.assertTrue(
            any("not only an LLM judge" in e for e in result.errors), result.errors
        )

    def test_a_later_failure_overrides_an_earlier_pass(self):
        cand = candidate(kind="skill", promotion_class="P3", consequential=True)
        result = self.fold_steps(
            cand,
            ("candidate", "evaluating", [], "2026-10-08T11:00:00Z"),
            (
                "evaluating",
                "canary",
                [gate("offline_eval", "2026-10-08T12:00:00Z")],
                "2026-10-08T12:01:00Z",
            ),
            (
                "canary",
                "rejected",
                [gate("canary", "2026-10-09T12:00:00Z", result="fail")],
                "2026-10-09T12:01:00Z",
            ),
        )
        self.assertEqual((result.state, result.errors), ("rejected", []))
        self.assertEqual(result.gates["canary"]["result"], "fail")

    def test_p8_owner_pass_must_be_on_the_activating_record(self):
        cand = candidate(kind="policy", promotion_class="P8")
        steps = [
            (
                "candidate",
                "evaluating",
                [gate("owner", "2026-10-08T11:00:00Z", OWNER)],
                "2026-10-08T11:00:00Z",
            ),
            (
                "evaluating",
                "active",
                [gate("tests", "2026-10-08T12:00:00Z")],
                "2026-10-08T12:01:00Z",
            ),
        ]
        refused = self.fold_steps(cand, *steps)
        self.assertTrue(
            any("never automatic" in e for e in refused.errors), refused.errors
        )
        steps[1] = (
            "evaluating",
            "active",
            [
                gate("tests", "2026-10-08T12:00:00Z"),
                gate("owner", "2026-10-08T12:00:00Z", OWNER),
            ],
            "2026-10-08T12:01:00Z",
        )
        self.assertEqual(self.fold_steps(cand, *steps).state, "active")

    def test_maturity_needs_the_full_window(self):
        records = chain()
        records[3]["gates"][0]["at"] = "2026-10-15T12:00:00Z"
        records[3]["at"] = "2026-10-15T12:01:00Z"
        result = lc.fold(candidate(), records)
        self.assertEqual(result.state, "probation")
        self.assertTrue(any("before 7 days" in e for e in result.errors), result.errors)

    def test_gates_are_judged_during_the_stay(self):
        records = chain()
        records[1]["gates"][0]["at"] = "2026-10-08T11:00:00Z"  # before evaluating began
        result = lc.fold(candidate(), records)
        self.assertEqual(result.state, "evaluating")
        self.assertTrue(any("outside the evaluating stay" in e for e in result.errors))

    def test_fork_stops_the_fold(self):
        records = chain()
        twin = copy.deepcopy(records[1])
        twin.update(id="prom_example-twin", to="rejected", gates=[])
        result = lc.fold(candidate(), records + [twin])
        self.assertEqual(result.state, "evaluating")
        self.assertTrue(
            any(e.startswith("fork after prom_example-0001") for e in result.errors)
        )

    def test_invalid_record_leaves_a_gap(self):
        records = chain()
        records[2]["to"] = "archived"
        result = lc.fold(candidate(), records)
        self.assertEqual(result.state, "canary")
        self.assertTrue(any("orphan" in e for e in result.errors), result.errors)

    def test_records_of_another_candidate_are_refused(self):
        records = chain()
        records[0]["candidate"] = "lc_other-0001"
        result = lc.fold(candidate(), records)
        self.assertEqual(result.state, "candidate")
        self.assertTrue(any("belongs to lc_other-0001" in e for e in result.errors))

    def test_class_must_match_the_candidate(self):
        records = chain()
        for record in records:
            record["promotion_class"] = "P5"
        self.assertEqual(lc.fold(candidate(), records).state, "candidate")

    def test_invalid_candidate_folds_nothing(self):
        result = lc.fold(candidate(evidence=[]), chain())
        self.assertEqual(result.chain, [])
        self.assertTrue(result.errors)


class SplitTests(unittest.TestCase):
    def test_split_is_deterministic_and_near_twenty_percent(self):
        sides = [lc.split_of(f"key-{n}") for n in range(10000)]
        self.assertEqual(sides, [lc.split_of(f"key-{n}") for n in range(10000)])
        self.assertTrue(1700 < sides.count("holdout") < 2300, sides.count("holdout"))

    def test_split_key_groups_runs(self):
        record = example("estate-experience.json")[0]
        keyed = dict(record, split_key="cluster-1")
        self.assertEqual(lc.experience_split(keyed), lc.split_of("cluster-1"))
        default = lc.split_of(f"{record['source']['kind']}|{record['source']['key']}")
        self.assertEqual(lc.experience_split(record), default)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = lc.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_validate_exit_codes(self):
        code, out, _ = self.run_cli("validate", *map(str, sorted(EXAMPLES.iterdir())))
        self.assertEqual((code, json.loads(out)["invalid"]), (0, 0))
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.jsonl"
            bad.write_text(json.dumps(candidate(evidence=[])) + "\n", "utf-8")
            self.assertEqual(self.run_cli("validate", str(bad))[0], 1)
            dup = Path(tmp) / "dup.json"
            dup.write_text('{"schema": "a", "schema": "b"}', "utf-8")
            code, _, err = self.run_cli("validate", str(dup))
            self.assertEqual(code, 2)
            self.assertIn("duplicate JSON key", err)

    def test_fold_command(self):
        code, out, _ = self.run_cli(
            "fold",
            "--candidate",
            str(EXAMPLES / "learning-candidate.json"),
            "--records",
            str(EXAMPLES / "promotion-chain.jsonl"),
        )
        self.assertEqual((code, json.loads(out)["state"]), (0, "active"))

    def test_experience_id_command(self):
        code, out, _ = self.run_cli("experience-id", "--kind", "muse-job", "--key", "k")
        self.assertEqual((code, out.strip()), (0, lc.experience_id("muse-job", "k")))


if __name__ == "__main__":
    unittest.main()
