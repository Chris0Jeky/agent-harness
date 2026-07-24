"""Floor v1.6.1: literal PowerShell scriptblocks cut in half by segmentation.

`quote_aware_segments_with_operators` treats `;`, `|`, `&` and newline as command
separators even inside a `{ ... }` scriptblock, so a perfectly well-formed literal
block is routinely split across segments. The old brace scanner reported that as
"malformed" and `check()` denied — the single largest false-positive class in the
issue #21 corpus (2,659 unique commands / 3,006 invocations).

`scan_powershell_literal_block` now distinguishes a segmentation artifact
(truncated) from a block that closes more braces than it opens (malformed), and
`powershell_literal_scriptblock_bodies` yields the truncated remainder so the body
is still recursed. See issue #25.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch = load_module("dispatch_block_scan", DISPATCH_PATH)


def stub_resolver(
    args, project_dir, git_globals=None, command_runner=None, deadline=None
):
    """No network during unit tests; treat every remote as private."""
    return False, "unit-test-stub-private"


def check(command: str, tier: int = 1, flags=None):
    tier_cfg = {"tier": tier, "flags": flags or {}}
    project_dir = str(ROOT)
    return dispatch.check(
        command, tier_cfg, project_dir, project_dir, remote_resolver=stub_resolver
    )


class PowershellBlockDepthTests(unittest.TestCase):
    def test_counts_plain_braces(self):
        self.assertEqual(dispatch.powershell_block_depth("{"), 1)
        self.assertEqual(dispatch.powershell_block_depth("}"), -1)
        self.assertEqual(dispatch.powershell_block_depth("{}"), 0)
        self.assertEqual(dispatch.powershell_block_depth("@{Name=$_.Name}"), 0)

    def test_backtick_escaped_braces_are_literal_characters(self):
        self.assertEqual(dispatch.powershell_block_depth("a`{b"), 0)
        self.assertEqual(dispatch.powershell_block_depth("a`}b"), 0)
        self.assertEqual(dispatch.powershell_block_depth("{a`}"), 1)

    def test_trailing_backtick_does_not_overrun(self):
        self.assertEqual(dispatch.powershell_block_depth("`"), 0)
        self.assertEqual(dispatch.powershell_block_depth("{`"), 1)


class ScanPowershellLiteralBlockTests(unittest.TestCase):
    def test_closed_block_reports_token_after_close(self):
        toks = ["ForEach-Object", "{", "$_", "}", "tail"]
        state, index = dispatch.scan_powershell_literal_block(toks, 2, "{")
        self.assertEqual(state, dispatch._BLOCK_CLOSED)
        self.assertEqual(index, 4)
        self.assertEqual(toks[index], "tail")

    def test_segment_truncated_block_is_not_malformed(self):
        toks = ["ForEach-Object", "{", "$i++"]
        state, index = dispatch.scan_powershell_literal_block(toks, 2, "{")
        self.assertEqual(state, dispatch._BLOCK_TRUNCATED)
        self.assertEqual(index, len(toks))

    def test_opening_token_that_over_closes_is_malformed(self):
        state, _index = dispatch.scan_powershell_literal_block(["x"], 0, "}")
        self.assertEqual(state, dispatch._BLOCK_MALFORMED)

    def test_nested_braces_close_at_the_outer_brace(self):
        toks = ["{", "@{", "Name", "=", "$_.Name", "}", "}", "tail"]
        state, index = dispatch.scan_powershell_literal_block(toks, 1, "{")
        self.assertEqual(state, dispatch._BLOCK_CLOSED)
        self.assertEqual(index, 7)


class LiteralScriptblockBodyTests(unittest.TestCase):
    def test_truncated_block_yields_in_segment_remainder(self):
        toks = ["ForEach-Object", "{", "rm", "-rf", "/critical/outside"]
        bodies = dispatch.powershell_literal_scriptblock_bodies(toks)
        self.assertEqual(bodies, ["rm -rf /critical/outside"])

    def test_closed_block_body_is_unchanged(self):
        toks = ["ForEach-Object", "{", "git", "status", "}"]
        self.assertEqual(
            dispatch.powershell_literal_scriptblock_bodies(toks), ["git status"]
        )


class BenignTruncatedBlocksAllowTests(unittest.TestCase):
    """The #21 corpus shapes that regressed into 'malformed'."""

    CASES = (
        "$i=0; Get-Content 'CLAUDE.md' | ForEach-Object { $i++; '{0,4}: {1}' -f $i,$_ }",
        "Get-Content x.txt | ForEach-Object { $i++; Write-Output $i }",
        "@('a','b') | ForEach-Object { $n=(Get-Content $_).Count; Write-Output $n }",
        "gci | %{ $a=1; $b=2 }",
        "Get-ChildItem | ForEach-Object { $_.Name | Write-Output }",
        "Invoke-Command -ScriptBlock { $i++; git status }",
    )

    def test_benign_truncated_blocks_allow(self):
        for command in self.CASES:
            with self.subTest(command=command):
                decision, reason = check(command)
                self.assertEqual(decision, "allow", reason)

    def test_no_command_reports_malformed_scriptblock(self):
        for command in self.CASES:
            with self.subTest(command=command):
                _decision, reason = check(command)
                self.assertNotIn("malformed", reason)


