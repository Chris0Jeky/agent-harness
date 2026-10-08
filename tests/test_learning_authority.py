"""Resolved authority (K1): a live effect, an owner gate, an approval or a veto
window means something only when the injected resolver finds the owner's answer."""

import copy
import datetime as dt
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "learning_contracts", ROOT / "scripts" / "learning_contracts.py"
)
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

SOURCE = "agent-hq@" + "b" * 40
CAND = "lc_auth-0001"
LEARNER = {"lane": "miner", "runtime": "claude", "model": None, "session": "learner-1"}
ORACLE = {"kind": "oracle", "runtime": "tool", "model": None, "session": "eval-1"}
OWNER = {"kind": "owner", "runtime": "owner", "model": None, "session": "owner-1"}
DEST = {
    "semantic": {"repo": "claude-config", "path": "projects/estate/memory/lesson.md"},
    "scheduler": {"repo": "claude-config", "path": "tools/muse_coordinator.py"},
    "policy": {"repo": "claude-config", "path": "rules/laws.md"},
    "recipe": {"repo": "claude-config", "path": "muse/recipes/doc-drift.md"},
}


def answer(
    decision,
    option="approve",
    answered_at="2026-09-01T00:00:00Z",
    status="answered",
    subject=CAND,
    created="2026-08-30T00:00:00Z",
    exit_bars=None,
    graduation=None,
):
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


MET = {"p1-shadow-exit": {"met": True, "at": "2026-09-02T00:00:00Z"}}
P1_C = answer("lp-p1-memory-autopromote", "c", subject=None, exit_bars=MET)
APPROVE = answer("approve-auth-0001")
P6_B = answer("lp-p6-p7-owner-approval", "b", subject=None)


def resolver(*answers):
    return lc.resolver_from(answers)


def candidate(kind="semantic", cls="P1", **extra):
    record = {
        "schema": "learning-candidate/v1",
        "id": CAND,
        "at": "2026-09-08T11:00:00Z",
        "producer": LEARNER,
        "kind": kind,
        "trigger": "owner_correction",
        "claim": "Run the unittest suite before claiming a fix is done.",
        "evidence": ["exp_auth-evidence-01"],
        "future_decision": "Whether an agent reports a fix as done before its tests ran.",
        "scope": {"repos": ["*"]},
        "destination": DEST[kind],
        "promotion_class": cls,
        "valid_from": "2026-09-08T11:00:00Z",
    }
    record.update(extra)
    return record


def gate(name, at, evaluator=ORACLE, **extra):
    item = {"gate": name, "result": "pass", "evaluator": evaluator, "at": at}
    if name in ("offline_eval", "replay", "retrieval_regression"):
        item.update(holdout_digest="c" * 64, training_excluded=True, anchors=[])
    item.update(extra)
    return item


def owner(at, ref="decision:approve-auth-0001"):
    return gate("owner", at, OWNER, ref=ref)


def chain(cls, steps):
    """steps: (from, to, at, gates, extra) -> linked promotion records."""
    records, prev = [], None
    for n, (frm, to, at, gates, extra) in enumerate(steps, 1):
        record = {
            "schema": "promotion-record/v1",
            "id": f"prom_auth-{n:04d}",
            "at": at,
            "producer": {
                "lane": "steward",
                "runtime": "tool",
                "model": None,
                "session": "st-1",
            },
            "candidate": CAND,
            "prev": prev,
            "from": frm,
            "to": to,
            "promotion_class": cls,
            "effect": "shadow",
            "gates": gates,
            "reason": "test",
        }
        record.update(extra)
        records.append(record)
        prev = record["id"]
    return records


LIVE_P1 = {"effect": "live", "authority": "decision:lp-p1-memory-autopromote"}


def p1_path(probation=None, active=None):
    checks = [
        gate("provenance", "2026-09-08T12:00:00Z"),
        gate("contradiction", "2026-09-08T12:00:00Z"),
    ]
    return chain(
        "P1",
        [
            ("candidate", "evaluating", "2026-09-08T11:10:00Z", [], {}),
            (
                "evaluating",
                "probation",
                "2026-09-08T12:01:00Z",
                checks,
                probation or dict(LIVE_P1),
            ),
            (
                "probation",
                "active",
                "2026-09-15T12:06:00Z",
                [gate("maturity", "2026-09-15T12:05:00Z")],
                active
                or dict(LIVE_P1, landed="pr:https://github.com/o/claude-config/pull/1"),
            ),
        ],
    )


