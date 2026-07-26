"""Cross-product coverage for command prefixes that must not hide the head."""

from __future__ import annotations

import importlib.util
import shlex
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch = load_module(
    "dispatch_command_prefixes", ROOT / "templates" / "hooks" / "dispatch.py"
)
smoke = load_module(
    "smoke_command_prefixes", ROOT / "templates" / "hooks" / "smoke_test.py"
)
floor_environment = load_module(
    "floor_environment_command_prefixes", ROOT / "tests" / "floor_environment.py"
)


def private_remote(*_args, **_kwargs):
    """Keep parser tests offline; the prefix must not change remote privacy."""
    return False, "test-private"


def decide(command: str, tier: int = 1, flags: dict | None = None):
    """Decide `command` with no inherited Git launch configuration.

    A prefix expectation that depends on the host's own Git helpers is not an
    expectation about prefixes; `tests/floor_environment.py` owns that isolation
    for every suite so the set cannot drift per file.
    """
    return floor_environment.hermetic_check(
        dispatch,
        command,
        {"tier": tier, "flags": flags or {}},
        str(ROOT),
        str(ROOT),
        remote_resolver=private_remote,
    )


class CommandHeadPrefixTests(unittest.TestCase):
    def test_leading_redirects_and_stop_parsing_reveal_the_real_head(self):
        cases = (
            (["2", ">&", "1", "rm", "-rf", "/critical/outside"], "rm"),
            ([">", "/dev/null", "sudo", "id"], "sudo"),
            (["2", ">", "err", "git", "push", "--force"], "git"),
            (["&>", "out", "rm", "-rf", "/critical/outside"], "rm"),
            ([">&", "1", "git", "push", "--force"], "git"),
            (["--%", "rm", "-rf", "/critical/outside"], "rm"),
            (
                ["FOO=bar", "2", ">", "err", ">", "out", "sudo", "id"],
                "sudo",
            ),
        )
        for argv, expected in cases:
            with self.subTest(argv=argv):
                self.assertEqual(dispatch.command_head(argv)[0], expected)

    def test_redirects_after_the_head_do_not_replace_it(self):
        self.assertEqual(
            dispatch.command_head(["echo", ">", "out", "rm", "-rf", "/"])[0],
            "echo",
        )

    def test_a_leading_process_substitution_is_not_a_redirect_prefix(self):
        self.assertEqual(dispatch.command_head(["<", "(printf", "x)", "tail"])[0], "<")

    def test_process_substitution_operand_is_consumed_whole(self):
        # shlex splits a multi-word producer across tokens; consuming a fixed
        # count lands the head inside the substitution.
        cases = (
            (["<", "<", "(git", "show", "HEAD:file)", "diff", "-"], "diff"),
            (["<", "<", "(printf", "x)", "tail"], "tail"),
            (["<", "<", "(cat", "(nested", "a)", "b)", "sort"], "sort"),
        )
        for argv, expected in cases:
            with self.subTest(argv=argv):
                self.assertEqual(dispatch.command_head(argv)[0], expected)

    def test_unterminated_process_substitution_is_undecidable(self):
        # No balancing `)`: the operand's extent is unknown, so no token can be
        # trusted as the executable. Resolving the operator as the head would be
        # an ALLOW (`<` matches no rule), not the conservative answer.
        self.assertIsNone(dispatch.process_substitution_end(["(git", "show"], 0))
        self.assertEqual(
            dispatch.leading_redirection_end(["<", "<", "(git", "show"], 0),
            dispatch._UNTERMINATED_REDIRECTION_OPERAND,
        )
        self.assertEqual(
            dispatch.command_head(["<", "<", "(git", "show"])[0],
            dispatch._UNDELIMITED_REDIRECTION,
        )

    def test_undelimited_operand_denies_instead_of_hiding_the_head(self):
        # No provenance survives a BACKSLASH-escaped paren -- POSIX shlex
        # consumes the escape and the token is byte-identical to a bare `(` --
        # so the operand's extent stays unknown. Every head after it is a guess;
        # deny rather than run whichever one we picked.
        for command in (
            r"< <(echo \( ) rm -rf ~",
            r"< <(printf \( ) git status",
            "< <(git show",
        ):
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny", reason)
                self.assertIn("delimit", reason)

    def test_a_quoted_paren_no_longer_unbalances_the_operand(self):
        # A paren restored from a QUOTED span is DATA to the shell, and the
        # tokenizer now masks it so the balance walk stops counting it as
        # syntax. The operand really does close at the bare `)`, so the real
        # head is reachable -- in BOTH directions.
        for command, expected in (
            ("< <(echo '(' ) rm -rf ~", "deny"),
            ("< <(echo '(' ) git push --force origin main", "deny"),
            ("< <(printf '(' ) sudo id", "deny"),
            # ... and these are the false positives the old count produced.
            ("< <(printf '(' ) git status", "allow"),
            ("< <(echo '(' ) cat -", "allow"),
        ):
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, expected, reason)

    def test_a_quoted_paren_cannot_close_the_operand_early(self):
        # The bypass this closes: the quoted `)` closed the substitution before
        # the real one, `harmless` was resolved as the head, and the quoted
        # `'git'` was masked out of the sanitized pass. The second spelling
        # balances the remainder, which defeats any "did the rest go negative"
        # heuristic -- only real provenance answers it.
        for command in (
            "< <(printf \")x\" harmless) 'git' push --force origin main",
            '< <(printf ")" harmless "(" ) \'git\' push --force origin main',
            "< <(printf \")x\" harmless) 'rm' -rf /critical/outside",
        ):
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny", reason)

    def test_balanced_process_substitutions_still_resolve_the_head(self):
        # The deny above must stay scoped to the undelimited case; an ordinary
        # process substitution keeps exposing the real executable.
        self.assertEqual(decide("< <(git show HEAD:file) diff -")[0], "allow")
        self.assertEqual(decide("< <(printf x) sort -u")[0], "allow")
        self.assertEqual(decide("< <(git show HEAD:file) rm -rf ~")[0], "deny")


