"""Learning-plane contracts: schemas, data files, validator and lifecycle fold.

Synthetic records only (schemas/learning/examples); no live ledger is read.
"""

import copy
import datetime as dt
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


def example_files():
    return sorted(p for p in EXAMPLES.rglob("*") if p.is_file())


def example(name):
    return lc.read_records(EXAMPLES / name)


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
    record = copy.deepcopy(example("learning-candidate.json")[0])
    if "genome" not in changes:  # genome exclusion has its own tests
        record.pop("genome", None)
    if "kind" in changes and "destination" not in changes:
        changes["destination"] = SURFACES[changes["kind"]]
    record.update(changes)
    return record


def chain():
    return copy.deepcopy(example("promotion-chain.jsonl"))


SOURCE = "agent-hq@" + "a" * 40


def answer(
    decision,
    option="approve",
    answered_at="2026-09-01T00:00:00Z",
    status="answered",
    subject="lc_example-0001",
    created="2026-08-30T00:00:00Z",
    exit_bars=None,
    graduation=None,
):
    """A decision-resolution/v1 as a resolver reading agent-hq origin/main returns it."""
    decided = status in ("answered", "defaulted")
    return {
        "schema": "decision-resolution/v1",
        "decision": decision,
        "source": SOURCE,
        "status": status,
        "option": option if decided else None,
        "answered_at": answered_at if decided else None,
        "created": created,
        "expires": None,
        "subject": {"candidate": subject} if subject else None,
        "measures": {"exit_bars": exit_bars or {}, "graduation": graduation or {}},
    }


APPROVAL = answer("test-owner-1")  # the owner approved lc_example-0001


def resolver(*answers):
    return lc.resolver_from(answers)


def gate(name, at, evaluator=ORACLE, result="pass"):
    item = {"gate": name, "result": result, "evaluator": evaluator, "at": at}
    if name == "owner":
        item["ref"] = "decision:test-owner-1"
    if name in ("offline_eval", "replay", "retrieval_regression"):
        item.update(
            holdout_digest=HOLDOUT,
            training_excluded=True,
            anchors=[],
            metrics={"cases": 20, "delta": 0.1, "wins": 8, "losses": 0, "anchored": 20},
        )
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
            listed = set(re.findall(r"`([a-z_0-9]+)`", row.split("|")[2]))
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
        paths = example_files()
        self.assertEqual(len(paths), 10)
        for path in paths:
            for record in lc.read_records(path):
                self.assertEqual(
                    lc.validate_record(record), [], record.get("id", path.name)
                )

    def test_example_chain_folds_to_active_in_shadow(self):
        result = lc.fold(candidate(), chain())
        self.assertEqual(result.errors, [])
        self.assertEqual((result.state, result.effect), ("active", "shadow"))
        self.assertEqual(len(result.chain), 4)

    def test_record_order_on_input_does_not_matter(self):
        result = lc.fold(candidate(), list(reversed(chain())))
        self.assertEqual((result.state, result.errors), ("active", []))


