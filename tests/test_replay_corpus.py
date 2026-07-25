"""Tests for the corpus replay instrument.

`scripts/replay_corpus.py` produces the false-positive numbers that decide
whether a floor change merges and whether a new deny floor is installed
globally, so its measurement machinery is load-bearing and gets the same
treatment as the floor itself. The cases below are the ones an independent
review found already broken: a decoder that fabricated commands out of string
concatenations, delta buckets that silently dropped `ask` transitions, an
extraction channel that was skipped without being counted, and a sample that
had to stay stable across runs for a smoke run and a full run to be comparable.
"""

import contextlib
import importlib.util
import io
import json
import tempfile
import textwrap
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAY_PATH = ROOT / "scripts" / "replay_corpus.py"

BACKSLASH = chr(92)
QUOTE = chr(34)

# A dispatch.py stand-in with the two shapes the replay harness requires: a
# `check()` with the current signature, and a `command_output` bound as some
# function's `command_runner` default so `make_module_offline` can prove the run
# spawns nothing. `DECIDE` is spliced in as the body of the verdict rule.
STUB_DISPATCH = """
FLOOR_VERSION = "{version}"


def command_output(argv, cwd="", timeout=None):  # pragma: no cover - never runs
    raise AssertionError("the replay must not spawn a subprocess")


def reads_git_config(project_dir, command_runner=command_output):
    return command_runner(["git", "config"], project_dir)


def check(command, tier_cfg, project_dir, command_cwd, remote_resolver=None):
    tier = tier_cfg["tier"]
    flags = tier_cfg["flags"]
{decide}
"""


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


replay = load_module("replay_corpus_under_test", REPLAY_PATH)


def literal(body: str) -> str:
    """Wrap `body` in double quotes, as it appears in a JS source file."""
    return QUOTE + body + QUOTE


class DecodeJsStringLiteralTests(unittest.TestCase):
    def test_plain_literal(self):
        self.assertEqual(
            replay.decode_js_string_literal(literal("git status"), 0),
            ("git status", 12),
        )

    def test_simple_escapes(self):
        decoded = replay.decode_js_string_literal(
            literal("a" + BACKSLASH + "nb" + BACKSLASH + "tc"), 0
        )
        self.assertEqual(decoded[0], "a\nb\tc")

    def test_escaped_quote_does_not_terminate(self):
        decoded = replay.decode_js_string_literal(
            literal("say " + BACKSLASH + QUOTE + "hi" + BACKSLASH + QUOTE), 0
        )
        self.assertEqual(decoded[0], 'say "hi"')

    def test_hex_and_brace_escapes(self):
        self.assertEqual(
            replay.decode_js_string_literal(literal(BACKSLASH + "x41"), 0)[0], "A"
        )
        self.assertEqual(
            replay.decode_js_string_literal(literal(BACKSLASH + "u{1F600}"), 0)[0],
            chr(0x1F600),
        )

    def test_hex_payload_is_validated_not_left_to_int(self):
        # `int(" 1", 16)` succeeds; the decoder must not accept that.
        self.assertIsNone(
            replay.decode_js_string_literal(literal(BACKSLASH + "x 1"), 0)
        )
        self.assertIsNone(
            replay.decode_js_string_literal(literal(BACKSLASH + "u 123"), 0)
        )

    def test_surrogate_pair_is_combined(self):
        decoded = replay.decode_js_string_literal(
            literal(BACKSLASH + "uD83D" + BACKSLASH + "uDE00"), 0
        )
        self.assertEqual(decoded[0], chr(0x1F600))
        # Encodable: a lone surrogate would raise here, hours into a real run.
        decoded[0].encode("utf-8")

    def test_lone_surrogate_is_refused(self):
        self.assertIsNone(
            replay.decode_js_string_literal(literal(BACKSLASH + "uD83D"), 0)
        )

    def test_line_continuation_elides_the_newline(self):
        # A backslash before a real newline is a LineContinuation. Emitting a
        # newline instead manufactures a shell statement separator, which is
        # exactly the class of thing this corpus is used to measure.
        decoded = replay.decode_js_string_literal(
            literal("git add ." + BACKSLASH + "\n && git commit"), 0
        )
        self.assertEqual(decoded[0], "git add . && git commit")

    def test_legacy_octal_is_refused_not_guessed(self):
        self.assertIsNone(
            replay.decode_js_string_literal(literal(BACKSLASH + "012"), 0)
        )
        # A plain NUL escape is still decodable.
        self.assertEqual(
            replay.decode_js_string_literal(literal(BACKSLASH + "0"), 0)[0], "\0"
        )

    def test_interpolated_template_literal_is_refused(self):
        source = "`git checkout ${branch}`"
        self.assertIsNone(replay.decode_js_string_literal(source, 0))

    def test_unterminated_literal_is_refused(self):
        self.assertIsNone(replay.decode_js_string_literal(QUOTE + "git status", 0))


