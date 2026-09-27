"""The merge-gate model: exhaustive invariants, seeded mutants, and named law scenarios."""

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "merge_gate_model.py"
spec = importlib.util.spec_from_file_location("merge_gate_model", MODULE)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)

HAPPY = [
    "lease",
    "start",
    "worker_ok",
    "proof_pass",
    "publish",
    "review_pass",
    "ci_green",
]
AGED = ["tick"] * model.AGE_MINUTES


def run(events, authority="free", mutants=frozenset()):
    state = model.initial(authority)
    for event in events:
        successor = model.step(state, event, mutants)
        if successor is None:
            raise AssertionError(f"{event!r} is not enabled in {state.phase}")
        state = successor
    return state


def enabled(state, event):
    return model.step(state, event) is not None


class ExhaustiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = model.model_check()

    def test_the_model_satisfies_every_invariant(self):
        self.assertTrue(self.result["ok"], self.result["violations"][:3])
        self.assertGreater(self.result["merge_edges"], 0)
        self.assertEqual(
            set(self.result["phases"]),
            {
                "Candidate", "Tasked", "Running", "Proving", "Proven", "Review", "Fixing",
                "AgeGate", "MergeReady", "Merged", "PostMerge", "Revert", "Closed",
                "Parked", "DeadLetter", "OwnerBlocked",
            },
        )  # fmt: skip

    def test_every_seeded_mutant_is_caught_with_the_expected_violation(self):
        expected = {
            "no_age_gate": ("illegal_merge", "aged"),
            "stale_review": ("illegal_merge", "reviewed"),
            "third_round": ("state", "review rounds"),
            "unbounded_fixes": ("unbounded_cycle", "repeat"),
            "merge_on_red": ("illegal_merge", "green CI"),
            "retarget_keeps_proof": ("illegal_merge", "proof"),
            "gated_merges": ("illegal_merge", "authority"),
            "draft_merge": ("illegal_merge", "ready-for-review"),
            # the review's slip-throughs: table bookkeeping the observer re-derives
            "age_kept_on_push": ("illegal_merge", "aged"),
            "uncounted_review": ("illegal_merge", "review rounds"),
            "changes_reopen": ("illegal_merge", "review rounds"),
            "conflict_keeps_review": ("illegal_merge", "reviewed"),
            # #359: observer hardening and law 2g's semantic retarget
            "semantic_retarget_keeps_review": ("illegal_merge", "reviewed"),
            "early_critical": ("illegal_merge", "review rounds"),
            "tick_before_push": ("illegal_merge", "aged"),
            "unfixed_critical": ("illegal_merge", "review rounds"),
        }
        self.assertEqual(set(expected), set(model.MUTANTS))
        for mutant, (kind, fragment) in expected.items():
            with self.subTest(mutant=mutant):
                result = model.model_check(frozenset({mutant}))
                self.assertFalse(result["ok"])
                self.assertTrue(
                    any(
                        v["kind"] == kind and fragment in v["detail"]
                        for v in result["violations"]
                    ),
                    result["violations"][:2],
                )

    def test_counterexample_traces_replay_to_the_violation(self):
        mutants = frozenset({"no_age_gate"})
        result = model.model_check(mutants)
        violation = next(
            v for v in result["violations"] if v["kind"] == "illegal_merge"
        )
        state = run(violation["trace"], violation["authority"], mutants)
        self.assertEqual(state.phase, "MergeReady")
        obs = model.Observer()
        for event in violation["trace"]:
            obs = model.observe(obs, event)
        merged = model.step(state, "merge", mutants)
        self.assertIn(
            "head has not aged three minutes",
            model.merge_violations(state, merged, obs),
        )


