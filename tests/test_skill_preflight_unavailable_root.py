"""Bounded unavailable-root fault injection; never touch a real drive root."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("harness_preflight_root", ROOT / "harness.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class UnavailableSkillRootTests(unittest.TestCase):
    def fixture(self, root):
        source = root / "source"
        source.mkdir()
        (source / "SKILL.md").write_text("# fictional\n", encoding="utf-8")
        (source / "notes.txt").write_text("preserve\n", encoding="utf-8")
        target = root / "skills" / "nested" / "sample"
        return source, target

    def test_missing_probe_root_refuses_without_repeating_the_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source, target = self.fixture(root)
            before = harness.tree_digest(root)
            missing = set(target.parents)
            actual_exists = Path.exists
            root_reads = 0

            def unavailable(path, *args, **kwargs):
                nonlocal root_reads
                if path in missing:
                    if path.parent == path:
                        root_reads += 1
                        self.assertLessEqual(root_reads, 1, "unbounded root traversal")
                    return False
                return actual_exists(path, *args, **kwargs)

            with mock.patch.object(Path, "exists", unavailable):
                with self.assertRaisesRegex(harness.HarnessError, "available ancestor"):
                    harness.preflight_skill_source_names(source, target)
            self.assertEqual(before, harness.tree_digest(root))
            self.assertFalse(target.parent.exists())

    def test_lost_lookup_root_refuses_and_removes_disposable_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source, target = self.fixture(root)
            before = harness.tree_digest(root)
            missing = {target, *target.parents}
            actual_is_dir = Path.is_dir
            actual_mkdtemp = tempfile.mkdtemp
            lost = False
            root_reads = 0

            def create_probe(*args, **kwargs):
                nonlocal lost
                probe = actual_mkdtemp(*args, **kwargs)
                lost = True
                return probe

            def unavailable(path, *args, **kwargs):
                nonlocal root_reads
                if lost and path in missing:
                    if path.parent == path:
                        root_reads += 1
                        self.assertLessEqual(root_reads, 1, "unbounded lookup traversal")
                    return False
                return actual_is_dir(path, *args, **kwargs)

            with mock.patch.object(Path, "is_dir", unavailable):
                with mock.patch.object(harness.tempfile, "mkdtemp", create_probe):
                    with self.assertRaisesRegex(
                        harness.HarnessError, "available lookup"
                    ):
                        harness.preflight_skill_source_names(source, target)
            self.assertEqual(before, harness.tree_digest(root))
            self.assertFalse(target.parent.exists())

    def test_ordinary_missing_parent_still_uses_an_available_ancestor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source, target = self.fixture(root)
            before = harness.tree_digest(root)
            harness.preflight_skill_source_names(source, target)
            self.assertEqual(before, harness.tree_digest(root))
            self.assertFalse(target.parent.exists())