class ExtractEmbeddedCommandsTests(unittest.TestCase):
    def extract(self, source):
        stats = Counter()
        return replay.extract_embedded_commands(source, stats), stats

    def test_literal_call_is_extracted(self):
        found, stats = self.extract('tools.shell_command({command: "git status"})')
        self.assertEqual(found, ["git status"])
        self.assertEqual(dict(stats), {})

    def test_concatenation_is_counted_not_fabricated(self):
        # The shape this actually failed on: a here-string piped into `python -`.
        # The old decoder returned the 3-character fragment `@'\n` and counted it
        # as a replay *success*.
        source = (
            "tools.shell_command({command:"
            + literal("@'" + BACKSLASH + "n")
            + " + script + "
            + literal(BACKSLASH + "n'@ | python -")
            + ", timeout_ms: 5})"
        )
        found, stats = self.extract(source)
        self.assertEqual(found, [])
        self.assertEqual(stats["unparsed-codex-embedded-concatenated"], 1)

    def test_trailing_method_call_is_counted(self):
        source = 'tools.shell_command({command: "git status".trim()})'
        found, stats = self.extract(source)
        self.assertEqual(found, [])
        self.assertEqual(stats["unparsed-codex-embedded-concatenated"], 1)

    def test_closing_brace_and_comma_both_terminate(self):
        for tail in ("}", ", timeout_ms: 1}"):
            found, stats = self.extract(
                'tools.shell_command({command: "ls"' + tail + ")"
            )
            self.assertEqual(found, ["ls"])
            self.assertEqual(dict(stats), {})

    def test_non_object_argument_is_counted(self):
        found, stats = self.extract("tools.shell_command(opts)")
        self.assertEqual(found, [])
        self.assertEqual(stats["unparsed-codex-embedded-non-object-argument"], 1)

    def test_variable_command_is_counted(self):
        found, stats = self.extract("tools.shell_command({command: cmd})")
        self.assertEqual(found, [])
        self.assertEqual(stats["unparsed-codex-embedded-non-literal-command"], 1)


class CommandFromArgvTests(unittest.TestCase):
    def test_legacy_powershell_wrapper(self):
        # The real shape in this corpus's 2025/11/18 rollouts.
        self.assertEqual(
            replay.command_from_argv(
                ["powershell.exe", "-NoLogo", "-Command", "Get-ChildItem -Recurse"]
            ),
            "Get-ChildItem -Recurse",
        )
        self.assertEqual(
            replay.command_from_argv(
                ["powershell.exe", "-Command", "Get-Content README.md"]
            ),
            "Get-Content README.md",
        )

    def test_posix_and_cmd_wrappers(self):
        self.assertEqual(replay.command_from_argv(["bash", "-lc", "ls -la"]), "ls -la")
        self.assertEqual(replay.command_from_argv(["/bin/sh", "-c", "id"]), "id")
        self.assertEqual(replay.command_from_argv(["cmd.exe", "/c", "dir"]), "dir")

    def test_plain_argv_is_joined(self):
        self.assertEqual(replay.command_from_argv(["git", "status"]), "git status")

    def test_argv_needing_quoting_is_refused(self):
        # Joining these would invent a command line no shell ever saw.
        self.assertIsNone(replay.command_from_argv(["node", "-e", "console.log(1)"]))
        self.assertIsNone(replay.command_from_argv(["echo", "a b"]))

    def test_degenerate_argv_is_refused(self):
        self.assertIsNone(replay.command_from_argv([]))
        self.assertIsNone(replay.command_from_argv(["bash", "-lc"]))
        self.assertIsNone(replay.command_from_argv(["git", 3]))


class NormalizeReasonTests(unittest.TestCase):
    def test_secret_path_is_replaced(self):
        self.assertEqual(
            replay.normalize_reason(
                "Redirecting output into a secret-looking file (/srv/.env) "
                "is floor-blocked.",
                "echo x > /srv/.env",
            ),
            "Redirecting output into a secret-looking file (<path>) "
            "is floor-blocked.",
        )

    def test_class_stops_fragmenting_per_path(self):
        template = "Mutating a secret-looking file ({0}) is floor-blocked."
        grouped = {
            replay.normalize_reason(template.format(path), "mv a " + path)
            for path in ("a/.env", "b/id_rsa", "c/server.pem")
        }
        self.assertEqual(len(grouped), 1)

    def test_delete_target_and_child_command_are_replaced(self):
        self.assertEqual(
            replay.normalize_reason(
                "rm -rf outside the project: /var/tmp/x", "rm -rf /var/tmp/x"
            ),
            "rm -rf outside the project: <path>",
        )
        self.assertEqual(
            replay.normalize_reason(
                "xargs can launch an uninspected child command; run the child "
                "directly.",
                "xargs foo",
            ),
            "<command> can launch an uninspected child command; run the child "
            "directly.",
        )

    def test_exception_text_is_masked_by_the_second_pass(self):
        self.assertEqual(
            replay.normalize_reason(
                "ValueError: bad token in /srv/app/.env", "cat /srv/app/.env"
            ),
            "ValueError: bad token in <path>",
        )

    def test_floor_wording_is_never_masked(self):
        # 'group/other' looks path-ish but is not in the command, so it stays.
        reason = (
            "chmod that grants group/other access to a secret-looking file "
            "is floor-blocked."
        )
        self.assertEqual(replay.normalize_reason(reason, "chmod 777 .env"), reason)


