"""Default-branch history protection vs the floor posture (issue #356).

Covers `harness.effective_floor_posture` and
`harness.default_branch_protection_findings` with a resolver keyed on argv:
no process is spawned and no network is touched.
"""

from __future__ import annotations

import tempfile
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
RULES_ARGV = (
    "gh",
    "api",
    "--hostname",
    "github.com",
    "repos/acme/widgets/rules/branches/main",
    "--jq",
    '[.[].type]|join(",")',
)
PROTECTION_ARGV = (
    "gh",
    "api",
    "--hostname",
    "github.com",
    "repos/acme/widgets/branches/main/protection",
    "--jq",
    "[.allow_force_pushes.enabled, .allow_deletions.enabled]"
    '|map(tostring)|join(",")',
)


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
                RULES_ARGV: (True, "non_fast_forward,deletion"),
            },
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["status"], harness.REALITY_OK)
        self.assertIn("acme/widgets", findings[0]["detail"])
        self.assertIn("main", findings[0]["detail"])
        self.assertEqual(
            runner.gh_calls(), [list(DEFAULT_BRANCH_ARGV), list(RULES_ARGV)]
        )

    def test_ok_when_classic_protection_denies_both(self):
        _, findings = self.run_protection(
            make_tier_data(),
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, "non_fast_forward"),
                PROTECTION_ARGV: (True, "false,false"),
            },
        )
        self.assertEqual([item["status"] for item in findings], ["ok"])

    def test_advisory_when_neither_lane_covers_history(self):
        _, findings = self.run_protection(
            make_tier_data(),
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, ""),
                PROTECTION_ARGV: (True, "false,true"),
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

    def test_advisory_when_classic_probe_fails(self):
        _, findings = self.run_protection(
            make_tier_data(),
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, "deletion"),
            },
        )
        self.assertEqual([item["status"] for item in findings], ["advisory"])
        self.assertIn("gh api -X POST", findings[0]["detail"])

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
            RULES_ARGV: (True, "non_fast_forward,deletion"),
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
                RULES_ARGV: (True, "non_fast_forward,deletion"),
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

    def test_missing_origin_is_out_of_scope(self):
        runner, findings = self.run_protection(
            make_tier_data(),
            {},
            remote_rows="upstream\thttps://github.com/acme/widgets.git (fetch)\n",
        )
        self.assertEqual(findings, [])
        self.assertEqual(runner.gh_calls(), [])

    def test_status_is_never_a_mismatch(self):
        scenarios = [
            {},
            {DEFAULT_BRANCH_ARGV: (True, "main")},
            {DEFAULT_BRANCH_ARGV: (True, "")},
            {DEFAULT_BRANCH_ARGV: (True, "null")},
            {
                DEFAULT_BRANCH_ARGV: (True, "main"),
                RULES_ARGV: (True, "deletion"),
                PROTECTION_ARGV: (True, "true,true"),
            },
        ]
        for responses in scenarios:
            with self.subTest(responses=sorted(responses)):
                _, findings = self.run_protection(make_tier_data(), responses)
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
                    RULES_ARGV: (True, "non_fast_forward,deletion"),
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
            self.assertIn("history protection", labels[0])
            self.assertIn("vendored", labels[1])


if __name__ == "__main__":
    unittest.main()
