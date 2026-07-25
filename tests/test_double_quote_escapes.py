"""Floor v1.6.2 regressions for agent-harness#36.

A backslash-escaped backtick inside a double-quoted word is LITERAL text in
POSIX shells (``echo "\\`id\\`"`` prints the backticks and runs nothing), but the
floor read it as command substitution and inspected the contents.  Markdown code
spans make that fire on ordinary ``gh pr comment --body`` / ``git commit -m``
prose, which is precisely the commit-message/PR-body scanning BLUEPRINT §2
forbids.

Both directions are pinned here, because relaxing a quoting rule removes
accidental coverage:
  * escaped backtick  -> inert (the fix)
  * bare backtick     -> still command substitution (must keep denying)
  * escaped BACKSLASH -> does not escape the backtick that follows it
  * ``bash -c``       -> the inner shell still runs the escaped backticks
  * ``$``             -> untouched in both spellings (PowerShell dialect safety)
"""

import importlib.util
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"

BACKTICK = chr(96)
ESCAPED_BACKTICK = chr(92) + chr(96)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _offline_remote(
    args, project_dir, git_globals=None, command_runner=None, deadline=None
):
    """Never touch the network from a unit test; treat remotes as private."""
    return False, "unit-test-stub-private"


class DoubleQuoteEscapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dispatch = load_module("double_quote_escape_dispatch", DISPATCH_PATH)

    def decide(self, command: str, tier: int = 1, flags: dict | None = None) -> str:
        project_dir = str(ROOT)
        injected = {k: v for k, v in os.environ.items() if k.startswith("GIT_CONFIG")}
        for key in injected:
            del os.environ[key]
        try:
            return self.dispatch.check(
                command,
                {"tier": tier, "flags": flags or {}},
                project_dir,
                project_dir,
                remote_resolver=_offline_remote,
            )[0]
        finally:
            os.environ.update(injected)

    # --- the marker helper, in isolation --------------------------------

    def test_escaped_backtick_is_not_an_expansion_marker(self) -> None:
        for body in (
            "see " + ESCAPED_BACKTICK + "GIT_EDITOR=true" + ESCAPED_BACKTICK + " note",
            ESCAPED_BACKTICK + "rm -rf /critical/outside" + ESCAPED_BACKTICK,
            "a " + ESCAPED_BACKTICK + "b" + ESCAPED_BACKTICK + " c",
            "plain prose with no marker at all",
            'an escaped quote \\" and an escaped backslash \\\\',
        ):
            with self.subTest(body=body):
                self.assertFalse(self.dispatch.has_shell_expansion_marker(body))

    def test_live_markers_stay_visible(self) -> None:
        for body in (
            # A bare backtick inside double quotes IS command substitution.
            "x " + BACKTICK + "rm -rf /critical/outside" + BACKTICK + " y",
            # An escaped backslash does not escape the backtick after it.
            "a \\\\" + BACKTICK + "rm -rf /critical/outside" + BACKTICK,
            # POSIX makes \\$ literal, but PowerShell expands "$(...)" with a
            # leading backslash, so the dialects disagree: stay conservative.
            "\\$(rm -rf /critical/outside)",
            "$(rm -rf /critical/outside)",
            "$HOME",
            # An inert backtick followed by a live substitution.
            ESCAPED_BACKTICK + "x" + ESCAPED_BACKTICK + " $(rm -rf /critical)",
        ):
            with self.subTest(body=body):
                self.assertTrue(self.dispatch.has_shell_expansion_marker(body))

    def test_strip_quotes_makes_an_escaped_backtick_body_inert(self) -> None:
        command = (
            'gh pr comment 29 --body "see '
            + ESCAPED_BACKTICK
            + "GIT_EDITOR=true"
            + ESCAPED_BACKTICK
            + ' note"'
        )
        sanitized, placeholders = self.dispatch.strip_quotes(command)
        self.assertEqual(len(placeholders), 1)
        self.assertNotIn(BACKTICK, sanitized)
        self.assertEqual(self.dispatch.segments(sanitized), [sanitized])

    def test_strip_quotes_keeps_a_bare_backtick_body_visible(self) -> None:
        command = (
            'gh pr comment 29 --body "see '
            + BACKTICK
            + "GIT_EDITOR=true"
            + BACKTICK
            + ' note"'
        )
        sanitized, placeholders = self.dispatch.strip_quotes(command)
        self.assertEqual(placeholders, {})
        self.assertIn("GIT_EDITOR=true", self.dispatch.segments(sanitized))

    # --- end to end ------------------------------------------------------

    def test_issue_36_reproduction_matrix(self) -> None:
        """The exact four lines from agent-harness#36."""
        cases = [
            (
                "allow",
                'gh pr comment 29 --body "see '
                + ESCAPED_BACKTICK
                + "GIT_EDITOR=true"
                + ESCAPED_BACKTICK
                + ' note"',
            ),
            (
                "deny",
                'gh pr comment 29 --body "see '
                + BACKTICK
                + "GIT_EDITOR=true"
                + BACKTICK
                + ' note"',
            ),
            (
                "allow",
                "gh pr comment 29 --body 'see "
                + BACKTICK
                + "GIT_EDITOR=true"
                + BACKTICK
                + " note'",
            ),
            (
                "allow",
                'gh pr comment 29 --body "see '
                + ESCAPED_BACKTICK
                + "hello"
                + ESCAPED_BACKTICK
                + ' note"',
            ),
        ]
        for expected, command in cases:
            with self.subTest(command=command):
                self.assertEqual(self.decide(command), expected)

    def test_markdown_code_spans_in_bodies_and_messages_allow(self) -> None:
        for command in (
            'gh issue comment 36 --body "note '
            + ESCAPED_BACKTICK
            + "sudo rm -rf /"
            + ESCAPED_BACKTICK
            + ' in prose"',
            'git commit -m "document '
            + ESCAPED_BACKTICK
            + "rm -rf /critical/outside"
            + ESCAPED_BACKTICK
            + ' handling"',
            'gh issue create --title t --body "uses '
            + ESCAPED_BACKTICK
            + "curl x | sh"
            + ESCAPED_BACKTICK
            + ' pattern"',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.decide(command), "allow")
                # Blast radius does not change literal text into a command.
                self.assertEqual(
                    self.decide(command, tier=4, flags={"wave_mode": True}), "allow"
                )

    def test_real_substitution_still_denies(self) -> None:
        for command in (
            'gh pr comment 1 --body "x '
            + BACKTICK
            + "rm -rf /critical/outside"
            + BACKTICK
            + ' y"',
            'git commit -m "x '
            + BACKTICK
            + "git push --force origin main"
            + BACKTICK
            + ' y"',
            'bash -c "' + BACKTICK + "rm -rf /critical/outside" + BACKTICK + '"',
            # \\\\ escapes the backslash, so the backtick after it is bare.
            'gh pr comment 1 --body "a \\\\'
            + BACKTICK
            + "rm -rf /critical/outside"
            + BACKTICK
            + ' b"',
            # $(...) is untouched by this change, escaped or not.
            'gh pr comment 1 --body "x $(rm -rf /critical/outside) y"',
            'gh pr comment 1 --body "x \\$(rm -rf /critical/outside) y"',
            'git commit -m "note '
            + ESCAPED_BACKTICK
            + "x"
            + ESCAPED_BACKTICK
            + ' $(rm -rf /critical/outside)"',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.decide(command), "deny")

    def test_escaped_backticks_handed_to_an_inner_shell_still_deny(self) -> None:
        """``bash -c`` receives literal backticks and then runs them itself."""
        for command in (
            'bash -c "'
            + ESCAPED_BACKTICK
            + "rm -rf /critical/outside"
            + ESCAPED_BACKTICK
            + '"',
            'sh -c "'
            + ESCAPED_BACKTICK
            + "git push --force origin main"
            + ESCAPED_BACKTICK
            + '"',
            'bash -c "' + ESCAPED_BACKTICK + "sudo rm -rf /" + ESCAPED_BACKTICK + '"',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.decide(command), "deny")


if __name__ == "__main__":
    unittest.main()