class MinimaTests(unittest.TestCase):
    """A passing hold-out gate's own results meet the pinned eval_minima (K3)."""

    def fold_with(self, **metrics):
        records = chain()
        gate_ = records[1]["gates"][0]
        gate_["metrics"].update(metrics)
        for name in [k for k, v in metrics.items() if v is None]:
            del gate_["metrics"][name]
        return lc.fold(candidate(), records)

    def test_every_hold_out_gate_has_pinned_minima(self):
        minima = dict(lc.classes()["eval_minima"])
        minima.pop("description")
        self.assertEqual(
            set(minima), {"offline_eval", "replay", "retrieval_regression"}
        )
        for pinned in minima.values():
            self.assertGreaterEqual(pinned["min_cases"], 20)
            self.assertEqual(pinned["max_sign_p"], 0.05)

    def test_short_or_lossy_or_unanchored_gates_do_not_count(self):
        for metrics, fragment in (
            ({"cases": 19, "anchored": 19}, "under 20"),
            ({"delta": -0.01}, "delta"),
            ({"wins": 4, "losses": 0}, "p = 0.062"),  # audit: W >= 5 at L = 0
            ({"wins": 6, "losses": 1}, "p = 0.062"),  # W >= 7 at L = 1
            ({"anchored": 5}, "anchored 0.21"),
            ({"anchored": None}, "does not report anchored"),
        ):
            result = self.fold_with(**metrics)
            self.assertEqual(result.state, "evaluating", metrics)
            self.assertTrue(
                any(fragment in e for e in result.errors), (metrics, result.errors)
            )

    def test_the_sign_test_matches_the_audit_table(self):
        # The smallest passing W for L = 0..4 at one-sided p < 0.05.
        for losses, wins in enumerate((5, 7, 9, 10, 12)):
            self.assertLess(lc.sign_p(wins, losses), 0.05, (wins, losses))
            self.assertGreaterEqual(lc.sign_p(wins - 1, losses), 0.05, (wins, losses))

    def test_a_failed_gate_is_not_held_to_the_minima(self):
        records = chain()
        records[1]["gates"][0].update(result="fail", metrics={})
        self.assertEqual(lc.minima_errors(records[1]["gates"][0]), [])


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
            candidate(valid_until="2026-09-01T00:00:00Z"), "after valid_from"
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
                    "evaluating",
                    "canary",
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

    T0 = "2026-09-08T11:00:00Z"  # the example candidate's own `at`

    def fold_steps(self, cand, *steps, cls=None, as_of=None, resolve=None):
        return lc.fold(
            cand,
            walk(*steps, cls=cls or cand["promotion_class"]),
            as_of=as_of,
            resolve=resolve or resolver(APPROVAL),
        )

    def path(self, evaluation, canary=None, active=(), effect=None):
        """candidate -> evaluating -> [canary ->] probation -> active, timed legally."""
        steps = [("candidate", "evaluating", [], self.T0)]
        if canary is None:
            steps.append(
                ("evaluating", "probation", evaluation, "2026-09-08T12:01:00Z")
            )
            entered = "2026-09-08T12:01:00Z"
        else:
            steps.append(("evaluating", "canary", evaluation, "2026-09-08T12:01:00Z"))
            steps.append(("canary", "probation", canary, "2026-09-09T12:01:00Z"))
            entered = "2026-09-09T12:01:00Z"
        mature = lc.parse_time(entered) + dt.timedelta(days=7, minutes=4)
        stamp = mature.strftime("%Y-%m-%dT%H:%M:%SZ")
        after = (mature + dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        steps.append(("probation", "active", [gate("maturity", stamp), *active], after))
        return steps

    def test_p4_cannot_skip_canary(self):
        steps = self.path([gate("offline_eval", "2026-09-08T12:00:00Z")])
        result = self.fold_steps(candidate(), *steps)
        self.assertEqual(result.state, "probation")
        self.assertTrue(
            any("pass of canary" in e for e in result.errors), result.errors
        )

    def test_p0_activates_directly(self):
        cand = candidate(kind="episodic", promotion_class="P0", destination=None)
        result = self.fold_steps(cand, ("candidate", "active", [], self.T0))
        self.assertEqual((result.state, result.errors), ("active", []))

    def test_no_class_above_p0_activates_without_probation(self):
        for kind, cls in (("semantic", "P1"), ("skill", "P3"), ("policy", "P8")):
            cand = candidate(kind=kind, promotion_class=cls)
            result = self.fold_steps(cand, ("candidate", "active", [], self.T0))
            self.assertEqual(result.state, "candidate", cls)
            self.assertTrue(
                any("pass of maturity" in e for e in result.errors), result.errors
            )
        self.assertNotIn("active", lc.lifecycle()["edges"]["evaluating"])

    def test_protected_memory_waits_for_the_owner_only_to_go_live(self):
        # In shadow nothing is written, so a protected note activates on its
        # checks; going live needs the owner's approval (test_learning_authority).
        cand = candidate(kind="semantic", promotion_class="P1", protected=True)
        checks = [
            gate("provenance", "2026-09-08T12:00:00Z"),
            gate("contradiction", "2026-09-08T12:00:00Z"),
        ]
        shadow = self.fold_steps(cand, *self.path(checks))
        self.assertEqual(
            (shadow.state, shadow.effect, shadow.errors), ("active", "shadow", [])
        )

    def test_the_learner_never_evaluates_itself(self):
        cand = candidate(kind="skill", promotion_class="P3")
        learner = dict(ORACLE, session=cand["producer"]["session"])
        for evaluator in (learner, dict(ORACLE, kind="self")):
            evaluation = [gate("offline_eval", "2026-09-08T12:00:00Z", evaluator)]
            result = self.fold_steps(cand, *self.path(evaluation))
            self.assertEqual(result.state, "probation", evaluator)
            self.assertTrue(
                any("independent pass of offline_eval" in e for e in result.errors)
            )

    def test_every_required_gate_is_checked_for_the_learner(self):
        cand = candidate()  # P4: the learner judging only the canary is refused
        learner = dict(ORACLE, session=cand["producer"]["session"])
        steps = self.path(
            [gate("offline_eval", "2026-09-08T12:00:00Z")],
            canary=[gate("canary", "2026-09-09T12:00:00Z", learner)],
        )
        result = self.fold_steps(cand, *steps)
        self.assertEqual(result.state, "probation")
        self.assertTrue(any("independent pass of canary" in e for e in result.errors))

    def test_an_llm_judge_alone_cannot_activate(self):
        cand = candidate(kind="skill", promotion_class="P3")
        judge = {"kind": "llm_judge", "runtime": "grok", "model": "m", "session": "j"}
        evaluation = [gate("offline_eval", "2026-09-08T12:00:00Z", judge)]
        # The oracle's maturity pass is a waiting period; it does not vouch.
        result = self.fold_steps(cand, *self.path(evaluation))
        self.assertEqual(result.state, "probation")
        self.assertTrue(
            any("not only an LLM judge" in e for e in result.errors), result.errors
        )
        review = [gate("independent_review", "2026-09-10T00:00:00Z")]
        accepted = self.fold_steps(cand, *self.path(evaluation, active=review))
        self.assertEqual(accepted.state, "probation")  # review is not required

    def test_a_later_failure_overrides_an_earlier_pass(self):
        cand = candidate(kind="skill", promotion_class="P3", consequential=True)
        result = self.fold_steps(
            cand,
            ("candidate", "evaluating", [], self.T0),
            (
                "evaluating",
                "canary",
                [gate("offline_eval", "2026-09-08T12:00:00Z")],
                "2026-09-08T12:01:00Z",
            ),
            (
                "canary",
                "rejected",
                [gate("canary", "2026-09-09T12:00:00Z", result="fail")],
                "2026-09-09T12:01:00Z",
            ),
        )
        self.assertEqual((result.state, result.errors), ("rejected", []))
        self.assertEqual(result.gates["canary"]["result"], "fail")

    def test_p8_owner_pass_must_be_on_the_activating_record(self):
        cand = candidate(kind="policy", promotion_class="P8")
        tests = [gate("tests", "2026-09-08T12:00:00Z")]
        early = self.path(tests)
        early[0] = ("candidate", "evaluating", [gate("owner", self.T0, OWNER)], self.T0)
        refused = self.fold_steps(cand, *early)
        self.assertTrue(
            any("never automatic" in e for e in refused.errors), refused.errors
        )
        owner = [gate("owner", "2026-09-10T00:00:00Z", OWNER)]
        self.assertEqual(
            self.fold_steps(cand, *self.path(tests, active=owner)).state, "active"
        )

    def test_p8_cannot_turn_live_without_the_owner_on_that_record(self):
        cand = candidate(kind="policy", promotion_class="P8")
        records = walk(
            ("candidate", "evaluating", [], self.T0),
            (
                "evaluating",
                "probation",
                [gate("tests", "2026-09-08T12:00:00Z")],
                "2026-09-08T12:01:00Z",
            ),
            cls="P8",
        )
        records[1].update(effect="live", authority="decision:lp-blanket")
        result = lc.fold(cand, records, resolve=resolver(APPROVAL))
        self.assertEqual((result.state, result.effect), ("evaluating", "shadow"))
        self.assertTrue(any("turns it live" in e for e in result.errors))
        records[1]["gates"].append(gate("owner", "2026-09-08T12:00:00Z", OWNER))
        records[1]["authority"] = "decision:test-owner-1"
        records[1]["landed"] = "commit:" + "e" * 40
        result = lc.fold(cand, records, resolve=resolver(APPROVAL))
        self.assertEqual(
            (result.state, result.effect, result.errors), ("probation", "live", [])
        )

    def test_live_only_into_live_capable_states(self):
        record = move(1, None, "candidate", "evaluating", effect="live")
        record["authority"] = "decision:x-1"
        self.assertTrue(any("nothing is live" in e for e in lc.validate_record(record)))

    def test_any_fold_error_fails_closed_to_shadow(self):
        cand = candidate(kind="episodic", promotion_class="P0", destination=None)
        records = walk(("candidate", "active", [], self.T0), cls="P0")
        records[0]["effect"] = "live"
        live = lc.fold(cand, records)
        self.assertEqual((live.state, live.effect, live.errors), ("active", "live", []))
        broken_revert = move(
            9,
            records[-1]["id"],
            "active",
            "reverted",
            at="2026-09-20T00:00:00Z",
            cls="P0",
        )  # no revert object: invalid
        result = lc.fold(cand, records + [broken_revert])
        self.assertEqual((result.state, result.effect), ("active", "shadow"))
        self.assertTrue(result.errors)

    def test_identical_retries_are_not_a_fork(self):
        records = chain()
        result = lc.fold(candidate(), records + [copy.deepcopy(records[2])])
        self.assertEqual((result.state, result.errors), ("active", []))

    def test_records_dated_after_as_of_are_refused(self):
        as_of = lc.parse_time("2026-09-12T00:00:00Z")
        result = lc.fold(candidate(), chain(), as_of=as_of)
        self.assertEqual(result.state, "probation")
        self.assertTrue(any("after the fold's as_of" in e for e in result.errors))

    def test_maturity_needs_the_full_window(self):
        records = chain()
        records[3]["gates"][0]["at"] = "2026-09-15T12:00:00Z"
        records[3]["at"] = "2026-09-15T12:01:00Z"
        result = lc.fold(candidate(), records)
        self.assertEqual(result.state, "probation")
        self.assertTrue(any("before 7 days" in e for e in result.errors), result.errors)

    def test_gates_are_judged_during_the_stay(self):
        records = chain()
        records[1]["gates"][0]["at"] = "2026-09-08T11:00:00Z"  # before evaluating
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
        self.assertTrue(lc.fold(["not", "a", "candidate"], chain()).errors)


class ExperienceFoldTests(unittest.TestCase):
    def test_latest_observation_wins(self):
        first = copy.deepcopy(example("estate-experience.json")[0])
        later = copy.deepcopy(first)
        later["observed_at"] = "2026-09-20T00:00:00Z"
        later["outcome"]["matured"] = "reverted"
        by_id, errors = lc.fold_experiences([later, first])
        self.assertEqual(errors, [])
        self.assertEqual(by_id[first["id"]]["outcome"]["matured"], "reverted")

    def test_split_key_is_fixed_by_the_first_observation(self):
        first = copy.deepcopy(example("estate-experience.json")[0])
        moved = copy.deepcopy(first)
        moved.update(observed_at="2026-09-20T00:00:00Z", split_key="pr:elsewhere")
        by_id, errors = lc.fold_experiences([first, moved])
        self.assertTrue(any("split_key differs" in e for e in errors), errors)
        self.assertNotIn("split_key", by_id[first["id"]])


class ReviewRegressionTests(unittest.TestCase):
    """Defects found by the #494 review lenses; each pins its fix."""

    def assertRejected(self, record, fragment):
        errors = lc.validate_record(record)
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_a_gate_evaluated_on_the_candidates_evidence_is_refused(self):
        records = chain()
        records[1]["gates"][0]["anchors"] = [candidate()["evidence"][0]]
        result = lc.fold(candidate(), records)
        self.assertEqual(result.state, "evaluating")
        self.assertTrue(
            any("own training evidence" in e for e in result.errors), result.errors
        )

    def test_offline_gates_must_name_their_anchors(self):
        bare = gate("offline_eval", "2026-10-08T11:00:00Z")
        del bare["anchors"]
        self.assertRejected(move(1, None, "evaluating", "canary", [bare]), "anchors")

    def test_owner_gate_cites_a_decision_and_authority_is_a_decision(self):
        owner = gate("owner", "2026-10-08T11:00:00Z", OWNER)
        del owner["ref"]
        self.assertRejected(move(1, None, "evaluating", "canary", [owner]), "'ref'")
        owner["ref"] = "claude-session:abc"
        self.assertRejected(move(1, None, "evaluating", "canary", [owner]), "decision")
        record = move(1, None, "evaluating", "canary", effect="live")
        record["authority"] = "claude-session:abc"
        self.assertRejected(record, "authority")

    def test_trailing_newline_never_matches_an_anchored_pattern(self):
        record = candidate()
        record["id"] = record["id"] + "\n"
        self.assertRejected(record, "does not match")
        self.assertFalse(lc._pattern_matches("^a$", "a\n"))
        self.assertTrue(lc._pattern_matches("^a$", "a"))

    def test_repository_and_path_cannot_climb(self):
        for repo in ("..", "a/..", ".git"):
            dest = {"repo": repo, "path": "x"}
            self.assertRejected(candidate(destination=dest), "destination")
        dest = {"repo": "example-repo", "path": "a\n../../x"}
        self.assertRejected(candidate(destination=dest), "destination")

    def test_a_run_never_judges_its_own_memory(self):
        record = copy.deepcopy(example("memory-use.json")[0])
        effect = record["memories"][0]["effect"]
        effect["evaluator"] = dict(effect["evaluator"], kind="self")
        self.assertRejected(record, "judged by the run itself")
        record = copy.deepcopy(example("memory-use.json")[0])
        effect = record["memories"][0]["effect"]
        effect["evaluator"] = dict(
            effect["evaluator"], session=record["producer"]["session"]
        )
        self.assertRejected(record, "judged by the run itself")

    def test_non_ascii_future_decision_counts_its_words(self):
        record = candidate(
            future_decision="Ob der Prüfer künftig generierte Dateien überspringt."
        )
        self.assertEqual(lc.validate_record(record), [])

    def test_integral_floats_are_integers_and_equal_their_ints(self):
        record = copy.deepcopy(example("estate-experience.json")[0])
        record["cost"]["tokens"]["input"] = 1.0
        self.assertEqual(lc.validate_record(record), [])
        schema = {"uniqueItems": True}
        self.assertTrue(lc._schema_errors([1, 1.0], schema, "common.schema.json", ""))
        self.assertFalse(
            lc._schema_errors(1.0, {"enum": [1]}, "common.schema.json", "")
        )

    def test_one_result_per_gate_per_record(self):
        learner = dict(ORACLE, kind="self")
        record = move(
            1,
            None,
            "evaluating",
            "probation",
            [
                gate("offline_eval", "2026-10-08T11:30:00Z", learner),
                gate("offline_eval", "2026-10-08T11:00:00Z"),
            ],
        )
        self.assertRejected(record, "offline_eval is recorded more than once")

    def test_hostile_fold_inputs_are_refused_not_raised(self):
        cand = candidate()
        for records in ([cand], [{"schema": []}], [None], ["x"]):
            result = lc.fold(cand, records)
            self.assertEqual(result.state, "candidate")
            self.assertTrue(result.errors)
        self.assertTrue(lc.fold(None, []).errors)

    def test_cli_refuses_deep_nesting_with_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep = Path(tmp) / "deep.json"
            deep.write_text("[" * 100000 + "]" * 100000, "utf-8")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = lc.main(["validate", str(deep)])
            self.assertEqual(code, 2)


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
        code, out, _ = self.run_cli("validate", *map(str, example_files()))
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
            "--genome",
            str(EXAMPLES / "candidate-genome.json"),
        )
        self.assertEqual((code, json.loads(out)["state"]), (0, "active"))

    def test_experience_id_command(self):
        code, out, _ = self.run_cli("experience-id", "--kind", "muse-job", "--key", "k")
        self.assertEqual((code, out.strip()), (0, lc.experience_id("muse-job", "k")))


if __name__ == "__main__":
    unittest.main()
