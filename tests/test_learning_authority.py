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
        item.update(
            holdout_digest="c" * 64,
            training_excluded=True,
            anchors=["exp_fixture-anchor"],
            metrics={"cases": 20, "delta": 0.4, "wins": 8, "losses": 0, "anchored": 20},
            salt_draw={"source": "agent-hq@" + "5" * 40, "at": at},
        )
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
                probation
                or dict(LIVE_P1, landed="pr:https://github.com/o/claude-config/pull/1"),
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


def ok_time():
    return lc.parse_time("2026-09-08T12:00:00Z")


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
                {
                    "effect": "live",
                    "authority": "decision:approve-auth-0001",
                    "landed": "commit:" + "e" * 40,
                },
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

    def path(self, live_gates=(), active_extra=None, live_from="canary"):
        """P6 through canary and probation to active; live from canary or only at active."""
        evaluation = [gate("offline_eval", "2026-09-08T12:00:00Z")]
        live = {"effect": "live", "authority": "decision:lp-p6-p7-owner-approval"}
        pr = "pr:https://github.com/o/claude-config/pull/2"
        early = dict(live) if live_from == "canary" else {}
        installed = dict(live, landed=pr) if live_from == "canary" else {}
        approval = list(live_gates and [owner("2026-09-16T12:05:00Z")])
        return chain(
            "P6",
            [
                ("candidate", "evaluating", "2026-09-08T11:10:00Z", [], {}),
                (
                    "evaluating",
                    "canary",
                    "2026-09-08T12:01:00Z",
                    evaluation + list(live_gates),
                    early,
                ),
                (
                    "canary",
                    "probation",
                    "2026-09-09T12:01:00Z",
                    [gate("canary", "2026-09-09T12:00:00Z")],
                    installed,
                ),
                (
                    "probation",
                    "active",
                    "2026-09-16T12:06:00Z",
                    [gate("maturity", "2026-09-16T12:05:00Z"), *approval],
                    dict(live, landed=pr, **(active_extra or {})),
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
        self.assertIn(
            "goes live and activates only with the owner's approval", errors_of(refused)
        )
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
            self.path(
                active_extra={"veto": "decision:veto-auth-0001"}, live_from="active"
            ),
            resolve=resolver(self.graduated(), window),
        )
        self.assertEqual(
            (result.state, result.effect, result.errors), ("active", "live", [])
        )

    def test_veto_window_refusals(self):
        missing = lc.fold(
            self.cand(),
            self.path(live_from="active"),
            resolve=resolver(self.graduated()),
        )
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
            self.path(active_extra=veto, live_from="active"),
            resolve=resolver(self.graduated(), vetoed),
        )
        self.assertIn("vetoed", errors_of(result))
        young = answer("veto-auth-0001", status="open", created="2026-09-15T00:00:00Z")
        result = lc.fold(
            self.cand(),
            self.path(active_extra=veto, live_from="active"),
            resolve=resolver(self.graduated(), young),
        )
        self.assertIn("has not closed", errors_of(result))


class OwnerGateTests(unittest.TestCase):
    def test_an_asserted_owner_gate_never_counts(self):
        # A protected P1 candidate goes live only with the owner's approval of it,
        # on the record that turns it live and on the activating record.
        cand = candidate(protected=True)
        steps = p1_path()
        for record, at in (
            (steps[1], "2026-09-08T12:00:00Z"),
            (steps[2], "2026-09-15T12:05:00Z"),
        ):
            record["gates"].append(owner(at, ref="decision:forged-owner"))
        result = lc.fold(cand, steps, resolve=resolver(P1_C))
        self.assertEqual((result.state, result.effect), ("evaluating", "shadow"))
        self.assertIn("owner's approval", errors_of(result))
        for record in steps[1:]:
            record["gates"][-1]["ref"] = "decision:approve-auth-0001"
        result = lc.fold(cand, steps, resolve=resolver(P1_C, APPROVE))
        self.assertEqual(
            (result.state, result.effect, result.errors), ("active", "live", [])
        )
        self.assertFalse(lc.fold(cand, steps).chain[1:])  # no resolver, no owner

    def test_an_approval_bound_to_another_version_does_not_count(self):
        cand = candidate(protected=True)
        steps = p1_path()
        for record, at in (
            (steps[1], "2026-09-08T12:00:00Z"),
            (steps[2], "2026-09-15T12:05:00Z"),
        ):
            record["gates"].append(owner(at))
        bound = answer("approve-auth-0001")
        bound["subject"]["digest"] = lc.candidate_digest(cand)
        ok = lc.fold(cand, steps, resolve=resolver(P1_C, bound))
        self.assertEqual((ok.state, ok.errors), ("active", []))
        changed = dict(
            cand, claim="Run the unittest suite twice before reporting a fix."
        )
        result = lc.fold(changed, steps, resolve=resolver(P1_C, bound))
        self.assertEqual((result.state, result.effect), ("evaluating", "shadow"))
        self.assertIn("owner's approval", errors_of(result))
        why = lc.approval_errors(
            "decision:approve-auth-0001", changed, ok_time(), resolver(bound)
        )
        self.assertIn("another version", " ".join(why))


class ReviewRegressionTests(unittest.TestCase):
    """Findings from the #507 lenses (deep-reviewer, Sol, reviewer); each pins its fix."""

    def p6(self):
        return P6P7Tests()

    def test_installed_live_records_name_their_landing(self):
        steps = p1_path(probation=dict(LIVE_P1))  # live in probation, no landing
        result = lc.fold(candidate(), steps, resolve=resolver(P1_C))
        self.assertEqual(result.state, "evaluating")
        self.assertIn("landed: pr:", errors_of(result))
        other_repo = dict(
            LIVE_P1, landed="pr:https://github.com/o/agent-harness/pull/9"
        )
        result = lc.fold(
            candidate(), p1_path(probation=other_repo), resolve=resolver(P1_C)
        )
        self.assertIn("in claude-config", errors_of(result))

    def test_p1_has_no_live_canary(self):
        steps = chain(
            "P1",
            [
                ("candidate", "evaluating", "2026-09-08T11:10:00Z", [], {}),
                (
                    "evaluating",
                    "canary",
                    "2026-09-08T12:01:00Z",
                    [gate("provenance", "2026-09-08T12:00:00Z")],
                    dict(LIVE_P1),
                ),
            ],
        )
        result = lc.fold(candidate(), steps, resolve=resolver(P1_C))
        self.assertIn("no canary stage", errors_of(result))

    def test_a_graduated_class_turning_live_late_still_waits_out_a_veto(self):
        x = self.p6()
        steps = x.path(live_from="active")
        for record in steps:  # activate entirely in shadow ...
            record.update(effect="shadow")
            record.pop("authority", None)
        steps.append(
            {
                **steps[-1],
                "id": "prom_auth-0005",
                "prev": steps[-1]["id"],
                "from": "active",
                "to": "reinforced",
                "at": "2026-09-20T00:00:00Z",
                "gates": [],
                "effect": "live",
                "authority": "decision:lp-p6-p7-owner-approval",
                "landed": "pr:https://github.com/o/claude-config/pull/2",
            }
        )  # ... then turn live on reinforcement
        result = lc.fold(x.cand(), steps, resolve=resolver(x.graduated()))
        self.assertEqual(result.effect, "shadow")
        self.assertIn("veto window", errors_of(result))

    def test_p2_has_no_owner_decision(self):
        self.assertEqual(lc.classes()["authority"]["P2"]["mode"], "no_live")

    def test_option_d_needs_no_approval_for_protected_notes(self):
        d = answer("lp-p1-memory-autopromote", "d", subject=None)
        result = lc.fold(candidate(protected=True), p1_path(), resolve=resolver(d))
        self.assertEqual(
            (result.state, result.effect, result.errors), ("active", "live", [])
        )

    def veto_fold(self, window):
        x = self.p6()
        return lc.fold(
            x.cand(),
            x.path(
                active_extra={"veto": "decision:veto-auth-0001"}, live_from="active"
            ),
            resolve=resolver(x.graduated(), window),
        )

    def test_an_elapsed_unvetoed_window_allows(self):
        expired = answer(
            "veto-auth-0001", status="expired", created="2026-09-12T00:00:00Z"
        )
        expired["expires"] = "2026-09-15T00:00:00Z"
        self.assertEqual(self.veto_fold(expired).errors, [])

    def test_a_window_must_run_its_days_and_open_in_the_stay(self):
        early_default = answer(
            "veto-auth-0001",
            option="allow",
            status="defaulted",
            created="2026-09-12T00:00:00Z",
            answered_at="2026-09-12T01:00:00Z",
        )
        self.assertIn("defaulted before", errors_of(self.veto_fold(early_default)))
        before_stay = answer(
            "veto-auth-0001",
            option="allow",
            status="defaulted",
            created="2026-09-01T00:00:00Z",
            answered_at="2026-09-05T00:00:00Z",
        )
        self.assertIn("opened before the stay", errors_of(self.veto_fold(before_stay)))

    def test_measures_hold_only_until_their_until(self):
        lapsed = answer(
            "lp-p1-memory-autopromote",
            "c",
            subject=None,
            exit_bars={
                "p1-shadow-exit": {
                    "met": True,
                    "at": "2026-09-02T00:00:00Z",
                    "until": "2026-09-10T00:00:00Z",
                }
            },
        )
        result = lc.fold(candidate(), p1_path(), resolve=resolver(lapsed))
        self.assertEqual(result.state, "probation")  # held at 09-08, lapsed by 09-15
        self.assertIn("exit bar", errors_of(result))

    def test_future_reverts_do_not_rewrite_graduation(self):
        t = lambda m, d: dt.datetime(2026, m, d, tzinfo=dt.timezone.utc)  # noqa: E731
        status = lc.graduation_status(
            "p6-p7-graduation", [t(8, 1), t(8, 2), t(8, 3)], [t(9, 10)], t(9, 1)
        )
        self.assertEqual(
            (status["graduated"], status["at"]), (True, "2026-08-29T00:00:00Z")
        )

    def test_a_live_p8_install_names_its_landing(self):
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
        result = lc.fold(cand, chain("P8", steps), resolve=resolver(APPROVE))
        self.assertIn("names where it landed", errors_of(result))

    def test_bad_resolutions_fail_closed_without_crashing(self):
        bad = answer(
            "lp-p6-p7-owner-approval",
            "b",
            subject=None,
            graduation={"P6": {"graduated": True, "at": "2026-02-31T00:00:00Z"}},
        )
        result = lc.fold(self.p6().cand(), self.p6().path(), resolve=resolver(bad))
        self.assertIn("invalid answer", errors_of(result))
        self.assertIsNone(lc.resolver_from([{}, None, {"decision": 7}])("decision:x"))


class LabelTests(unittest.TestCase):
    """agent-hq answers per-candidate decisions with keys a/b; the label is the meaning."""

    def test_approval_and_veto_meaning_comes_from_the_label(self):
        cand = candidate("policy", "P8")
        at = lc.parse_time("2026-09-09T00:00:00Z")
        approve = dict(answer("approve-auth-0001", option="a"), option_label="Approve")
        decline = dict(answer("approve-auth-0001", option="b"), option_label="Decline")
        ref = "decision:approve-auth-0001"
        self.assertEqual(lc.approval_errors(ref, cand, at, resolver(approve)), [])
        self.assertTrue(lc.approval_errors(ref, cand, at, resolver(decline)))
        unlabeled = answer("approve-auth-0001", option="a")
        self.assertTrue(lc.approval_errors(ref, cand, at, resolver(unlabeled)))
        veto = dict(
            answer(
                "veto-auth-0001",
                option="b",
                created="2026-09-01T00:00:00Z",
                answered_at="2026-09-02T00:00:00Z",
            ),
            option_label="Veto",
        )
        errors = lc._veto_errors(
            "decision:veto-auth-0001", cand, at, 3, resolver(veto), None
        )
        self.assertTrue(any("vetoed" in e for e in errors), errors)


class GateReviewTests(unittest.TestCase):
    """Findings from the #507 gate review."""

    def test_an_owner_graded_eval_counts_but_vouches_for_nothing(self):
        # learning_eval labels a run 'owner' when owner-graded labels were used;
        # the gate's ref is an eval-run, so the claim is unproven.
        cand = candidate("recipe", "P4")
        owner_eval = gate(
            "offline_eval",
            "2026-09-08T12:00:00Z",
            OWNER,
            ref="eval-run:run_" + "1" * 16,
        )
        self.assertTrue(lc._counts(owner_eval, cand, None))
        self.assertFalse(lc._independent(owner_eval, cand, None))
        self.assertTrue(
            lc._independent(gate("offline_eval", "2026-09-08T12:00:00Z"), cand, None)
        )

    def test_a_defaulted_approval_never_approves(self):
        defaulted = answer("approve-auth-0001", status="defaulted")
        at = lc.parse_time("2026-09-09T00:00:00Z")
        errors = lc.approval_errors(
            "decision:approve-auth-0001", candidate(), at, resolver(defaulted)
        )
        self.assertTrue(any("defaulted, not answered" in e for e in errors), errors)

    def test_option_semantics_per_class(self):
        e = answer("lp-p6-p7-owner-approval", "e", subject=None)
        self.assertEqual(lc.class_option("P6", e)["approval"], "until_graduated")
        self.assertEqual(lc.class_option("P7", e)["approval"], "per_promotion")
        self.assertIsNone(
            lc.class_option("P1", e)
        )  # the P6/P7 decision does not decide P1
        d = answer("lp-p6-p7-owner-approval", "d", subject=None)
        self.assertEqual(lc.class_option("P7", d)["approval"], "none")
        unknown = answer("lp-p6-p7-owner-approval", "z", subject=None)
        self.assertIsNone(lc.class_option("P6", unknown))


class HelperTests(unittest.TestCase):
    def test_exit_bar_status(self):
        good = {
            "shadow_days": 30,
            "judged": 60,
            "precision": 0.93,
            "contradiction_or_revert_rate": 0.02,
        }
        self.assertTrue(lc.exit_bar_status("p1-shadow-exit", good)["met"])
        self.assertFalse(
            lc.exit_bar_status("p1-shadow-exit", dict(good, precision=0.85))["met"]
        )
        self.assertFalse(
            lc.exit_bar_status(
                "p1-shadow-exit", dict(good, contradiction_or_revert_rate=0.2)
            )["met"]
        )
        partial = lc.exit_bar_status("p1-shadow-exit", {"judged": 60})
        self.assertEqual(
            (partial["met"], partial["missing"]),
            (False, ["contradiction_or_revert_rate", "precision", "shadow_days"]),
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
