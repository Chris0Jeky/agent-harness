"""Bundle transaction faults retain recoverable bytes and name their destinations."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import unittest
from unittest import mock

import harness
import test_harness as fixtures


class BundleTransactionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HarnessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def make(self, name, *, first_present=True):
        config, home, bin_home, args = self.fixture.make_bundle_sync_fixture(name)
        first = home / "tools/worker.py"
        if first_present:
            first.parent.mkdir(parents=True)
            first.write_bytes(b"previous worker\x00")
        second = bin_home / "muse-recipes"
        second.mkdir(parents=True)
        (second / "review.md").write_bytes(b"previous recipe\x00")
        return config, home, first, second, args

    def install(self, args):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, harness.sync_global(args))
        return Path(
            next(
                line.removeprefix("bundle receipt: ")
                for line in output.getvalue().splitlines()
                if line.startswith("bundle receipt: ")
            )
        )

    def recovery_run(self, home):
        runs = list((home / ".harness-backups/sync-global-bundles").iterdir())
        self.assertEqual(1, len(runs))
        self.assertFalse((runs[0] / "receipt.json").exists())
        return runs[0]

    def assert_component_map(self, message, first, second):
        self.assertIn(f"0000 -> {first}", message)
        self.assertIn(f"0001 -> {second}", message)

    def test_second_backup_move_failure_restores_or_preserves_drifted_first(self):
        for first_present, drift in ((False, False), (True, False), (True, True)):
            with self.subTest(first_present=first_present, drift=drift):
                config, home, first, second, args = self.make(
                    f"backup-fault-{first_present}-{drift}",
                    first_present=first_present,
                )
                before_source = harness.tree_digest(config)
                real_rename = Path.rename

                def fail_second_backup(path, destination):
                    if path == second and Path(destination).parent.name == "backups":
                        if drift:
                            first.write_bytes(b"concurrent worker\x00")
                        raise OSError("injected second backup move failure")
                    return real_rename(path, destination)

                with (
                    mock.patch.object(Path, "rename", fail_second_backup),
                    redirect_stdout(io.StringIO()),
                    self.assertRaisesRegex(
                        harness.HarnessError, "second backup move failure"
                    ) as caught,
                ):
                    harness.sync_global(args)
                run = self.recovery_run(home)
                self.assertEqual(first_present, first.exists())
                if first_present:
                    self.assertEqual(
                        b"concurrent worker\x00" if drift else b"previous worker\x00",
                        first.read_bytes(),
                    )
                    self.assertEqual(
                        b"previous worker\x00", (run / "backups/0000").read_bytes()
                    )
                self.assertEqual(
                    b"previous recipe\x00", (second / "review.md").read_bytes()
                )
                self.assertFalse((run / "backups/0001").exists())
                self.assertEqual(before_source, harness.tree_digest(config))
                message = str(caught.exception)
                if drift:
                    self.assertIn("live target drift prevents restore", message)
                self.assertIn(f"recovery backups: {run}", message)
                self.assert_component_map(message, first, second)

    def test_second_promotion_failure_retains_backups_when_copy_restore_fails(self):
        for restore_fails in (False, True):
            with self.subTest(restore_fails=restore_fails):
                config, home, first, second, args = self.make(
                    f"promotion-fault-{restore_fails}"
                )
                before_source = harness.tree_digest(config)
                real_rename = Path.rename
                real_copy = harness.copy_bundle_component

                def fail_second_promotion(path, destination):
                    if path.parent.name == "staged" and Path(destination) == second:
                        raise OSError("injected staged promotion failure")
                    return real_rename(path, destination)

                def copy(kind, source, target):
                    if (
                        restore_fails
                        and source.parent.name == "backups"
                        and target == second
                    ):
                        raise OSError("injected backup copy restore failure")
                    return real_copy(kind, source, target)

                with (
                    mock.patch.object(Path, "rename", fail_second_promotion),
                    mock.patch.object(harness, "copy_bundle_component", copy),
                    redirect_stdout(io.StringIO()),
                    self.assertRaises(harness.HarnessError) as caught,
                ):
                    harness.sync_global(args)
                run = self.recovery_run(home)
                self.assertEqual(b"previous worker\x00", first.read_bytes())
                self.assertEqual(not restore_fails, second.exists())
                if not restore_fails:
                    self.assertEqual(
                        b"previous recipe\x00", (second / "review.md").read_bytes()
                    )
                self.assertEqual(
                    b"previous worker\x00", (run / "backups/0000").read_bytes()
                )
                self.assertEqual(
                    b"previous recipe\x00",
                    (run / "backups/0001/review.md").read_bytes(),
                )
                self.assertEqual(before_source, harness.tree_digest(config))
                message = str(caught.exception)
                self.assertIn(
                    "copy restore failure"
                    if restore_fails
                    else "staged promotion failure",
                    message,
                )
                self.assertIn(f"recovery backups: {run}", message)
                self.assert_component_map(message, first, second)

    def test_changed_moved_backup_is_returned_or_retained_when_undo_fails(self):
        for undo_fails in (False, True):
            with self.subTest(undo_fails=undo_fails):
                _config, home, first, second, args = self.make(
                    f"backup-drift-{undo_fails}"
                )
                real_rename = Path.rename

                def moved_backup_drift(path, destination):
                    destination = Path(destination)
                    if (
                        path.parent.name == "backups"
                        and destination == second
                        and undo_fails
                    ):
                        raise OSError("injected backup undo failure")
                    result = real_rename(path, destination)
                    if path == second and destination.parent.name == "backups":
                        (destination / "review.md").write_bytes(b"late recipe\x00")
                    return result

                with (
                    mock.patch.object(Path, "rename", moved_backup_drift),
                    redirect_stdout(io.StringIO()),
                    self.assertRaises(harness.HarnessError) as caught,
                ):
                    harness.sync_global(args)
                run = self.recovery_run(home)
                self.assertEqual(b"previous worker\x00", first.read_bytes())
                self.assertEqual(not undo_fails, second.exists())
                retained = run / "backups/0001" if undo_fails else second
                self.assertEqual(
                    b"late recipe\x00", (retained / "review.md").read_bytes()
                )
                self.assertEqual(undo_fails, (run / "backups/0001").exists())
                self.assert_component_map(str(caught.exception), first, second)

    def test_receipt_publication_failure_restores_every_installed_component(self):
        _config, home, first, second, args = self.make("receipt-fault")
        with (
            mock.patch.object(
                harness, "write_atomic_json", side_effect=OSError("receipt unavailable")
            ),
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(
                harness.HarnessError, "receipt unavailable"
            ) as caught,
        ):
            harness.sync_global(args)
        run = self.recovery_run(home)
        self.assertEqual(b"previous worker\x00", first.read_bytes())
        self.assertEqual(b"previous recipe\x00", (second / "review.md").read_bytes())
        self.assertEqual(b"previous worker\x00", (run / "backups/0000").read_bytes())
        self.assertEqual(
            b"previous recipe\x00", (run / "backups/0001/review.md").read_bytes()
        )
        self.assert_component_map(str(caught.exception), first, second)

    def test_rollback_promotion_failure_recovers_present_and_absent_targets(self):
        for first_present in (False, True):
            with self.subTest(first_present=first_present):
                _config, _home, first, second, args = self.make(
                    f"rollback-promotion-{first_present}", first_present=first_present
                )
                receipt = self.install(args)
                args.rollback_receipt = str(receipt)
                real_rename = Path.rename

                def fail_second_promotion(path, destination):
                    if path.parent.name == "staged" and Path(destination) == second:
                        raise OSError("injected rollback promotion failure")
                    return real_rename(path, destination)

                with (
                    mock.patch.object(Path, "rename", fail_second_promotion),
                    redirect_stdout(io.StringIO()),
                    self.assertRaisesRegex(
                        harness.HarnessError, "rollback promotion failure"
                    ) as caught,
                ):
                    harness.sync_global(args)
                self.assertEqual(b"new worker\x00", first.read_bytes())
                self.assertEqual(b"new recipe\n", (second / "review.md").read_bytes())
                self.assertEqual(
                    b"previous recipe\x00",
                    (receipt.parent / "backups/0001/review.md").read_bytes(),
                )
                self.assertEqual(
                    first_present, (receipt.parent / "backups/0000").exists()
                )
                recovery = list(receipt.parent.glob("rollback-*"))
                self.assertEqual(1, len(recovery))
                self.assertEqual([], list((recovery[0] / "installed").iterdir()))
                message = str(caught.exception)
                self.assertIn(str(recovery[0] / "installed"), message)
                self.assert_component_map(message, first, second)

    def test_rollback_failure_reports_installed_bytes_when_recovery_is_blocked(self):
        for drift in (False, True):
            with self.subTest(drift=drift):
                _config, _home, first, second, args = self.make(
                    f"rollback-recovery-{drift}"
                )
                receipt = self.install(args)
                args.rollback_receipt = str(receipt)
                real_rename = Path.rename

                def fail_second_and_recovery(path, destination):
                    destination = Path(destination)
                    if path == second and destination.parent.name == "installed":
                        if drift:
                            first.write_bytes(b"concurrent rollback worker\x00")
                        raise OSError("injected rollback move failure")
                    if (
                        not drift
                        and path.parent.name == "installed"
                        and destination == first
                    ):
                        raise OSError("injected installed recovery failure")
                    return real_rename(path, destination)

                with (
                    mock.patch.object(Path, "rename", fail_second_and_recovery),
                    redirect_stdout(io.StringIO()),
                    self.assertRaisesRegex(
                        harness.HarnessError, "rollback move failure"
                    ) as caught,
                ):
                    harness.sync_global(args)
                self.assertEqual(drift, first.exists())
                if drift:
                    self.assertEqual(
                        b"concurrent rollback worker\x00", first.read_bytes()
                    )
                self.assertEqual(b"new recipe\n", (second / "review.md").read_bytes())
                recovery = list(receipt.parent.glob("rollback-*"))
                self.assertEqual(1, len(recovery))
                self.assertEqual(
                    b"new worker\x00", (recovery[0] / "installed/0000").read_bytes()
                )
                self.assertEqual(
                    b"previous worker\x00",
                    (receipt.parent / "backups/0000").read_bytes(),
                )
                message = str(caught.exception)
                self.assertIn(
                    "drift prevents recovery" if drift else "cannot recover", message
                )
                self.assertIn(str(recovery[0] / "installed"), message)
                self.assert_component_map(message, first, second)
