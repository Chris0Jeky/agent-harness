"""Exact-byte managed-agent ownership and replacement regressions (#253)."""

from contextlib import redirect_stdout
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import stat
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

    def test_final_mode_is_on_the_descriptor_when_it_is_flushed(self):
        real_fsync = os.fsync
        observed = []

        def record(descriptor):
            observed.append(stat.S_IMODE(os.fstat(descriptor).st_mode))
            return real_fsync(descriptor)

        for mode in (0o640, 0o444):
            with self.subTest(mode=oct(mode)):
                observed.clear()
                target = self.targets / f"mode-{mode:o}.toml"
                with mock.patch.object(harness.os, "fsync", record):
                    harness.write_managed_codex_file(target, b"model = 'm'\n", mode)
                self.assertEqual(len(observed), 1)
                if os.name == "nt":
                    # Windows reports only the read-only attribute through the mode.
                    self.assertEqual(
                        bool(observed[0] & stat.S_IWRITE), bool(mode & stat.S_IWRITE)
                    )
                else:
                    self.assertEqual(observed[0], mode)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), observed[0])
                self.assertEqual(target.read_bytes(), b"model = 'm'\n")
                os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
        self.assertEqual(list(self.targets.glob(".harness-agent-*")), [])

    def test_alias_target_or_parent_is_refused_before_any_write(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "luna.toml").write_bytes(b"outside bytes")
        try:
            os.symlink(outside / "luna.toml", self.target)
            os.symlink(outside, self.home / "linked", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"host cannot create a symlink: {exc}")
        for path in (self.target, self.home / "linked" / "luna.toml"):
            with self.subTest(path=path):
                with self.assertRaises(harness.HarnessError):
                    harness.write_managed_codex_file(path, b"new agent", 0o644)
        self.assertEqual((outside / "luna.toml").read_bytes(), b"outside bytes")
        self.assertEqual(list(outside.iterdir()), [outside / "luna.toml"])
        self.assertEqual(list(self.targets.glob(".harness-agent-*")), [])

    def test_ownership_record_bytes_are_canonical(self):
        harness.write_managed_codex_agents_state(
            self.state, {"zeta.toml": "b" * 64, "luna.toml": "a" * 64}
        )
        self.assertEqual(
            self.state.read_bytes(),
            (
                '{\n  "schema_version": 1,\n  "agents": {\n'
                f'    "luna.toml": "{"a" * 64}",\n'
                f'    "zeta.toml": "{"b" * 64}"\n'
                "  }\n}\n"
            ).encode("utf-8"),
        )

    def test_ownership_failure_after_agent_replacement_then_retry(self):
        self.target.write_bytes(b"previous agent")
        previous_digest = hashlib.sha256(b"previous agent").hexdigest()
        previous_state = (
            '{"schema_version": 1, "agents": {"luna.toml": "%s"}}\n' % previous_digest
        ).encode("utf-8")
        self.state.write_bytes(previous_state)
        original = harness.write_managed_codex_file

        def fail_ownership(path, content, mode=None):
            if path == self.state:
                raise harness.HarnessError("fictional ownership write failure")
            return original(path, content, mode)

        with mock.patch.object(harness, "write_managed_codex_file", fail_ownership):
            with self.assertRaises(harness.HarnessError):
                self.sync()
        # The agent replacement already happened; ownership still names the old bytes.
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.state.read_bytes(), previous_state)
        agent_backups = list((self.home / "backups").glob("*/agents/luna.toml"))
        self.assertEqual([p.read_bytes() for p in agent_backups], [b"previous agent"])
        state_backups = list(
            (self.home / "backups").glob("*/managed-codex-agents-state.json")
        )
        self.assertEqual([p.read_bytes() for p in state_backups], [previous_state])
        self.assertEqual(list(self.targets.glob(".harness-agent-*")), [])
        self.assertEqual(list(self.home.glob(".harness-agent-*")), [])

        # A plain retry finds the live agent equal to the source and publishes ownership.
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        payload = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["agents"],
            {"luna.toml": hashlib.sha256(self.source.read_bytes()).hexdigest()},
        )
        agent_backups = list((self.home / "backups").glob("*/agents/luna.toml"))
        self.assertEqual([p.read_bytes() for p in agent_backups], [b"previous agent"])