class AbstractionTests(unittest.TestCase):
    MUTANT_SETS = [frozenset()] + [frozenset({m}) for m in model.MUTANTS]

    def walks(self, mutants, count=60):
        """Yield (state, observer, event, successor) along seeded walks, final states included."""
        for trace in model.random_traces(count, seed=7, max_steps=80, mutants=mutants):
            state, obs = model.initial(trace["authority"]), model.Observer()
            for event in trace["events"] + [None]:
                successor = None if event is None else model.step(state, event, mutants)
                yield state, obs, event, successor
                if event is not None:
                    state, obs = successor, model.observe(obs, event)

    def test_canonical_states_preserve_every_spec_verdict(self):
        """The finite abstraction must never change whether a merge or state is lawful."""
        for mutants in self.MUTANT_SETS:
            for state, obs, event, successor in self.walks(mutants):
                if (
                    successor
                    and successor.phase == "Merged"
                    and state.phase != "Merged"
                ):
                    self.assertEqual(
                        model.merge_violations(state, successor, obs),
                        model.merge_violations(
                            model.canonical(state), model.canonical(successor), obs
                        ),
                    )
                if state.phase not in model.TERMINAL:
                    self.assertEqual(
                        model.state_violations(state),
                        model.state_violations(model.canonical(state)),
                    )

    def test_canonical_commutes_with_step(self):
        """Exploring canonical states reaches exactly the canonical images of real ones."""
        for mutants in self.MUTANT_SETS:
            for state, _, _, _ in self.walks(mutants, count=20):
                collapsed = model.canonical(state)
                for event in model.EVENTS:
                    concrete = model.step(state, event, mutants)
                    abstract = model.step(collapsed, event, mutants)
                    self.assertEqual(concrete is None, abstract is None)
                    if concrete is not None:
                        self.assertEqual(
                            model.canonical(concrete), model.canonical(abstract)
                        )

    def test_liveness_fails_when_free_authority_can_never_merge(self):
        original = model.step

        def owner_only(state, event, mutants=frozenset()):
            result = original(state, event, mutants)
            if result is not None and result.phase == "MergeReady":
                return result._replace(phase="OwnerBlocked")
            return result

        model.step = owner_only
        self.addCleanup(setattr, model, "step", original)
        result = model.model_check()
        self.assertTrue(any(v["kind"] == "liveness" for v in result["violations"]))


class LawScenarioTests(unittest.TestCase):
    def test_happy_path_merges_only_after_aging(self):
        state = run(HAPPY)
        self.assertFalse(enabled(state, "evaluate"))
        state = run(
            HAPPY + AGED + ["evaluate", "merge", "postmerge_start", "postmerge_pass"]
        )
        self.assertEqual(state.phase, "Closed")
        self.assertEqual(state.merged_head, state.head)

    def test_only_free_authority_merges_autonomously(self):
        for authority in ("gated", "human-only", "none"):
            with self.subTest(authority=authority):
                state = run(HAPPY + AGED + ["evaluate"], authority)
                self.assertEqual(state.phase, "OwnerBlocked")
                self.assertFalse(enabled(state, "merge"))

    def test_second_round_changes_park_the_pr(self):
        state = run(
            HAPPY[:5]
            + ["review_changes", "fix_logic", "proof_pass", "publish", "review_changes"]
        )
        self.assertEqual((state.phase, state.review_rounds), ("Parked", 2))

    def test_a_new_critical_reopens_once_then_parks(self):
        prefix = HAPPY[:5] + ["review_changes", "fix_logic", "proof_pass", "publish"]
        reopened = prefix + ["review_critical", "fix_logic", "proof_pass", "publish"]
        state = run(reopened)
        self.assertEqual(
            (state.phase, state.review_rounds, state.reopened), ("Review", 2, True)
        )
        self.assertEqual(run(reopened + ["review_critical"]).phase, "Parked")
        self.assertFalse(enabled(run(HAPPY[:5]), "review_critical"))

    def test_a_critical_on_a_base_change_round_cannot_reopen(self):
        """Law 2d reopens only for a CRITICAL introduced by the fixes (Codex, #361)."""
        state = run(
            HAPPY[:5] + ["review_pass", "ci_green", "retarget_semantic"]
            + ["proof_pass", "publish"]
        )  # fmt: skip
        self.assertEqual((state.phase, state.review_rounds), ("Review", 1))
        self.assertFalse(enabled(state, "review_critical"))
        self.assertEqual(model.step(state, "review_changes").phase, "Parked")

    def test_logic_change_after_the_last_round_parks_but_a_mechanical_fix_ships(self):
        rounds_spent = HAPPY[:5] + [
            "review_changes", "fix_logic", "proof_pass", "publish", "review_pass", "ci_red",
        ]  # fmt: skip
        logic = run(rounds_spent + ["fix_logic", "proof_pass", "publish"])
        self.assertEqual(logic.phase, "Parked")
        state = run(
            rounds_spent
            + ["fix_mechanical", "proof_pass", "publish", "ci_green"]
            + AGED
            + ["evaluate", "merge"]
        )
        self.assertEqual(state.phase, "Merged")

    def test_retarget_keeps_the_review_but_reproves_ci_without_resetting_age(self):
        state = run(HAPPY + ["tick", "retarget"])
        self.assertEqual(state.phase, "Proving")
        self.assertTrue(state.reviewed)
        state = run(HAPPY + ["tick", "retarget", "proof_pass", "publish"])
        self.assertEqual((state.phase, state.age), ("AgeGate", 1))
        self.assertFalse(enabled(state, "evaluate"))  # CI must re-run for the new base
        state = run(
            HAPPY
            + ["tick", "retarget", "proof_pass", "publish", "ci_green", "tick", "tick"]
            + ["evaluate", "merge"]
        )
        self.assertEqual(state.phase, "Merged")

    def test_a_semantic_retarget_needs_a_fresh_review_but_keeps_aging(self):
        state = run(HAPPY + ["tick", "retarget_semantic", "proof_pass", "publish"])
        self.assertEqual((state.phase, state.reviewed, state.age), ("Review", False, 1))
        state = run(
            HAPPY
            + ["tick", "retarget_semantic", "proof_pass", "publish", "review_pass"]
            + ["ci_green", "tick", "tick", "evaluate", "merge"]
        )
        self.assertEqual(state.phase, "Merged")

    def test_a_conflicting_refresh_needs_a_fresh_review(self):
        state = run(HAPPY + AGED + ["refresh_conflict", "proof_pass", "publish"])
        self.assertEqual((state.phase, state.reviewed, state.age), ("Review", False, 0))
        spent = HAPPY[:5] + [
            "review_changes", "fix_logic", "proof_pass", "publish", "review_pass",
        ]  # fmt: skip
        parked = run(spent + ["refresh_conflict", "proof_pass", "publish"])
        self.assertEqual(parked.phase, "Parked")  # no round left to review it

    def test_a_refresh_merge_commit_is_a_new_head_that_ages_again(self):
        state = run(
            HAPPY + AGED + ["refresh_merge", "proof_pass", "publish", "ci_green"]
        )
        self.assertEqual((state.phase, state.age, state.reviewed), ("AgeGate", 0, True))
        self.assertFalse(enabled(state, "evaluate"))

    def test_counters_terminate_every_loop(self):
        attempts = ["lease"] + ["start", "worker_fail"] * model.MAX_ATTEMPTS + ["start"]
        self.assertEqual(run(attempts).phase, "DeadLetter")
        fixes = ["ci_red", "fix_mechanical", "proof_pass", "publish"] * model.MAX_FIXES
        self.assertEqual(run(HAPPY[:-1] + fixes + ["ci_red"]).phase, "Parked")
        refreshes = ["retarget", "proof_pass", "publish"] * model.MAX_REFRESHES
        self.assertEqual(run(HAPPY + refreshes + ["retarget"]).phase, "Parked")

    def test_post_merge_regression_reverts_or_asks_the_owner(self):
        merged = HAPPY + AGED + ["evaluate", "merge", "postmerge_start"]
        state = run(merged + ["postmerge_regression", "revert_done"])
        self.assertEqual((state.phase, state.reverted), ("Closed", True))
        state = run(merged + ["postmerge_regression", "revert_irreversible"])
        self.assertEqual(state.phase, "OwnerBlocked")