def errors_of(result):
    return " | ".join(result.errors)


class P1AuthorityTests(unittest.TestCase):
    def test_option_c_with_its_exit_bar_met_goes_live_through_a_pr(self):
        result = lc.fold(candidate(), p1_path(), resolve=resolver(P1_C))
        self.assertEqual(
            (result.state, result.effect, result.errors), ("active", "live", [])
        )

    def test_no_resolver_means_no_live_effect(self):
        result = lc.fold(candidate(), p1_path())
        self.assertEqual((result.state, result.effect), ("evaluating", "shadow"))
        self.assertIn("without a resolver", errors_of(result))

    def test_a_forged_decision_does_not_resolve(self):
        forged = dict(LIVE_P1, authority="decision:forged-not-in-inbox")
        result = lc.fold(candidate(), p1_path(probation=forged), resolve=resolver(P1_C))
        self.assertEqual(result.effect, "shadow")
        self.assertIn("does not resolve", errors_of(result))

    def test_option_a_keeps_the_class_in_shadow(self):
        a = answer("lp-p1-memory-autopromote", "a", subject=None)
        result = lc.fold(candidate(), p1_path(), resolve=resolver(a))
        self.assertIn("keeps P1 in shadow", errors_of(result))

    def test_the_exit_bar_must_be_met_by_the_move(self):
        unmet = answer(
            "lp-p1-memory-autopromote",
            "c",
            subject=None,
            exit_bars={"p1-shadow-exit": {"met": False, "at": "2026-09-02T00:00:00Z"}},
        )
        self.assertIn(
            "exit bar",
            errors_of(lc.fold(candidate(), p1_path(), resolve=resolver(unmet))),
        )
        late = answer(
            "lp-p1-memory-autopromote",
            "c",
            subject=None,
            exit_bars={"p1-shadow-exit": {"met": True, "at": "2026-09-30T00:00:00Z"}},
        )
        self.assertIn(
            "exit bar",
            errors_of(lc.fold(candidate(), p1_path(), resolve=resolver(late))),
        )

    def test_an_answer_after_the_move_does_not_count(self):
        later = answer(
            "lp-p1-memory-autopromote",
            "c",
            answered_at="2026-09-10T00:00:00Z",
            subject=None,
            exit_bars=MET,
        )
        result = lc.fold(candidate(), p1_path(), resolve=resolver(later))
        self.assertIn("answered after the move", errors_of(result))

    def test_unanswered_and_wrong_decisions_are_refused(self):
        open_ = answer("lp-p1-memory-autopromote", status="open", subject=None)
        self.assertIn(
            "is open",
            errors_of(lc.fold(candidate(), p1_path(), resolve=resolver(open_))),
        )
        other = dict(LIVE_P1, authority="decision:lp-p6-p7-owner-approval")
        result = lc.fold(candidate(), p1_path(probation=other), resolve=resolver(P6_B))
        self.assertIn("does not decide P1", errors_of(result))

    def test_option_c_lands_only_through_a_pr(self):
        result = lc.fold(
            candidate(), p1_path(active=dict(LIVE_P1)), resolve=resolver(P1_C)
        )
        self.assertEqual(result.state, "probation")
        self.assertIn("landed: pr:", errors_of(result))

    def test_a_resolver_that_fails_or_lies_fails_closed(self):
        def broken(ref):
            raise OSError("agent-hq unreachable")

        self.assertIn(
            "resolver failed",
            errors_of(lc.fold(candidate(), p1_path(), resolve=broken)),
        )
        bad = dict(P1_C, source="working-copy")
        self.assertIn(
            "invalid answer",
            errors_of(lc.fold(candidate(), p1_path(), resolve=resolver(bad))),
        )
        renamed = dict(P1_C, decision="something-else")
        self.assertIn(
            "resolved to something-else",
            errors_of(lc.fold(candidate(), p1_path(), resolve=lambda ref: renamed)),
        )