class PrefixCrossProductTests(unittest.TestCase):
    PREFIXES = (
        "2>&1 ",
        ">/dev/null ",
        "2>agent-harness-prefix.err ",
        "&>agent-harness-prefix.out ",
        ">&1 ",
        # Bash's brace-named descriptor: `{fd}>file` truncates the file and
        # stores the descriptor in `$fd`; the head is still the word after it.
        "{harness_fd}>agent-harness-prefix.out ",
        "HARNESS_PREFIX=1 ",
        # Bash's APPEND assignment is a command-scoped prefix too, and `_ASSIGN`
        # used to match only `=`, so this spelling stood as the head.
        "HARNESS_PREFIX+=1 ",
        "--% ",
    )

    def test_every_direct_deny_stays_denied_behind_each_prefix(self):
        eligible = 0
        for command, tier, flags, expected in smoke.CASES:
            if expected != "deny":
                continue
            eligible += 1
            with self.subTest(
                prefix="<direct>", command=command, tier=tier, flags=flags
            ):
                decision, reason = decide(command, tier, flags)
                self.assertEqual(decision, "deny", reason)
            for prefix in self.PREFIXES:
                with self.subTest(
                    prefix=prefix, command=command, tier=tier, flags=flags
                ):
                    decision, reason = decide(prefix + command, tier, flags)
                    self.assertEqual(decision, "deny", reason)
        self.assertGreater(eligible, 1000)