class CompareTierBucketTests(unittest.TestCase):
    """`compare_tier` decides merges, so its buckets must partition changes."""

    def compare(self, rows, top=10):
        commands = [f"cmd-{index}" for index in range(len(rows))]
        corpus = {command: {"codex": 1, "claude": 0} for command in commands}
        baseline = [[row[0]] for row in rows]
        candidate = [[row[1]] for row in rows]
        return replay.compare_tier(commands, corpus, baseline, candidate, 0, top)

    def test_directionality(self):
        delta = self.compare(
            [
                (("allow", ""), ("deny", "r")),
                (("deny", "r"), ("allow", "")),
            ]
        )
        self.assertEqual(delta["newly_blocked_unique"], 1)
        self.assertEqual(delta["newly_allowed_unique"], 1)

    def test_ask_transitions_land_in_their_own_buckets(self):
        delta = self.compare(
            [
                (("deny", "r"), ("ask", "confirm")),
                (("ask", "confirm"), ("deny", "r")),
            ]
        )
        self.assertEqual(delta["ask_gained_unique"], 1)
        self.assertEqual(delta["ask_lost_unique"], 1)
        # Neither is an allow-edge: the old code reported both as nothing.
        self.assertEqual(delta["newly_blocked_unique"], 0)
        self.assertEqual(delta["newly_allowed_unique"], 0)

    def test_ask_to_allow_and_allow_to_ask_follow_the_allow_edge(self):
        delta = self.compare(
            [
                (("ask", "confirm"), ("allow", "")),
                (("allow", ""), ("ask", "confirm")),
            ]
        )
        self.assertEqual(delta["newly_allowed_unique"], 1)
        self.assertEqual(delta["newly_blocked_unique"], 1)
        self.assertEqual(delta["ask_gained_unique"], 0)
        self.assertEqual(delta["ask_lost_unique"], 0)

    def test_buckets_are_mutually_exclusive_and_exhaustive(self):
        pairs = [(a, b) for a in replay.DECISIONS for b in replay.DECISIONS if a != b]
        delta = self.compare([((a, "ra"), (b, "rb")) for a, b in pairs], top=100)
        bucketed = sum(
            delta[f"{label}_unique"]
            for label in (
                "newly_blocked",
                "newly_allowed",
                "ask_gained",
                "ask_lost",
                "crash_moved",
            )
        )
        self.assertEqual(bucketed, len(pairs))
        commands = set()
        for label in (
            "newly_blocked",
            "newly_allowed",
            "ask_gained",
            "ask_lost",
            "crash_moved",
        ):
            for row in delta[f"{label}_top"]:
                self.assertNotIn(row["command"], commands)
                commands.add(row["command"])

    def test_reclassified_needs_the_same_decision(self):
        delta = self.compare(
            [
                (("deny", "old rule"), ("deny", "new rule")),
                (("deny", "same"), ("deny", "same")),
            ]
        )
        self.assertEqual(delta["reclassified_unique"], 1)
        self.assertEqual(delta["newly_blocked_unique"], 0)
        self.assertEqual(delta["newly_allowed_unique"], 0)


class SummarizeTierTests(unittest.TestCase):
    def test_ask_counts_as_blocked_but_not_as_refused(self):
        commands = ["a", "b", "c", "d"]
        corpus = {command: {"codex": 2, "claude": 0} for command in commands}
        verdicts = [
            [("allow", "")],
            [("ask", "confirm")],
            [("deny", "no")],
            [("error", "boom")],
        ]
        summary = replay.summarize_tier(commands, corpus, verdicts, 0)
        self.assertEqual(summary["unique_blocked"], 3)
        self.assertEqual(summary["unique_refused"], 2)
        self.assertEqual(summary["unique_ask"], 1)
        self.assertAlmostEqual(summary["unique_block_rate"], 0.75)
        self.assertAlmostEqual(summary["unique_refuse_rate"], 0.5)


class SelectCommandsTests(unittest.TestCase):
    def test_sampling_is_deterministic_and_order_independent(self):
        corpus = {f"command {index}": {"codex": 1, "claude": 0} for index in range(200)}
        first, _ = replay.select_commands(corpus, 25, 20000)
        second, _ = replay.select_commands(corpus, 25, 20000)
        self.assertEqual(first, second)
        reversed_corpus = dict(reversed(list(corpus.items())))
        third, _ = replay.select_commands(reversed_corpus, 25, 20000)
        self.assertEqual(sorted(first), sorted(third))

    def test_a_smaller_sample_is_a_subset_of_a_larger_one(self):
        # A smoke run and a full run of the same corpus must agree on the
        # commands they share, or their numbers cannot be compared.
        corpus = {f"command {index}": {"codex": 1, "claude": 0} for index in range(200)}
        small, _ = replay.select_commands(corpus, 10, 20000)
        large, _ = replay.select_commands(corpus, 50, 20000)
        self.assertTrue(set(small) <= set(large))

    def test_over_long_commands_are_dropped_and_counted(self):
        corpus = {
            "short": {"codex": 1, "claude": 0},
            "x" * 50: {"codex": 1, "claude": 0},
        }
        kept, notes = replay.select_commands(corpus, None, 20)
        self.assertEqual(kept, ["short"])
        self.assertEqual(notes["skipped-over-max-chars"], 1)


