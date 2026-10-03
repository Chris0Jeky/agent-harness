"""Quarantine failure is not proof that a promoted target still exists (#278)."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import unittest
from unittest import mock

import harness
import test_harness as fixtures


class BundleQuarantineDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HarnessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def assert_failed_quarantine(self, *, vanished, present):
        config, home, bin_home, args = self.fixture.make_bundle_sync_fixture(
            f"quarantine-{vanished}-{present}"
        )
        target = home / "tools" / "worker.py"
        old = b"previous worker\x00"
        if present:
            target.parent.mkdir(parents=True)
            target.write_bytes(old)
        source = config / "tools" / "worker.py"
        source_bytes = source.read_bytes()
        real_digest = harness.bundle_component_digest
        real_rename = Path.rename

        def changed_after_promotion(kind, path, label):
            if path == target and label == "installed bundle target":
                if vanished:
                    path.unlink()
                    return None
                return "0" * 64
            return real_digest(kind, path, label)

        def denied_quarantine(path, destination):
            if path == target and Path(destination).parent.name == "unverified":
                if not vanished:
                    raise PermissionError("fictional quarantine refusal")
            return real_rename(path, destination)

        with (
            redirect_stdout(io.StringIO()),
            mock.patch.object(harness, "bundle_component_digest", changed_after_promotion),
            mock.patch.object(Path, "rename", denied_quarantine),
            self.assertRaises(harness.HarnessError) as raised,
        ):
            harness.sync_global(args)
        runs = list((home / ".harness-backups" / "sync-global-bundles").iterdir())
        self.assertEqual(len(runs), 1)
        backup = runs[0] / "backups" / "0000"
        if present:
            self.assertEqual(backup.read_bytes(), old)
        else:
            self.assertFalse(backup.exists())
        self.assertEqual(target.exists(), not vanished)
        if not vanished:
            self.assertEqual(target.read_bytes(), source_bytes)
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertFalse((runs[0] / "receipt.json").exists())
        self.assertFalse((bin_home / "muse-recipes").exists())
        message = str(raised.exception)
        self.assertNotIn("bytes are still live", message)
        self.assertIn("current live state is unverified", message)
        expected_backup = str(backup) if present else "none (previously absent)"
        self.assertIn(f"previous target backup: {expected_backup}", message)
        self.assertIn(f"recovery backups: {runs[0]}", message)

    def test_vanished_target_is_not_reported_as_still_live(self):
        for present in (False, True):
            with self.subTest(present=present):
                self.assert_failed_quarantine(vanished=True, present=present)

    def test_denied_quarantine_preserves_live_bytes_and_backup(self):
        for present in (False, True):
            with self.subTest(present=present):
                self.assert_failed_quarantine(vanished=False, present=present)