class BraceDescriptorPrefixTests(unittest.TestCase):
    """`{name}>file` is a redirection, not a PowerShell script block."""

    def test_brace_descriptor_exposes_the_head(self):
        for command in (
            "{fd}>out git push --force origin main",
            "{fd}>>out git push --force origin main",
            "{fd}>out rm -rf /critical/outside",
            "{my_fd2}>out sudo id",
        ):
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "deny")

    def test_brace_descriptor_target_is_still_judged(self):
        for command in (
            "{fd}>'.env' true",
            '{fd}>".env" true',
            "{fd}<>'.env' true",
            "{fd}>.env true",
        ):
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny", reason)

    def test_a_script_block_no_longer_swallows_what_follows_it(self):
        # The unwrap replaced the command with the block body and DROPPED any
        # non-separator suffix, so everything after the brace run went
        # uninspected.  Same hole the brace-descriptor bypass rode in on.
        for command in (
            "{ echo hi } rm -rf /critical/outside",
            "{ echo hi } git push --force origin main",
        ):
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "deny")

    def test_ordinary_script_blocks_keep_their_verdicts(self):
        self.assertEqual(decide("{ echo hi }")[0], "allow")
        self.assertEqual(decide("{ echo hi } | Out-Null")[0], "allow")
        self.assertEqual(decide("& { git push --force origin main }")[0], "deny")
        self.assertEqual(decide("{ rm -rf /critical/outside }")[0], "deny")

    def test_brace_expansion_is_not_read_as_a_descriptor(self):
        # A descriptor name is a shell identifier; brace EXPANSION never is.
        for token in ("{a,b}", "{1..3}", "{}"):
            with self.subTest(token=token):
                self.assertIsNone(
                    dispatch._REDIRECTION_DESCRIPTOR_TOKEN.fullmatch(token)
                )
        self.assertIsNotNone(dispatch._REDIRECTION_DESCRIPTOR_TOKEN.fullmatch("{fd}"))