class HostEnvironmentTests(unittest.TestCase):
    def test_home_names_are_never_cleared(self):
        # The floor resolves '~' and home-root comparisons through these.
        for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
            self.assertIn(name, replay.HOST_ENV_KEEP)

    def test_declared_names_exclude_the_keep_set(self):
        # Harvesting a floor version's own registries is what keeps a future
        # version's new non-GIT_ variable from reintroducing host dependence;
        # HOME/USERPROFILE must survive it, since the floor resolves '~'
        # through them.
        class FakeModule:
            _GIT_PROCESS_ENVIRONMENT = {"GIT_EDITOR", "SSH_ASKPASS"}
            _GIT_REPOSITORY_CONTEXT_ENVIRONMENT = {"HOME", "USERPROFILE"}
            _FUTURE_SHELL_ENVIRONMENT = {"BASH_ENV"}
            PROJECT_MARKERS = {"IGNORED"}

        names = replay.declared_env_names([FakeModule])
        self.assertEqual(names, {"GIT_EDITOR", "SSH_ASKPASS", "BASH_ENV"})


class OfflineStubTests(unittest.TestCase):
    def test_defaults_are_rebound_and_a_missing_hook_raises(self):
        module = load_module("replay_offline_probe", REPLAY_PATH)

        def command_output(argv, cwd, timeout=3):  # pragma: no cover - never run
            raise AssertionError("the replay must not spawn a subprocess")

        def uses_runner(project_dir, command_runner=command_output):
            return command_runner(["git", "config"], project_dir)

        module.command_output = command_output
        module.uses_runner = uses_runner
        self.assertEqual(replay.make_module_offline(module), 1)
        self.assertEqual(uses_runner("."), "")

        bare = load_module("replay_offline_probe_bare", REPLAY_PATH)
        bare.command_output = command_output
        with self.assertRaises(RuntimeError):
            replay.make_module_offline(bare)


