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


class DangerousPrefixTests(unittest.TestCase):
    """The prefix itself can carry the irreversible act.

    Stripping the leading redirection to expose the head must not also discard
    the redirect target.  The argv rule is the only check that sees an
    inert-QUOTED target, because the whole-command text scan runs on
    ``strip_quotes`` output where ``'.env'`` is already a placeholder.
    """

    SECRET_TARGETS = ("'.env'", '".env"', "'~/.ssh/id_rsa'", '"my.credentials"')
    WRITE_OPERATORS = ("> ", ">> ", "2> ", "2>> ", "&> ", "&>> ", ">| ", ">&")

    def test_quoted_secret_redirect_in_the_prefix_is_denied(self):
        for target in self.SECRET_TARGETS:
            for operator in self.WRITE_OPERATORS:
                for tail in ("", " echo hi", " git status"):
                    command = f"{operator}{target}{tail}"
                    with self.subTest(command=command):
                        decision, reason = decide(command)
                        self.assertEqual(decision, "deny", reason)
                        self.assertIn("secret-looking file", reason)

    def test_split_descriptor_spelling_is_denied(self):
        for command in ("2 > '.env' true", "2 >> '.env' true", "* > '.env' true"):
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny", reason)

    def test_bare_secret_redirect_in_the_prefix_stays_denied(self):
        for command in ("> .env echo hi", "2>.env git status", "&>.env echo hi"):
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "deny")

    def test_reading_a_secret_file_through_the_prefix_stays_allowed(self):
        # The floor blocks the irreversible, not disclosure by read.  Denying
        # `< '.env' cat` would be a new false positive, not a charter win.
        for command in ("< '.env' cat", "< .env cat", "<& 3 cat"):
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "allow")


class PrefixAllowSideTests(unittest.TestCase):
    """Legitimate commands must survive every prefix form.

    ``PrefixCrossProductTests`` only proves denies stay denied.  A prefix change
    that starts blocking ordinary work is as serious a defect as one that lets a
    charter shape through, so the allow direction needs its own gate.
    """

    BENIGN = (
        "git status",
        "git log --oneline -5",
        "git diff HEAD~1",
        "ls -la",
        "cat README.md",
        "py -3 -m pytest tests",
        "npm run build",
        "make -j4 all",
        "grep -rn TODO src",
        "echo hello",
        "git commit -m 'ship it'",
        "gh pr view 53",
    )

    def test_every_benign_command_allows_behind_each_prefix(self):
        for command in self.BENIGN:
            with self.subTest(prefix="<direct>", command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "allow", reason)
            for prefix in PrefixCrossProductTests.PREFIXES:
                with self.subTest(prefix=prefix, command=command):
                    decision, reason = decide(prefix + command, 1)
                    self.assertEqual(decision, "allow", reason)

    def test_benign_redirect_targets_are_not_secret_looking(self):
        commands = (
            "> build.log make all",
            ">> build.log make all",
            "2> errors.txt git fetch origin",
            "&> combined.log npm test",
            ">| out.txt ls",
            "> /dev/null git gc",
            "< input.txt sort -u",
        )
        for command in commands:
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "allow", reason)


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


class WindowsGrammarSegmentationTests(unittest.TestCase):
    """`&>` is one redirect in PowerShell and two commands in cmd.exe.

    The recovery paths cannot know which shell runs the line, so committing to
    the PowerShell reading drops the cmd command hiding behind the redirect.
    """

    OUTSIDE_DELETE = r'rd /s /q "C:\critical\outside path\"'

    def test_aggregate_redirect_does_not_hide_a_following_delete(self):
        for operator in ("&>", "&>>"):
            for lead in ("echo x", "call other.bat", "start other.exe"):
                command = f"{lead} {operator}nul {self.OUTSIDE_DELETE}"
                with self.subTest(command=command):
                    decision, reason = decide(command)
                    self.assertEqual(decision, "deny", reason)

    def test_both_separator_readings_are_recovered(self):
        merged = dispatch.windows_recovery_segments("echo x &>nul rd /s /q C:\\x")
        segments = [segment for segment, _operator in merged]
        self.assertIn("echo x &>nul rd /s /q C:\\x", segments)
        self.assertIn("echo x", segments)
        self.assertIn(">nul rd /s /q C:\\x", segments)

    def test_powershell_aggregate_redirect_stays_allowed(self):
        commands = (
            r'Get-Content "C:\logs\app\" &> out.txt',
            r'Write-Output "note\" &>> build.log',
            "npm test &> combined.log",
        )
        for command in commands:
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "allow", reason)


if __name__ == "__main__":
    unittest.main()
