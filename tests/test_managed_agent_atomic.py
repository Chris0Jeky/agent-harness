"""Exact-byte managed-agent ownership and replacement regressions (#253)."""

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import harness


class ManagedAgentAtomicTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config = self.root / "config"
        self.sources = self.config / "codex" / "agents"
        self.sources.mkdir(parents=True)
        self.home = self.root / "codex-home"
        self.targets = self.home / "agents"
        self.targets.mkdir(parents=True)
        self.source = self.sources / "luna.toml"
        self.source.write_bytes(b"model = 'new'\n")
        self.target = self.targets / self.source.name
        self.state = harness.managed_codex_agents_state_path(self.home)
        self.args = SimpleNamespace(
            config_root=str(self.config),
            codex_home=str(self.home),
            claude_home=str(self.root / "claude"),
            skills_home=str(self.root / "skills"),
            only=["codex-agents"],
            apply=True,
        )

    def sync(self):
        with redirect_stdout(io.StringIO()):
            return harness.sync_global(self.args)

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file()
        }

    def test_duplicate_state_keys_and_casefold_names_refuse_before_writes(self):
        digest = "a" * 64
        records = (
            '{"schema_version":1,"schema_version":1,"agents":{}}',
            '{"schema_version":1,"agents":{},"agents":{}}',
            '{"schema_version":1,"agents":{"luna.toml":"%s","luna.toml":"%s"}}'
            % (digest, digest),
            '{"schema_version":1,"agents":{"Luna.toml":"%s","luna.toml":"%s"}}'
            % (digest, digest),
        )
        for apply in (False, True):
            for record in records:
                with self.subTest(apply=apply, record=record):
                    self.args.apply = apply
                    self.state.write_text(record, encoding="utf-8")
                    before = self.snapshot()
                    with self.assertRaises(harness.HarnessError):
                        self.sync()
                    self.assertEqual(self.snapshot(), before)
                    self.assertFalse((self.home / "backups").exists())

    def test_unrelated_entries_are_preserved(self):
        (self.targets / "README.md").write_bytes(b"human notes")
        (self.targets / ".keep").write_bytes(b"keep")
        (self.targets / "cache").mkdir()
        (self.targets / "cache" / "record.bin").write_bytes(b"opaque")
        try:
            result = self.sync()
        except harness.HarnessError as exc:
            self.fail(f"unrelated non-agent entries prevented reconciliation: {exc}")
        self.assertEqual(result, 0)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual((self.targets / "README.md").read_bytes(), b"human notes")
        self.assertEqual((self.targets / ".keep").read_bytes(), b"keep")
        self.assertEqual(
            (self.targets / "cache" / "record.bin").read_bytes(), b"opaque"
        )

    def test_active_replacement_breaks_hardlink_and_preserves_backup(self):
        self.target.write_bytes(b"previous agent")
        other = self.root / "unrelated.toml"
        try:
            os.link(self.target, other)
        except OSError as exc:
            self.skipTest(f"host cannot create a hardlink: {exc}")
        self.assertEqual(self.sync(), 0)
        self.assertEqual(other.read_bytes(), b"previous agent")
        self.assertFalse(self.target.samefile(other))
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        backups = list((self.home / "backups").glob("*/agents/luna.toml"))
        self.assertEqual([p.read_bytes() for p in backups], [b"previous agent"])

    def test_directory_appearing_during_apply_cannot_absorb_source(self):
        self.target.write_bytes(b"previous agent")
        original = Path.mkdir
        injected = False

        def mutate(path, *args, **kwargs):
            nonlocal injected
            result = original(path, *args, **kwargs)
            if path == self.targets and not injected:
                injected = True
                self.target.unlink()
                original(self.target)
                (self.target / "human.txt").write_bytes(b"late directory")
            return result

        with mock.patch.object(Path, "mkdir", mutate):
            with self.assertRaises(harness.HarnessError):
                self.sync()
        self.assertTrue(injected)
        self.assertEqual(list(p.name for p in self.target.iterdir()), ["human.txt"])
        self.assertEqual((self.target / "human.txt").read_bytes(), b"late directory")
        self.assertFalse(self.state.exists())
        backups = list((self.home / "backups").glob("*/agents/luna.toml"))
        self.assertEqual([p.read_bytes() for p in backups], [b"previous agent"])
        self.assertEqual(list(self.targets.glob(".harness-agent-*")), [])

    def test_source_snapshot_binds_installed_bytes_and_ownership_digest(self):
        planned = self.source.read_bytes()
        original = harness.reserve_backup_root

        def mutate(*args, **kwargs):
            self.source.write_bytes(b"model = 'changed after planning'\n")
            return original(*args, **kwargs)

        with mock.patch.object(harness, "reserve_backup_root", mutate):
            self.assertEqual(self.sync(), 0)
        self.assertEqual(self.target.read_bytes(), planned)
        payload = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["agents"]["luna.toml"],
            hashlib.sha256(self.target.read_bytes()).hexdigest(),
        )
        self.assertNotEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_active_flush_failure_leaves_live_bytes_and_recovery_copy(self):
        self.target.write_bytes(b"previous agent")
        with mock.patch.object(
            harness.os, "fsync", side_effect=OSError("fictional flush failure")
        ):
            with self.assertRaises(harness.HarnessError):
                self.sync()
        self.assertEqual(self.target.read_bytes(), b"previous agent")
        self.assertFalse(self.state.exists())
        backups = list((self.home / "backups").glob("*/agents/luna.toml"))
        self.assertEqual([p.read_bytes() for p in backups], [b"previous agent"])
        self.assertEqual(list(self.targets.glob(".harness-agent-*")), [])

    def test_late_edit_to_planned_noop_is_not_recorded_as_owned_bytes(self):
        self.target.write_bytes(self.source.read_bytes())
        original = harness.reserve_backup_root

        def mutate(*args, **kwargs):
            self.target.write_bytes(b"late human edit")
            return original(*args, **kwargs)

        with mock.patch.object(harness, "reserve_backup_root", mutate):
            with self.assertRaises(harness.HarnessError):
                self.sync()
        self.assertEqual(self.target.read_bytes(), b"late human edit")
        self.assertFalse(self.state.exists())

    def test_casefold_equivalent_extension_is_canonicalized(self):
        upper = self.targets / "Luna.TOML"
        upper.write_bytes(b"previous agent")
        self.assertEqual(self.sync(), 0)
        self.assertEqual([p.name for p in self.targets.iterdir()], ["luna.toml"])
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_ownership_write_breaks_hardlink(self):
        original = b'{"schema_version":1,"agents":{}}\n'
        self.state.write_bytes(original)
        other = self.root / "previous-state.json"
        try:
            os.link(self.state, other)
        except OSError as exc:
            self.skipTest(f"host cannot create a hardlink: {exc}")
        harness.write_managed_codex_agents_state(self.state, {"luna.toml": "a" * 64})
        self.assertEqual(other.read_bytes(), original)
        self.assertFalse(self.state.samefile(other))
        self.assertEqual(
            json.loads(self.state.read_text())["agents"], {"luna.toml": "a" * 64}
        )

    def test_ownership_flush_failure_preserves_previous_bytes(self):
        original = b'{"schema_version":1,"agents":{}}\n'
        self.state.write_bytes(original)
        with mock.patch.object(
            harness.os, "fsync", side_effect=OSError("fictional flush failure")
        ):
            with self.assertRaises(harness.HarnessError):
                harness.write_managed_codex_agents_state(
                    self.state, {"luna.toml": "a" * 64}
                )
        self.assertEqual(self.state.read_bytes(), original)
        self.assertEqual(
            set(p.name for p in self.home.iterdir()), {"agents", self.state.name}
        )

    def test_ownership_replace_failure_preserves_previous_bytes(self):
        original = b'{"schema_version":1,"agents":{}}\n'
        self.state.write_bytes(original)
        with mock.patch.object(
            harness.os,
            "replace",
            side_effect=PermissionError("fictional replace failure"),
        ):
            with self.assertRaises(harness.HarnessError):
                harness.write_managed_codex_agents_state(
                    self.state, {"luna.toml": "a" * 64}
                )
        self.assertEqual(self.state.read_bytes(), original)
        self.assertEqual(
            set(p.name for p in self.home.iterdir()), {"agents", self.state.name}
        )