class EndToEndTestCase(unittest.TestCase):
    """Drive `main()` over throwaway stub floors, as a gate caller would.

    The findings these cover are all about what the CLI does with a run, not
    about a pure function, so they are only reachable through `main()`.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write_corpus(self, *commands):
        path = self.dir / "corpus.jsonl"
        path.write_text(
            "".join(
                json.dumps({"command": command, "codex": 1, "claude": 0}) + "\n"
                for command in commands
            ),
            encoding="utf-8",
        )
        return path

    def write_dispatch(self, name, version, decide):
        path = self.dir / f"{name}.py"
        body = "\n".join(
            "    " + line for line in textwrap.dedent(decide).strip().splitlines()
        )
        path.write_text(
            STUB_DISPATCH.format(version=version, decide=body), encoding="utf-8"
        )
        return path

    def run_main(self, *argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = replay.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class OverlayFlagTests(EndToEndTestCase):
    """Overlays were hard-coded off, so a T2 row described no estate repo."""

    def test_decide_passes_the_flag_set_into_check(self):
        seen = []

        class RecordingModule:
            @staticmethod
            def check(command, tier_cfg, project_dir, command_cwd, **kwargs):
                seen.append(tier_cfg)
                return "allow", ""

        replay.decide(RecordingModule, "git push", 2, ".", {"wave_mode": True})
        self.assertEqual(seen[-1], {"tier": 2, "flags": {"wave_mode": True}})
        # Omitted entirely, the floor must see a declared-no-flags repo.
        replay.decide(RecordingModule, "git push", 2, ".")
        self.assertEqual(seen[-1], {"tier": 2, "flags": {}})

    def test_each_call_gets_its_own_flags_dict(self):
        # A floor version that normalises its config in place must not be able
        # to carry a flag from one replayed command into the next.
        seen = []

        class MutatingModule:
            @staticmethod
            def check(command, tier_cfg, project_dir, command_cwd, **kwargs):
                seen.append(dict(tier_cfg["flags"]))
                tier_cfg["flags"]["sensitive_data"] = True
                return "allow", ""

        flags = {"wave_mode": True}
        replay.decide(MutatingModule, "a", 2, ".", flags)
        replay.decide(MutatingModule, "b", 2, ".", flags)
        self.assertEqual(seen, [{"wave_mode": True}, {"wave_mode": True}])
        self.assertEqual(flags, {"wave_mode": True})

    def test_cli_flag_reaches_the_replay_and_changes_the_verdict(self):
        corpus = self.write_corpus("git reset --hard HEAD~1")
        floor = self.write_dispatch(
            "wave_aware",
            "9.9.9",
            """
            if flags.get("wave_mode"):
                return "deny", "work-loss guard is a wall under wave_mode"
            return "allow", ""
            """,
        )
        common = [
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(floor),
            "--candidate",
            str(floor),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--quiet",
        ]
        code, plain, _ = self.run_main(*common)
        self.assertEqual(code, 0)
        code, waved, _ = self.run_main(*common, "--flag", "wave_mode")
        self.assertEqual(code, 0)
        # Same command, same tier, opposite verdict: the overlay is load-bearing
        # and a run that cannot set it cannot speak for a wave_mode repo.
        self.assertIn("deny=0", plain)
        self.assertIn("deny=1", waved)

    def test_active_overlays_label_the_report_and_the_json(self):
        corpus = self.write_corpus("git push")
        floor = self.write_dispatch("allowing", "9.9.9", 'return "allow", ""')
        json_path = self.dir / "out.json"
        code, text, _ = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(floor),
            "--candidate",
            str(floor),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--json",
            str(json_path),
            "--quiet",
            "--flag",
            "wave_mode",
            "--flag",
            "sensitive_data",
        )
        self.assertEqual(code, 0)
        self.assertIn("overlays  : sensitive_data, wave_mode", text)
        # The tier row itself carries the overlay; a bare "T2" would claim to
        # describe repos this run never measured.
        self.assertIn("T2+sensitive_data+wave_mode", text)
        run = json.loads(json_path.read_text(encoding="utf-8"))["run"]
        self.assertEqual(run["overlays"], ["sensitive_data", "wave_mode"])
        self.assertEqual(run["flags"], {"sensitive_data": True, "wave_mode": True})

    def test_an_unknown_overlay_is_rejected(self):
        # Silently measuring the no-overlay case under a misspelt overlay name
        # is the exact under-count this option exists to remove.
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            replay.build_parser().parse_args(["--flag", "wave-mode"])

    def test_tier_label_is_stable_without_overlays(self):
        self.assertEqual(replay.tier_label(3, []), "T3")
        self.assertEqual(replay.tier_label(3, ["wave_mode"]), "T3+wave_mode")


class CheckErrorGuardTests(EndToEndTestCase):
    """A crashing version counts as blocked, which zeroes the regression number."""

    ERRORS_ON_ONE = """
    if command == "boom":
        raise TypeError("check() got an unexpected keyword argument")
    return "allow", ""
    """

    def scenario(self, *extra):
        corpus = self.write_corpus("boom", "git status")
        baseline = self.write_dispatch("crashing", "1.0.0", self.ERRORS_ON_ONE)
        candidate = self.write_dispatch("healthy", "2.0.0", 'return "allow", ""')
        return self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--quiet",
            *extra,
        )

    def test_an_erroring_version_exits_non_zero_with_a_banner(self):
        code, text, err = self.scenario()
        self.assertEqual(code, replay.EXIT_ERRORS_PRESENT)
        self.assertNotEqual(replay.EXIT_ERRORS_PRESENT, 0)
        self.assertIn("check() RAISED", text)
        # Loud on both streams: a gate may capture only one of them.
        self.assertIn("check() RAISED", err)

    def test_the_error_count_is_in_the_headline_table(self):
        _, text, _ = self.scenario()
        headline = text.split("block rate by tier")[1].split("=" * 78)[0]
        self.assertIn("err b/c", headline)
        # baseline raised once, candidate never: exactly the shape that turns a
        # real regression into a NEWLY ALLOWED row. Previously the count showed
        # up only in the per-tier detail and the block-class table.
        tier_row = next(line for line in headline.splitlines() if "T2" in line)
        self.assertTrue(tier_row.rstrip().endswith("1/0"), tier_row)

    def test_the_crash_still_inflates_newly_allowed_which_is_why_it_aborts(self):
        # Documents the mechanism the exit code protects against: the error is
        # counted as blocked, so error -> allow is reported as a relaxation.
        _, text, _ = self.scenario()
        self.assertIn("NEWLY ALLOWED", text)
        self.assertIn("1 unique", text.split("NEWLY ALLOWED")[1][:60])

    def test_allow_errors_is_the_only_way_back_to_zero(self):
        code, text, _ = self.scenario("--allow-errors")
        self.assertEqual(code, 0)
        self.assertNotIn("check() RAISED", text)

    def test_a_clean_run_reports_zero_errors_and_exits_zero(self):
        corpus = self.write_corpus("git status")
        floor = self.write_dispatch("clean", "1.0.0", 'return "allow", ""')
        json_path = self.dir / "clean.json"
        code, text, _ = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(floor),
            "--candidate",
            str(floor),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--json",
            str(json_path),
            "--quiet",
        )
        self.assertEqual(code, 0)
        self.assertNotIn("check() RAISED", text)
        run = json.loads(json_path.read_text(encoding="utf-8"))["run"]
        self.assertEqual(run["errors"], {"baseline": 0, "candidate": 0})

    def test_count_errors_sums_every_replayed_tier(self):
        result = {
            "tier_order": [1, 2],
            "tiers": {
                1: {
                    "baseline": {"decisions": {"error": 2, "allow": 1}},
                    "candidate": {"decisions": {"allow": 3}},
                },
                2: {
                    "baseline": {"decisions": {"error": 5}},
                    "candidate": {"decisions": {"error": 1}},
                },
            },
        }
        self.assertEqual(replay.count_errors(result), {"baseline": 7, "candidate": 1})


class UntruncatedDeltaTests(EndToEndTestCase):
    """`--top` is a display limit; the JSON has to hold the whole delta."""

    def test_compare_tier_keeps_the_full_lists_alongside_the_top_slice(self):
        commands = [f"cmd-{index}" for index in range(9)]
        corpus = {command: {"codex": 1, "claude": 0} for command in commands}
        baseline = [[("deny", "old")] for _ in commands]
        candidate = [[("allow", "")] for _ in commands]
        delta = replay.compare_tier(commands, corpus, baseline, candidate, 0, 2)
        self.assertEqual(delta["newly_allowed_unique"], 9)
        self.assertEqual(len(delta["newly_allowed_top"]), 2)
        self.assertEqual(len(delta["newly_allowed_all"]), 9)
        self.assertEqual(
            {row["command"] for row in delta["newly_allowed_all"]}, set(commands)
        )
        for label in ("newly_blocked", "ask_gained", "ask_lost", "crash_moved"):
            self.assertIn(f"{label}_all", delta)
        self.assertIn("reclassified_all", delta)

    def test_the_json_holds_every_row_and_stdout_holds_only_top(self):
        commands = [f"secret-command-{index}" for index in range(6)]
        corpus = self.write_corpus(*commands)
        baseline = self.write_dispatch("blocking", "1.0.0", 'return "deny", "old"')
        candidate = self.write_dispatch("allowing", "2.0.0", 'return "allow", ""')
        json_path = self.dir / "out.json"
        code, text, _ = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--json",
            str(json_path),
            "--top",
            "2",
            "--quiet",
        )
        self.assertEqual(code, 0)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        delta = payload["tiers"]["2"]["delta"]
        self.assertEqual(delta["newly_allowed_unique"], 6)
        self.assertEqual(
            sorted(row["command"] for row in delta["newly_allowed_all"]),
            sorted(commands),
        )
        # stdout stays a summary, and says where the rest of the evidence is.
        self.assertEqual(text.count("secret-command-"), 2)
        self.assertIn("and 4 more", text)
        self.assertIn("tiers.2.delta.newly_allowed_all", text)


class MaxCommandCharsReportingTests(EndToEndTestCase):
    """Dropped-for-length commands bias the rate down, so say so up front."""

    def test_the_skipped_count_is_in_the_block_rate_table(self):
        corpus = self.write_corpus("git status", "x" * 400)
        floor = self.write_dispatch("allowing", "1.0.0", 'return "allow", ""')
        _, text, _ = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(floor),
            "--candidate",
            str(floor),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--max-command-chars",
            "100",
            "--quiet",
        )
        headline = text.split("block rate by tier")[1].split("=" * 78)[0]
        self.assertIn("excluded before replay: 1 command(s)", headline)
        self.assertIn("--max-command-chars (100)", headline)


# Two throwaway floors that differ only in what `check()` declares. `LEGACY` is
# the shape floor 1.2.0 actually ships (issue #39): three parameters, no
# `command_cwd`, no `remote_resolver`. `MODERN` is today's shape. Both deny the
# same one command, so any difference in their measured block rate is the
# instrument, not the policy.
LEGACY_FLOOR = '''
FLOOR_VERSION = "1.2.0"


def command_output(argv, cwd="", timeout=None):  # pragma: no cover - never runs
    raise AssertionError("the replay must not spawn a subprocess")


def reads_git_config(project_dir, command_runner=command_output):
    return command_runner(["git", "config"], project_dir)


def check(command, tier_cfg, project_dir):
    """The pre-`remote_resolver` signature, verbatim from floor 1.2.0."""
    if command == "git push --force":
        return "deny", "no force variants at all"
    return "allow", ""
'''

MODERN_FLOOR = """
FLOOR_VERSION = "1.6.5"


