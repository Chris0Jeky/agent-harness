"""Cross-product coverage for command prefixes that must not hide the head."""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch = load_module(
    "dispatch_command_prefixes", ROOT / "templates" / "hooks" / "dispatch.py"
)
smoke = load_module(
    "smoke_command_prefixes", ROOT / "templates" / "hooks" / "smoke_test.py"
)


def private_remote(*_args, **_kwargs):
    """Keep parser tests offline; the prefix must not change remote privacy."""
    return False, "test-private"


def clean_environment() -> dict[str, str]:
    env = smoke.clean_dispatch_environment()
    return {
        name: value for name, value in env.items() if not name.startswith("GIT_CONFIG")
    }


def decide(command: str, tier: int = 1, flags: dict | None = None):
    with patch.dict(os.environ, clean_environment(), clear=True):
        return dispatch.check(
            command,
            {"tier": tier, "flags": flags or {}},
            str(ROOT),
            str(ROOT),
            remote_resolver=private_remote,
        )


class CommandHeadPrefixTests(unittest.TestCase):
    def test_leading_redirects_and_stop_parsing_reveal_the_real_head(self):
        cases = (
            (["2", ">&", "1", "rm", "-rf", "/critical/outside"], "rm"),
            ([">", "/dev/null", "sudo", "id"], "sudo"),
            (["2", ">", "err", "git", "push", "--force"], "git"),
            (["&>", "out", "rm", "-rf", "/critical/outside"], "rm"),
            ([">&", "1", "git", "push", "--force"], "git"),
            (["--%", "rm", "-rf", "/critical/outside"], "rm"),
            (
                ["FOO=bar", "2", ">", "err", ">", "out", "sudo", "id"],
                "sudo",
            ),
        )
        for argv, expected in cases:
            with self.subTest(argv=argv):
                self.assertEqual(dispatch.command_head(argv)[0], expected)

    def test_redirects_after_the_head_do_not_replace_it(self):
        self.assertEqual(
            dispatch.command_head(["echo", ">", "out", "rm", "-rf", "/"])[0],
            "echo",
        )

    def test_a_leading_process_substitution_is_not_a_redirect_prefix(self):
        self.assertEqual(dispatch.command_head(["<", "(printf", "x)", "tail"])[0], "<")


class PrefixCrossProductTests(unittest.TestCase):
    PREFIXES = (
        "2>&1 ",
        ">/dev/null ",
        "2>agent-harness-prefix.err ",
        "&>agent-harness-prefix.out ",
        ">&1 ",
        "HARNESS_PREFIX=1 ",
        "--% ",
    )

    def test_every_direct_deny_stays_denied_behind_each_prefix(self):
        eligible = 0
        for command, tier, flags, expected in smoke.CASES:
            if expected != "deny":
                continue
            eligible += 1
            with self.subTest(
                prefix="<direct>", command=command, tier=tier, flags=flags
            ):
                decision, reason = decide(command, tier, flags)
                self.assertEqual(decision, "deny", reason)
            for prefix in self.PREFIXES:
                with self.subTest(
                    prefix=prefix, command=command, tier=tier, flags=flags
                ):
                    decision, reason = decide(prefix + command, tier, flags)
                    self.assertEqual(decision, "deny", reason)
        self.assertGreater(eligible, 1000)


class AssignmentPrefixPolicyTests(unittest.TestCase):
    def test_exposed_shell_keeps_bash_env_policy(self):
        decision, reason = decide("HARNESS_PREFIX=1 BASH_ENV=/tmp/opaque bash -c :")
        self.assertEqual(decision, "deny")
        self.assertIn("BASH_ENV", reason)

    def test_assignment_looking_argument_remains_data(self):
        self.assertEqual(decide("Write-Output GIT_CONFIG_COUNT=1")[0], "allow")


class AggregateConfigRedirectTests(unittest.TestCase):
    def test_aggregate_redirects_poison_a_later_push(self):
        for operator in ("&>", "&>>", ">&"):
            command = f"echo x {operator} .git/config; git push origin"
            with self.subTest(operator=operator):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny")
                self.assertIn("push-config-unverifiable", reason)


class CmdAggregateSeparatorTests(unittest.TestCase):
    def test_cmd_aggregate_spelling_exposes_the_following_delete(self):
        for switch in ("c", "k"):
            switch_prefixes = (
                f"cmd /{switch}",
                f"cmd.exe /d /{switch}",
                f"cmd.exe /d/{switch}",
                f"cmd /q/{switch}",
            )
            for switch_prefix in switch_prefixes:
                for operator in ("&>", "&>>"):
                    commands = (
                        rf"""{switch_prefix} "echo harmless {operator}nul """
                        r'''rd /s /q C:\critical\outside path\"''',
                        rf"""{switch_prefix}"echo harmless {operator}nul """
                        r'''rd /s /q C:\critical\outside path\"''',
                        rf"""{switch_prefix}echo harmless {operator}nul """
                        r'''rd /s /q "C:\critical\outside path\"''',
                    )
                    for command in commands:
                        with self.subTest(command=command):
                            decision, reason = decide(command)
                            self.assertEqual(decision, "deny", reason)


if __name__ == "__main__":
    unittest.main()
