"""Disposable bundle root, rename-boundary and inspection recovery controls."""

from contextlib import redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import harness
import test_harness as fixtures


class BundlePreflightRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HarnessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def make(self, name, only=None):
        config, home, bin_home, args = self.fixture.make_bundle_sync_fixture(name)
        if only is not None:
            manifest = config / harness.SYNC_GLOBAL_BUNDLE_MANIFEST
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["bundles"]["muse-runtime"]["components"] = [
                component
                for component in payload["bundles"]["muse-runtime"]["components"]
                if component["destination"]["root"] == only
            ]
            manifest.write_text(json.dumps(payload), encoding="utf-8")
        return config, home, bin_home, args

    def invoke(self, args):
        output = io.StringIO()
        with redirect_stdout(output):
            result = harness.sync_global(args)
        self.assertEqual(result, 0)
        return output.getvalue()

    def receipt(self, args):
        text = self.invoke(args)
        return Path(
            next(
                line.removeprefix("bundle receipt: ")
                for line in text.splitlines()
                if line.startswith("bundle receipt: ")
            )
        )

    def link(self, path, destination):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.symlink_to(destination, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlink unavailable: {exc}")

    def assert_refuses_without_writes(self, args, root, message):
        before = harness.tree_digest(root)
        with mock.patch.object(
            harness, "copy_bundle_component", wraps=harness.copy_bundle_component
        ) as copied, mock.patch.object(
            harness, "reserve_backup_root", wraps=harness.reserve_backup_root
        ) as reserved:
            with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                harness.HarnessError, message
            ):
                harness.sync_global(args)
            copied.assert_not_called()
            reserved.assert_not_called()
        self.assertEqual(before, harness.tree_digest(root))

    def test_unused_bin_traversal_does_not_block_claude_only_install(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                config, home, _, args = self.make(f"unused-bin-{apply}", "claude-home")
                args.user_bin_home = str(config.parent / "ignored/../bin")
                args.apply = apply
                try:
                    self.invoke(args)
                except harness.HarnessError as exc:
                    self.fail(f"unused root was inspected: {exc}")
                self.assertEqual((home / "tools/worker.py").exists(), apply)
                self.assertFalse((config.parent / "ignored").exists())

    def test_unused_bin_alias_does_not_block_claude_only_install(self):
        config, home, _, args = self.make("unused-bin-alias", "claude-home")
        external = config.parent / "external"
        external.mkdir()
        alias = config.parent / "bin-link"
        self.link(alias, external)
        args.user_bin_home = str(alias)
        try:
            self.invoke(args)
        except harness.HarnessError as exc:
            self.fail(f"unused bin alias was inspected: {exc}")
        self.assertEqual(list(external.iterdir()), [])
        self.assertTrue((home / "tools/worker.py").is_file())

    def test_selected_bin_traversal_still_refuses(self):
        config, _, _, args = self.make("selected-bin", "user-bin-home")
        args.user_bin_home = str(config.parent / "ignored/../bin")
        self.assert_refuses_without_writes(args, config.parent, "parent traversal")

    def test_bin_only_install_requires_valid_claude_recovery_root_even_in_preview(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                config, _, _, args = self.make(
                    f"required-home-{apply}", "user-bin-home"
                )
                args.claude_home = str(config.parent / "ignored/../claude")
                args.apply = apply
                self.assert_refuses_without_writes(
                    args, config.parent, "parent traversal"
                )

    def test_same_roots_refuse_when_both_are_used(self):
        config, home, _, args = self.make("same-roots")
        args.user_bin_home = str(home)
        self.assert_refuses_without_writes(args, config.parent, "must be distinct")

    def test_unused_same_root_does_not_block_claude_only_install(self):
        _, home, _, args = self.make("same-unused-root", "claude-home")
        args.user_bin_home = str(home)
        try:
            self.invoke(args)
        except harness.HarnessError as exc:
            self.fail(f"unused root affected selection: {exc}")
        self.assertTrue((home / "tools/worker.py").is_file())

    def test_bin_only_rollback_ignores_unused_config_and_claude_root(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                config, _, bin_home, args = self.make(
                    f"rollback-unused-{apply}", "user-bin-home"
                )
                receipt = self.receipt(args)
                args.rollback_receipt = str(receipt)
                args.config_root = str(config.parent / "irrelevant/../config")
                args.claude_home = str(config.parent / "irrelevant/../claude")
                args.apply = apply
                try:
                    self.invoke(args)
                except harness.HarnessError as exc:
                    self.fail(f"unused rollback root was inspected: {exc}")
                self.assertEqual((bin_home / "muse-recipes").exists(), not apply)
                self.assertTrue(receipt.is_file())

    def test_install_preview_rejects_recovery_parent_alias(self):
        config, home, _, args = self.make("backup-alias", "claude-home")
        external = config.parent / "outside"
        external.mkdir()
        self.link(home / ".harness-backups", external)
        args.apply = False
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
            harness.HarnessError, "path alias"
        ):
            harness.sync_global(args)
        self.assertEqual(list(external.iterdir()), [])
        self.assertFalse((home / "tools").exists())

    def test_install_preview_rejects_recovery_parent_overlap(self):
        config, home, _, args = self.make("backup-overlap", "user-bin-home")
        # A non-reserved logical bin root physically aliases the recovery tree.
        args.user_bin_home = str(home / ".harness-backups/sync-global-bundles")
        args.apply = False
        self.assert_refuses_without_writes(args, config.parent, "overlaps")

    def test_rollback_rejects_live_components_inside_its_recovery_directory(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                config, _, bin_home, args = self.make(
                    f"rollback-overlap-{apply}", "user-bin-home"
                )
                receipt = self.receipt(args)
                # A valid receipt relocated beside its live component must not turn
                # that component's containing directory into recovery storage.
                relocated = bin_home / "receipt.json"
                relocated.write_bytes(receipt.read_bytes())
                args.rollback_receipt = str(relocated)
                args.apply = apply
                self.assert_refuses_without_writes(args, config.parent, "overlaps")

    def test_install_cross_device_refuses_before_reserving_or_copying(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                config, _, bin_home, args = self.make(f"install-device-{apply}")
                bin_home.mkdir()
                args.apply = apply
                original_stat = Path.stat

                def another_device(path, *a, **kw):
                    result = original_stat(path, *a, **kw)
                    if path == bin_home:
                        fields = list(result)
                        fields[2] += 1000
                        return os.stat_result(fields)
                    return result

                with mock.patch.object(Path, "stat", another_device):
                    self.assert_refuses_without_writes(
                        args, config.parent, "same-filesystem"
                    )

    def test_rollback_cross_device_refuses_before_mutation(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                config, _, bin_home, args = self.make(f"rollback-device-{apply}")
                args.rollback_receipt = str(self.receipt(args))
                args.apply = apply
                original_stat = Path.stat

                def another_device(path, *a, **kw):
                    result = original_stat(path, *a, **kw)
                    if path == bin_home or path == bin_home / "muse-recipes":
                        fields = list(result)
                        fields[2] += 1000
                        return os.stat_result(fields)
                    return result

                with mock.patch.object(Path, "stat", another_device):
                    self.assert_refuses_without_writes(
                        args, config.parent, "same-filesystem"
                    )

    @unittest.skipUnless(os.name == "posix", "native POSIX second filesystem")
    def test_native_second_filesystem_is_refused_without_cross_volume_copy(self):
        config, home, _, args = self.make("native-second-device")
        alternate = Path("/dev/shm")
        if not alternate.is_dir() or alternate.stat().st_dev == config.stat().st_dev:
            self.skipTest("no writable second filesystem fixture")
        try:
            tmp = tempfile.TemporaryDirectory(prefix="harness-bundle-", dir=alternate)
        except OSError as exc:
            self.skipTest(f"second filesystem unavailable: {exc}")
        self.addCleanup(tmp.cleanup)
        args.user_bin_home = tmp.name
        for apply in (False, True):
            args.apply = apply
            with self.subTest(apply=apply):
                self.assert_refuses_without_writes(
                    args, config.parent, "same-filesystem"
                )
                self.assertEqual(list(Path(tmp.name).iterdir()), [])
                self.assertFalse(home.exists())

    def test_post_promotion_inspection_errors_quarantine_and_restore(self):
        for present in (False, True):
            for exception in (harness.HarnessError, PermissionError):
                with self.subTest(present=present, error=exception.__name__):
                    config, home, _, args = self.make(
                        f"inspection-{present}-{exception.__name__}", "claude-home"
                    )
                    target = home / "tools/worker.py"
                    old = b"previous bytes"
                    if present:
                        target.parent.mkdir(parents=True)
                        target.write_bytes(old)
                    real_digest = harness.bundle_component_digest

                    def unavailable(kind, path, label):
                        if path == target and label == "installed bundle target":
                            raise exception("fictional inspection failure")
                        return real_digest(kind, path, label)

                    with mock.patch.object(
                        harness, "bundle_component_digest", unavailable
                    ), redirect_stdout(io.StringIO()):
                        with self.assertRaises(harness.HarnessError) as caught:
                            harness.sync_global(args)
                    runs = list(
                        (home / ".harness-backups/sync-global-bundles").iterdir()
                    )
                    self.assertEqual(len(runs), 1)
                    quarantined = runs[0] / "unverified/0000"
                    self.assertTrue(quarantined.is_file(), str(caught.exception))
                    self.assertEqual(
                        quarantined.read_bytes(),
                        (config / "tools/worker.py").read_bytes(),
                    )
                    self.assertEqual(target.exists(), present)
                    if present:
                        self.assertEqual(target.read_bytes(), old)
                        self.assertEqual((runs[0] / "backups/0000").read_bytes(), old)
                    self.assertIn("fictional inspection failure", str(caught.exception))
                    self.assertFalse((runs[0] / "receipt.json").exists())

    def test_inspection_error_on_later_component_restores_earlier_component(self):
        config, home, bin_home, args = self.make("later-inspection")
        target = home / "tools/worker.py"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"previous first")
        real_digest = harness.bundle_component_digest

        def unavailable(kind, path, label):
            if path == bin_home / "muse-recipes" and label == "installed bundle target":
                raise harness.HarnessError("fictional tree inspection")
            return real_digest(kind, path, label)

        with mock.patch.object(
            harness, "bundle_component_digest", unavailable
        ), redirect_stdout(io.StringIO()):
            with self.assertRaises(harness.HarnessError):
                harness.sync_global(args)
        self.assertEqual(target.read_bytes(), b"previous first")
        self.assertFalse((bin_home / "muse-recipes").exists())
        runs = list((home / ".harness-backups/sync-global-bundles").iterdir())
        self.assertEqual(
            (runs[0] / "unverified/0001/review.md").read_text(), "new recipe\n"
        )
        self.assertFalse((runs[0] / "receipt.json").exists())

    def test_unavailable_rename_device_is_a_classified_no_write_refusal(self):
        config, home, _, args = self.make("unreadable-device", "claude-home")
        home.mkdir()
        args.apply = False
        real_stat = Path.stat

        def unavailable(path, *a, **kw):
            if path == home:
                raise PermissionError("fictional device inspection failure")
            return real_stat(path, *a, **kw)

        # Baseline may inspect this path through alias validation on Windows;
        # either route must refuse rather than manufacture device equality.
        with mock.patch.object(Path, "stat", unavailable):
            with redirect_stdout(io.StringIO()), self.assertRaises(
                harness.HarnessError
            ):
                harness.sync_global(args)
        self.assertEqual(list(home.iterdir()), [])
        self.assertTrue(config.is_dir())

    def test_quarantine_of_a_target_alias_does_not_touch_the_referent(self):
        config, home, _, args = self.make("quarantine-target-link", "claude-home")
        external = config.parent / "untouched.txt"
        external.write_bytes(b"external bytes")
        target = home / "tools/worker.py"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"old worker")
        probe = config.parent / "probe-link"
        try:
            probe.symlink_to(external)
        except OSError as exc:
            self.skipTest(f"file symlink unavailable: {exc}")
        probe.unlink()
        real_digest = harness.bundle_component_digest

        def replace_with_alias(kind, path, label):
            if path == target and label == "installed bundle target":
                path.unlink()
                path.symlink_to(external)
            return real_digest(kind, path, label)

        with mock.patch.object(
            harness, "bundle_component_digest", replace_with_alias
        ), redirect_stdout(io.StringIO()):
            with self.assertRaises(harness.HarnessError):
                harness.sync_global(args)
        self.assertEqual(external.read_bytes(), b"external bytes")
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_bytes(), b"old worker")
        runs = list((home / ".harness-backups/sync-global-bundles").iterdir())
        self.assertTrue((runs[0] / "unverified/0000").is_symlink())
        self.assertFalse((runs[0] / "receipt.json").exists())

    def test_quarantine_refuses_a_swapped_parent_without_touching_external_bytes(self):
        config, home, _, args = self.make("quarantine-parent-link", "claude-home")
        target = home / "tools/worker.py"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"old worker")
        external = config.parent / "external"
        external.mkdir()
        (external / "worker.py").write_bytes(b"external worker")
        probe = config.parent / "probe-dir-link"
        self.link(probe, external)
        probe.unlink()
        real_digest = harness.bundle_component_digest
        retained = home / "tools-retained"

        def replace_parent(kind, path, label):
            if path == target and label == "installed bundle target":
                path.parent.rename(retained)
                path.parent.symlink_to(external, target_is_directory=True)
            return real_digest(kind, path, label)

        with mock.patch.object(
            harness, "bundle_component_digest", replace_parent
        ), redirect_stdout(io.StringIO()):
            with self.assertRaises(harness.HarnessError) as caught:
                harness.sync_global(args)
        self.assertEqual((external / "worker.py").read_bytes(), b"external worker")
        self.assertEqual(
            (retained / "worker.py").read_bytes(),
            (config / "tools/worker.py").read_bytes(),
        )
        self.assertIn("current live state is unverified", str(caught.exception))
        runs = list((home / ".harness-backups/sync-global-bundles").iterdir())
        self.assertEqual((runs[0] / "backups/0000").read_bytes(), b"old worker")
        self.assertFalse((runs[0] / "receipt.json").exists())

    @unittest.skipUnless(os.name == "posix", "native POSIX undecodable filename")
    def test_undecodable_promoted_tree_name_is_quarantined_and_restores_prior_components(
        self,
    ):
        for present in (False, True):
            with self.subTest(present=present):
                config, home, bin_home, args = self.make(
                    f"unicode-inspection-{present}"
                )
                first = home / "tools/worker.py"
                first.parent.mkdir(parents=True)
                first.write_bytes(b"previous first")
                target = bin_home / "muse-recipes"
                if present:
                    target.mkdir(parents=True)
                    (target / "previous.txt").write_bytes(b"previous tree")
                previous = harness.tree_digest(target)
                source_before = harness.tree_digest(config)
                # Use the host's byte-name API; the digest itself is not mocked.
                raw_name = b"late-\xff.txt"
                probe = os.fsencode(config.parent) + b"/" + raw_name
                try:
                    with open(probe, "wb") as stream:
                        stream.write(b"probe")
                except OSError as exc:
                    if exc.errno == errno.EILSEQ:
                        self.skipTest("filesystem refuses undecodable byte names")
                    raise
                decoded = os.fsdecode(raw_name)
                try:
                    decoded.encode("utf-8")
                except UnicodeEncodeError:
                    pass
                else:
                    os.unlink(probe)
                    self.skipTest("host filename codec decodes every fixture byte")
                os.unlink(probe)
                rename = Path.rename
                injected = []

                def publish_with_late_name(path, destination):
                    result = rename(path, destination)
                    if path.parent.name == "staged" and Path(destination) == target:
                        with open(
                            os.fsencode(target) + b"/" + raw_name, "wb"
                        ) as stream:
                            stream.write(b"late writer bytes")
                        injected.append(True)
                    return result

                with mock.patch.object(Path, "rename", publish_with_late_name):
                    with redirect_stdout(io.StringIO()):
                        try:
                            harness.sync_global(args)
                        except harness.HarnessError as exc:
                            problem = str(exc)
                        except UnicodeError as exc:
                            self.fail(f"inspection escaped recovery: {exc}")
                        else:
                            self.fail("unverified tree was reported installed")
                self.assertEqual(injected, [True])
                self.assertIn("inspection failed", problem)
                self.assertIn("recovery backups:", problem)
                self.assertEqual(first.read_bytes(), b"previous first")
                self.assertEqual(harness.tree_digest(target), previous)
                self.assertEqual(harness.tree_digest(config), source_before)
                runs = list((home / ".harness-backups/sync-global-bundles").iterdir())
                self.assertEqual(len(runs), 1)
                quarantine = runs[0] / "unverified/0001"
                with open(os.fsencode(quarantine) + b"/" + raw_name, "rb") as stream:
                    self.assertEqual(stream.read(), b"late writer bytes")
                self.assertEqual(
                    (quarantine / "review.md").read_bytes(), b"new recipe\n"
                )
                self.assertEqual(
                    (runs[0] / "backups/0000").read_bytes(), b"previous first"
                )
                if present:
                    self.assertEqual(
                        harness.tree_digest(runs[0] / "backups/0001"), previous
                    )
                self.assertFalse((runs[0] / "receipt.json").exists())