def command_output(argv, cwd="", timeout=None):  # pragma: no cover - never runs
    raise AssertionError("the replay must not spawn a subprocess")


def reads_git_config(project_dir, command_runner=command_output):
    return command_runner(["git", "config"], project_dir)


def check(
    command,
    tier_cfg,
    project_dir,
    command_cwd,
    _depth=0,
    remote_resolver=None,
    _remote_cache=None,
):
    assert command_cwd == project_dir
    assert remote_resolver is not None
    if command == "git push --force":
        return "deny", "no force variants at all"
    return "allow", ""
"""

# A floor that reaches for a subprocess the offline stub does not cover. The
# harness's own guard fires; that is the *tool* failing, not a policy verdict.
SPAWNING_FLOOR = """
import subprocess

FLOOR_VERSION = "9.9.9"


def command_output(argv, cwd="", timeout=None):  # pragma: no cover - never runs
    raise AssertionError("the replay must not spawn a subprocess")


def reads_git_config(project_dir, command_runner=command_output):
    return command_runner(["git", "config"], project_dir)


def check(command, tier_cfg, project_dir, command_cwd, remote_resolver=None):
    if command == "git push":
        subprocess.run(["git", "config", "--get-regexp", "remote.*"])
    return "allow", ""
"""


class PlanCheckCallTests(unittest.TestCase):
    """The binding plan is what makes an old baseline measurable at all."""

    def plan(self, function):
        import inspect

        return replay.plan_check_call(inspect.signature(function))

    def test_the_legacy_three_parameter_shape_binds_positionally(self):
        def check(command, tier_cfg, project_dir):  # pragma: no cover - not called
            return "allow", ""

        positional, keyword = self.plan(check)
        self.assertEqual(positional, ["command", "tier_cfg", "project_dir"])
        self.assertEqual(keyword, [])

    def test_the_current_shape_binds_cwd_and_the_resolver_too(self):
        def check(  # pragma: no cover - not called
            command,
            tier_cfg,
            project_dir,
            command_cwd,
            _depth=0,
            remote_resolver=None,
        ):
            return "allow", ""

        positional, keyword = self.plan(check)
        # `_depth` is unknown to the replay and has a default, so it is left
        # alone -- which closes the positional run and sends `remote_resolver`
        # through as a keyword.
        self.assertEqual(
            positional, ["command", "tier_cfg", "project_dir", "command_cwd"]
        )
        self.assertEqual(keyword, [("remote_resolver", "remote_resolver")])

    def test_a_keyword_only_resolver_is_bound_by_name(self):
        def check(  # pragma: no cover - not called
            command, tier_cfg, project_dir, *, remote_resolver=None
        ):
            return "allow", ""

        positional, keyword = self.plan(check)
        self.assertEqual(positional, ["command", "tier_cfg", "project_dir"])
        self.assertEqual(keyword, [("remote_resolver", "remote_resolver")])

    def test_an_unsupplied_required_parameter_is_refused_loudly(self):
        # The whole point: never guess. A guess would raise per command and be
        # counted as a block, which is the bug this replaces.
        def check(command, tier_cfg, project_dir, audit_sink):  # pragma: no cover
            return "allow", ""

        with self.assertRaises(replay.CheckSignatureError) as caught:
            self.plan(check)
        self.assertIn("audit_sink", str(caught.exception))

    def test_a_signature_without_the_replay_subject_is_refused(self):
        def check(tier_cfg, project_dir=""):  # pragma: no cover - not called
            return "allow", ""

        with self.assertRaises(replay.CheckSignatureError) as caught:
            self.plan(check)
        self.assertIn("command", str(caught.exception))

    def test_a_positional_only_parameter_after_a_skip_cannot_be_bound(self):
        source = (
            "def check(command, tier_cfg, unknown=1, project_dir='', /):\n"
            "    return 'allow', ''\n"
        )
        namespace = {}
        exec(source, namespace)  # noqa: S102 - a signature fixture, never called
        with self.assertRaises(replay.CheckSignatureError):
            self.plan(namespace["check"])

    def test_build_check_caller_rejects_a_module_with_no_check(self):
        class Empty:
            __name__ = "empty"

        with self.assertRaises(replay.CheckSignatureError):
            replay.build_check_caller(Empty)


class SignatureDispatchTests(EndToEndTestCase):
    """Issue #39: a baseline several versions old must replay, not read 100%."""

    def write_floor(self, name, source):
        path = self.dir / f"{name}.py"
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        return path

    def test_decide_calls_a_legacy_three_parameter_check_successfully(self):
        module = load_module(
            "replay_legacy_floor", self.write_floor("legacy", LEGACY_FLOOR)
        )
        self.assertEqual(
            replay.decide(module, "git push --force", 4, str(self.dir)),
            ("deny", "no force variants at all"),
        )
        # And the ordinary command is allowed, rather than becoming an `error`
        # decision that `summarize_tier` would count as a block.
        self.assertEqual(
            replay.decide(module, "git status", 4, str(self.dir))[0], "allow"
        )

    def test_two_signatures_measure_the_same_policy_identically(self):
        corpus = self.write_corpus("git push --force", "git status", "ls")
        legacy = self.write_floor("legacy", LEGACY_FLOOR)
        modern = self.write_floor("modern", MODERN_FLOOR)
        json_path = self.dir / "out.json"
        code, text, _ = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(legacy),
            "--candidate",
            str(modern),
            "--tier",
            "4",
            "--project-dir",
            str(self.dir),
            "--json",
            str(json_path),
            "--quiet",
        )
        self.assertEqual(code, 0)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        baseline = payload["tiers"]["4"]["baseline"]
        candidate = payload["tiers"]["4"]["candidate"]
        # Before the fix this row read 3 blocked / 100%, with three `error`
        # decisions carrying "check() takes 3 positional arguments".
        self.assertEqual(baseline["unique_blocked"], 1)
        self.assertEqual(baseline["decisions"].get("error", 0), 0)
        self.assertEqual(baseline["unique_blocked"], candidate["unique_blocked"])
        delta = payload["tiers"]["4"]["delta"]
        self.assertEqual(delta["newly_blocked_unique"], 0)
        self.assertEqual(delta["newly_allowed_unique"], 0)
        self.assertNotIn("check() RAISED", text)

    def test_the_bound_parameters_are_recorded_and_printed(self):
        corpus = self.write_corpus("git status")
        legacy = self.write_floor("legacy", LEGACY_FLOOR)
        modern = self.write_floor("modern", MODERN_FLOOR)
        json_path = self.dir / "out.json"
        code, text, _ = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(legacy),
            "--candidate",
            str(modern),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--json",
            str(json_path),
            "--quiet",
        )
        self.assertEqual(code, 0)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["baseline"]["check_parameters"],
            ["command", "tier_cfg", "project_dir"],
        )
        self.assertEqual(
            payload["candidate"]["check_parameters"],
            [
                "command",
                "tier_cfg",
                "project_dir",
                "command_cwd",
                "remote_resolver=remote_resolver",
            ],
        )
        # A reader must be able to see which shape produced the number.
        self.assertIn("check(command, tier_cfg, project_dir)", text)

    def test_an_unbindable_floor_aborts_before_any_number_is_printed(self):
        corpus = self.write_corpus("git status")
        modern = self.write_floor("modern", MODERN_FLOOR)
        broken = self.write_floor(
            "broken",
            """
            FLOOR_VERSION = "0.0.1"


            def check(command, tier_cfg, project_dir, audit_sink):
                return "allow", ""
            """,
        )
        code, text, err = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(broken),
            "--candidate",
            str(modern),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--quiet",
        )
        self.assertEqual(code, replay.EXIT_TOOL_FAILURE)
        self.assertIn("audit_sink", err)
        # No block rate at all: an unmeasurable version gets no table.
        self.assertNotIn("block rate by tier", text)