class LiteralRedirectionOperatorTests(unittest.TestCase):
    """A QUOTED operator in head position is a command name, not syntax.

    `'<' input rm -rf /critical/outside` asks the shell to execute a program
    called `<`; the delete never runs, so denying it is a pure false positive on
    a floor whose measured defect is over-blocking. Only `>` and `>>` were
    protected, and the placeholder encoded len(value), which cannot tell `>|`
    from `>&` from `&>` -- the constraint issue #74 records.
    """

    OPERATORS = ("<", ">", ">>", ">|", ">&", "&>", "&>>", "<>", "<&", "<<", "<<<")

    def test_a_quoted_operator_head_is_inert(self):
        for operator in self.OPERATORS:
            for command in (
                f"'{operator}' input rm -rf /critical/outside",
                f"'{operator}' out git push --force origin main",
                f'"{operator}" out git push --force origin main',
                f"'{operator}'out git push --force origin main",
            ):
                with self.subTest(command=command):
                    decision, reason = decide(command)
                    self.assertEqual(decision, "allow", reason)

    def test_every_operator_gets_a_distinct_marker(self):
        markers = [
            dispatch._LITERAL_REDIRECT_MARKERS[operator] for operator in self.OPERATORS
        ]
        self.assertEqual(len(set(markers)), len(markers))

    def test_quoted_operator_marker_round_trips_through_child_text(self):
        values = (*self.OPERATORS, "2>", "9>|", "{fd}>&")
        for value in values:
            with self.subTest(value=value):
                parent = dispatch.quote_aware_segments(f'"{value}"')[0][0]
                self.assertIn("__HARNESS_LITERAL_REDIRECT_", parent)
                expected = dispatch.restore_literal_redirect_markers(parent)
                for _generation in range(2):
                    child_text = dispatch.join_child_argv([parent])
                    child = dispatch.quote_aware_segments(child_text)[0][0]
                    self.assertEqual(
                        dispatch.restore_literal_redirect_markers(child), expected
                    )
                    parent = child

    def test_quoted_operator_option_value_survives_every_child_rejoin(self):
        wrappers = (
            "taskset -c 0 <CMD>",
            "flock /tmp/floor.lock <CMD>",
            "watch -x <CMD>",
            "wsl <CMD>",
            "call <CMD>",
            "taskset -c 0 wsl <CMD>",
            "1 | ForEach-Object { <CMD> }",
            "Start-Job -ScriptBlock { <CMD> }",
            "Start-ThreadJob -ScriptBlock { <CMD> }",
            "Start-Job -ScriptBlock { Start-ThreadJob -ScriptBlock { <CMD> } }",
        )
        for operator in (*self.OPERATORS, "2>", "9>|", "{fd}>&"):
            payload = f'curl -q -o "{operator}" .env https://example.invalid/file'
            self.assertEqual(decide(payload)[0], "allow")
            for template in wrappers:
                command = template.replace("<CMD>", payload)
                with self.subTest(operator=operator, command=command):
                    decision, reason = decide(command)
                    self.assertEqual(decision, "allow", reason)

    def test_quoted_operator_keeps_an_adjacent_suffix_inert(self):
        wrappers = (
            "taskset -c 0 <CMD>",
            "flock /tmp/floor.lock <CMD>",
            "watch -x <CMD>",
            "wsl <CMD>",
            "1 | ForEach-Object { <CMD> }",
            "Start-Job -ScriptBlock { <CMD> }",
            "Start-ThreadJob -ScriptBlock { <CMD> }",
        )
        for suffix in ("foo$bar", "foo`bar", 'foo"bar'):
            payload = (
                'curl -q -o ">"' + shlex.quote(suffix) + " .env "
                "https://example.invalid/file"
            )
            self.assertEqual(decide(payload)[0], "allow")
            for template in wrappers:
                command = template.replace("<CMD>", payload)
                with self.subTest(suffix=suffix, command=command):
                    decision, reason = decide(command)
                    self.assertEqual(decision, "allow", reason)

        for suffix in ("foo", "foo$bar", "foo`bar"):
            command = (
                'cmd /d /c curl -q -o ">"' + suffix + " .env "
                "https://example.invalid/file"
            )
            with self.subTest(cmd_suffix=suffix):
                decision, reason = decide(command)
                self.assertEqual(decision, "allow", reason)

    def test_quoted_operator_option_value_survives_start_process_argv(self):
        for operator in (*self.OPERATORS, "2>", "9>|", "{fd}>&"):
            command = (
                "Start-Process curl -ArgumentList "
                f"'-q','-o', \"{operator}\", '.env',"
                "'https://example.invalid/file'"
            )
            with self.subTest(operator=operator):
                decision, reason = decide(command)
                self.assertEqual(decision, "allow", reason)

    def test_eval_restores_quoted_operator_argv_as_program_syntax(self):
        for operator in (">", ">>", ">|", ">&", "&>", "&>>", "<>", "2>", "{fd}>"):
            command = f'eval "{operator}" .env'
            with self.subTest(operator=operator):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny", reason)
                self.assertIn("secret-looking file", reason)
        self.assertEqual(decide('eval "<" .env')[0], "allow")

    def test_watch_default_reparses_source_but_exec_preserves_direct_argv(self):
        for payload in (
            "git push --force origin main",
            "rm -rf /critical/outside",
            "echo x > .env",
        ):
            with self.subTest(payload=payload):
                self.assertEqual(decide(f'watch "{payload}"')[0], "deny")
                self.assertEqual(decide(f'watch -x "{payload}"')[0], "allow")
        self.assertEqual(decide('watch echo x ">" .env')[0], "deny")
        self.assertEqual(decide("watch -x git push --force origin main")[0], "deny")
        self.assertEqual(decide("watch -q 2 git push --force origin main")[0], "deny")
        self.assertEqual(decide("watch --equexit 2 git status")[0], "allow")

    def test_cmd_reparse_preserves_double_quoted_operator_data(self):
        for operator in (*self.OPERATORS, "2>", "9>|", "{fd}>&"):
            payload = f'curl -q -o "{operator}" .env https://example.invalid/file'
            for template in ("cmd /d /c <CMD>", "cmd /d /c cmd /d /c <CMD>"):
                command = template.replace("<CMD>", payload)
                with self.subTest(operator=operator, command=command):
                    decision, reason = decide(command)
                    self.assertEqual(decision, "allow", reason)
        # cmd.exe does not treat single quotes as quoting. Restoring that operator as
        # syntax keeps the conservative write reading instead of granting POSIX rules.
        self.assertEqual(decide("cmd /d /c echo x '>' .env")[0], "deny")

    def test_a_typed_marker_cannot_be_forged(self):
        markers = (
            *dispatch._LITERAL_REDIRECT_MARKERS.values(),
            dispatch._CMD_DOUBLE_QUOTED_REDIRECT_MARK,
            dispatch._CMD_DOUBLE_QUOTED_REDIRECT_END,
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, dispatch.scrub_internal_markers(marker))

    def test_the_bare_operator_still_denies(self):
        # The relaxation is scoped to QUOTED text; every bare spelling that the
        # prefix gate was built for keeps its verdict.
        for operator in ("<", ">", ">>", "&>", "&>>", ">|", "<>"):
            with self.subTest(operator=operator):
                self.assertEqual(
                    decide(f"{operator} out git push --force origin main")[0], "deny"
                )
        self.assertEqual(decide("> '.env' echo hi")[0], "deny")
        self.assertEqual(decide("1>'.env' true")[0], "deny")


