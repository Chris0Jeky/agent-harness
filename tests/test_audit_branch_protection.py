"""Default-branch history protection vs the floor posture (issue #356).

Covers `harness.effective_floor_posture` and
`harness.default_branch_protection_findings` with a resolver keyed on argv:
no process is spawned and no network is touched.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import harness

GITHUB_REMOTE_ROWS = (
    "origin\thttps://github.com/acme/widgets.git (fetch)\n"
    "origin\thttps://github.com/acme/widgets.git (push)"
)
REMOTE_ARGV = ("git", "remote", "--verbose")
DEFAULT_BRANCH_ARGV = (
    "gh",
    "api",
    "--hostname",
    "github.com",
    "repos/acme/widgets",
    "--jq",
    ".default_branch",
)
RULES_JQ = '.[]|"\\(.type) \\(.ruleset_id // "")"'


def rules_argv(branch_path="main"):
    """The paginated rules probe for one URL-encoded branch path."""
    return (
        "gh",
        "api",
        "--hostname",
        "github.com",
        "--paginate",
        f"repos/acme/widgets/rules/branches/{branch_path}",
        "--jq",
        RULES_JQ,
    )


def protection_argv(branch_path="main"):
    """The classic protection probe for one URL-encoded branch path."""
    return (
        "gh",
        "api",
        "--hostname",
        "github.com",
        f"repos/acme/widgets/branches/{branch_path}/protection",
        "--jq",
        "[.allow_force_pushes.enabled, .allow_deletions.enabled, "
        '.enforce_admins.enabled]|map(tostring)|join(",")',
    )


def bypass_argv(ruleset_id):
    """The bypass probe for one ruleset id."""
    return (
        "gh",
        "api",
        "--hostname",
        "github.com",
        f"repos/acme/widgets/rulesets/{ruleset_id}",
        "--jq",
        ".current_user_can_bypass",
    )


RULES_ARGV = rules_argv()
PROTECTION_ARGV = protection_argv()
BYPASS_7 = bypass_argv(7)
BOTH_RULES = "non_fast_forward 7\ndeletion 7\n"


def make_tier_data(tier=2, flags=None, floor_posture=None, floor_wiring=None):
    """One merged tier declaration; None means the key is absent."""
    data = {"tier": tier, "flags": dict(flags or {})}
    if floor_posture is not None:
        data["floor_posture"] = floor_posture
    if floor_wiring is not None:
        data["floor_wiring"] = floor_wiring
    return data


class ArgvRunner:
    """A stand-in resolver keyed on exact argv: records calls, spawns nothing."""

    def __init__(self, responses, default=(False, "")):
        self.responses = dict(responses)
        self.default = default
        self.calls = []

    def __call__(self, argv, cwd=None, **kwargs):
        self.calls.append(list(argv))
        return self.responses.get(tuple(argv), self.default)

    def gh_calls(self):
        """Every recorded `gh` probe argv."""
        return [argv for argv in self.calls if argv[:1] == ["gh"]]


class OfflineRunner(ArgvRunner):
    """Refuses network resolvers the way `local_only_command_result` does."""

    def __call__(self, argv, cwd=None, **kwargs):
        self.calls.append(list(argv))
        if harness.command_reaches_the_network(list(argv)):
            return False, "", "--offline refused the network resolver `gh`"
        return self.responses.get(tuple(argv), self.default)


class EffectiveFloorPostureTests(unittest.TestCase):
    def test_posture_table(self):
        rows = [
            (make_tier_data(tier=4), "wall"),
            (make_tier_data(tier=4, floor_posture="guide"), "wall"),
            (make_tier_data(flags={"wave_mode": True}), "wall"),
            (make_tier_data(flags={"wave_mode": True}, floor_posture="core"), "wall"),
            (make_tier_data(), "core"),
            (make_tier_data(tier=3), "core"),
            (make_tier_data(flags={"sensitive_data": True}), "wall"),
            (
                make_tier_data(flags={"sensitive_data": True}, floor_posture="guide"),
                "guide",
            ),
            (
                make_tier_data(flags={"sensitive_data": True}, floor_posture="core"),
                "guide",
            ),
            (make_tier_data(floor_posture="wall"), "wall"),
            (make_tier_data(floor_posture="guide"), "guide"),
            (make_tier_data(floor_posture="core"), "core"),
            (make_tier_data(floor_posture="fence"), "core"),
            (
                make_tier_data(flags={"sensitive_data": True}, floor_posture="fence"),
                "wall",
            ),
        ]
        for data, wanted in rows:
            with self.subTest(data=data):
                self.assertEqual(harness.effective_floor_posture(data), wanted)


class BranchProtectionFindingTests(unittest.TestCase):
    def run_protection(self, data, responses, remote_rows=GITHUB_REMOTE_ROWS):
        full = {REMOTE_ARGV: (True, remote_rows)}
        full.update(responses)
        runner = ArgvRunner(full)
        findings = harness.default_branch_protection_findings(
            Path("."), data, command_runner=runner, deadline=None
        )
        return runner, findings

    def test_ok_when_ruleset_blocks_both(self):
        runner, findings = self.run_protection(
            make_tier_data(),
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, BOTH_RULES),
                BYPASS_7: (True, "never"),
            },
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["status"], harness.REALITY_OK)
        self.assertIn("acme/widgets", findings[0]["detail"])
        self.assertIn("main", findings[0]["detail"])
        self.assertEqual(
            runner.gh_calls(),
            [list(DEFAULT_BRANCH_ARGV), list(RULES_ARGV), list(BYPASS_7)],
        )

    def test_ok_when_classic_protection_denies_both(self):
        _, findings = self.run_protection(
            make_tier_data(),
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, "non_fast_forward 7"),
                PROTECTION_ARGV: (True, "false,false,true"),
                BYPASS_7: (True, "never"),
            },
        )
        self.assertEqual([item["status"] for item in findings], ["ok"])

    def test_advisory_when_neither_lane_covers_history(self):
        _, findings = self.run_protection(
            make_tier_data(),
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, ""),
                PROTECTION_ARGV: (True, "false,true,true"),
            },
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["status"], harness.REALITY_ADVISORY)
        detail = findings[0]["detail"]
        for needle in (
            "acme/widgets",
            "main",
            "gh api -X POST repos/acme/widgets/rulesets",
            "protect-default-branch",
            "non_fast_forward",
            "deletion",
            "#356",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, detail)

    def test_advisory_when_classic_protection_is_absent(self):
        _, findings = self.run_protection(
            make_tier_data(),
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, "deletion 7"),
                PROTECTION_ARGV: (False, "", "gh: Branch not protected (HTTP 404)"),
            },
        )
        self.assertEqual([item["status"] for item in findings], ["advisory"])
        self.assertIn("gh api -X POST", findings[0]["detail"])

    def test_unproven_when_classic_probe_fails_for_another_reason(self):
        # Review of #369 (M2): a missing admin scope measured nothing.
        for failure in ("", "gh: Resource not accessible by integration (HTTP 403)"):
            with self.subTest(failure=failure):
                _, findings = self.run_protection(
                    make_tier_data(),
                    {
                        DEFAULT_BRANCH_ARGV: (True, "main"),
                        RULES_ARGV: (True, "deletion 7"),
                        PROTECTION_ARGV: (False, "", failure),
                    },
                )
                self.assertEqual([item["status"] for item in findings], ["UNPROVEN"])
                self.assertNotIn("gh api -X POST", findings[0]["detail"])

    def test_a_malformed_tier_never_crashes_the_leg(self):
        # Review of #369 (M3): the merge passes an invalid raw tier through.
        for tier in ("3", None, 9):
            with self.subTest(tier=tier):
                data = make_tier_data()
                data["tier"] = tier
                self.assertEqual(harness.effective_floor_posture(data), "core")

    def test_unproven_when_default_branch_is_unanswered(self):
        runner, findings = self.run_protection(make_tier_data(), {})
        self.assertEqual([item["status"] for item in findings], ["UNPROVEN"])
        self.assertIn("unmeasured", findings[0]["detail"])
        self.assertEqual(len(runner.calls), 2)

    def test_unproven_when_rules_are_unanswered(self):
        _, findings = self.run_protection(
            make_tier_data(), {DEFAULT_BRANCH_ARGV: (True, "main")}
        )
        self.assertEqual([item["status"] for item in findings], ["UNPROVEN"])
        self.assertIn("unmeasured", findings[0]["detail"])

    def test_unproven_when_offline_refuses_network_probes(self):
        runner = OfflineRunner({REMOTE_ARGV: (True, GITHUB_REMOTE_ROWS)})
        findings = harness.default_branch_protection_findings(
            Path("."), make_tier_data(), command_runner=runner, deadline=None
        )
        self.assertEqual([item["status"] for item in findings], ["UNPROVEN"])
        self.assertIn("offline", findings[0]["detail"])
        self.assertEqual(len(runner.calls), 2)

    def test_skipped_unless_core_or_floorless(self):
        answered = {
            DEFAULT_BRANCH_ARGV: (True, "main"),
            RULES_ARGV: (True, BOTH_RULES),
            BYPASS_7: (True, "never"),
        }
        skipped = [
            make_tier_data(tier=4),
            make_tier_data(flags={"wave_mode": True}),
            make_tier_data(flags={"sensitive_data": True}),
            make_tier_data(floor_posture="wall"),
            make_tier_data(floor_posture="guide"),
        ]
        for data in skipped:
            with self.subTest(data=data):
                runner, findings = self.run_protection(data, answered)
                self.assertEqual(findings, [])
                self.assertEqual(runner.calls, [])

    def test_floor_wiring_none_applies_without_a_floor(self):
        runner, findings = self.run_protection(
            make_tier_data(floor_posture="guide", floor_wiring="none"),
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, BOTH_RULES),
                BYPASS_7: (True, "never"),
            },
        )
        self.assertEqual([item["status"] for item in findings], ["ok"])
        self.assertTrue(runner.gh_calls())

    def test_non_github_origin_is_out_of_scope(self):
        runner, findings = self.run_protection(
            make_tier_data(),
            {},
            remote_rows=(
                "origin\thttps://gitlab.example/acme/widgets.git (fetch)\n"
                "origin\thttps://gitlab.example/acme/widgets.git (push)"
            ),
        )
        self.assertEqual(findings, [])
        self.assertEqual(runner.gh_calls(), [])

    def test_a_non_github_push_url_is_out_of_scope(self):
        # Codex P1 on #369: pushes go elsewhere, so the GitHub fetch repository
        # says nothing about them.
        runner, findings = self.run_protection(
            make_tier_data(),
            {},
            remote_rows=(
                "origin\thttps://github.com/acme/widgets.git (fetch)\n"
                "origin\thttps://git.example.invalid/acme/widgets.git (push)"
            ),
        )
        self.assertEqual(findings, [])
        self.assertEqual(runner.gh_calls(), [])

    def test_unproven_when_remotes_cannot_be_enumerated(self):
        runner = ArgvRunner({REMOTE_ARGV: (False, "", "git: not found")})
        findings = harness.default_branch_protection_findings(
            Path("."), make_tier_data(), command_runner=runner, deadline=None
        )
        self.assertEqual([item["status"] for item in findings], ["UNPROVEN"])
        self.assertEqual(runner.gh_calls(), [])

    def test_missing_origin_is_out_of_scope(self):
        runner, findings = self.run_protection(
            make_tier_data(),
            {},
            remote_rows="upstream\thttps://github.com/acme/widgets.git (fetch)\n",
        )
        self.assertEqual(findings, [])
        self.assertEqual(runner.gh_calls(), [])

    def statuses(self, responses, data=None):
        """Run the leg on `main` with the given probe answers; return statuses."""
        full = {DEFAULT_BRANCH_ARGV: (True, "main")}
        full.update(responses)
        runner, findings = self.run_protection(data or make_tier_data(), full)
        return runner, findings, [item["status"] for item in findings]

    # Item 1: the rules probe paginates and carries ruleset ids.
    def test_rules_probe_paginates_and_reads_ruleset_ids(self):
        self.assertIn("--paginate", RULES_ARGV)
        self.assertEqual(
            harness.parse_branch_rules(
                "non_fast_forward 7\n\n  \ndeletion 9\nupdate\n"
            ),
            [("non_fast_forward", "7"), ("deletion", "9"), ("update", "")],
        )
        # Two pages concatenate; each distinct backing ruleset is probed once.
        runner, _, statuses = self.statuses(
            {
                RULES_ARGV: (True, "non_fast_forward 7\nupdate 3\n\ndeletion 9\n"),
                BYPASS_7: (True, "never"),
                bypass_argv(9): (True, "pull_requests_only"),
            }
        )
        self.assertEqual(statuses, ["ok"])
        self.assertEqual(runner.gh_calls()[2:], [list(BYPASS_7), list(bypass_argv(9))])
        self.assertNotIn(list(bypass_argv(3)), runner.gh_calls())
        self.assertNotIn(list(PROTECTION_ARGV), runner.gh_calls())

    # Item 2: bypass actors on the backing rulesets.
    def test_bypass_answers_grade_the_ruleset_block(self):
        rows = [
            ("never", "ok"),
            ("pull_requests_only", "ok"),
            ("always", "advisory"),
            ("exempt", "advisory"),
            ("null", "UNPROVEN"),
            ("", "UNPROVEN"),
            ("sometimes", "UNPROVEN"),
        ]
        for answer, wanted in rows:
            with self.subTest(answer=answer):
                _, findings, statuses = self.statuses(
                    {RULES_ARGV: (True, BOTH_RULES), BYPASS_7: (True, answer)}
                )
                self.assertEqual(statuses, [wanted])
                if wanted == "advisory":
                    self.assertIn("can bypass", findings[0]["detail"])
                    self.assertIn("rulesets/7", findings[0]["detail"])

    def test_unresolved_bypass_probe_is_unproven_and_named(self):
        _, findings, statuses = self.statuses(
            {
                RULES_ARGV: (True, BOTH_RULES),
                BYPASS_7: (False, "", "gh: HTTP 403 Resource not accessible"),
            }
        )
        self.assertEqual(statuses, ["UNPROVEN"])
        # The probe note's credential redaction masks the long REST path, so
        # the finding names the ruleset and the probed field itself.
        self.assertIn("ruleset 7", findings[0]["detail"])
        self.assertIn(".current_user_can_bypass", findings[0]["detail"])

    def test_one_bypassable_ruleset_among_two_is_advisory(self):
        _, _, statuses = self.statuses(
            {
                RULES_ARGV: (True, "non_fast_forward 7\ndeletion 9\n"),
                BYPASS_7: (True, "never"),
                bypass_argv(9): (True, "always"),
            }
        )
        self.assertEqual(statuses, ["advisory"])

    def test_a_ruleset_rule_without_a_numeric_id_is_unproven(self):
        for rules in ("non_fast_forward\ndeletion 7\n", "non_fast_forward ../x\n"):
            with self.subTest(rules=rules):
                runner, _, statuses = self.statuses(
                    {
                        RULES_ARGV: (True, rules + "deletion 7\n"),
                        BYPASS_7: (True, "never"),
                    }
                )
                self.assertEqual(statuses, ["UNPROVEN"])
                self.assertFalse(
                    any("rulesets/.." in " ".join(argv) for argv in runner.calls)
                )

    # Item 3: coverage split across rulesets and classic protection.
    def test_coverage_split_across_mechanisms_is_ok(self):
        runner, _, statuses = self.statuses(
            {
                RULES_ARGV: (True, "non_fast_forward 7"),
                PROTECTION_ARGV: (True, "true,false,true"),
                BYPASS_7: (True, "never"),
            }
        )
        self.assertEqual(statuses, ["ok"])
        self.assertEqual(
            runner.gh_calls()[1:],
            [list(RULES_ARGV), list(PROTECTION_ARGV), list(BYPASS_7)],
        )

    def test_coverage_split_keeps_the_ruleset_bypass_check(self):
        _, _, statuses = self.statuses(
            {
                RULES_ARGV: (True, "deletion 7"),
                PROTECTION_ARGV: (True, "false,true,true"),
                BYPASS_7: (True, "exempt"),
            }
        )
        self.assertEqual(statuses, ["advisory"])

    def test_coverage_split_that_leaves_a_rule_open_is_advisory(self):
        _, findings, statuses = self.statuses(
            {
                RULES_ARGV: (True, "deletion 7"),
                PROTECTION_ARGV: (True, "true,true,true"),
            }
        )
        self.assertEqual(statuses, ["advisory"])
        self.assertIn("force-push", findings[0]["detail"])
        self.assertIn("gh api -X POST", findings[0]["detail"])

    # Item 4: classic protection with enforce_admins false.
    def test_classic_block_without_enforce_admins_is_advisory(self):
        for rules in ("", "non_fast_forward 7\n"):
            with self.subTest(rules=rules):
                _, findings, statuses = self.statuses(
                    {
                        RULES_ARGV: (True, rules),
                        PROTECTION_ARGV: (True, "false,false,false"),
                        BYPASS_7: (True, "never"),
                    }
                )
                self.assertEqual(statuses, ["advisory"])
                self.assertIn("enforce_admins is false", findings[0]["detail"])
                self.assertIn("false,false,false", findings[0]["detail"])

    def test_classic_block_with_enforce_admins_is_ok(self):
        _, _, statuses = self.statuses(
            {RULES_ARGV: (True, ""), PROTECTION_ARGV: (True, "false,false,true")}
        )
        self.assertEqual(statuses, ["ok"])

    def test_classic_block_with_unknown_enforce_admins_is_unproven(self):
        for answer in ("false,false", "false,false,null"):
            with self.subTest(answer=answer):
                _, _, statuses = self.statuses(
                    {RULES_ARGV: (True, ""), PROTECTION_ARGV: (True, answer)}
                )
                self.assertEqual(statuses, ["UNPROVEN"])

    # Item 5: an empty or null classic answer is unmeasured.
    def test_empty_or_null_classic_answer_is_unproven(self):
        for answer in ("", "  \n", "null", "null,null,true", "false,null,true"):
            with self.subTest(answer=answer):
                _, findings, statuses = self.statuses(
                    {RULES_ARGV: (True, "deletion 7"), PROTECTION_ARGV: (True, answer)}
                )
                self.assertEqual(statuses, ["UNPROVEN"])
                self.assertNotIn("gh api -X POST", findings[0]["detail"])

    # Item 6: the branch is URL-encoded in both probe paths.
    def test_branch_is_url_encoded_in_probe_paths(self):
        encoded = "release/v1%20beta%232"
        runner, _, statuses = self.statuses(
            {
                DEFAULT_BRANCH_ARGV: (True, "release/v1 beta#2"),
                rules_argv(encoded): (True, "non_fast_forward 7"),
                protection_argv(encoded): (True, "true,false,true"),
                BYPASS_7: (True, "never"),
            }
        )
        self.assertEqual(statuses, ["ok"])
        self.assertIn(list(rules_argv(encoded)), runner.gh_calls())
        self.assertIn(list(protection_argv(encoded)), runner.gh_calls())

    def test_an_expired_deadline_is_unproven_never_ok(self):
        runner = ArgvRunner(
            {
                REMOTE_ARGV: (True, GITHUB_REMOTE_ROWS),
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, BOTH_RULES),
                BYPASS_7: (True, "never"),
            }
        )
        findings = harness.default_branch_protection_findings(
            Path("."),
            make_tier_data(),
            command_runner=runner,
            deadline=time.monotonic() - 1,
        )
        self.assertEqual([item["status"] for item in findings], ["UNPROVEN"])
        self.assertEqual(runner.calls, [])

    def test_status_is_never_a_mismatch(self):
        scenarios = [
            {},
            {DEFAULT_BRANCH_ARGV: (True, "main")},
            {DEFAULT_BRANCH_ARGV: (True, "")},
            {DEFAULT_BRANCH_ARGV: (True, "null")},
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, "deletion 7"),
                PROTECTION_ARGV: (True, "true,true,true"),
            },
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, "deletion 7"),
                PROTECTION_ARGV: (True, "null,null,null"),
            },
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, BOTH_RULES),
                BYPASS_7: (True, "always"),
            },
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, BOTH_RULES),
            },
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, BOTH_RULES),
                BYPASS_7: (True, "never"),
            },
        ]
        for responses in scenarios:
            with self.subTest(responses=sorted(responses)):
                _, findings = self.run_protection(make_tier_data(), responses)
                # Non-vacuous: every scenario is in scope and must report.
                self.assertGreaterEqual(len(findings), 1)
                for item in findings:
                    self.assertIn(
                        item["status"],
                        (
                            harness.REALITY_OK,
                            harness.REALITY_ADVISORY,
                            harness.REALITY_UNPROVEN,
                        ),
                    )

    def test_reality_findings_wires_the_leg_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            harness_root = repo / "harness"
            (harness_root / "templates" / "hooks").mkdir(parents=True)
            claude_home = repo / "claude-home"
            (claude_home / "hooks").mkdir(parents=True)
            runner = ArgvRunner(
                {
                    REMOTE_ARGV: (True, GITHUB_REMOTE_ROWS),
                    DEFAULT_BRANCH_ARGV: (True, "main"),
                    RULES_ARGV: (True, BOTH_RULES),
                    BYPASS_7: (True, "never"),
                }
            )
            findings = harness.reality_findings(
                repo,
                2,
                make_tier_data(),
                harness_root=harness_root,
                claude_home=claude_home,
                command_runner=runner,
                deadline=None,
            )
            labels = [item["check"] for item in findings]
            # Review of #369 (M1): the advisory-only leg runs after the
            # vendored leg, which can MISMATCH and must get the budget first.
            vendored = next(i for i, x in enumerate(labels) if "vendored" in x)
            history = next(i for i, x in enumerate(labels) if "history protection" in x)
            self.assertLess(vendored, history)


if __name__ == "__main__":
    unittest.main()