class ClassModeTests(unittest.TestCase):
    def test_p3_to_p5_never_go_live(self):
        steps = [
            ("candidate", "evaluating", "2026-09-08T11:10:00Z", [], {}),
            (
                "evaluating",
                "canary",
                "2026-09-08T12:01:00Z",
                [gate("offline_eval", "2026-09-08T12:00:00Z")],
                {"effect": "live", "authority": "decision:lp-p1-memory-autopromote"},
            ),
        ]
        cand = candidate("recipe", "P4")
        result = lc.fold(cand, chain("P4", steps), resolve=resolver(P1_C))
        self.assertIn("never goes live", errors_of(result))

    def test_p8_is_the_owners_approval_of_this_candidate(self):
        cand = candidate("policy", "P8")
        steps = [
            ("candidate", "evaluating", "2026-09-08T11:10:00Z", [], {}),
            (
                "evaluating",
                "probation",
                "2026-09-08T12:01:00Z",
                [gate("tests", "2026-09-08T12:00:00Z"), owner("2026-09-08T12:00:00Z")],
                {"effect": "live", "authority": "decision:approve-auth-0001"},
            ),
        ]
        ok = lc.fold(cand, chain("P8", steps), resolve=resolver(APPROVE))
        self.assertEqual((ok.state, ok.effect, ok.errors), ("probation", "live", []))
        other = answer("approve-auth-0001", subject="lc_someone-else")
        refused = lc.fold(cand, chain("P8", steps), resolve=resolver(other))
        self.assertIn("not lc_auth-0001", errors_of(refused))
        declined = answer("approve-auth-0001", option="decline")
        refused = lc.fold(cand, chain("P8", steps), resolve=resolver(declined))
        self.assertIn("not an approval", errors_of(refused))


class P6P7Tests(unittest.TestCase):
    """Option b: approval for each promotion until the class graduates, then a veto window."""

    def path(self, live_gates=(), active_extra=None):
        evaluation = [gate("offline_eval", "2026-09-08T12:00:00Z")]
        live = {"effect": "live", "authority": "decision:lp-p6-p7-owner-approval"}
        return chain(
            "P6",
            [
                ("candidate", "evaluating", "2026-09-08T11:10:00Z", [], {}),
                (
                    "evaluating",
                    "canary",
                    "2026-09-08T12:01:00Z",
                    evaluation + list(live_gates),
                    dict(live),
                ),
                (
                    "canary",
                    "probation",
                    "2026-09-09T12:01:00Z",
                    [gate("canary", "2026-09-09T12:00:00Z")],
                    dict(live),
                ),
                (
                    "probation",
                    "active",
                    "2026-09-16T12:06:00Z",
                    [
                        gate("maturity", "2026-09-16T12:05:00Z"),
                        *list(live_gates and [owner("2026-09-16T12:05:00Z")]),
                    ],
                    dict(
                        live,
                        landed="pr:https://github.com/o/claude-config/pull/2",
                        **(active_extra or {}),
                    ),
                ),
            ],
        )

    def cand(self):
        return candidate("scheduler", "P6")

    def test_before_graduation_each_promotion_needs_its_own_approval(self):
        refused = lc.fold(self.cand(), self.path(), resolve=resolver(P6_B, APPROVE))
        self.assertEqual(
            refused.state, "evaluating"
        )  # refused where it would turn live
        self.assertIn("turns live only with the owner's approval", errors_of(refused))
        approved = lc.fold(
            self.cand(),
            self.path([owner("2026-09-08T12:00:00Z")]),
            resolve=resolver(P6_B, APPROVE),
        )
        self.assertEqual(
            (approved.state, approved.effect, approved.errors), ("active", "live", [])
        )

    def test_an_approval_for_another_promotion_is_not_reused(self):
        elsewhere = answer("approve-auth-0001", subject="lc_previous-promotion")
        refused = lc.fold(
            self.cand(),
            self.path([owner("2026-09-08T12:00:00Z")]),
            resolve=resolver(P6_B, elsewhere),
        )
        self.assertEqual(refused.effect, "shadow")
        self.assertIn("owner's approval", errors_of(refused))

    def graduated(self):
        return answer(
            "lp-p6-p7-owner-approval",
            "b",
            subject=None,
            graduation={"P6": {"graduated": True, "at": "2026-09-05T00:00:00Z"}},
        )

    def test_a_graduated_class_activates_after_its_veto_window(self):
        window = answer(
            "veto-auth-0001",
            option="allow",
            status="defaulted",
            answered_at="2026-09-16T00:00:00Z",
            created="2026-09-12T00:00:00Z",
        )
        result = lc.fold(
            self.cand(),
            self.path(active_extra={"veto": "decision:veto-auth-0001"}),
            resolve=resolver(self.graduated(), window),
        )
        self.assertEqual(
            (result.state, result.effect, result.errors), ("active", "live", [])
        )

    def test_veto_window_refusals(self):
        missing = lc.fold(self.cand(), self.path(), resolve=resolver(self.graduated()))
        self.assertIn("veto window", errors_of(missing))
        veto = {"veto": "decision:veto-auth-0001"}
        vetoed = answer(
            "veto-auth-0001",
            option="veto",
            created="2026-09-12T00:00:00Z",
            answered_at="2026-09-13T00:00:00Z",
        )
        result = lc.fold(
            self.cand(),
            self.path(active_extra=veto),
            resolve=resolver(self.graduated(), vetoed),
        )
        self.assertIn("vetoed", errors_of(result))
        young = answer("veto-auth-0001", status="open", created="2026-09-15T00:00:00Z")
        result = lc.fold(
            self.cand(),
            self.path(active_extra=veto),
            resolve=resolver(self.graduated(), young),
        )
        self.assertIn("has not closed", errors_of(result))


