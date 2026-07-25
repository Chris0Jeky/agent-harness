"""PR #22 review: a drifted executable bit must not read as an identical tree.

`tree_digest` hashed only entry kind, path and file contents, so a managed skill
whose helper script had lost its executable bit (source 0755, installed 0644)
digested identically. `same_tree` then made `sync-global --apply` skip the copy
that would have restored the mode, leaving an installed skill that cannot run its
own script.

Only the executable bit is digested: the rest of the mode is umask/filesystem
noise, and Windows reports no meaningful bits, so this test skips there.
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


def write_tree(root: Path, executable: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    script = root / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    mode = 0o755 if executable else 0o644
    os.chmod(script, mode)


@unittest.skipIf(os.name == "nt", "Windows does not model the POSIX executable bit")
class SkillTreeModeDigestTests(unittest.TestCase):
    def test_executable_drift_changes_the_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base / "source", executable=True)
            write_tree(base / "target", executable=False)
            self.assertNotEqual(
                harness.tree_digest(base / "source"),
                harness.tree_digest(base / "target"),
            )
            self.assertFalse(harness.same_tree(base / "source", base / "target"))

    def test_identical_modes_still_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base / "source", executable=True)
            write_tree(base / "target", executable=True)
            self.assertTrue(harness.same_tree(base / "source", base / "target"))

    def test_group_or_other_execute_counts_as_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base / "source", executable=False)
            script = base / "source" / "run.sh"
            os.chmod(script, script.stat().st_mode | stat.S_IXOTH)
            write_tree(base / "target", executable=False)
            self.assertFalse(harness.same_tree(base / "source", base / "target"))


if __name__ == "__main__":
    unittest.main()