class AssignmentPrefixPolicyTests(unittest.TestCase):
    def test_exposed_shell_keeps_bash_env_policy(self):
        decision, reason = decide("HARNESS_PREFIX=1 BASH_ENV=/tmp/opaque bash -c :")
        self.assertEqual(decision, "deny")
        self.assertIn("BASH_ENV", reason)

    def test_assignment_looking_argument_remains_data(self):
        self.assertEqual(decide("Write-Output GIT_CONFIG_COUNT=1")[0], "allow")


class AggregateConfigRedirectTests(unittest.TestCase):
    def test_aggregate_redirects_poison_a_later_push(self):
        for operator in ("&>", "&>>", ">&"):
            command = f"echo x {operator} .git/config; git push origin"
            with self.subTest(operator=operator):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny")
                self.assertIn("push-config-unverifiable", reason)


class DangerousPrefixTests(unittest.TestCase):
    """The prefix itself can carry the irreversible act.

    Stripping the leading redirection to expose the head must not also discard
    the redirect target.  The argv rule is the only check that sees an
    inert-QUOTED target, because the whole-command text scan runs on
    ``strip_quotes`` output where ``'.env'`` is already a placeholder.
    """

    SECRET_TARGETS = ("'.env'", '".env"', "'~/.ssh/id_rsa'", '"my.credentials"')
    WRITE_OPERATORS = ("> ", ">> ", "2> ", "2>> ", "&> ", "&>> ", ">| ", ">&")

    def test_quoted_secret_redirect_in_the_prefix_is_denied(self):
        for target in self.SECRET_TARGETS:
            for operator in self.WRITE_OPERATORS:
                for tail in ("", " echo hi", " git status"):
                    command = f"{operator}{target}{tail}"
                    with self.subTest(command=command):
                        decision, reason = decide(command)
                        self.assertEqual(decision, "deny", reason)
                        self.assertIn("secret-looking file", reason)

    def test_split_descriptor_spelling_is_denied(self):
        for command in ("2 > '.env' true", "2 >> '.env' true", "* > '.env' true"):
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny", reason)

    def test_bare_secret_redirect_in_the_prefix_stays_denied(self):
        for command in ("> .env echo hi", "2>.env git status", "&>.env echo hi"):
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "deny")

    def test_read_write_open_of_a_secret_file_is_denied(self):
        # `n<>file` opens for READ AND WRITE and creates the file when absent.
        # Its `<` spelling is the only thing about it that looks read-only, and
        # the quoted target is invisible to the whole-command text scan.
        for command in (
            "1<> '.env' echo x",
            "<> '.env' echo x",
            "1<>'.env' echo x",
            '2<> ".env" git status',
            "<> '~/.ssh/id_rsa' true",
        ):
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny", reason)
                self.assertIn("secret-looking file", reason)

    def test_read_write_open_of_an_ordinary_file_stays_allowed(self):
        for command in ("1<> build.log echo x", "<> 'notes.txt' git status"):
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "allow")

    def test_descriptor_duplication_is_not_a_write_target(self):
        # Numeric operands duplicate in every supported shell. A non-numeric word is
        # dialect-dependent: Bash rejects it, while zsh opens it as a file.
        for argv in (
            ["2>&1", "git", "status"],
            ["2", ">&", "1", "git", "status"],
            [">&", "2", "git", "status"],
            ["2>&-", "git", "status"],
            ["1<&0", "git", "status"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(dispatch.leading_redirection_write_targets(argv), [])
        # Unknown shell syntax stays conservative; an explicit Bash parse may classify
        # the same word as an ambiguous duplication operand.
        self.assertEqual(
            dispatch.leading_redirection_write_targets(["2>&out.log", "git", "status"]),
            ["out.log"],
        )
        self.assertEqual(
            dispatch.leading_redirection_write_targets(
                ["2>&out.log", "git", "status"],
                descriptor_words_are_files=False,
            ),
            [],
        )
        for command in (
            "2>&1 git status",
            "2 >& 1 git status",
            "2>&- git status",
            "bash -c \"2>&'.env' git status\"",
            "bash -c \"{fd}>&'.env' git status\"",
            'bash -c "{fd}>&.env git status"',
        ):
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "allow")
        self.assertEqual(decide("2>&'.env' git status")[0], "deny")
        self.assertEqual(decide("zsh -c \"2>&'.env' git status\"")[0], "deny")
        self.assertEqual(decide("{fd}>&'.env' git status")[0], "deny")
        self.assertEqual(decide("zsh -c \"{fd}>&'.env' git status\"")[0], "deny")
        self.assertEqual(decide(">&'.env' git status")[0], "deny")

    def test_raw_redirect_scan_keeps_operator_and_target_provenance(self):
        allows = (
            r"printf '%s\n' \>'.env'",
            r"echo hi >'.e\nv'",
            r'echo hi >".e\nv"',
            r"echo hi >.e'\n'v",
            r'''powershell -Command "& { echo hi >'.e\nv' }"''',
            r'''powershell -Command "iex 'echo hi >.e\nv'"''',
        )
        denies = (
            r"printf '%s\n' \\> '.env'",
            r'cmd /d /s /c "echo hi \>.env"',
            r"echo hi ^>.env",
            r"echo hi >.\env",
            r"echo hi >.e\nv",
            r"echo hi >.en\v",
            r"bash -c 'echo hi >.\env'",
            r"sh -c 'echo hi >.e\nv'",
            "bash -c \"eval 'echo hi >.e\\nv'\"",
        )
        for command in allows:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "allow")
        for command in denies:
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "deny")

        self.assertEqual(decide("bash -c \"eval '2>&.env echo hi'\"")[0], "allow")

    def test_raw_redirect_target_ends_at_shell_separators(self):
        for separator in (";", "&&", "|", "&"):
            command = f"echo hi >.env{separator}echo ok"
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "deny")

    def test_dynamic_redirect_targets_stay_denied(self):
        for command in ("echo hi >(cat)", "echo hi > >(cat)", "echo hi > <(cat)"):
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny")
                self.assertIn("dynamic redirect target", reason)

    def test_reading_a_secret_file_through_the_prefix_stays_allowed(self):
        # The floor blocks the irreversible, not disclosure by read.  Denying
        # `< '.env' cat` would be a new false positive, not a charter win.
        for command in ("< '.env' cat", "< .env cat", "<& 3 cat"):
            with self.subTest(command=command):
                self.assertEqual(decide(command)[0], "allow")


