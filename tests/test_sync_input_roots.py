"""Raw sync roots cannot hide an alias behind parent normalization (#273)."""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import unittest

import harness
import test_harness as fixtures


class SyncInputRootTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HarnessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_claude_skill_parent_components_refuse_before_writes(self):
        for apply in (False, True):
            for field in ("config_root", "claude_home"):
                with self.subTest(apply=apply, field=field):
                    config, home, args = self.fixture.make_claude_skill_sync_fixture(
                        f"parent-{field}-{apply}"
                    )
                    original = Path(getattr(args, field))
                    child = original.parent / "plain-child"
                    child.mkdir()
                    setattr(args, field, str(child / ".." / original.name))
                    args.apply = apply
                    before = harness.tree_digest(config.parent)
                    with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                        harness.HarnessError, "parent traversal"
                    ):
                        harness.sync_global(args)
                    self.assertEqual(before, harness.tree_digest(config.parent))
                    self.assertFalse(home.exists())

    def test_alias_then_parent_cannot_select_a_different_physical_root(self):
        config, home, args = self.fixture.make_claude_skill_sync_fixture("alias-parent")
        physical = config.parent / "physical" / "nested"
        physical.mkdir(parents=True)
        alias = config.parent / "alias"
        cleanup = self.fixture.make_directory_alias(physical, alias)
        self.addCleanup(cleanup)
        args.claude_home = str(alias / ".." / home.name)
        self.assertNotEqual(Path(args.claude_home).resolve(), home)
        for apply in (False, True):
            with self.subTest(apply=apply):
                args.apply = apply
                with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                    harness.HarnessError, "parent traversal"
                ):
                    harness.sync_global(args)
                self.assertFalse(home.exists())
                self.assertFalse((physical.parent / home.name).exists())
                self.assertEqual((config / "skills/sample/SKILL.md").read_text(), "# source sample\n")

    def test_bundle_inputs_and_rollback_receipt_refuse_parent_components(self):
        for apply in (False, True):
            for field in ("config_root", "claude_home", "user_bin_home", "rollback_receipt"):
                with self.subTest(apply=apply, field=field):
                    config, home, bin_home, args = self.fixture.make_bundle_sync_fixture(
                        f"bundle-{field}-{apply}"
                    )
                    original = Path(getattr(args, field) or config.parent / "receipt.json")
                    child = original.parent / "child"
                    child.mkdir()
                    setattr(args, field, str(child / ".." / original.name))
                    args.apply = apply
                    before = harness.tree_digest(config.parent)
                    with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                        harness.HarnessError, "parent traversal"
                    ):
                        harness.sync_global(args)
                    self.assertEqual(before, harness.tree_digest(config.parent))
                    self.assertFalse(home.exists())
                    self.assertFalse(bin_home.exists())

    def test_codex_selected_roots_refuse_parent_components(self):
        for field in ("config_root", "codex_home", "skills_home"):
            with self.subTest(field=field):
                source, _, _, _, args = self.fixture.make_scoped_sync_fixture(f"codex-{field}")
                args.only = ["skill:other"]
                original = Path(getattr(args, field))
                child = original.parent / "plain"
                child.mkdir()
                setattr(args, field, str(child / ".." / original.name))
                root = source.parent.parent.resolve()
                before = harness.tree_digest(root)
                with redirect_stdout(io.StringIO()), self.assertRaisesRegex(harness.HarnessError, "parent traversal"):
                    harness.sync_global(args)
                self.assertEqual(before, harness.tree_digest(root))

    def test_plain_relative_roots_and_unused_roots_remain_usable(self):
        config, home, args = self.fixture.make_claude_skill_sync_fixture("relative")
        cwd = Path.cwd()
        try:
            os.chdir(config.parent)
            args.config_root = "config"
            args.claude_home = "./claude-home"
            args.codex_home = "unused/../codex"
            args.skills_home = "unused/../skills"
            for apply in (False, True):
                args.apply = apply
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(harness.sync_global(args), 0)
        finally:
            os.chdir(cwd)
        self.assertEqual((home / "skills/sample/SKILL.md").read_bytes(), (config / "skills/sample/SKILL.md").read_bytes())

    def test_direct_alias_check_refuses_raw_parent_before_normalizing(self):
        root = Path(self.fixture.temp.name)
        with self.assertRaisesRegex(harness.HarnessError, "parent traversal"):
            harness.reject_sync_path_aliases(root / "child" / ".." / "target", "test root")