class ToolFailureBucketTests(EndToEndTestCase):
    """A harness malfunction must be its own bucket, never a deny."""

    def test_a_harness_error_is_toolfail_and_a_floor_crash_stays_error(self):
        class HarnessBreaks:
            __name__ = "harness_breaks"

            @staticmethod
            def check(command, tier_cfg, project_dir, command_cwd, **kwargs):
                raise replay.ReplayHarnessError("offline guard fired")

        class FloorBreaks:
            __name__ = "floor_breaks"

            @staticmethod
            def check(command, tier_cfg, project_dir, command_cwd, **kwargs):
                raise ValueError("the floor itself crashed")

        self.assertEqual(replay.decide(HarnessBreaks, "x", 2, ".")[0], replay.TOOLFAIL)
        self.assertEqual(replay.decide(FloorBreaks, "x", 2, ".")[0], "error")

    def test_toolfail_is_in_no_rate(self):
        commands = ["a", "b", "c", "d"]
        corpus = {command: {"codex": 1, "claude": 0} for command in commands}
        verdicts = [
            [("allow", "")],
            [("deny", "no")],
            [(replay.TOOLFAIL, "ReplayHarnessError: offline guard fired")],
            [(replay.TOOLFAIL, "ReplayHarnessError: offline guard fired")],
        ]
        summary = replay.summarize_tier(commands, corpus, verdicts, 0)
        self.assertEqual(summary["unique_toolfail"], 2)
        self.assertEqual(summary["unique_measured"], 2)
        self.assertEqual(summary["unique_blocked"], 1)
        # 1/2 measured, not 3/4: counting the two failures as blocked is exactly
        # the artifact issue #39 mistook for a 100% block rate.
        self.assertAlmostEqual(summary["unique_block_rate"], 0.5)
        self.assertEqual(len(summary["reasons"]), 1)
        self.assertEqual(summary["toolfail_reasons"][0]["unique"], 2)

    def test_toolfail_never_lands_in_an_allow_edge_bucket(self):
        commands = ["a", "b"]
        corpus = {command: {"codex": 1, "claude": 0} for command in commands}
        baseline = [[(replay.TOOLFAIL, "harness")], [("allow", "")]]
        candidate = [[("allow", "")], [(replay.TOOLFAIL, "harness")]]
        delta = replay.compare_tier(commands, corpus, baseline, candidate, 0, 5)
        self.assertEqual(delta["tool_failed_unique"], 2)
        for label in ("newly_blocked", "newly_allowed", "ask_gained", "crash_moved"):
            self.assertEqual(delta[f"{label}_unique"], 0, label)

    def test_the_offline_guard_produces_toolfail_and_exit_three(self):
        corpus = self.write_corpus("git push", "git status")
        path = self.dir / "spawning.py"
        path.write_text(textwrap.dedent(SPAWNING_FLOOR).lstrip(), encoding="utf-8")
        code, text, err = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(path),
            "--candidate",
            str(path),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--quiet",
        )
        self.assertEqual(code, replay.EXIT_TOOL_FAILURE)
        self.assertNotEqual(replay.EXIT_TOOL_FAILURE, replay.EXIT_ERRORS_PRESENT)
        self.assertIn("REPLAY TOOL FAILURE", text)
        # Loud on both streams: a gate may capture only one of them.
        self.assertIn("REPLAY TOOL FAILURE", err)
        self.assertIn("toolfail=1", text)

    def test_allow_errors_cannot_suppress_a_tool_failure(self):
        corpus = self.write_corpus("git push")
        path = self.dir / "spawning.py"
        path.write_text(textwrap.dedent(SPAWNING_FLOOR).lstrip(), encoding="utf-8")
        code, _, _ = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(path),
            "--candidate",
            str(path),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--quiet",
            "--allow-errors",
        )
        # --allow-errors censuses floor crashes; there is nothing to census when
        # the script could not run the floor.
        self.assertEqual(code, replay.EXIT_TOOL_FAILURE)

    def test_count_toolfails_sums_every_replayed_tier(self):
        result = {
            "tier_order": [1, 2],
            "tiers": {
                1: {
                    "baseline": {"unique_toolfail": 2},
                    "candidate": {"unique_toolfail": 0},
                },
                2: {
                    "baseline": {"unique_toolfail": 5},
                    "candidate": {"unique_toolfail": 1},
                },
            },
        }
        self.assertEqual(
            replay.count_toolfails(result), {"baseline": 7, "candidate": 1}
        )


