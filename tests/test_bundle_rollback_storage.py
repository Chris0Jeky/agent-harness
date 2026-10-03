"""Rollback receipts retain install's reserved-destination boundary (#278)."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import harness


class BundleRollbackStorageTests(unittest.TestCase):
    def write_component(self, kind, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "tree":
            path.mkdir()
            (path / "payload.txt").write_bytes(payload)
        else:
            path.write_bytes(payload)

    def fixture(self, root, kind, root_name, destination, previous):
        homes = {name: root / name for name in ("claude-home", "user-bin-home")}
        receipt = root / "receipts" / "receipt.json"
        receipt.parent.mkdir()
        ordinary = homes["claude-home"] / "ordinary.txt"
        self.write_component("file", ordinary, b"ordinary installed")
        ordinary_backup = receipt.parent / "backups" / "0"
        self.write_component("file", ordinary_backup, b"ordinary previous")
        target = homes[root_name] / destination
        self.write_component(kind, target, b"reserved installed")
        backup = receipt.parent / "backups" / "1"
        prior = {"state": "absent"}
        if previous:
            self.write_component(kind, backup, b"reserved previous")
            prior = {
                "state": "present",
                "digest": harness.bundle_component_digest(kind, backup, "fixture"),
                "backup": "backups/1",
            }
        payload = {
            "schema_version": 1,
            "operation": "sync-global-bundle",
            "bundle": "muse-runtime",
            "components": [
                {
                    "kind": "file",
                    "source": "ordinary.txt",
                    "destination": {"root": "claude-home", "path": "ordinary.txt"},
                    "installed_digest": harness.bundle_file_digest(ordinary, "fixture"),
                    "previous": {
                        "state": "present",
                        "digest": harness.bundle_file_digest(
                            ordinary_backup, "fixture"
                        ),
                        "backup": "backups/0",
                    },
                },
                {
                    "kind": kind,
                    "source": "sample",
                    "destination": {"root": root_name, "path": destination},
                    "installed_digest": harness.bundle_component_digest(
                        kind, target, "fixture"
                    ),
                    "previous": prior,
                },
            ],
        }
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        args = SimpleNamespace(
            config_root=str(root / "config"),
            claude_home=str(homes["claude-home"]),
            user_bin_home=str(homes["user-bin-home"]),
            rollback_receipt=str(receipt),
            only=["bundle:muse-runtime"],
            apply=False,
        )
        return args, target, backup, ordinary, receipt

    def test_reserved_root_and_descendants_refuse_before_any_rollback(self):
        for kind in ("file", "tree"):
            for root_name in ("claude-home", "user-bin-home"):
                for destination in (".harness-backups", ".harness-backups/nested/item"):
                    for previous in (False, True):
                        for apply in (False, True):
                            with self.subTest(
                                kind=kind,
                                root=root_name,
                                destination=destination,
                                previous=previous,
                                apply=apply,
                            ), tempfile.TemporaryDirectory() as tmp:
                                root = Path(tmp).resolve()
                                args, _, _, _, _ = self.fixture(
                                    root, kind, root_name, destination, previous
                                )
                                args.apply = apply
                                before = harness.tree_digest(root)
                                with mock.patch.object(
                                    harness,
                                    "rollback_sync_bundle",
                                    wraps=harness.rollback_sync_bundle,
                                ) as rollback:
                                    with redirect_stdout(
                                        io.StringIO()
                                    ), self.assertRaisesRegex(
                                        harness.HarnessError,
                                        "receipt destination overlaps recovery storage",
                                    ):
                                        harness.sync_global(args)
                                    rollback.assert_not_called()
                                self.assertEqual(before, harness.tree_digest(root))

    def test_nonreserved_spellings_keep_present_and_absent_rollback(self):
        for kind in ("file", "tree"):
            for root_name in ("claude-home", "user-bin-home"):
                for destination in (
                    "backups/item",
                    ".harness-backups-old/item",
                    "tools/.harness-backups/item",
                ):
                    for previous in (False, True):
                        with self.subTest(
                            kind=kind,
                            root=root_name,
                            destination=destination,
                            previous=previous,
                        ), tempfile.TemporaryDirectory() as tmp:
                            root = Path(tmp).resolve()
                            args, target, backup, ordinary, receipt = self.fixture(
                                root, kind, root_name, destination, previous
                            )
                            before = harness.tree_digest(root)
                            with redirect_stdout(io.StringIO()):
                                self.assertEqual(0, harness.sync_global(args))
                            self.assertEqual(before, harness.tree_digest(root))
                            args.apply = True
                            with redirect_stdout(io.StringIO()):
                                self.assertEqual(0, harness.sync_global(args))
                            self.assertEqual(
                                ordinary.read_bytes(), b"ordinary previous"
                            )
                            if previous:
                                self.assertEqual(
                                    harness.bundle_component_digest(
                                        kind, target, "fixture"
                                    ),
                                    harness.bundle_component_digest(
                                        kind, backup, "fixture"
                                    ),
                                )
                            else:
                                self.assertFalse(target.exists())
                            self.assertTrue(receipt.is_file())
                            self.assertEqual(
                                (receipt.parent / "backups/0").read_bytes(),
                                b"ordinary previous",
                            )

    def test_selector_refusals_leave_receipt_and_live_bytes_untouched(self):
        for selection in (["bundle:muse-runtime", "agents"], ["agents"]):
            with self.subTest(
                selection=selection
            ), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                args, _, _, _, _ = self.fixture(
                    root, "file", "claude-home", "tools/item", True
                )
                args.only = selection
                args.apply = True
                before = harness.tree_digest(root)
                with redirect_stdout(io.StringIO()), self.assertRaises(
                    harness.HarnessError
                ):
                    harness.sync_global(args)
                self.assertEqual(before, harness.tree_digest(root))
