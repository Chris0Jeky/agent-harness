"""Controlled-path regressions for floorless Doctor declarations (#275)."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import unittest

import harness
from tests import test_harness as fixtures


class DoctorFloorRegistrationTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        fixture = fixtures.HarnessTests()
        fixture.setUp()
        try:
            repo = fixture.make_repo()
            fixture.write_floorless_tier(repo)
            home = Path(fixture.temp.name) / "claude-home"
            home.mkdir(exist_ok=True)
            sources = (
                home / "settings.json",
                repo / ".claude" / "settings.json",
                repo / ".claude" / "settings.local.json",
            )
            yield fixture, repo, home, sources
        finally:
            fixture.tearDown()

    @staticmethod
    def write_handler(source, command, *, event="PreToolUse", kind="command"):
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            json.dumps(
                {"hooks": {event: [{"hooks": [{"type": kind, "command": command}]}]}}
            ),
            encoding="utf-8",
        )

    def test_foreign_dispatchers_do_not_contradict_floorless_in_any_scope(self):
        for scope in range(3):
            for filename in ("dispatch.py", "dispatch.py.backup", "not-dispatch.py"):
                with self.subTest(scope=scope, filename=filename), self.fixture() as data:
                    fixture, repo, home, sources = data
                    self.write_handler(sources[scope], f'python "{repo / filename}"')
                    self.assertIsNone(harness.claude_settings_register_floor(home, repo))
                    code, output = fixture.run_doctor_with_fixture_globals(repo)
                    self.assertEqual(0, code, output)
                    self.assertIn("floorless by declaration", output)

    def test_controlled_absolute_path_is_detected_in_every_scope(self):
        for scope in range(3):
            with self.subTest(scope=scope), self.fixture() as data:
                fixture, repo, home, sources = data
                dispatcher = home / "hooks" / "dispatch.py"
                self.write_handler(sources[scope], f'python "{dispatcher}" --event pre')
                self.assertEqual(
                    sources[scope], harness.claude_settings_register_floor(home, repo)
                )
                code, output = fixture.run_doctor_with_fixture_globals(repo)
                self.assertEqual(1, code, output)
                self.assertIn("still registers the PreToolUse dispatcher", output)

    def test_supported_home_spellings_keep_the_controlled_path_identity(self):
        commands = (
            "python ~/.claude/hooks/dispatch.py --event pre",
            'python "$HOME/.claude/hooks/dispatch.py" --event pre',
            'python "${HOME}/.claude/hooks/dispatch.py" --event pre',
            "py -3 $env:USERPROFILE/.claude/hooks/DISPATCH.PY --event pre",
            r'py -3 "%USERPROFILE%\.claude\hooks\DISPATCH.PY" --event pre',
        )
        for command in commands:
            with self.subTest(command=command), self.fixture() as data:
                _fixture, repo, home, sources = data
                self.write_handler(sources[0], command)
                self.assertEqual(
                    sources[0], harness.claude_settings_register_floor(home, repo)
                )

    def test_embedded_paths_and_unknown_home_variables_are_not_shared(self):
        with self.fixture() as data:
            _fixture, repo, home, sources = data
            dispatcher = home / "hooks" / "dispatch.py"
            commands = (
                f'python "{dispatcher}.backup"',
                f'python "{dispatcher}/child.py"',
                f'python "prefix{dispatcher}"',
                "python ~/other/.claude/hooks/dispatch.py",
                "python ~another/.claude/hooks/dispatch.py",
                "python $OTHER_HOME/.claude/hooks/dispatch.py",
                "python $HOME_OTHER/.claude/hooks/dispatch.py",
                "python $HOME/.claude/hooks/dispatch.py.backup",
                "py $env:USERPROFILE/.claude/hooks/dispatch.py.backup",
                "py $env:OTHERPROFILE/.claude/hooks/dispatch.py",
                "python relative/dispatch.py",
            )
            for command in commands:
                with self.subTest(command=command):
                    self.write_handler(sources[0], command)
                    self.assertIsNone(harness.claude_settings_register_floor(home, repo))

    def test_lifecycle_prompt_and_comment_mentions_do_not_register_a_floor(self):
        with self.fixture() as data:
            _fixture, repo, home, sources = data
            command = f'python "{home / "hooks" / "dispatch.py"}"'
            for event, kind, text in (
                ("SessionStart", "command", command),
                ("PreToolUse", "prompt", command),
                ("PreToolUse", "agent", command),
                ("PreToolUse", "command", "echo ok # " + command),
                ("PreToolUse", "command", "# " + command),
            ):
                with self.subTest(event=event, kind=kind, command=text):
                    self.write_handler(sources[0], text, event=event, kind=kind)
                    self.assertIsNone(harness.claude_settings_register_floor(home, repo))

    def test_absolute_path_case_follows_host_not_a_global_lowercase(self):
        with self.fixture() as data:
            _fixture, repo, home, sources = data
            self.write_handler(sources[0], f'python "{home / "hooks" / "DISPATCH.PY"}"')
            expected = sources[0] if os.name == "nt" else None
            self.assertEqual(expected, harness.claude_settings_register_floor(home, repo))

    def test_scan_continues_past_foreign_and_malformed_sources(self):
        with self.fixture() as data:
            _fixture, repo, home, sources = data
            self.write_handler(sources[0], 'python "foreign/dispatch.py"')
            sources[1].parent.mkdir(parents=True, exist_ok=True)
            sources[1].write_text('{"hooks":', encoding="utf-8")
            self.write_handler(sources[2], f'python "{home / "hooks" / "dispatch.py"}"')
            self.assertEqual(sources[2], harness.claude_settings_register_floor(home, repo))


if __name__ == "__main__":
    unittest.main()