class CorpusIntegrityTests(unittest.TestCase):
    """A shorter corpus that nobody was told about is a silent measurement bug."""

    def test_an_unreadable_transcript_is_counted(self):
        stats = Counter()
        with tempfile.TemporaryDirectory() as tmp:
            # Opening a directory raises OSError on every supported platform.
            records = list(replay.iter_jsonl(Path(tmp), stats))
        self.assertEqual(records, [])
        self.assertEqual(stats["unparsed-file-unreadable"], 1)

    def test_an_unwalkable_transcript_tree_is_counted(self):
        class Unwalkable:
            def rglob(self, pattern):
                raise PermissionError("the profile subtree is locked")

        stats = Counter()
        self.assertEqual(replay.iter_transcripts(Unwalkable(), stats), [])
        self.assertEqual(stats["unparsed-transcript-tree-unwalkable"], 1)

    def test_a_missing_verdict_aborts_instead_of_being_defaulted(self):
        with self.assertRaises(replay.ReplayHarnessError) as caught:
            replay.assert_every_command_replayed(
                [[("allow", "")], None], [[("allow", "")], [("allow", "")]]
            )
        self.assertIn("1 of 2", str(caught.exception))
        # The complete case must stay silent.
        replay.assert_every_command_replayed([[("allow", "")]], [[("allow", "")]])


if __name__ == "__main__":
    unittest.main()