class PrefixAllowSideTests(unittest.TestCase):
    """Legitimate commands must survive every prefix form.

    ``PrefixCrossProductTests`` only proves denies stay denied.  A prefix change
    that starts blocking ordinary work is as serious a defect as one that lets a
    charter shape through, so the allow direction needs its own gate.
    """

    BENIGN = (
        "git status",
        "git log --oneline -5",
        "git diff HEAD~1",
        "ls -la",
        "cat README.md",
        "py -3 -m pytest tests",
        "npm run build",
        "make -j4 all",
        "grep -rn TODO src",
        "echo hello",
        "git commit -m 'ship it'",
        "gh pr view 53",
    )

    def test_every_benign_command_allows_behind_each_prefix(self):
        for command in self.BENIGN:
            with self.subTest(prefix="<direct>", command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "allow", reason)
            for prefix in PrefixCrossProductTests.PREFIXES:
                with self.subTest(prefix=prefix, command=command):
                    decision, reason = decide(prefix + command, 1)
                    self.assertEqual(decision, "allow", reason)

    def test_benign_redirect_targets_are_not_secret_looking(self):
        commands = (
            "> build.log make all",
            ">> build.log make all",
            "2> errors.txt git fetch origin",
            "&> combined.log npm test",
            ">| out.txt ls",
            "> /dev/null git gc",
            "< input.txt sort -u",
        )
        for command in commands:
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "allow", reason)


