"""Sync recovery refuses source containment through existing root identities."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest import mock

import harness
import test_harness as fixtures


class SyncOverlapIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HarnessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def assert_identity_refusal(self, args, source, home, alias=None):
        home.mkdir()
        alias = home if alias is None else alias
        if alias != home:
            alias.mkdir(parents=True)
        before = harness.tree_digest(source), set(source.rglob("*"))
        before_home = set(home.rglob("*"))
        real_samefile = Path.samefile

        def identity(path, other):
            if {path, Path(other)} == {source, alias}:
                return True
            return real_samefile(path, other)

        with (
            mock.patch.object(Path, "samefile", identity),
            mock.patch.object(harness, "reserve_backup_root") as reserve,
            mock.patch.object(harness, "copy_bundle_component") as bundle_copy,
            mock.patch.object(harness.shutil, "copytree") as tree_copy,
            mock.patch.object(harness.tempfile, "mkdtemp") as probe,
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(harness.HarnessError, "overlap"):
                harness.sync_global(args)
            reserve.assert_not_called()
            bundle_copy.assert_not_called()
            tree_copy.assert_not_called()
            probe.assert_not_called()
        self.assertEqual(before, (harness.tree_digest(source), set(source.rglob("*"))))
        self.assertEqual(before_home, set(home.rglob("*")))

    def test_bundle_recovery_identity_overlap_refuses_before_writes(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                config, home, _bin, args = self.fixture.make_bundle_sync_fixture(
                    f"bundle-{apply}"
                )
                manifest = config / harness.SYNC_GLOBAL_BUNDLE_MANIFEST
                payload = json.loads(manifest.read_text("utf-8"))
                components = payload["bundles"]["muse-runtime"]["components"]
                payload["bundles"]["muse-runtime"]["components"] = [components[1]]
                manifest.write_text(json.dumps(payload), encoding="utf-8")
                args.apply = apply
                self.assert_identity_refusal(args, config / "muse/recipes", home)

    def test_claude_skill_identity_overlap_refuses_before_writes(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                config, home, args = self.fixture.make_claude_skill_sync_fixture(
                    f"skill-{apply}"
                )
                args.apply = apply
                self.assert_identity_refusal(args, config / "skills/sample", home)

    def test_recovery_ancestor_identity_overlap_refuses_before_writes(self):
        for lane in ("bundle", "skill"):
            for apply in (False, True):
                with self.subTest(lane=lane, apply=apply):
                    name = f"recovery-{lane}-{apply}"
                    if lane == "bundle":
                        config, home, _bin, args = (
                            self.fixture.make_bundle_sync_fixture(name)
                        )
                        source = config / "muse/recipes"
                    else:
                        config, home, args = (
                            self.fixture.make_claude_skill_sync_fixture(name)
                        )
                        source = config / "skills/sample"
                    args.apply = apply
                    self.assert_identity_refusal(
                        args, source, home, home / ".harness-backups"
                    )

    def test_disjoint_bundle_and_skill_install_still_succeed(self):
        for lane in ("bundle", "skill"):
            with self.subTest(lane=lane):
                if lane == "bundle":
                    config, home, _bin, args = self.fixture.make_bundle_sync_fixture(
                        "normal-bundle"
                    )
                    target = home / "tools/worker.py"
                    source = config / "tools/worker.py"
                else:
                    config, home, args = self.fixture.make_claude_skill_sync_fixture(
                        "normal-skill"
                    )
                    target = home / "skills/sample/SKILL.md"
                    source = config / "skills/sample/SKILL.md"
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(0, harness.sync_global(args))
                self.assertEqual(source.read_bytes(), target.read_bytes())

    def test_lexical_overlap_and_absent_disjoint_paths(self):
        root = Path(self.fixture.temp.name)
        self.assertTrue(
            harness.sync_paths_overlap(root / "absent", root / "absent/child")
        )
        self.assertFalse(harness.sync_paths_overlap(root / "one", root / "two"))

    def test_identity_inspection_errors_are_bounded(self):
        left, right = (
            Path(self.fixture.temp.name) / "left",
            Path(self.fixture.temp.name) / "right",
        )
        left.mkdir()
        right.mkdir()
        real_stat = Path.stat

        def stat(path, *args, **kwargs):
            if path == left:
                raise PermissionError("identity unavailable")
            return real_stat(path, *args, **kwargs)

        for operation, replacement in (
            ("stat", stat),
            (
                "samefile",
                mock.Mock(side_effect=PermissionError("identity unavailable")),
            ),
        ):
            with (
                self.subTest(operation=operation),
                mock.patch.object(Path, operation, replacement),
            ):
                with self.assertRaisesRegex(
                    harness.HarnessError, "identity unavailable"
                ):
                    harness.sync_paths_overlap(left, right)


if __name__ == "__main__":
    unittest.main()
