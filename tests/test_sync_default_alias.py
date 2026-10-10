"""Default sync refuses aliased destinations before changing fictional homes."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import unittest
from unittest import mock

import harness
import test_harness as fixtures


class DefaultSyncAliasTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HarnessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def fixture_for(self, name):
        return self.fixture.make_scoped_sync_fixture(name)

    def check_aliases(self, link):
        for apply in (False, True):
            for name in (
                "AGENTS.md",
                "REPOS.md",
                "dispatch.py",
                "smoke_test.py",
                "hooks.json",
            ):
                with self.subTest(apply=apply, name=name):
                    source, codex, claude, skills, args = self.fixture_for(
                        f"{link}-{apply}-{name}"
                    )
                    args.apply = apply
                    target = (
                        claude / "hooks" / name
                        if name in ("dispatch.py", "smoke_test.py")
                        else codex / name
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    victim = source.parent.parent / "outside-sentinel"
                    original = b"outside sentinel\n"
                    if name == "hooks.json":
                        original = json.dumps(
                            {
                                "hooks": {
                                    "PreToolUse": [
                                        {
                                            "hooks": [
                                                harness.canonical_legacy_codex_floor_handler(
                                                    codex / "hooks" / "dispatch.py"
                                                )
                                            ]
                                        }
                                    ]
                                }
                            }
                        ).encode()
                    victim.write_bytes(original)
                    mode = stat.S_IMODE(victim.stat().st_mode)
                    try:
                        if link == "symlink":
                            target.symlink_to(victim)
                        else:
                            os.link(victim, target)
                    except OSError as exc:
                        self.skipTest(f"{link} unavailable: {exc}")
                    with redirect_stdout(io.StringIO()), mock.patch.object(
                        harness,
                        "reserve_backup_root",
                        wraps=harness.reserve_backup_root,
                    ) as reserved:
                        with self.assertRaises(harness.HarnessError):
                            harness.sync_global(args)
                    reserved.assert_not_called()
                    self.assertEqual(original, victim.read_bytes())
                    self.assertEqual(mode, stat.S_IMODE(victim.stat().st_mode))
                    self.assertFalse((codex / "backups").exists())
                    self.assertFalse(skills.exists())

    def test_symlink_destinations_refuse_before_any_write(self):
        self.check_aliases("symlink")

    def test_hardlink_destinations_refuse_before_any_write(self):
        self.check_aliases("hardlink")

    def test_directory_alias_home_refuses_before_resolution(self):
        for home in ("codex_home", "claude_home"):
            with self.subTest(home=home):
                source, codex, claude, skills, args = self.fixture_for(home)
                external = source.parent.parent / "outside-home"
                external.mkdir()
                destination = Path(getattr(args, home))
                remove_alias = self.fixture.make_directory_alias(external, destination)
                self.addCleanup(remove_alias)
                with redirect_stdout(io.StringIO()), self.assertRaises(
                    harness.HarnessError
                ):
                    harness.sync_global(args)
                self.assertEqual([], list(external.iterdir()))
                self.assertFalse(skills.exists())

    def test_ordinary_destinations_install_and_identity_is_unchanged(self):
        source, codex, claude, skills, args = self.fixture_for("ordinary")
        codex.mkdir()
        (codex / "AGENTS.md").write_bytes(b"previous guidance\n")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, harness.sync_global(args))
        self.assertEqual(
            (source / "AGENTS.md").read_bytes(), (codex / "AGENTS.md").read_bytes()
        )
        self.assertTrue(
            any(
                path.read_bytes() == b"previous guidance\n"
                for path in (codex / "backups").rglob("AGENTS.md")
            )
        )
        with mock.patch.object(harness, "write_managed_codex_file") as published:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, harness.sync_global(args))
        published.assert_not_called()

    def test_late_hardlink_publication_keeps_external_bytes_and_mode(self):
        source, codex, _claude, _skills, _args = self.fixture_for("late-hardlink")
        codex.mkdir()
        target = codex / "AGENTS.md"
        target.write_bytes(b"old guidance\n")
        victim = source.parent.parent / "outside-sentinel"
        victim.write_bytes(b"outside sentinel\n")
        mode = stat.S_IMODE(victim.stat().st_mode)
        original_publish = harness.write_managed_codex_file

        def substitute_then_publish(path, content, final_mode):
            path.unlink()
            os.link(victim, path)
            original_publish(path, content, final_mode)

        with mock.patch.object(
            harness, "write_managed_codex_file", substitute_then_publish
        ):
            self.assertEqual(
                "updated",
                harness.copy_with_backup(
                    source / "AGENTS.md", target, codex / "backups"
                ),
            )
        self.assertEqual(b"outside sentinel\n", victim.read_bytes())
        self.assertEqual(mode, stat.S_IMODE(victim.stat().st_mode))
        self.assertEqual((source / "AGENTS.md").read_bytes(), target.read_bytes())
        self.assertEqual(
            b"old guidance\n", (codex / "backups" / "AGENTS.md").read_bytes()
        )

    def test_uninspectable_target_refuses_before_backup(self):
        _source, codex, _claude, _skills, args = self.fixture_for("inspection-error")
        codex.mkdir()
        target = codex / "AGENTS.md"
        original_lstat = Path.lstat

        def inspect(path, *args, **kwargs):
            if path == target:
                raise PermissionError("fictional inspection refusal")
            return original_lstat(path, *args, **kwargs)

        with mock.patch.object(Path, "lstat", inspect), redirect_stdout(io.StringIO()):
            with self.assertRaises(harness.HarnessError):
                harness.sync_global(args)
        self.assertFalse((codex / "backups").exists())


if __name__ == "__main__":
    unittest.main()
