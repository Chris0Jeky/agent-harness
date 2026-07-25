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


if __name__ == "__main__":
    unittest.main()
