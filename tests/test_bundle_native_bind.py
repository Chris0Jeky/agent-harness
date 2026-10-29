"""Real same-device bind-mount coverage; opt in only inside a private namespace."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import harness


def mount_entries(text: str) -> list[tuple[Path, list[str]]]:
    entries = []
    for line in text.splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if not separator or len(fields) < 6 or len(after.split()) < 3:
            raise RuntimeError("invalid /proc mountinfo record")
        mountpoint = re.sub(
            r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4]
        )
        if not mountpoint.startswith("/"):
            raise RuntimeError("mountinfo mountpoint is not absolute")
        entries.append((Path(mountpoint), fields[6:]))
    return entries


def require_private_namespace(current: str, parent: str, mountinfo: str) -> None:
    if not current or not parent or current == parent:
        raise RuntimeError("native bind tests require a separate mount namespace")
    entries = mount_entries(mountinfo)
    if not any(path == Path("/") for path, _ in entries):
        raise RuntimeError("mountinfo has no root mount")
    for _, optional in entries:
        if any(
            field == "unbindable"
            or field.startswith(("shared:", "master:", "propagate_from:"))
            for field in optional
        ):
            raise RuntimeError("native bind tests require recursively private mounts")


class NativeBindSafetyGateTests(unittest.TestCase):
    PRIVATE = "1 0 8:1 / / rw - ext4 /dev/root rw\n"

    def test_unchanged_namespace_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "separate mount namespace"):
            require_private_namespace("mnt:[1]", "mnt:[1]", self.PRIVATE)

    def test_nonprivate_child_mount_is_refused(self):
        for flag in ("shared:1", "master:2", "propagate_from:3", "unbindable"):
            with self.subTest(flag=flag):
                child = f"2 1 8:2 / /tmp rw {flag} - ext4 /dev/data rw\n"
                with self.assertRaisesRegex(RuntimeError, "private mounts"):
                    require_private_namespace(
                        "mnt:[2]", "mnt:[1]", self.PRIVATE + child
                    )

    def test_malformed_mount_table_is_refused(self):
        for mountinfo in ("", "invalid", "1 0 8:1 / /tmp rw - ext4 /dev/root rw"):
            with self.subTest(mountinfo=mountinfo), self.assertRaises(RuntimeError):
                require_private_namespace("mnt:[2]", "mnt:[1]", mountinfo)

    def test_private_mount_table_accepts_and_decodes_mountpoints(self):
        child = r"2 1 8:1 / /tmp/space\040name rw - ext4 /dev/root rw"
        require_private_namespace("mnt:[2]", "mnt:[1]", self.PRIVATE + child)
        self.assertEqual(mount_entries(child)[0][0], Path("/tmp/space name"))


class BundleNativeBindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = os.environ.get("HARNESS_REQUIRE_NATIVE_BIND_MOUNTS")
        if required is None:
            raise unittest.SkipTest(
                "requires the dedicated private Linux mount-namespace CI lane"
            )
        if required != "1" or sys.platform != "linux":
            raise RuntimeError("required native bind mode needs Linux and value 1")
        # CI invokes unshare without --fork: Python's parent remains outside.
        require_private_namespace(
            os.readlink("/proc/self/ns/mnt"),
            os.readlink(f"/proc/{os.getppid()}/ns/mnt"),
            cls.read_mountinfo(),
        )
        cls.mount_command = shutil.which("mount")
        cls.umount_command = shutil.which("umount")
        if not cls.mount_command or not cls.umount_command:
            raise RuntimeError("required native bind mode needs mount and umount")

    @staticmethod
    def read_mountinfo():
        return Path("/proc/self/mountinfo").read_text(
            encoding="utf-8", errors="surrogateescape"
        )

    def setUp(self):
        # Do not use TemporaryDirectory: its finalizer could delete through a
        # mount whose unmount failed. Preserve the fixture in that failure case.
        self.root = Path(tempfile.mkdtemp(prefix="harness-native-bind-")).resolve()
        self.mount_targets = []
        self.addCleanup(self.cleanup_fixture)

    def cleanup_fixture(self):
        for target in reversed(self.mount_targets):
            if target in {path for path, _ in mount_entries(self.read_mountinfo())}:
                subprocess.run(
                    [self.umount_command, "--", str(target)],
                    check=True,
                    timeout=10,
                )
        remaining = {path for path, _ in mount_entries(self.read_mountinfo())}
        if any(target in remaining for target in self.mount_targets):
            raise RuntimeError(f"native mounts remain; preserving fixture {self.root}")
        shutil.rmtree(self.root)

    def bind(self, source, target):
        self.assertTrue(source.is_relative_to(self.root))
        self.assertTrue(target.is_relative_to(self.root))
        target.mkdir(parents=True, exist_ok=True)
        self.assertEqual(source.stat().st_dev, target.stat().st_dev)
        # A timeout can happen after the kernel creates the mount.
        self.mount_targets.append(target)
        subprocess.run(
            [self.mount_command, "--bind", str(source), str(target)],
            check=True,
            timeout=10,
        )
        self.assertIn(
            target, {path for path, _ in mount_entries(self.read_mountinfo())}
        )
        self.assertTrue(source.samefile(target))
        self.assertEqual(
            (source.stat().st_dev, source.stat().st_ino),
            (target.stat().st_dev, target.stat().st_ino),
        )

    def fixture(self, name):
        case = self.root / name
        config = case / "config"
        source = config / "skills"
        (source / "recipes").mkdir(parents=True)
        (source / "empty").mkdir()
        (source / "worker").write_bytes(b"worker\x00\xff\r\n")
        (source / "worker").chmod(0o750)
        (source / "recipes" / "review.md").write_bytes(b"review\n")
        manifest = config / harness.SYNC_GLOBAL_BUNDLE_MANIFEST
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "bundles": {
                        "muse-runtime": {
                            "components": [
                                {
                                    "kind": "tree",
                                    "source": "skills",
                                    "destination": {
                                        "root": "claude-home",
                                        "path": "installed/tool",
                                    },
                                }
                            ]
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        home = case / "claude-home"
        home.mkdir()
        args = SimpleNamespace(
            config_root=str(config),
            claude_home=str(home),
            codex_home=str(case / "codex-home"),
            user_bin_home=str(case / "user-bin-home"),
            skills_home=str(case / "skills-home"),
            apply=False,
            only=["bundle:muse-runtime"],
            rollback_receipt=None,
        )
        return case, source, home, args

    def snapshot(self, root):
        result = {}
        for path in [root, *sorted(root.rglob("*"))]:
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                value = ("directory", stat.S_IMODE(mode), None)
            else:
                self.assertTrue(stat.S_ISREG(mode), f"unexpected entry: {path}")
                value = ("file", stat.S_IMODE(mode), path.read_bytes())
            result[path.relative_to(root).as_posix()] = value
        return result

    def assert_overlap_refused(self, case, source, home, args):
        before = self.snapshot(case)
        # These traps bound a guard regression before self-copy can recurse.
        # Native stat/samefile observations and all overlap checks remain real.
        with contextlib.ExitStack() as stack:
            boundaries = [
                stack.enter_context(
                    mock.patch.object(
                        harness,
                        name,
                        side_effect=AssertionError(f"write boundary reached: {name}"),
                    )
                )
                for name in (
                    "preflight_bundle_destination_lookup",
                    "reserve_backup_root",
                    "copy_bundle_component",
                )
            ]
            with (
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaisesRegex(
                    harness.HarnessError, "bundle source and destination overlap"
                ),
            ):
                harness.sync_global(args)
            for boundary in boundaries:
                boundary.assert_not_called()
        self.assertEqual(self.snapshot(case), before)
        self.assertFalse((source / ".harness-backups").exists())
        self.assertFalse((home / ".harness-backups").exists())

    def test_source_bound_as_home_refuses_absent_destination(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                case, source, home, args = self.fixture(f"home-{apply}")
                self.bind(source, home)
                self.assertFalse((home / "installed" / "tool").exists())
                args.apply = apply
                self.assert_overlap_refused(case, source, home, args)
                self.assertFalse((home / "installed").exists())

    def test_source_bound_as_live_destination_is_refused(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                case, source, home, args = self.fixture(f"target-{apply}")
                self.bind(source, home / "installed" / "tool")
                args.apply = apply
                self.assert_overlap_refused(case, source, home, args)

    def test_disjoint_bound_home_dry_run_and_apply_succeed(self):
        case, source, home, args = self.fixture("disjoint")
        storage = case / "destination-storage"
        storage.mkdir()
        self.bind(storage, home)
        before = self.snapshot(case)
        source_before = self.snapshot(source)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(harness.sync_global(args), 0)
        self.assertEqual(self.snapshot(case), before)
        args.apply = True
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(harness.sync_global(args), 0)
        self.assertEqual(self.snapshot(source), source_before)
        self.assertEqual(self.snapshot(home / "installed" / "tool"), source_before)
        self.assertEqual(self.snapshot(storage / "installed" / "tool"), source_before)
        receipts = list(
            (home / ".harness-backups" / "sync-global-bundles").glob("*/receipt.json")
        )
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())["bundle"], "muse-runtime")
