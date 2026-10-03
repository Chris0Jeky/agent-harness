"""Prepare the bounded PR 436 fixture repair against its exact original blob."""
import hashlib
from pathlib import Path
import subprocess

TARGET = "tests/test_managed_agent_atomic.py"
BASE = "58569535fbcd6554515b79d3b7985d44f86494f0"
ORIGINAL = "f3d86705bea363048e68ca578a18afaf9690d5a1"


def blob_id(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def repair(text):
    replacements = {
        'self.assertEqual(self.dacl(self.target), f"D:P(A;;FA;;;{self.user})")':
        'self.assertEqual(\n            self.dacl(self.target), canonical_sddl(f"D:P(A;;FA;;;{self.user})")\n        )',
        'self.assertEqual(self.dacl(state), f"D:P(A;;FA;;;{self.user})")':
        'self.assertEqual(self.dacl(state), canonical_sddl(f"D:P(A;;FA;;;{self.user})"))',
        'self.assertEqual(file_dacl_sddl(self.target, 0x1), f"O:{self.user}")':
        'self.assertEqual(\n            file_dacl_sddl(self.target, 0x1), canonical_sddl(f"O:{self.user}", 0x1)\n        )',
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise RuntimeError("fixture repair context changed")
        text = text.replace(old, new, 1)
    tests = '''    def test_sddl_oracle_equates_sid_aliases_with_numeric_sids(self):
        for alias, numeric, information in (
            ("O:SY", "O:S-1-5-18", 0x1),
            ("D:P(A;;FA;;;SY)", "D:P(A;;FA;;;S-1-5-18)", 0x4),
        ):
            with self.subTest(information=information):
                self.assertEqual(
                    canonical_sddl(alias, information),
                    canonical_sddl(numeric, information),
                )

    def test_sddl_oracle_retains_owner_acl_flags_rights_and_order(self):
        self.assertNotEqual(canonical_sddl("O:SY", 0x1), canonical_sddl("O:WD", 0x1))
        expected = canonical_sddl("D:P(A;;FA;;;SY)")
        for changed in (
            "D:(A;;FA;;;SY)",
            "D:P(A;;FA;;;WD)",
            "D:P(A;;FR;;;SY)",
            "D:P(D;;FA;;;SY)",
            "D:P(A;ID;FA;;;SY)",
            "D:P(A;;FA;;;SY)(A;;FR;;;WD)",
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(expected, canonical_sddl(changed))
        self.assertNotEqual(
            canonical_sddl("D:P(D;;FR;;;WD)(A;;FA;;;SY)"),
            canonical_sddl("D:P(A;;FA;;;SY)(D;;FR;;;WD)"),
        )

'''
    marker = "    def test_moved_destination_keeps_its_own_inherited_entries(self):"
    if text.count(marker) != 1:
        raise RuntimeError("native test insertion context changed")
    text = text.replace(marker, tests + marker, 1)
    helper = '''def canonical_sddl(text: str, information: int = 0x4) -> str:
    """Round-trip expected SDDL through Win32 without using production helpers.

    Win32 may render a numeric SID as an alias, including LA for the local
    administrator. Keep the complete descriptor comparison, not a spelling test.
    """
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    )
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    )
    descriptor = ctypes.c_void_p()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        text, 1, ctypes.byref(descriptor), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    rendered = ctypes.c_void_p()
    try:
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, information, ctypes.byref(rendered), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.wstring_at(rendered.value)
    finally:
        if rendered.value:
            kernel.LocalFree(rendered)
        kernel.LocalFree(descriptor)


'''
    marker = "def current_user_sid() -> str:"
    if text.count(marker) != 1:
        raise RuntimeError("native helper insertion context changed")
    return text.replace(marker, helper + marker, 1)


if __name__ == "__main__":
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != BASE:
        raise RuntimeError("preparation requires the pinned PR head")
    original = subprocess.check_output(["git", "show", f"HEAD:{TARGET}"])
    if blob_id(original) != ORIGINAL:
        raise RuntimeError("original test blob mismatch")
    candidate = repair(original.decode("utf-8")).encode("utf-8")
    compile(candidate, TARGET, "exec")
    Path(TARGET).write_bytes(candidate)
    print("candidate_file_blob=" + blob_id(candidate))
