"""PR #22 review: a drifted executable bit must not read as an identical tree.

`tree_digest` hashed only entry kind, path and file contents, so a managed skill
whose helper script had lost its executable bit (source 0755, installed 0644)
digested identically. `same_tree` then made `sync-global --apply` skip the copy
that would have restored the mode, leaving an installed skill that cannot run its
own script.

Only each file and directory's executable-bit tuple is digested: the rest of the
mode is umask/filesystem noise, and Windows reports no meaningful bits, so this
test skips there.
"""

import importlib.util
import ctypes
import io
import os
import shutil
import stat
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = load_module("harness_tree_mode", ROOT / "harness.py")


def write_tree(root: Path, mode: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    script = root / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    os.chmod(script, mode)


@unittest.skipIf(os.name == "nt", "Windows does not model the POSIX executable bit")
class SkillTreeModeDigestTests(unittest.TestCase):
    def test_executable_drift_changes_the_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base / "source", mode=0o755)
            write_tree(base / "target", mode=0o644)
            self.assertNotEqual(
                harness.tree_digest(base / "source"),
                harness.tree_digest(base / "target"),
            )
            self.assertFalse(harness.same_tree(base / "source", base / "target"))

    def test_identical_modes_still_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base / "source", mode=0o755)
            write_tree(base / "target", mode=0o755)
            self.assertTrue(harness.same_tree(base / "source", base / "target"))

    def test_group_or_other_execute_counts_as_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base / "source", mode=0o644)
            script = base / "source" / "run.sh"
            os.chmod(script, script.stat().st_mode | stat.S_IXOTH)
            write_tree(base / "target", mode=0o644)
            self.assertFalse(harness.same_tree(base / "source", base / "target"))

    def test_distinct_executable_bit_tuples_do_not_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base / "source", mode=0o750)
            write_tree(base / "target", mode=0o705)
            self.assertNotEqual(
                harness.tree_digest(base / "source"),
                harness.tree_digest(base / "target"),
            )
            self.assertFalse(harness.same_tree(base / "source", base / "target"))

    def test_distinct_root_directory_execute_tuples_do_not_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base / "source", mode=0o755)
            write_tree(base / "target", mode=0o755)
            os.chmod(base / "source", 0o750)
            os.chmod(base / "target", 0o705)
            self.assertFalse(harness.same_tree(base / "source", base / "target"))

    def test_distinct_nested_directory_execute_tuples_do_not_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base / "source", mode=0o755)
            write_tree(base / "target", mode=0o755)
            for tree, mode in (("source", 0o750), ("target", 0o705)):
                directory = base / tree / "scripts"
                directory.mkdir()
                os.chmod(directory, mode)
            self.assertFalse(harness.same_tree(base / "source", base / "target"))