@unittest.skipUnless(os.name == "nt", "NTFS security descriptors are Windows-only")
class ManagedAgentWindowsPublicationTests(unittest.TestCase):
    """Real NTFS DACL, sharing and read-only semantics; no mocked PermissionError."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve() / "agents"
        self.parent.mkdir()
        self.user = current_user_sid()
        # A deliberately shared directory: everyone inherits read access.
        set_dacl(self.parent, f"D:(A;OICI;FA;;;{self.user})(A;OICI;FR;;;WD)", True)
        self.target = self.parent / "luna.toml"

    def dacl(self, path):
        return file_dacl_sddl(path)

    def staging(self):
        return list(self.parent.glob(".harness-agent-*"))

    def test_restricted_destination_keeps_its_protected_dacl(self):
        self.target.write_bytes(b"previous agent")
        set_dacl(self.target, f"D:(A;;FA;;;{self.user})", True)
        before = self.dacl(self.target)
        self.assertNotIn(";WD)", before)
        harness.write_managed_codex_file(self.target, b"new agent", 0o644)
        self.assertEqual(self.target.read_bytes(), b"new agent")
        self.assertEqual(ace_body(self.dacl(self.target)), ace_body(before))
        self.assertTrue(self.dacl(self.target).startswith("D:P"))
        self.assertEqual(self.staging(), [])

    def test_inheriting_destination_keeps_its_explicit_deny(self):
        self.target.write_bytes(b"previous agent")
        set_dacl(self.target, "D:(D;;FR;;;BG)", False)
        before = self.dacl(self.target)
        self.assertIn("(D;;FR;;;BG)", before)
        harness.write_managed_codex_file(self.target, b"new agent", 0o644)
        self.assertEqual(ace_body(self.dacl(self.target)), ace_body(before))
        self.assertEqual(self.target.read_bytes(), b"new agent")

    def test_new_destination_is_owner_only_not_parent_inherited(self):
        harness.write_managed_codex_file(self.target, b"new agent", 0o644)
        self.assertEqual(self.dacl(self.target), f"D:P(A;;FA;;;{self.user})")
        state = self.parent / "state.json"
        harness.write_managed_codex_file(state, b"{}\n")
        self.assertEqual(self.dacl(state), f"D:P(A;;FA;;;{self.user})")

    def test_moved_destination_keeps_its_own_inherited_entries(self):
        # Inherited entries from a narrower former parent must not be recomputed from
        # the shared parent when the staging file is created.
        narrow = self.parent.parent / "narrow"
        narrow.mkdir()
        set_dacl(narrow, f"D:(A;OICI;FA;;;{self.user})", True)
        (narrow / "luna.toml").write_bytes(b"previous agent")
        os.rename(narrow / "luna.toml", self.target)
        before = self.dacl(self.target)
        self.assertNotIn(";WD)", before)
        harness.write_managed_codex_file(self.target, b"new agent", 0o644)
        self.assertEqual(ace_body(self.dacl(self.target)), ace_body(before))
        self.assertNotIn(";WD)", self.dacl(self.target))

    def test_staging_dacl_mismatch_refuses_before_any_byte(self):
        self.target.write_bytes(b"previous agent")
        set_dacl(self.target, f"D:(A;;FA;;;{self.user})", True)
        before = self.dacl(self.target)
        real = harness.windows_file_dacl_descriptor
        broader = real(self.parent)

        def merged(path):
            # Simulate a host that merged the shared parent's entries at creation.
            return broader if path.name.startswith(".harness-agent-") else real(path)

        with mock.patch.object(harness, "windows_file_dacl_descriptor", merged):
            with self.assertRaises(harness.HarnessError):
                harness.write_managed_codex_file(self.target, b"new agent", 0o644)
        self.assertEqual(self.target.read_bytes(), b"previous agent")
        self.assertEqual(self.dacl(self.target), before)
        self.assertEqual(self.staging(), [])

    def test_new_destination_is_owned_by_the_token_user(self):
        harness.write_managed_codex_file(self.target, b"new agent", 0o644)
        self.assertEqual(file_dacl_sddl(self.target, 0x1), f"O:{self.user}")

    def test_no_reader_can_open_the_staging_file_before_replacement(self):
        self.target.write_bytes(b"previous agent")
        real_fsync = os.fsync
        refused = []

        def probe(descriptor):
            for candidate in self.staging():
                # ERROR_SHARING_VIOLATION, not an ACL denial or success.
                refused.append(open_for_read_error(candidate) == 32)
            return real_fsync(descriptor)

        with mock.patch.object(harness.os, "fsync", probe):
            harness.write_managed_codex_file(self.target, b"new agent", 0o644)
        self.assertEqual(refused, [True])
        self.assertEqual(self.target.read_bytes(), b"new agent")

    def test_open_destination_handle_refuses_without_live_change(self):
        self.target.write_bytes(b"previous agent")
        with open(self.target, "rb"):
            with self.assertRaises(harness.HarnessError):
                harness.write_managed_codex_file(self.target, b"new agent", 0o644)
            self.assertEqual(self.staging(), [])
        self.assertEqual(self.target.read_bytes(), b"previous agent")
        harness.write_managed_codex_file(self.target, b"new agent", 0o644)
        self.assertEqual(self.target.read_bytes(), b"new agent")

    def test_read_only_destination_refuses_without_live_change(self):
        self.target.write_bytes(b"previous agent")
        os.chmod(self.target, stat.S_IREAD)
        self.addCleanup(os.chmod, self.target, stat.S_IREAD | stat.S_IWRITE)
        with self.assertRaises(harness.HarnessError):
            harness.write_managed_codex_file(self.target, b"new agent", 0o644)
        self.assertEqual(self.target.read_bytes(), b"previous agent")
        self.assertFalse(self.target.stat().st_mode & stat.S_IWRITE)
        self.assertEqual(self.staging(), [])

    def test_read_only_source_mode_publishes_a_read_only_destination(self):
        harness.write_managed_codex_file(self.target, b"new agent", 0o444)
        self.addCleanup(os.chmod, self.target, stat.S_IREAD | stat.S_IWRITE)
        self.assertEqual(self.target.read_bytes(), b"new agent")
        self.assertFalse(self.target.stat().st_mode & stat.S_IWRITE)
        self.assertEqual(self.staging(), [])


def current_user_sid() -> str:
    """Read the token user SID independently of the helpers under test."""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    advapi.OpenProcessToken.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi.GetTokenInformation.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    )
    advapi.ConvertSidToStringSidW.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    token = ctypes.c_void_p()
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    user = ctypes.create_string_buffer(512)
    needed = ctypes.c_uint32(0)
    try:
        if not advapi.GetTokenInformation(token, 1, user, 512, ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(token)
    text = ctypes.c_void_p()
    if not advapi.ConvertSidToStringSidW(
        ctypes.c_void_p.from_buffer(user).value, ctypes.byref(text)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.wstring_at(text.value)
    finally:
        kernel.LocalFree(text)


def open_for_read_error(path: Path) -> int:
    """Open with full sharing through CreateFileW and return the Win32 error (0 = opened)."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0x80, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        return ctypes.get_last_error()
    kernel.CloseHandle(handle)
    return 0