class CmdAggregateSeparatorTests(unittest.TestCase):
    def test_cmd_aggregate_spelling_exposes_the_following_delete(self):
        for switch in ("c", "k"):
            switch_prefixes = (
                f"cmd /{switch}",
                f"cmd.exe /d /{switch}",
                f"cmd.exe /d/{switch}",
                f"cmd /q/{switch}",
            )
            for switch_prefix in switch_prefixes:
                for operator in ("&>", "&>>"):
                    commands = (
                        rf"""{switch_prefix} "echo harmless {operator}nul """
                        r'''rd /s /q C:\critical\outside path\"''',
                        rf"""{switch_prefix}"echo harmless {operator}nul """
                        r'''rd /s /q C:\critical\outside path\"''',
                        rf"""{switch_prefix}echo harmless {operator}nul """
                        r'''rd /s /q "C:\critical\outside path\"''',
                    )
                    for command in commands:
                        with self.subTest(command=command):
                            decision, reason = decide(command)
                            self.assertEqual(decision, "deny", reason)


class WindowsGrammarSegmentationTests(unittest.TestCase):
    """`&>` is one redirect in PowerShell and two commands in cmd.exe.

    The recovery paths cannot know which shell runs the line, so committing to
    the PowerShell reading drops the cmd command hiding behind the redirect.
    """

    OUTSIDE_DELETE = r'rd /s /q "C:\critical\outside path\"'

    def test_aggregate_redirect_does_not_hide_a_following_delete(self):
        for operator in ("&>", "&>>"):
            for lead in ("echo x", "call other.bat", "start other.exe"):
                command = f"{lead} {operator}nul {self.OUTSIDE_DELETE}"
                with self.subTest(command=command):
                    decision, reason = decide(command)
                    self.assertEqual(decision, "deny", reason)

    def test_both_separator_readings_are_recovered(self):
        merged = dispatch.windows_recovery_segments("echo x &>nul rd /s /q C:\\x")
        segments = [segment for segment, _operator in merged]
        self.assertIn("echo x &>nul rd /s /q C:\\x", segments)
        self.assertIn("echo x", segments)
        self.assertIn(">nul rd /s /q C:\\x", segments)

    # Trailing backslash inside a double-quoted path: POSIX shlex rejects the
    # line, so these are the allow-side commands that actually enter the
    # recovery path the union widening lives on.
    RECOVERED_ALLOW = (
        r'Get-Content "C:\logs\app\" &> out.txt',
        r'Write-Output "note\" &>> build.log',
        r'Write-Output "C:\build\" &> "C:\logs\build.log"',
        r'Get-ChildItem "C:\logs\" &>> listing.txt',
    )

    def test_powershell_aggregate_redirect_stays_allowed(self):
        commands = (*self.RECOVERED_ALLOW, "npm test &> combined.log")
        for command in commands:
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "allow", reason)

    def test_the_allow_side_actually_reaches_the_recovery_path(self):
        # Reachability, not usage: a benign command that never enters the
        # recovery path proves nothing about the `&`-grammar widening.  If a
        # future quoting change moves these onto the ordinary shlex path, the
        # allow assertions above would keep passing while covering nothing --
        # so pin that these commands really do reach it.  The widening itself
        # is pinned by test_both_separator_readings_are_recovered; both
        # assertions below survive reverting it, so do not read this as its
        # guard.
        for command in self.RECOVERED_ALLOW:
            with self.subTest(command=command):
                segments = [
                    argv
                    for argv, _op in dispatch.quote_aware_segments_with_operators(
                        command
                    )
                ]
                self.assertGreater(len(segments), 1, segments)
                self.assertTrue(
                    any(argv and argv[0].startswith(">") for argv in segments),
                    segments,
                )