class SkillTreeFilesystemLookupTests(unittest.TestCase):
    def set_case_sensitive(self, directory: Path) -> None:
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        )
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.SetFileInformationByHandle.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel.CreateFileW(str(directory), 0x100, 7, None, 3, 0x02000000, None)
        if handle == ctypes.c_void_p(-1).value:
            self.skipTest("host cannot open directory to enable NTFS case sensitivity")
        try:
            flags = ctypes.c_uint32(1)
            if not kernel.SetFileInformationByHandle(
                handle, 23, ctypes.byref(flags), 4
            ):
                self.skipTest(
                    f"host cannot enable NTFS case sensitivity: {ctypes.get_last_error()}"
                )
        finally:
            kernel.CloseHandle(handle)

    def collision_fixture(self, root, names, kind, target_present):
        source = root / "config" / "codex" / "skills" / "sample"
        source.mkdir(parents=True)
        self.set_case_sensitive(source)
        (source / "SKILL.md").write_text("# sample\n", encoding="utf-8")
        for name in names:
            entry = source / name
            try:
                if kind == "directory":
                    entry.mkdir()
                    (entry / "payload.txt").write_text(name, encoding="utf-8")
                else:
                    with entry.open("x", encoding="utf-8") as stream:
                        stream.write(name)
            except FileExistsError:
                self.skipTest("source filesystem cannot represent distinct names")
        target = root / "skills-home" / "sample"
        target.parent.mkdir()
        if target_present:
            target.mkdir()
            (target / "SKILL.md").write_text("old skill", encoding="utf-8")
        args = SimpleNamespace(
            config_root=str(root / "config"),
            codex_home=str(root / "codex-home"),
            claude_home=str(root / "claude-home"),
            skills_home=str(target.parent),
            only=["skill:sample"],
            apply=False,
        )
        return source, target, args

    def test_source_collision_refuses_before_any_sync_mutation(self):
        for apply in (False, True):
            for present in (False, True):
                for kind in ("file", "directory"):
                    with self.subTest(
                        apply=apply, present=present, kind=kind
                    ), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        source, target, args = self.collision_fixture(
                            root, ("Foo", "foo"), kind, present
                        )
                        if not harness.skill_tree_destination_is_case_insensitive(
                            target.parent
                        ):
                            self.skipTest("destination filesystem is case sensitive")
                        before = harness.tree_digest(root)
                        args.apply = apply
                        with mock.patch.object(
                            harness.shutil, "copytree", wraps=shutil.copytree
                        ) as copy:
                            with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                                harness.HarnessError, "source skill entries collide"
                            ):
                                harness.sync_global(args)
                            copy.assert_not_called()
                        self.assertEqual(before, harness.tree_digest(root))
                        self.assertFalse(Path(args.codex_home).exists())

    def test_case_sensitive_destination_retains_source_case_pair(self):
        for present in (False, True):
            with self.subTest(present=present), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, target, args = self.collision_fixture(
                    root, ("Foo", "foo"), "file", present
                )
                if present:
                    (target / "SKILL.md").unlink()
                self.set_case_sensitive(target if present else target.parent)
                if present:
                    (target / "SKILL.md").write_text("old skill", encoding="utf-8")
                args.apply = True
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(0, harness.sync_global(args))
                self.assertEqual(
                    harness.tree_digest(source), harness.tree_digest(target)
                )
                self.assertFalse((target / "Foo").samefile(target / "foo"))

    def test_nested_source_collision_refuses_before_copy(self):
        for apply in (False, True):
            with self.subTest(apply=apply), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, target, args = self.collision_fixture(
                    root, ("Foo", "foo"), "file", True
                )
                nested = source / "scripts"
                nested.mkdir()
                self.set_case_sensitive(nested)
                for name in ("Foo", "foo"):
                    (source / name).rename(nested / name)
                if not harness.skill_tree_destination_is_case_insensitive(
                    target.parent
                ):
                    self.skipTest("destination filesystem is case sensitive")
                before = harness.tree_digest(root)
                args.apply = apply
                with redirect_stdout(io.StringIO()), mock.patch.object(
                    harness.shutil, "copytree"
                ) as copy:
                    with self.assertRaisesRegex(
                        harness.HarnessError, "source skill entries collide"
                    ):
                        harness.sync_global(args)
                    copy.assert_not_called()
                self.assertEqual(before, harness.tree_digest(root))

    def test_collision_with_absent_destination_parent_leaves_it_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target, args = self.collision_fixture(
                root, ("Foo", "foo"), "file", False
            )
            if not harness.skill_tree_destination_is_case_insensitive(target.parent):
                self.skipTest("destination filesystem is case sensitive")
            target.parent.rmdir()
            before = harness.tree_digest(root)
            args.apply = True
            with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                harness.HarnessError, "source skill entries collide"
            ):
                harness.sync_global(args)
            self.assertFalse(target.parent.exists())
            self.assertEqual(before, harness.tree_digest(root))

    @unittest.skipUnless(os.name == "nt", "requires case-insensitive NTFS lookup")
    def test_case_variant_hardlink_ambiguity_still_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            source.mkdir()
            target.mkdir()
            (source / "foo").write_text("new", encoding="utf-8")
            (target / "Foo").write_text("old", encoding="utf-8")
            try:
                os.link(target / "Foo", target / "other")
            except OSError as exc:
                self.skipTest(f"host cannot create hard links: {exc}")
            before = harness.tree_digest(target)
            with self.assertRaisesRegex(
                harness.HarnessError, "ambiguous skill destination spelling"
            ):
                harness.canonicalize_skill_tree_case(source, target)
            self.assertEqual(before, harness.tree_digest(target))

    def selection_fixture(self, root, selector, present, names=("Foo", "foo")):
        """Two selected skill roots whose names differ only by case."""
        source_parent = (
            root
            / "config"
            / ("skills" if selector == "claude-skill" else "codex/skills")
        )
        source_parent.mkdir(parents=True)
        self.set_case_sensitive(source_parent)
        for name in names:
            skill = source_parent / name
            try:
                skill.mkdir()
            except FileExistsError:
                self.skipTest("source filesystem cannot represent distinct roots")
            (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        home = root / (
            "claude-home/skills" if selector == "claude-skill" else "skills-home"
        )
        home.mkdir(parents=True)
        if present:
            (home / names[0]).mkdir()
            (home / names[0] / "SKILL.md").write_text("old skill", encoding="utf-8")
        args = SimpleNamespace(
            config_root=str(root / "config"),
            codex_home=str(root / "codex-home"),
            claude_home=str(root / "claude-home"),
            skills_home=str(home),
            only=[f"{selector}:{name}" for name in names],
            apply=False,
        )
        return home, args

    def test_selected_root_name_collision_refuses_before_mutation(self):
        for selector in ("skill", "claude-skill"):
            for apply in (False, True):
                for present in (False, True):
                    with self.subTest(
                        selector=selector, apply=apply, present=present
                    ), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        home, args = self.selection_fixture(root, selector, present)
                        if not harness.skill_tree_destination_is_case_insensitive(home):
                            self.skipTest("destination filesystem is case sensitive")
                        args.apply = apply
                        before = harness.tree_digest(root)
                        with mock.patch.object(
                            harness.shutil, "copytree", wraps=shutil.copytree
                        ) as copy, redirect_stdout(io.StringIO()):
                            with self.assertRaisesRegex(
                                harness.HarnessError, "selected skill roots collide"
                            ):
                                harness.sync_global(args)
                            copy.assert_not_called()
                        self.assertEqual(before, harness.tree_digest(root))
                        self.assertFalse((root / "codex-home").exists())
                        self.assertFalse(
                            (root / "claude-home" / ".harness-backups").exists()
                        )

    def test_selected_roots_on_case_sensitive_destination_both_install(self):
        for selector in ("skill", "claude-skill"):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                home, args = self.selection_fixture(root, selector, False)
                self.set_case_sensitive(home)
                if harness.skill_tree_destination_is_case_insensitive(home):
                    self.skipTest("destination filesystem is case insensitive")
                if selector == "claude-skill":
                    # Claude stages every replacement under its backup parent.
                    backups = root / "claude-home" / ".harness-backups"
                    backups.mkdir()
                    self.set_case_sensitive(backups)
                args.apply = True
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(0, harness.sync_global(args))
                self.assertEqual(
                    "# Foo\n", (home / "Foo" / "SKILL.md").read_text("utf-8")
                )
                self.assertEqual(
                    "# foo\n", (home / "foo" / "SKILL.md").read_text("utf-8")
                )

    @unittest.skipUnless(os.name == "nt", "needs a case-sensitive NTFS destination")
    def test_selected_roots_colliding_in_the_backup_parent_refuse_first(self):
        for selector in ("skill", "claude-skill"):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                home, args = self.selection_fixture(root, selector, False)
                self.set_case_sensitive(home)
                for name in ("Foo", "foo"):
                    (home / name).mkdir()
                    (home / name / "SKILL.md").write_text("old", encoding="utf-8")
                args.apply = True
                before = harness.tree_digest(root)
                with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                    harness.HarnessError, "selected skill roots collide"
                ):
                    harness.sync_global(args)
                self.assertEqual(before, harness.tree_digest(root))

    def test_case_variant_hardlink_refusal_is_actionable_and_restores(self):
        """L1: fail closed, name the entries, and leave the live skill intact."""
        for apply in (False, True):
            with self.subTest(apply=apply), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, target, args = self.collision_fixture(root, (), "file", True)
                (source / "foo").write_text("new", encoding="utf-8")
                (target / "Foo").write_text("old", encoding="utf-8")
                if not harness.skill_tree_destination_is_case_insensitive(target):
                    self.skipTest("destination filesystem is case sensitive")
                try:
                    os.link(target / "Foo", target / "other")
                except OSError as exc:
                    self.skipTest(f"host cannot create hard links: {exc}")
                args.apply = apply
                before = harness.tree_digest(target)
                with redirect_stdout(io.StringIO()):
                    if not apply:
                        self.assertEqual(0, harness.sync_global(args))
                        self.assertEqual(before, harness.tree_digest(target))
                        continue
                    with self.assertRaises(harness.HarnessError) as caught:
                        harness.sync_global(args)
                message = str(caught.exception)
                self.assertIn("ambiguous skill destination spelling", message)
                self.assertIn("Foo, other", message)
                self.assertIn("remove the extra hard link", message)
                self.assertEqual(before, harness.tree_digest(target))
                self.assertEqual("old", (target / "Foo").read_text("utf-8"))

    def test_case_sensitive_destination_subdirectory_keeps_nested_case_pair(self):
        """L3: per-directory NTFS sensitivity applies below the skill root."""
        for apply in (False, True):
            with self.subTest(apply=apply), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, target, args = self.collision_fixture(root, (), "file", True)
                nested = source / "scripts"
                nested.mkdir()
                self.set_case_sensitive(nested)
                for name in ("Foo", "foo"):
                    try:
                        (nested / name).write_text(name, encoding="utf-8")
                    except OSError:
                        self.skipTest(
                            "source filesystem cannot represent distinct names"
                        )
                if len(list(nested.iterdir())) != 2:
                    self.skipTest("source filesystem cannot represent distinct names")
                scripts = target / "scripts"
                scripts.mkdir()
                self.set_case_sensitive(scripts)
                if harness.skill_tree_destination_is_case_insensitive(scripts):
                    self.skipTest("destination subdirectory is case insensitive")
                args.apply = apply
                before = harness.tree_digest(root)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(0, harness.sync_global(args))
                if not apply:
                    self.assertEqual(before, harness.tree_digest(root))
                    continue
                self.assertEqual(
                    harness.tree_digest(source), harness.tree_digest(target)
                )
                self.assertFalse((scripts / "Foo").samefile(scripts / "foo"))

    def test_failed_name_probe_refuses_without_live_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target, args = self.collision_fixture(
                root, ("one", "two"), "file", True
            )
            args.apply = True
            before = harness.tree_digest(root)
            with mock.patch.object(
                harness.tempfile,
                "mkdtemp",
                side_effect=PermissionError("probe unavailable"),
            ):
                with self.assertRaisesRegex(
                    harness.HarnessError, "cannot preflight skill source names"
                ):
                    harness.sync_global(args)
            self.assertEqual(before, harness.tree_digest(root))

    def test_normalization_pair_follows_destination_filesystem(self):
        for apply in (False, True):
            with self.subTest(apply=apply), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, target, args = self.collision_fixture(
                    root, ("\u00e9.txt", "e\u0301.txt"), "file", False
                )
                probe = target.parent / "\u00e9.txt"
                probe.write_text("probe", encoding="utf-8")
                equivalent = (target.parent / "e\u0301.txt").exists()
                probe.unlink()
                args.apply = apply
                before = harness.tree_digest(root)
                with redirect_stdout(io.StringIO()):
                    if equivalent:
                        with self.assertRaisesRegex(
                            harness.HarnessError, "source skill entries collide"
                        ):
                            harness.sync_global(args)
                        self.assertEqual(before, harness.tree_digest(root))
                    else:
                        self.assertEqual(0, harness.sync_global(args))
                        if apply:
                            self.assertEqual(
                                harness.tree_digest(source), harness.tree_digest(target)
                            )
                        else:
                            self.assertEqual(before, harness.tree_digest(root))

    def write_distinct_unicode_files(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        first = root / "Straße.txt"
        second = root / "STRASSE.txt"
        first.write_text("first payload", encoding="utf-8")
        try:
            with second.open("x", encoding="utf-8") as stream:
                stream.write("second payload")
        except FileExistsError:
            self.skipTest("filesystem equates the two Unicode spellings")
        self.assertFalse(first.samefile(second))

    def test_distinct_unicode_files_survive_case_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            self.write_distinct_unicode_files(source)
            shutil.copytree(source, target)
            before = harness.tree_digest(target)
            try:
                harness.canonicalize_skill_tree_case(source, target)
            except harness.HarnessError as exc:
                self.fail(f"representable distinct Unicode names rejected: {exc}")
            self.assertEqual(before, harness.tree_digest(target))
            self.assertEqual(harness.tree_digest(source), harness.tree_digest(target))

    def test_distinct_unicode_directories_survive_case_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            source.mkdir()
            for name in ("Straße", "STRASSE"):
                directory = source / name
                try:
                    directory.mkdir()
                except FileExistsError:
                    self.skipTest("filesystem equates the two Unicode spellings")
                (directory / "payload.txt").write_text(name, encoding="utf-8")
            shutil.copytree(source, target)
            try:
                harness.canonicalize_skill_tree_case(source, target)
            except harness.HarnessError as exc:
                self.fail(f"representable distinct Unicode directories rejected: {exc}")
            self.assertEqual(harness.tree_digest(source), harness.tree_digest(target))

    def test_existing_distinct_hardlink_names_remain_representable(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            source.mkdir()
            target.mkdir()
            for name in ("first.txt", "second.txt"):
                (source / name).write_text("same payload", encoding="utf-8")
            (target / "first.txt").write_text("same payload", encoding="utf-8")
            try:
                os.link(target / "first.txt", target / "second.txt")
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"host cannot create a hard link: {exc}")
            self.assertTrue((target / "first.txt").samefile(target / "second.txt"))
            before = harness.tree_digest(target)
            try:
                harness.canonicalize_skill_tree_case(source, target)
            except harness.HarnessError as exc:
                self.fail(f"distinct existing directory entries rejected: {exc}")
            self.assertEqual(before, harness.tree_digest(target))
            self.assertEqual(harness.tree_digest(source), harness.tree_digest(target))

    def test_repeat_copy_retains_distinct_unicode_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            self.write_distinct_unicode_files(source)
            harness.copy_skill_tree_over(source, target)
            (source / "Straße.txt").write_text("updated first", encoding="utf-8")
            (target / "stale.txt").write_text("stale", encoding="utf-8")
            harness.copy_skill_tree_over(source, target)
            self.assertFalse((target / "stale.txt").exists())
            self.assertEqual(harness.tree_digest(source), harness.tree_digest(target))
            self.assertEqual(
                "second payload", (target / "STRASSE.txt").read_text("utf-8")
            )

    def test_first_copy_checks_exact_names_and_bytes(self):
        for fault in ("missing-name", "changed-bytes"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                source, target = Path(tmp) / "source", Path(tmp) / "target"
                self.write_distinct_unicode_files(source)
                original_copy = shutil.copytree
                injected = []

                def incomplete_copy(src, dst, *args, **kwargs):
                    result = original_copy(src, dst, *args, **kwargs)
                    if Path(dst) == target:
                        injected.append(fault)
                        affected = target / "Straße.txt"
                        if fault == "missing-name":
                            affected.unlink()
                        else:
                            affected.write_text("different", encoding="utf-8")
                    return result

                with mock.patch.object(
                    harness.shutil, "copytree", side_effect=incomplete_copy
                ):
                    with self.assertRaisesRegex(
                        harness.HarnessError, "copied skill tree does not match source"
                    ):
                        harness.copy_skill_tree_over(source, target)
                self.assertEqual([fault], injected)
                self.assertEqual(
                    "first payload", (source / "Straße.txt").read_text("utf-8")
                )
                self.assertTrue(target.is_dir())

    def test_first_copy_rejects_an_uninspectable_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            self.write_distinct_unicode_files(source)
            original_digest = harness.tree_digest
            inspected = []

            def uninspectable(path):
                inspected.append(path)
                return None if path == target else original_digest(path)

            with mock.patch.object(harness, "tree_digest", side_effect=uninspectable):
                with self.assertRaisesRegex(
                    harness.HarnessError, "copied skill tree does not match source"
                ):
                    harness.copy_skill_tree_over(source, target)
            self.assertIn(source, inspected)
            self.assertIn(target, inspected)
            self.assertEqual(original_digest(source), original_digest(target))

    def test_first_copy_of_a_complete_tree_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "parent" / "target"
            self.write_distinct_unicode_files(source)
            before = harness.tree_digest(source)
            harness.copy_skill_tree_over(source, target)
            self.assertEqual(before, harness.tree_digest(source))
            self.assertEqual(before, harness.tree_digest(target))


class UnifiedSkillPreflightTests(unittest.TestCase):
    def fixture(self, root, codex_names, claude_names, shared=True, present=False):
        config = root / "config"
        claude_home = root / "claude-home"
        claude_home.mkdir()
        skills_home = claude_home / "skills" if shared else root / "codex-skills"
        args = SimpleNamespace(
            config_root=str(config),
            codex_home=str(root / "codex-home"),
            claude_home=str(claude_home),
            skills_home=str(skills_home),
            only=[
                *(f"skill:{name}" for name in codex_names),
                *(f"claude-skill:{name}" for name in claude_names),
            ],
            apply=False,
        )
        entries = []
        for family, names, source_parent, target_parent in (
            ("codex", codex_names, config / "codex/skills", skills_home),
            ("claude", claude_names, config / "skills", claude_home / "skills"),
        ):
            for name in names:
                source, target = source_parent / name, target_parent / name
                source.mkdir(parents=True)
                (source / "SKILL.md").write_text(f"{family}:{name}", encoding="utf-8")
                if present and not target.exists():
                    shutil.copytree(source, target)
                entries.append((source, target))
        return args, entries

    def assert_refuses_without_mutation(self, args, root):
        before = harness.tree_digest(root)
        with mock.patch.object(
            harness, "reserve_backup_root", wraps=harness.reserve_backup_root
        ) as reserve:
            with mock.patch.object(
                harness.shutil, "copytree", wraps=shutil.copytree
            ) as copy:
                with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                    harness.HarnessError, "selected skill roots collide"
                ):
                    harness.sync_global(args)
                copy.assert_not_called()
            reserve.assert_not_called()
        self.assertEqual(before, harness.tree_digest(root))

    def test_mixed_identical_roots_refuse_before_any_mutation(self):
        for present in (False, True):
            for apply in (False, True):
                with self.subTest(
                    present=present, apply=apply
                ), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve()
                    args, _ = self.fixture(
                        root, ("sample",), ("sample",), present=present
                    )
                    args.apply = apply
                    self.assert_refuses_without_mutation(args, root)

    def test_mixed_case_and_unicode_roots_follow_native_lookup(self):
        # Separate source families can represent both spellings even on an
        # insensitive/normalizing source volume. This does not skip on APFS.
        for names in (("Foo", "foo"), ("caf\u00e9", "cafe\u0301")):
            for present in (False, True):
                for apply in (False, True):
                    with self.subTest(
                        names=names, present=present, apply=apply
                    ), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp).resolve()
                        args, entries = self.fixture(
                            root, names[:1], names[1:], present=present
                        )
                        parent = entries[0][1].parent
                        parent.mkdir(exist_ok=True)
                        # An independent native mkdir oracle observes lookup,
                        # without asking the production preflight for a verdict.
                        probe = parent / ".fixture-lookup"
                        probe.mkdir()
                        (probe / names[0]).mkdir()
                        try:
                            (probe / names[1]).mkdir()
                        except FileExistsError:
                            collides = True
                        else:
                            collides = False
                        shutil.rmtree(probe)
                        args.apply = apply
                        if collides:
                            self.assert_refuses_without_mutation(args, root)
                        else:
                            before = harness.tree_digest(root)
                            with redirect_stdout(io.StringIO()):
                                self.assertEqual(harness.sync_global(args), 0)
                            if not apply:
                                self.assertEqual(before, harness.tree_digest(root))
                            else:
                                for source, target in entries:
                                    self.assertEqual(
                                        harness.tree_digest(source),
                                        harness.tree_digest(target),
                                    )

    def test_same_names_in_separate_destination_parents_remain_valid(self):
        for apply in (False, True):
            with self.subTest(apply=apply), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                args, entries = self.fixture(
                    root, ("sample",), ("sample",), shared=False
                )
                args.apply = apply
                before = harness.tree_digest(root)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(harness.sync_global(args), 0)
                if not apply:
                    self.assertEqual(before, harness.tree_digest(root))
                else:
                    for source, target in entries:
                        self.assertEqual(
                            harness.tree_digest(source), harness.tree_digest(target)
                        )
                    self.assertNotEqual(
                        harness.tree_digest(entries[0][1]),
                        harness.tree_digest(entries[1][1]),
                    )

    def test_existing_parent_case_aliases_are_grouped_by_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            parent = root / "parent"
            parent.mkdir()
            alias = root / "PARENT"
            if not alias.exists():
                self.skipTest("host lookup keeps these parent spellings distinct")
            before = harness.tree_digest(root)
            with self.assertRaisesRegex(
                harness.HarnessError, "selected skill roots collide"
            ):
                harness.preflight_selected_skill_roots(
                    [parent / "sample", alias / "sample"], None, [], "fixture"
                )
            self.assertEqual(before, harness.tree_digest(root))

    def test_distinct_sensitive_parents_do_not_merge_because_of_spelling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            SkillTreeFilesystemLookupTests.set_case_sensitive(self, root)
            first, second = root / "Home", root / "home"
            first.mkdir()
            try:
                second.mkdir()
            except FileExistsError:
                self.skipTest("host cannot represent distinct case-sensitive parents")
            before = harness.tree_digest(root)
            harness.preflight_selected_skill_roots(
                [first / "sample", second / "sample"], None, [], "fixture"
            )
            self.assertEqual(before, harness.tree_digest(root))

    def test_only_changed_entries_are_probed_on_the_backup_parent(self):
        names = ("alpha", "beta", "gamma")
        for family in ("codex", "claude"):
            for changed in ((), names[:1], names[:2]):
                for apply in (False, True):
                    with self.subTest(
                        family=family, changed=changed, apply=apply
                    ), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp).resolve()
                        args, entries = self.fixture(
                            root,
                            names if family == "codex" else (),
                            names if family == "claude" else (),
                            present=True,
                        )
                        backup_parent = root / (
                            "codex-home/backups"
                            if family == "codex"
                            else "claude-home/.harness-backups"
                        )
                        backup_parent.mkdir(parents=True)
                        for source, _target in entries:
                            if source.name in changed:
                                (source / "SKILL.md").write_text(
                                    "updated", encoding="utf-8"
                                )
                        real = harness.probe_distinct_skill_names
                        observed = []

                        def record(lookup, scratch, created, probed):
                            if lookup == backup_parent:
                                observed.append(list(probed))
                            return real(lookup, scratch, created, probed)

                        before = harness.tree_digest(root)
                        args.apply = apply
                        with mock.patch.object(
                            harness, "probe_distinct_skill_names", record
                        ), redirect_stdout(io.StringIO()):
                            self.assertEqual(harness.sync_global(args), 0)
                        self.assertEqual(
                            observed, [list(changed)] if len(changed) > 1 else []
                        )
                        if not apply or not changed:
                            self.assertEqual(before, harness.tree_digest(root))

    def test_unused_backup_lookup_failure_cannot_block_identical_skills(self):
        for family in ("codex", "claude"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                names = ("alpha", "beta")
                args, _ = self.fixture(
                    root,
                    names if family == "codex" else (),
                    names if family == "claude" else (),
                    present=True,
                )
                backup_parent = root / (
                    "codex-home/backups"
                    if family == "codex"
                    else "claude-home/.harness-backups"
                )
                backup_parent.mkdir(parents=True)
                real = harness.probe_distinct_skill_names

                def unavailable(lookup, scratch, created, probed):
                    if lookup == backup_parent:
                        raise OSError("fictional unused recovery lookup unavailable")
                    return real(lookup, scratch, created, probed)

                args.apply = True
                before = harness.tree_digest(root)
                with mock.patch.object(
                    harness, "probe_distinct_skill_names", unavailable
                ), redirect_stdout(io.StringIO()):
                    self.assertEqual(harness.sync_global(args), 0)
                self.assertEqual(before, harness.tree_digest(root))


class SkillNameProbeCleanupTests(unittest.TestCase):
    def test_probe_creation_and_removal_are_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor = Path(tmp).resolve()
            made, removed = [], []
            real_make, real_remove = tempfile.mkdtemp, Path.rmdir

            def create(*args, **kwargs):
                result = Path(real_make(*args, **kwargs))
                self.assertTrue(result.is_dir())
                made.append(result)
                return str(result)

            def remove(path):
                self.assertTrue(path.is_dir())
                real_remove(path)
                self.assertFalse(path.exists())
                removed.append(path)

            with mock.patch.object(
                harness.tempfile, "mkdtemp", create
            ), mock.patch.object(Path, "rmdir", remove):
                self.assertFalse(
                    harness.skill_name_chains_alias(
                        anchor, ("left", "nested"), ("right", "nested")
                    )
                )
            self.assertEqual(len(made), 1)
            self.assertEqual(made[0].parent, anchor)
            self.assertEqual(
                removed, [made[0] / "left/nested", made[0] / "left", made[0]]
            )
            self.assertEqual(list(anchor.iterdir()), [])

    def test_failed_cleanup_names_the_retained_probe(self):
        for fail_at in ("child", "scratch"):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as tmp:
                anchor = Path(tmp).resolve()
                made, failed = [], []
                real_make, real_remove = tempfile.mkdtemp, Path.rmdir

                def create(*args, **kwargs):
                    result = Path(real_make(*args, **kwargs))
                    made.append(result)
                    return str(result)

                def remove(path):
                    target = made[0] / "left" if fail_at == "child" else made[0]
                    if path == target:
                        failed.append(path)
                        raise PermissionError("fixture cleanup denied")
                    real_remove(path)

                with mock.patch.object(
                    harness.tempfile, "mkdtemp", create
                ), mock.patch.object(Path, "rmdir", remove):
                    with self.assertRaises(harness.HarnessError) as caught:
                        harness.skill_name_chains_alias(anchor, ("left",), ("right",))
                self.assertEqual(len(made), 1)
                self.assertEqual(len(failed), 1)
                self.assertTrue(made[0].is_dir())
                self.assertIn("probe directory may remain", str(caught.exception))
                self.assertIn(str(made[0]), str(caught.exception))
                self.assertIn(str(failed[0]), str(caught.exception))
                self.assertIsInstance(caught.exception.__cause__, PermissionError)

    def test_creation_failure_does_not_claim_a_retained_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor = Path(tmp).resolve()
            with mock.patch.object(
                harness.tempfile,
                "mkdtemp",
                side_effect=PermissionError("fixture create denied"),
            ):
                with self.assertRaisesRegex(
                    harness.HarnessError, "cannot preflight selected skill roots"
                ) as caught:
                    harness.skill_name_chains_alias(anchor, ("left",), ("right",))
            self.assertNotIn("probe directory may remain", str(caught.exception))
            self.assertEqual(list(anchor.iterdir()), [])


class SkillDestinationOverlapTests(unittest.TestCase):
    """Cross-family destination overlap and absent-parent aliases (#444)."""

    def build(self, root, codex_name, claude_name, skills_home, claude_home):
        config = root / "config"
        for family, source in (
            ("codex", config / "codex/skills" / codex_name),
            ("claude", config / "skills" / claude_name),
        ):
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text(family, encoding="utf-8")
        return SimpleNamespace(
            config_root=str(config),
            codex_home=str(root / "codex-home"),
            claude_home=str(claude_home),
            skills_home=str(skills_home),
            only=[f"skill:{codex_name}", f"claude-skill:{claude_name}"],
            apply=False,
        )

    def assert_refuses(self, args, root, pattern):
        before = harness.tree_digest(root)
        with mock.patch.object(
            harness, "reserve_backup_root", wraps=harness.reserve_backup_root
        ) as reserve, mock.patch.object(
            harness.shutil, "copytree", wraps=shutil.copytree
        ) as copy:
            with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                harness.HarnessError, pattern
            ):
                harness.sync_global(args)
            copy.assert_not_called()
            reserve.assert_not_called()
        self.assertEqual(before, harness.tree_digest(root))

    def nested_case(self, root, order, state):
        """Return args for one nested layout; the inner target sits in the outer."""
        config = root / "config"
        if order == "codex-in-claude":
            claude_home = root / "claude-home"
            claude_home.mkdir()
            outer = claude_home / "skills" / "outer"
            args = self.build(root, "inner", "outer", outer / "skills", claude_home)
            inner = outer / "skills" / "inner"
            outer_source = config / "skills/outer"
            inner_source = config / "codex/skills/inner"
        else:
            skills_home = root / "codex-skills"
            outer = skills_home / "outer"
            claude_home = outer / "claude-home"
            skills_home.mkdir()
            args = self.build(root, "outer", "inner", skills_home, claude_home)
            inner = claude_home / "skills" / "inner"
            outer_source = config / "codex/skills/outer"
            inner_source = config / "skills/inner"
        if state >= 1:
            shutil.copytree(outer_source, outer)
        if state >= 2:
            shutil.copytree(inner_source, inner)
        return args

    def test_nested_cross_family_destinations_refuse_before_mutation(self):
        # State 2 was already refused for unknown paths before overlap preflight.
        # It is a diagnostic control, not proof of an earlier partial-write bug.
        for order in ("codex-in-claude", "claude-in-codex"):
            for state in (0, 1, 2):
                for apply in (False, True):
                    with self.subTest(
                        order=order, state=state, apply=apply
                    ), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp).resolve()
                        args = self.nested_case(root, order, state)
                        args.apply = apply
                        self.assert_refuses(
                            args, root, "selected skill destinations overlap"
                        )

    def test_dry_run_cleanup_failure_names_probe_without_installing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            claude_home = root / "claude-home"
            claude_home.mkdir()
            args = self.build(
                root, "sample", "sample", claude_home / "Skills", claude_home
            )
            before = set(root.rglob("*"))
            made = []
            real_make, real_remove = tempfile.mkdtemp, Path.rmdir

            def create(*args, **kwargs):
                result = Path(real_make(*args, **kwargs))
                made.append(result)
                return str(result)

            def remove(path):
                if made and path == made[0]:
                    raise PermissionError("fixture cleanup denied")
                real_remove(path)

            with mock.patch.object(
                harness.tempfile, "mkdtemp", create
            ), mock.patch.object(Path, "rmdir", remove), mock.patch.object(
                harness, "reserve_backup_root", wraps=harness.reserve_backup_root
            ) as reserve, mock.patch.object(
                harness.shutil, "copytree", wraps=shutil.copytree
            ) as copy, redirect_stdout(
                io.StringIO()
            ):
                with self.assertRaises(harness.HarnessError) as caught:
                    harness.sync_global(args)
                reserve.assert_not_called()
                copy.assert_not_called()
            self.assertEqual(len(made), 1)
            self.assertTrue(made[0].is_dir())
            self.assertIn("probe directory may remain", str(caught.exception))
            self.assertIn(str(made[0]), str(caught.exception))
            self.assertEqual(set(root.rglob("*")), before | {made[0]})
            self.assertFalse((claude_home / "Skills/sample").exists())
            self.assertFalse((claude_home / "skills/sample").exists())

    def test_sibling_and_distinct_targets_are_not_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "a").mkdir()
            before = harness.tree_digest(root)
            harness.preflight_skill_destination_overlap(
                [root / "a" / "x", root / "a" / "y"],
                [root / "a" / "xy", root / "b" / "x", root / "ax"],
            )
            self.assertEqual(before, harness.tree_digest(root))

    def test_mixed_absent_case_alias_parents_refuse_before_mutation(self):
        for apply in (False, True):
            with self.subTest(apply=apply), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                claude_home = root / "claude-home"
                claude_home.mkdir()
                args = self.build(
                    root, "sample", "sample", claude_home / "Skills", claude_home
                )
                # Independent native mkdir oracle, not the production probe.
                probe = claude_home / ".fixture-lookup"
                probe.mkdir()
                (probe / "skills").mkdir()
                try:
                    (probe / "Skills").mkdir()
                except FileExistsError:
                    collides = True
                else:
                    collides = False
                shutil.rmtree(probe)
                args.apply = apply
                if collides:
                    self.assert_refuses(args, root, "selected skill roots collide")
                else:
                    before = harness.tree_digest(root)
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(harness.sync_global(args), 0)
                    if apply:
                        self.assertTrue((claude_home / "Skills/sample").is_dir())
                        self.assertTrue((claude_home / "skills/sample").is_dir())
                    else:
                        self.assertEqual(before, harness.tree_digest(root))

    def test_absent_deep_parent_chains_group_by_native_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "home").mkdir()
            probe = root / "home" / ".fixture-lookup"
            probe.mkdir()
            (probe / "a").mkdir()
            try:
                (probe / "A").mkdir()
            except FileExistsError:
                collides = True
            else:
                collides = False
            shutil.rmtree(probe)
            before = harness.tree_digest(root)
            targets = [root / "home/a/b/sample", root / "home/A/b/sample"]
            if collides:
                with self.assertRaisesRegex(
                    harness.HarnessError, "selected skill roots collide"
                ):
                    harness.preflight_selected_skill_roots(targets, None, [], "fixture")
            else:
                harness.preflight_selected_skill_roots(targets, None, [], "fixture")
            self.assertEqual(before, harness.tree_digest(root))

    def test_distinct_case_sensitive_absent_parents_stay_independent(self):
        for apply in (False, True):
            with self.subTest(apply=apply), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                claude_home = root / "claude-home"
                claude_home.mkdir()
                SkillTreeFilesystemLookupTests.set_case_sensitive(self, claude_home)
                first, second = claude_home / "Skills", claude_home / "skills"
                first.mkdir()
                try:
                    second.mkdir()
                except FileExistsError:
                    self.skipTest(
                        "host cannot represent distinct case-sensitive parents"
                    )
                first.rmdir()
                second.rmdir()
                args = self.build(root, "sample", "sample", first, claude_home)
                args.apply = apply
                before = harness.tree_digest(root)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(harness.sync_global(args), 0)
                if apply:
                    self.assertTrue((first / "sample/SKILL.md").is_file())
                    self.assertTrue((second / "sample/SKILL.md").is_file())
                else:
                    self.assertEqual(before, harness.tree_digest(root))


if __name__ == "__main__":
    unittest.main()
