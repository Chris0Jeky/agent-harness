"""Sync recovery refuses source containment through existing root identities."""

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


class SyncOverlapIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HarnessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def assert_identity_refusal(
        self, args, source, home, alias=None, identity_source=None
    ):
        home.mkdir()
        alias = home if alias is None else alias
        if alias != home:
            alias.mkdir(parents=True)
        before = harness.tree_digest(source), set(source.rglob("*"))
        before_home = set(home.rglob("*"))
        real_stat = Path.stat
        identity_source = source if identity_source is None else identity_source

        def identity(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if path == alias:
                values = list(info)
                source_info = real_stat(identity_source)
                values[stat.ST_DEV] = source_info.st_dev
                values[stat.ST_INO] = source_info.st_ino
                return os.stat_result(values)
            return info

        with (
            mock.patch.object(Path, "stat", identity),
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

    def test_source_descendant_identity_overlap_refuses_before_writes(self):
        for lane in ("bundle", "skill"):
            for recovery in (False, True):
                for apply in (False, True):
                    with self.subTest(lane=lane, recovery=recovery, apply=apply):
                        name = f"descendant-{lane}-{recovery}-{apply}"
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
                        descendant = source / "assets"
                        descendant.mkdir()
                        (descendant / "sentinel.txt").write_text(
                            "untouched", encoding="utf-8"
                        )
                        args.apply = apply
                        alias = home / ".harness-backups" if recovery else home
                        self.assert_identity_refusal(
                            args, source, home, alias, identity_source=descendant
                        )

    def test_source_overlap_does_not_walk_absent_or_file_sources(self):
        root = Path(self.fixture.temp.name)
        source = root / "file"
        source.write_bytes(b"ordinary")
        with mock.patch.object(harness, "skill_tree_entry_kinds") as walk:
            self.assertFalse(harness.sync_source_overlaps_path(source, root / "target"))
            self.assertFalse(
                harness.sync_source_overlaps_path(root / "absent", root / "target")
            )
            walk.assert_not_called()

    def test_live_descendant_identity_refuses_before_backup_or_pruning(self):
        for lane in ("bundle", "skill", "codex"):
            for nested_source in (False, True):
                for apply in (False, True):
                    with self.subTest(
                        lane=lane, nested_source=nested_source, apply=apply
                    ):
                        name = f"live-{lane}-{nested_source}-{apply}"
                        if lane == "bundle":
                            config, home, bin_home, args = (
                                self.fixture.make_bundle_sync_fixture(name)
                            )
                            source = config / "muse/recipes"
                            target = bin_home / "muse-recipes"
                        elif lane == "skill":
                            config, home, args = (
                                self.fixture.make_claude_skill_sync_fixture(name)
                            )
                            source = config / "skills/sample"
                            target = home / "skills/sample"
                        else:
                            source, target, _skills_home, args = (
                                self.fixture.make_sync_global_skill_fixture(name)
                            )
                            home = Path(args.codex_home)
                            args.only = ["skill:sample"]
                        home.mkdir(parents=True, exist_ok=True)
                        descendant = source / "assets"
                        descendant.mkdir()
                        (descendant / "sentinel.txt").write_bytes(b"preserve source")
                        alias = target / "assets"
                        alias.mkdir(parents=True)
                        (target / "SKILL.md").write_bytes(b"old skill")
                        (alias / "sentinel.txt").write_bytes(b"preserve source")
                        identity_source = descendant if nested_source else source
                        real_stat = Path.stat

                        def identity(path, *args, **kwargs):
                            info = real_stat(path, *args, **kwargs)
                            if path == alias:
                                values = list(info)
                                source_info = real_stat(identity_source)
                                values[stat.ST_DEV] = source_info.st_dev
                                values[stat.ST_INO] = source_info.st_ino
                                return os.stat_result(values)
                            return info

                        args.apply = apply
                        before = harness.tree_digest(source), harness.tree_digest(
                            target
                        )
                        with (
                            mock.patch.object(Path, "stat", identity),
                            mock.patch.object(
                                harness,
                                "reserve_backup_root",
                                side_effect=AssertionError("backup reached"),
                            ) as reserve,
                            mock.patch.object(
                                harness,
                                "remove_skill_tree_entry",
                                side_effect=AssertionError("pruning reached"),
                            ) as prune,
                            mock.patch.object(
                                harness.shutil,
                                "copytree",
                                side_effect=AssertionError("copy reached"),
                            ) as copy,
                            redirect_stdout(io.StringIO()),
                        ):
                            with self.assertRaisesRegex(
                                harness.HarnessError, "overlap"
                            ):
                                harness.sync_global(args)
                            reserve.assert_not_called()
                            prune.assert_not_called()
                            copy.assert_not_called()
                        self.assertEqual(
                            before,
                            (harness.tree_digest(source), harness.tree_digest(target)),
                        )

    def test_lexical_overlap_and_absent_disjoint_paths(self):
        root = Path(self.fixture.temp.name)
        self.assertTrue(
            harness.sync_paths_overlap(root / "absent", root / "absent/child")
        )
        self.assertFalse(harness.sync_paths_overlap(root / "one", root / "two"))

    def test_selected_pair_preflight_enumerates_each_tree_once(self):
        names = tuple(f"skill-{index}" for index in range(12))
        _config, home, args = self.fixture.make_claude_skill_sync_fixture(
            "pair-count", names
        )
        for name in names:
            target = home / "skills" / name
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old skill", encoding="utf-8")
        with (
            mock.patch.object(
                harness,
                "sync_tree_directory_paths",
                wraps=harness.sync_tree_directory_paths,
            ) as enumerate_tree,
            mock.patch.object(
                harness,
                "preflight_selected_skill_roots",
                side_effect=RuntimeError("pair preflight complete"),
            ),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(RuntimeError, "pair preflight complete"):
                harness.sync_global(args)
        self.assertEqual(2 * len(names), enumerate_tree.call_count)

    def test_bundle_preflight_enumerates_each_tree_once(self):
        config, home, _bin, _args = self.fixture.make_bundle_sync_fixture(
            "bundle-count"
        )
        components = []
        for index in range(12):
            relative = f"skills/skill-{index}"
            for root in (config, home):
                tree = root / relative
                tree.mkdir(parents=True)
                (tree / "SKILL.md").write_text("skill", encoding="utf-8")
            components.append(
                {
                    "kind": "tree",
                    "source": relative,
                    "destination": {"root": "claude-home", "path": relative},
                }
            )
        manifest = config / harness.SYNC_GLOBAL_BUNDLE_MANIFEST
        payload = json.loads(manifest.read_text("utf-8"))
        payload["bundles"]["muse-runtime"]["components"] = components
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        for _ in range(2):
            with mock.patch.object(
                harness,
                "sync_tree_directory_paths",
                wraps=harness.sync_tree_directory_paths,
            ) as enumerate_tree:
                harness.load_sync_bundle(config, {"claude-home": home}, "muse-runtime")
            self.assertEqual(2 * len(components), enumerate_tree.call_count)

    def test_apply_rechecks_tree_identity_after_staging(self):
        config, home, args = self.fixture.make_claude_skill_sync_fixture(
            "late-identity"
        )
        source = config / "skills/sample"
        target = home / "skills/sample"
        for tree in (source, target):
            (tree / "assets").mkdir(parents=True)
        (target / "SKILL.md").write_bytes(b"old skill")
        before = harness.tree_digest(target)
        real_copytree = harness.shutil.copytree
        real_stat = Path.stat
        staged = False

        def copytree(src, dst, *a, **kw):
            nonlocal staged
            result = real_copytree(src, dst, *a, **kw)
            if Path(src) == source:
                staged = True
            return result

        def identity(path, *a, **kw):
            info = real_stat(path, *a, **kw)
            if staged and path == target / "assets":
                values = list(info)
                source_info = real_stat(source)
                values[stat.ST_DEV] = source_info.st_dev
                values[stat.ST_INO] = source_info.st_ino
                return os.stat_result(values)
            return info

        with (
            mock.patch.object(harness.shutil, "copytree", side_effect=copytree),
            mock.patch.object(Path, "stat", identity),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(harness.HarnessError, "overlap"):
                harness.sync_global(args)
        self.assertTrue(staged)
        self.assertEqual(before, harness.tree_digest(target))

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