def file_dacl_sddl(path: Path, information: int = 0x4) -> str:
    """Read a file's DACL as SDDL independently of the helpers under test."""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    advapi.GetFileSecurityW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    )
    buffer = ctypes.create_string_buffer(4096)
    needed = ctypes.c_uint32(0)
    if not advapi.GetFileSecurityW(
        str(path), information, buffer, 4096, ctypes.byref(needed)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    text = ctypes.c_void_p()
    if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        buffer, 1, information, ctypes.byref(text), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.wstring_at(text.value)
    finally:
        kernel.LocalFree(text)


def ace_body(text: str) -> str:
    """Drop the DACL control flags (P, AI) and keep the ordered ACE list."""
    return text[text.index("(") :]


def set_dacl(path: Path, text: str, protected: bool) -> None:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    )
    advapi.GetSecurityDescriptorDacl.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_int),
    )
    advapi.SetNamedSecurityInfoW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    descriptor = ctypes.c_void_p()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        text, 1, ctypes.byref(descriptor), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, dacl, defaulted = ctypes.c_int(), ctypes.c_void_p(), ctypes.c_int()
        if not advapi.GetSecurityDescriptorDacl(
            descriptor,
            ctypes.byref(present),
            ctypes.byref(dacl),
            ctypes.byref(defaulted),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        # PROTECTED_ or UNPROTECTED_DACL_SECURITY_INFORMATION with the DACL itself.
        flags = 0x4 | (0x80000000 if protected else 0x20000000)
        error = advapi.SetNamedSecurityInfoW(
            str(path), 1, flags, None, None, dacl, None
        )
        if error:
            raise ctypes.WinError(error)
    finally:
        kernel.LocalFree(descriptor)