class TruncatedBlockStillDeniesThreatsTests(unittest.TestCase):
    """Truncation must not become a laundering channel for charter shapes."""

    CASES = (
        "1 | ForEach-Object { $i++; rm -rf /critical/outside }",
        "1 | ForEach-Object { rm -rf /critical/outside ; $i++ }",
        "1 | ForEach-Object { echo a; git push --force origin main }",
        "1 | ForEach-Object { $x=1; sudo rm -rf / }",
        "1 | ForEach-Object { echo a; Remove-Item -Recurse -Force C:\\ }",
        "1 | %{ $i++; rm -rf /critical/outside }",
        "1 | ForEach-Object -Process { $i++; rm -rf /critical/outside }",
        'powershell -Command "1 | ForEach-Object { $i++; rm -rf /critical/outside }"',
        "1 | ForEach-Object { rm -rf /critical/outside `}",
        "Invoke-Command -ScriptBlock { $i++; rm -rf /critical/outside }",
    )

    def test_threat_inside_truncated_block_denies(self):
        for command in self.CASES:
            with self.subTest(command=command):
                decision, _reason = check(command)
                self.assertEqual(decision, "deny")


class SplitArgvRejoinTests(unittest.TestCase):
    """A cmdlet's arguments after the block's `}` must stay inspectable.

    Segmentation pushes them into a continuation segment led by `}`, which
    strip_control_prefixes otherwise discards entirely. Every command here was a
    live deny->allow regression found by adversarial review of this slice.
    """

    CASES = (
        "1 | ForEach-Object { $_ ; } -MemberName Delete",
        "1 | ForEach-Object { $_ | Out-Null } -MemberName Delete",
        "1 | ForEach-Object { $_ ; } @args",
        "$sb={ rm -rf /critical/outside }; 1 | ForEach-Object { $_ ; } $sb",
        "Invoke-Command -ScriptBlock { $_ ; } -FilePath payload.ps1",
        "Invoke-Command { $_ ; } ([scriptblock]::Create('rm -rf /critical/outside'))",
    )

    def test_payload_after_split_block_still_denies(self):
        for command in self.CASES:
            with self.subTest(command=command):
                decision, _reason = check(command)
                self.assertEqual(decision, "deny")

    def test_rejoin_stops_once_the_block_closes(self):
        joined = dispatch.complete_scriptblock_argv(
            ["ForEach-Object", "{", "$_"],
            [["}", "-MemberName", "Delete"], ["rm", "-rf", "/critical/outside"]],
        )
        self.assertEqual(
            joined, ["ForEach-Object", "{", "$_", "}", "-MemberName", "Delete"]
        )

    def test_balanced_argv_is_returned_untouched(self):
        toks = ["ForEach-Object", "{", "$_", "}"]
        followers = [["rm", "-rf", "/critical/outside"]]
        self.assertEqual(dispatch.complete_scriptblock_argv(toks, followers), toks)

    def test_unterminated_block_consumes_all_followers(self):
        joined = dispatch.complete_scriptblock_argv(
            ["ForEach-Object", "{", "$_"], [["a"], ["b"]]
        )
        self.assertEqual(joined, ["ForEach-Object", "{", "$_", "a", "b"])


class DynamicPayloadBranchesUnchangedTests(unittest.TestCase):
    """The branches this slice does NOT touch must keep denying."""

    CASES = (
        "$sb={ rm -rf /critical/outside }; 1 | ForEach-Object $sb",
        "$sb={ rm -rf /critical/outside }; 1 | % $sb",
        "$sb={ rm -rf /critical/outside }; 1 | ForEach-Object ($sb)",
        "1 | ForEach-Object -Process $sb",
        "1 | Where-Object -FilterScript $f",
        "Get-ChildItem | ForEach-Object -MemberName Delete",
        "Get-ChildItem | ForEach-Object @args",
        "1 | ForEach-Object ([scriptblock]::Create('rm -rf /critical/outside'))",
        "Invoke-Command -ScriptBlock $sb",
        "Invoke-Command -FilePath .\\payload.ps1",
        "Invoke-Command ([scriptblock]::Create('git push --force origin main'))",
    )

    def test_dynamic_payloads_still_deny(self):
        for command in self.CASES:
            with self.subTest(command=command):
                decision, _reason = check(command)
                self.assertEqual(decision, "deny")


if __name__ == "__main__":
    unittest.main()