class OwnerGateTests(unittest.TestCase):
    def test_an_asserted_owner_gate_never_counts(self):
        cand = candidate(protected=True)
        steps = p1_path(
            active=dict(LIVE_P1, landed="pr:https://github.com/o/claude-config/pull/1")
        )
        steps[2]["gates"].append(
            owner("2026-09-15T12:05:00Z", ref="decision:forged-owner")
        )
        result = lc.fold(cand, steps, resolve=resolver(P1_C))
        self.assertEqual(result.state, "probation")
        self.assertIn("pass of owner", errors_of(result))
        steps[2]["gates"][-1]["ref"] = "decision:approve-auth-0001"
        result = lc.fold(cand, steps, resolve=resolver(P1_C, APPROVE))
        self.assertEqual((result.state, result.errors), ("active", []))
        self.assertFalse(lc.fold(cand, steps).chain[2:])  # no resolver, no owner


class HelperTests(unittest.TestCase):
    def test_exit_bar_status(self):
        good = {"shadow_days": 30, "judged": 60, "precision": 0.93}
        self.assertTrue(lc.exit_bar_status("p1-shadow-exit", good)["met"])
        self.assertFalse(
            lc.exit_bar_status("p1-shadow-exit", dict(good, precision=0.85))["met"]
        )
        partial = lc.exit_bar_status("p1-shadow-exit", {"judged": 60})
        self.assertEqual(
            (partial["met"], partial["missing"]), (False, ["precision", "shadow_days"])
        )

    def test_graduation_status(self):
        t = lambda d: dt.datetime(2026, 9, d, tzinfo=dt.timezone.utc)  # noqa: E731
        as_of = dt.datetime(2026, 10, 30, tzinfo=dt.timezone.utc)
        done = lc.graduation_status("p6-p7-graduation", [t(1), t(2), t(3)], [], as_of)
        self.assertEqual(
            (done["graduated"], done["at"]), (True, "2026-09-29T00:00:00Z")
        )
        reset = lc.graduation_status(
            "p6-p7-graduation", [t(1), t(2), t(3)], [t(10)], as_of
        )
        self.assertFalse(reset["graduated"])
        early = lc.graduation_status("p6-p7-graduation", [t(1), t(2), t(3)], [], t(20))
        self.assertFalse(early["graduated"])

    def test_resolutions_are_validated(self):
        bad = copy.deepcopy(P1_C)
        bad["option"] = None
        self.assertTrue(lc.validate_record(bad))
        self.assertEqual(lc.validate_record(P1_C), [])


if __name__ == "__main__":
    unittest.main()