class _CountingSegment(tuple):
    """A recovery entry that records how often it is compared for equality."""

    comparisons = 0

    def __eq__(self, other):
        type(self).comparisons += 1
        return tuple.__eq__(self, other)

    def __hash__(self):
        return tuple.__hash__(self)


class RecoverySegmentScaleTests(unittest.TestCase):
    """The dual-grammar union must merge in LINEAR time.

    Both grammars usually read a long command identically, so the second pass
    re-offers every entry the first emitted.  Deduplicating with `in merged`
    made that quadratic: a 4,000-segment command took ~4s end to end here
    against a 5-second Codex hook timeout, and 6,000 segments took ~8s -- past
    the timeout, which means no deny is returned at all.  Asserting on equality
    COUNTS rather than wall-clock keeps this deterministic on a loaded machine.
    """

    SEGMENT_COUNT = 400

    def test_merging_the_two_grammars_stays_linear(self):
        entries = [
            _CountingSegment((f"echo seg{index}", "&"))
            for index in range(self.SEGMENT_COUNT)
        ]
        _CountingSegment.comparisons = 0
        with patch.object(
            dispatch, "windows_operator_segments", side_effect=lambda *a, **k: entries
        ):
            merged = dispatch.windows_recovery_segments("unused")
        self.assertEqual(len(merged), self.SEGMENT_COUNT)
        # Linear merging compares each entry a bounded number of times; the list
        # scan this replaced needed ~n^2/2 for the first pass alone.
        self.assertLess(
            _CountingSegment.comparisons,
            4 * self.SEGMENT_COUNT,
            _CountingSegment.comparisons,
        )

    def test_order_and_uniqueness_survive_the_set(self):
        entries = [
            ("echo a", "&"),
            ("echo b", "&"),
            ("echo a", "&"),
            ("echo c", ""),
        ]
        with patch.object(
            dispatch, "windows_operator_segments", side_effect=lambda *a, **k: entries
        ):
            merged = dispatch.windows_recovery_segments("unused")
        self.assertEqual(merged, [("echo a", "&"), ("echo b", "&"), ("echo c", "")])

    def test_a_long_generated_command_still_denies(self):
        # The real path, not a patched one: a malformed-quote recursive delete
        # behind thousands of benign segments is exactly the shape that timed
        # out.  Correctness only -- the timing claim lives in the counting test.
        segments = [f"echo seg{index}" for index in range(2000)]
        segments.append(r'rd /s /q "C:\critical\outside path\"')
        decision, reason = decide(" & ".join(segments))
        self.assertEqual(decision, "deny", reason)


if __name__ == "__main__":
    unittest.main()