class CliTests(unittest.TestCase):
    def test_traces_are_seeded_and_replayable(self):
        first = list(model.random_traces(20, seed=3))
        self.assertEqual(first, list(model.random_traces(20, seed=3)))
        for trace in first:
            state = model.initial(trace["authority"])
            self.assertEqual(len(trace["refused"]), len(trace["events"]) + 1)
            for index, event in enumerate(trace["events"] + [None]):
                for refused in trace["refused"][index]:
                    self.assertIsNone(model.step(state, refused))
                if event is not None:
                    state = model.step(state, event)
                    self.assertEqual(state.phase, trace["phases"][index])
            self.assertEqual(state._asdict(), trace["final"])

    def test_counters_are_checked_on_raw_successors(self):
        """Violations are read from the uncollapsed successor, which terminal collapse would hide."""
        result = model.model_check(frozenset({"third_round"}))
        self.assertTrue(
            any(
                v["kind"] == "state" and "review rounds" in v["detail"]
                and v["detail"].endswith(("after review_changes", "after review_critical"))
                for v in result["violations"]
            ),
            result["violations"][:3],
        )  # fmt: skip

    def test_refusals_align_when_the_step_limit_ends_the_walk(self):
        for trace in model.random_traces(10, seed=5, max_steps=2):
            self.assertEqual(len(trace["events"]), 2)
            self.assertEqual(len(trace["refused"]), 3)
            self.assertEqual(len(trace["phases"]), 2)

    def test_all_mutants_cli_exits_zero_only_when_every_mutant_is_caught(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = model.main(["check", "--all-mutants"])
        self.assertEqual(code, 0)
        self.assertTrue(all(json.loads(out.getvalue())["mutants_caught"].values()))

    def test_diagram_names_every_phase(self):
        diagram = model.mermaid()
        for phase in (
            "Candidate",
            "MergeReady",
            "Merged",
            "DeadLetter",
            "OwnerBlocked",
        ):
            self.assertIn(phase, diagram)


if __name__ == "__main__":
    unittest.main()
