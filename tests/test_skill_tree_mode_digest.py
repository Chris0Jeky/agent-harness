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
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
