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
import hashlib
import importlib.util
import io
import json
import os as os_module
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAY_PATH = ROOT / "scripts" / "replay_corpus.py"
# `templates/hooks/dispatch.py` exactly as commit bd884ee7a3c708e3291d04e5bcb92b5
# fb2a92f91 shipped it: the real floor 1.2.0, three-argument `check()`, no
# `command_output`, no `subprocess`. Vendored rather than read out of git so the
# case runs from a source tree with no history; the digest below is the guard
# against anyone "fixing" the fixture into a synthetic one.
FLOOR_1_2_0_PATH = ROOT / "tests" / "fixtures" / "floor_1_2_0_dispatch.py"
FLOOR_1_2_0_SHA256 = "38ccb952831975f344fa1a42cb2384d4e85f16afb29c9726e3b9fb12b94dcc14"

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
        # A `ReplayHarnessError`, not a bare `RuntimeError`: only the former
        # reaches `main()`'s handler and exits 3. A plain RuntimeError escaped
        # as a traceback with interpreter exit code 1, which this script
        # documents as "nothing to replay".
        with self.assertRaises(replay.ReplayHarnessError):
            replay.make_module_offline(bare)

    def test_a_module_with_no_command_output_is_already_offline(self):
        # The headline `--baseline <real floor 1.2.0>` case: a floor that
        # predates the `command_output` seam. It cannot spawn, so there is
        # nothing to stub and nothing to refuse. This used to abort the run —
        # which made the one baseline issue #39 is about unmeasurable.
        module = load_module("replay_offline_probe_no_output", FLOOR_1_2_0_PATH)
        self.assertIsNone(getattr(module, "command_output", None))
        self.assertEqual(replay.make_module_offline(module), 0)

    def test_a_spawn_route_is_proxied_even_with_no_command_output(self):
        # "No seam" is only safe because every spawn-capable global is still
        # neutralised: an uncovered spawn site raises at the call instead of
        # starting a real process.
        module = load_module("replay_offline_probe_spawner", REPLAY_PATH)
        module.subprocess = subprocess
        module.os = os_module
        self.assertEqual(replay.make_module_offline(module), 0)
        for call in (
            lambda: module.subprocess.run(["git", "status"]),
            lambda: module.os.system("git status"),
        ):
            with self.assertRaises(replay.ReplayHarnessError):
                call()
        # Non-spawning attributes of the same modules keep working, or every
        # path verdict in the floor would break.
        self.assertIs(module.os.environ, os_module.environ)
        self.assertIs(module.subprocess.PIPE, subprocess.PIPE)

    def test_neutralising_twice_leaves_the_proxy_alone(self):
        module = load_module("replay_offline_probe_twice", REPLAY_PATH)
        module.subprocess = subprocess
        self.assertIn("subprocess", replay.neutralise_spawn_routes(module))
        self.assertEqual(replay.neutralise_spawn_routes(module), [])
        with self.assertRaises(replay.ReplayHarnessError):
            module.subprocess.run(["git", "status"])


class DispatchLoadTests(unittest.TestCase):
    """An unimportable floor is a broken instrument, not an empty corpus."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_a_missing_file_raises_a_harness_error(self):
        with self.assertRaises(replay.ReplayHarnessError):
            replay.load_dispatch("replay_missing", self.dir / "nope.py")

    def test_an_import_time_failure_raises_a_harness_error(self):
        # A vendored old floor can fail on a SyntaxError under a newer
        # interpreter, or on a module-level import this environment lacks.
        path = self.dir / "unimportable.py"
        path.write_text("def check(  # unterminated\n", encoding="utf-8")
        with self.assertRaises(replay.ReplayHarnessError) as caught:
            replay.load_dispatch("replay_unimportable", path)
        self.assertIn("SyntaxError", str(caught.exception))

    def test_a_module_level_raise_is_wrapped_too(self):
        path = self.dir / "raises.py"
        path.write_text("raise ImportError('no such module')\n", encoding="utf-8")
        with self.assertRaises(replay.ReplayHarnessError):
            replay.load_dispatch("replay_raises", path)


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


class PremiseMismatchTests(EndToEndTestCase):
    """Two signatures replay under two premises, and that must be said out loud.

    `remote_resolver` is stubbed to "every remote is private" only for a version
    that declares it. A version that does not keeps its internal resolver, which
    reads through the offline `command_output` stub and reports the remote
    unresolved. Under `sensitive_data` that is allow on one side and deny on the
    other for the same push, so the whole class lands in NEWLY ALLOWED as if it
    were a relaxation.
    """

    def write_floor(self, name, source):
        path = self.dir / f"{name}.py"
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        return path

    def test_only_roles_are_compared_not_the_calling_convention(self):
        # Positional versus keyword is a calling detail, never a premise.
        self.assertEqual(
            replay.check_parameter_delta(
                ["command", "tier_cfg", "project_dir", "remote_resolver"],
                [
                    "command",
                    "tier_cfg",
                    "project_dir",
                    "remote_resolver=remote_resolver",
                ],
            ),
            [],
        )

    def test_a_role_bound_on_one_side_only_is_reported(self):
        self.assertEqual(
            replay.check_parameter_delta(
                ["command", "tier_cfg", "project_dir"],
                ["command", "tier_cfg", "project_dir", "remote_resolver"],
            ),
            ["remote_resolver"],
        )

    def test_the_asymmetry_is_warned_about_and_recorded(self):
        corpus = self.write_corpus("git push")
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
        # A warning, not an abort: comparing two signatures is why this exists.
        self.assertEqual(code, 0)
        self.assertIn("PREMISE MISMATCH", text)
        self.assertIn("remote_resolver", text.split("PREMISE MISMATCH")[1][:400])
        run = json.loads(json_path.read_text(encoding="utf-8"))["run"]
        self.assertEqual(
            run["check_parameter_delta"], ["command_cwd", "remote_resolver"]
        )

    # The two halves of the finding's scenario, as close to the real floors as a
    # fixture gets: the old one resolves the remote itself (and therefore reads
    # through the offline `command_output` stub, which returns ""), the new one
    # takes a `remote_resolver` (and therefore gets `stub_resolver`'s "private").
    RESOLVES_INTERNALLY = '''
    FLOOR_VERSION = "1.2.0"


    def command_output(argv, cwd="", timeout=None):
        raise AssertionError("the replay must not spawn a subprocess")


    def remote_url(project_dir, command_runner=command_output):
        return command_runner(["git", "config", "--get", "remote.origin.url"], "")


    def check(command, tier_cfg, project_dir):
        """Pre-`remote_resolver`: resolves the remote through command_output."""
        if command.startswith("git push") and tier_cfg["flags"].get("sensitive_data"):
            if not remote_url(project_dir):
                return "deny", (
                    "sensitive_data repo: could not verify push remote "
                    "privacy (origin)"
                )
        return "allow", ""
    '''

    TAKES_A_RESOLVER = '''
    FLOOR_VERSION = "1.6.5"


    def command_output(argv, cwd="", timeout=None):
        raise AssertionError("the replay must not spawn a subprocess")


    def remote_url(project_dir, command_runner=command_output):
        return command_runner(["git", "config", "--get", "remote.origin.url"], "")


    def check(command, tier_cfg, project_dir, command_cwd, remote_resolver=None):
        """Current shape: the replay hands it a resolver that says "private"."""
        if command.startswith("git push") and tier_cfg["flags"].get("sensitive_data"):
            public, _name = remote_resolver(["git", "push"], project_dir)
            if public:
                return "deny", "sensitive_data repo: refusing a push to public remote"
        return "allow", ""
    '''

    def test_asymmetric_stubbing_reads_as_a_relaxation_and_is_flagged(self):
        corpus = self.write_corpus("git push")
        old = self.write_floor("resolves_internally", self.RESOLVES_INTERNALLY)
        new = self.write_floor("takes_a_resolver", self.TAKES_A_RESOLVER)
        json_path = self.dir / "out.json"
        code, text, _ = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(old),
            "--candidate",
            str(new),
            "--tier",
            "2",
            "--flag",
            "sensitive_data",
            "--project-dir",
            str(self.dir),
            "--json",
            str(json_path),
            "--quiet",
        )
        self.assertEqual(code, 0)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        # Same policy on both sides; the delta is produced entirely by which
        # side got the stub. Without the warning a reviewer reads this as a
        # relaxation needing security review.
        self.assertEqual(payload["tiers"]["2"]["delta"]["newly_allowed_unique"], 1)
        self.assertIn("could not verify push remote privacy", text)
        self.assertIn("PREMISE MISMATCH", text)
        self.assertEqual(
            payload["run"]["check_parameter_delta"],
            ["command_cwd", "remote_resolver"],
        )

    def test_matching_signatures_print_no_warning(self):
        corpus = self.write_corpus("git push")
        modern = self.write_floor("modern", MODERN_FLOOR)
        json_path = self.dir / "out.json"
        code, text, _ = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(modern),
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
        self.assertNotIn("PREMISE MISMATCH", text)
        run = json.loads(json_path.read_text(encoding="utf-8"))["run"]
        self.assertEqual(run["check_parameter_delta"], [])


class PremiseMismatchWordingTests(unittest.TestCase):
    """The warning must name the difference that actually happened.

    A reviewer who is told "these deltas may be stubbing artifacts" discounts
    them. Saying it about a mismatch that does not involve `remote_resolver`
    discounts the exact rows the run was made to measure.
    """

    def banner(self, *mismatch):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            replay.print_premise_mismatch(list(mismatch))
        return out.getvalue()

    def test_no_mismatch_prints_nothing(self):
        self.assertEqual(self.banner(), "")

    def test_a_cwd_only_transition_does_not_blame_the_remote_stub(self):
        # Three-argument floor vs one that added cwd tracking: neither side
        # declares remote_resolver, so nothing here is a stubbing artifact.
        text = self.banner("command_cwd")
        self.assertIn("PREMISE MISMATCH", text)
        self.assertIn("command_cwd", text)
        self.assertNotIn("remote_resolver", text)
        self.assertNotIn("private-remote stub", text)
        self.assertIn("real modelling difference", text)

    def test_a_resolver_transition_keeps_the_remote_privacy_explanation(self):
        text = self.banner("remote_resolver")
        self.assertIn("private-remote stub", text)
        self.assertIn("stubbing", text)
        self.assertNotIn("Only a version declaring command_cwd", text)

    def test_both_roles_get_both_paragraphs(self):
        # The real 1.2.0-vs-HEAD shape.
        text = self.banner("command_cwd", "remote_resolver")
        self.assertIn("private-remote stub", text)
        self.assertIn("Only a version declaring command_cwd", text)

    def test_an_unknown_role_still_gets_the_generic_warning(self):
        text = self.banner("tier_cfg")
        self.assertIn("PREMISE MISMATCH", text)
        self.assertIn("not a policy change", text)
        self.assertNotIn("private-remote stub", text)


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


class HarnessFailurePreflightTests(EndToEndTestCase):
    """Every tool-side failure exits 3, in the parent, before the pool exists.

    The PR's principle is that a tool-side failure must never be readable as a
    measurement. These are the three that used to escape it: a floor that will
    not import, one whose `command_output` has no `command_runner` default to
    rebind, and one whose `check()` cannot be bound. All three raised a plain
    `RuntimeError` that `main()` did not catch — a traceback with interpreter
    exit code 1, which this script documents as "nothing to replay".

    The counter-case matters just as much and is `RealLegacyFloorTests` below: a
    floor with no seam at all is not a tool-side failure, and refusing it made
    the one baseline this instrument exists to measure unmeasurable.
    """

    # `command_output` present, but bound to nothing the replay can rebind: the
    # seam moved, so the offline claim is unprovable and the run must abort.
    UNSTUBBABLE = """
        FLOOR_VERSION = "1.2.0"


        def command_output(argv, cwd="", timeout=None):
            return ""


        def check(command, tier_cfg, project_dir):
            return "allow", ""
        """

    def scenario(self, broken_source, *extra):
        corpus = self.write_corpus("git status")
        broken = self.dir / "broken_floor.py"
        broken.write_text(textwrap.dedent(broken_source).lstrip(), encoding="utf-8")
        healthy = self.write_dispatch("healthy", "2.0.0", 'return "allow", ""')
        return self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(broken),
            "--candidate",
            str(healthy),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--quiet",
            *extra,
        )

    def test_an_unstubbable_floor_exits_three_not_one(self):
        code, text, err = self.scenario(self.UNSTUBBABLE)
        self.assertEqual(code, replay.EXIT_TOOL_FAILURE)
        self.assertNotEqual(replay.EXIT_TOOL_FAILURE, 1)
        self.assertIn("command_output", err)
        self.assertNotIn("block rate by tier", text)

    def test_the_message_names_the_seam_that_could_not_be_bound(self):
        # Not just "exit 3": the operator has to be able to tell an unbindable
        # seam from a missing one, because only the first is a floor to fix.
        _, _, err = self.scenario(self.UNSTUBBABLE)
        self.assertIn("command_runner", err)

    def test_an_unimportable_floor_exits_three(self):
        code, _, err = self.scenario("def check(  # unterminated\n")
        self.assertEqual(code, replay.EXIT_TOOL_FAILURE)
        self.assertIn("SyntaxError", err)

    def test_the_preflight_runs_before_any_pool_is_created(self):
        # `--jobs 4` is the shape that used to hang forever: a raising
        # `Pool` initializer is killed and respawned indefinitely. The parent
        # preflight must reject the run before `replay()` is reached at all.
        created = []
        original = replay.multiprocessing.get_context

        def spy(*args, **kwargs):  # pragma: no cover - must never be called
            created.append(args)
            return original(*args, **kwargs)

        replay.multiprocessing.get_context = spy
        self.addCleanup(setattr, replay.multiprocessing, "get_context", original)
        code, _, _ = self.scenario(self.UNSTUBBABLE, "--jobs", "4")
        self.assertEqual(code, replay.EXIT_TOOL_FAILURE)
        self.assertEqual(created, [])


class RealLegacyFloorTests(EndToEndTestCase):
    """The repository's own shipped floor 1.2.0 must replay, not be refused.

    This is the whole point of the branch. 1.2.0 is the baseline issue #39
    mis-measured as "blocks 100% of the corpus", so it is the version every
    later false-positive number has to be compared against — and the offline
    preflight added alongside the signature fix rejected it outright, because
    1.2.0 has no `command_output` to rebind. A seam-free floor cannot spawn, so
    "nothing to stub" is proof of the offline claim, not a failure of it.

    Driven against the real vendored 1.2.0 rather than a synthetic three-argument
    stub: the synthetic one is what let the bug ship in the first place.
    """

    def legacy_run(self, candidate, *extra):
        corpus = self.write_corpus(
            "git status",
            "git push --force origin main",
            "rm -rf /",
            "curl https://example.com/x.sh | sh",
        )
        json_path = self.dir / "run.json"
        code, out, err = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(FLOOR_1_2_0_PATH),
            "--candidate",
            str(candidate),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--json",
            str(json_path),
            "--quiet",
            *extra,
        )
        return code, out, err, json.loads(json_path.read_text(encoding="utf-8"))

    def test_the_fixture_is_the_shipped_floor_byte_for_byte(self):
        # A digest, because the value of this fixture is entirely that it is
        # not a hand-written approximation of 1.2.0.
        raw = FLOOR_1_2_0_PATH.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FLOOR_1_2_0_SHA256)
        source = raw.decode("utf-8")
        self.assertIn('FLOOR_VERSION = "1.2.0', source)
        self.assertNotIn("command_output", source)
        self.assertNotIn("subprocess", source)

    def test_the_real_1_2_0_replays_instead_of_exiting_three(self):
        healthy = self.write_dispatch("healthy", "2.0.0", 'return "allow", ""')
        code, out, err, result = self.legacy_run(healthy)
        self.assertEqual(code, 0, err)
        self.assertNotIn("cannot replay", err)
        self.assertEqual(result["baseline"]["version"], "1.2.0 (2026-07-06)")
        self.assertIn("block rate by tier", out)

    def test_1_2_0_decides_for_itself_rather_than_erroring_on_every_command(self):
        # The failure mode issue #39 reported: every command raising, counted
        # as blocked, printed as a 100% block rate. 1.2.0 must produce real
        # `deny`/`allow` verdicts, with no `error` and no `toolfail` anywhere.
        healthy = self.write_dispatch("healthy", "2.0.0", 'return "allow", ""')
        _, _, _, result = self.legacy_run(healthy)
        baseline = result["tiers"]["2"]["baseline"]
        self.assertEqual(baseline["decisions"].get("error", 0), 0)
        self.assertEqual(baseline.get("unique_toolfail", 0), 0)
        self.assertGreater(baseline["decisions"]["deny"], 0)
        self.assertGreater(baseline["decisions"]["allow"], 0)
        self.assertEqual(result["run"]["errors"]["baseline"], 0)
        self.assertEqual(result["run"]["toolfails"]["baseline"], 0)

    def test_1_2_0_measures_against_the_floor_this_repo_actually_ships(self):
        # The end the instrument exists for: 1.2.0 vs HEAD's dispatch.py, the
        # comparison that was impossible before this fix.
        code, _, err, result = self.legacy_run(replay.DEFAULT_DISPATCH)
        self.assertEqual(code, 0, err)
        self.assertEqual(result["run"]["errors"], {"baseline": 0, "candidate": 0})
        self.assertEqual(result["run"]["toolfails"], {"baseline": 0, "candidate": 0})
        # Different signatures, so the premise-mismatch record must be there.
        self.assertEqual(
            result["run"]["check_parameter_delta"], ["command_cwd", "remote_resolver"]
        )

    def test_the_offline_claim_still_holds_for_a_seam_free_floor(self):
        # It spawns nothing because it *can* spawn nothing, and the run says so.
        healthy = self.write_dispatch("healthy", "2.0.0", 'return "allow", ""')
        _, out, _, result = self.legacy_run(healthy)
        self.assertEqual(result["run"]["offline_git_config_reads"], 0)
        self.assertIn("0 subprocesses spawned", out)


class WorkerInitFailureTests(unittest.TestCase):
    """`_worker_init` must never raise; the failure comes back as a task error.

    A `multiprocessing.Pool` initializer that raises makes CPython kill the
    worker and start another one, forever. The parent preflight above is the
    first line of defence; this is the backstop for anything that only fails
    inside a worker (a path that resolves differently there, a spawn-only
    import error).
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.addCleanup(replay._WORKER.clear)

    def test_a_failing_init_stashes_instead_of_raising(self):
        missing = self.dir / "not-a-floor.py"
        replay._worker_init(str(missing), str(missing), (2,), str(self.dir), {})
        self.assertIn("init_error", replay._WORKER)

    def test_the_stashed_failure_is_raised_by_the_worker_task(self):
        missing = self.dir / "not-a-floor.py"
        replay._worker_init(str(missing), str(missing), (2,), str(self.dir), {})
        with self.assertRaises(replay.ReplayHarnessError) as caught:
            replay._worker_run([(0, "git status")])
        self.assertIn("replay worker could not start", str(caught.exception))

    def test_the_single_process_path_fails_before_the_first_chunk(self):
        missing = self.dir / "not-a-floor.py"
        with self.assertRaises(replay.ReplayHarnessError):
            replay.replay(
                ["git status"], missing, missing, (2,), str(self.dir), 1, False, {}
            )

    def test_a_successful_init_leaves_no_stashed_failure(self):
        path = self.dir / "floor.py"
        path.write_text(
            STUB_DISPATCH.format(version="1.0.0", decide='    return "allow", ""'),
            encoding="utf-8",
        )
        replay._worker_init(str(path), str(path), (2,), str(self.dir), {})
        self.assertNotIn("init_error", replay._WORKER)
        replay.raise_if_worker_init_failed()


class MultiprocessReplayTests(unittest.TestCase):
    """Actually run `--jobs > 1`, because it was previously never exercised.

    It cannot be driven through the in-process `replay` module: under `spawn`,
    `_worker_run` is pickled by qualified name and the child would have to
    import `replay_corpus_under_test`, which exists only in this process. Run as
    a real script it is `__main__`, which multiprocessing re-imports from the
    path. So these shell out — the only way to prove the pool neither hangs nor
    lies. Every one carries a timeout: a hang is the failure under test.
    """

    TIMEOUT = 180

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.corpus = self.dir / "corpus.jsonl"
        self.corpus.write_text(
            "".join(
                json.dumps({"command": f"git status {n}", "codex": 1, "claude": 0})
                + "\n"
                for n in range(40)
            ),
            encoding="utf-8",
        )

    def write_floor(self, name, source):
        path = self.dir / f"{name}.py"
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        return path

    def run_script(self, floor, jobs, candidate=None):
        try:
            return subprocess.run(
                [
                    sys.executable,
                    str(REPLAY_PATH),
                    "--from-corpus",
                    str(self.corpus),
                    "--baseline",
                    str(floor),
                    "--candidate",
                    str(candidate or floor),
                    "--tier",
                    "2",
                    "--project-dir",
                    str(self.dir),
                    "--jobs",
                    str(jobs),
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT,
            )
        except subprocess.TimeoutExpired:  # pragma: no cover - the bug being fixed
            self.fail(f"--jobs {jobs} hung for {self.TIMEOUT}s instead of finishing")

    def test_a_healthy_run_agrees_with_the_single_process_run(self):
        floor = self.write_floor(
            "healthy",
            STUB_DISPATCH.format(
                version="1.0.0",
                decide='    return ("deny", "no") if "7" in command else ("allow", "")',
            ),
        )
        serial = self.run_script(floor, 1)
        parallel = self.run_script(floor, 2)
        self.assertEqual(serial.returncode, 0, serial.stderr)
        self.assertEqual(parallel.returncode, 0, parallel.stderr)
        table = "block rate by tier"
        self.assertIn(table, parallel.stdout)
        # Identical numbers, not merely a clean exit: a pool that dropped a
        # chunk would still exit 0 with a smaller, plausible-looking rate.
        self.assertEqual(serial.stdout.split(table)[1], parallel.stdout.split(table)[1])

    def test_a_floor_the_harness_cannot_stub_exits_three_without_hanging(self):
        # The regression: `make_module_offline` raised a plain RuntimeError from
        # inside a Pool initializer, which CPython respawns forever.
        floor = self.write_floor(
            "legacy",
            """
            FLOOR_VERSION = "1.2.0"


            def command_output(argv, cwd="", timeout=None):
                return ""


            def check(command, tier_cfg, project_dir):
                return "allow", ""
            """,
        )
        result = self.run_script(floor, 2)
        self.assertEqual(result.returncode, replay.EXIT_TOOL_FAILURE)
        self.assertIn("command_runner", result.stderr)
        # It never reached a worker: the parent preflight is what refused it.
        self.assertIn("cannot replay:", result.stderr)

    def test_a_worker_only_failure_comes_back_as_a_task_error(self):
        """The `_worker_init` stash/re-raise backstop, actually exercised.

        Every other failure in this file is caught by the parent preflight, so
        the documented multiprocess safety net had never run: `_worker_init`
        stashing instead of raising was only ever proven by calling it directly,
        in-process, with no pool. That leaves the claim it exists for — that a
        raising `Pool` initializer would be respawned forever and hang the run —
        untested end to end.

        This floor imports cleanly exactly once. The parent preflight consumes
        that import, so every spawned worker fails, which is the only shape that
        reaches the backstop: init stashes, `_worker_run` re-raises, the task
        exception propagates out of `imap_unordered` into `main()`, and the run
        ends with exit 3 instead of spinning up replacement workers forever.
        """
        floor = self.write_floor(
            "once",
            """
            import pathlib

            FLOOR_VERSION = "9.9.9"

            _MARKER = pathlib.Path(__file__).with_name("once.imported")
            if _MARKER.exists():
                raise RuntimeError("this floor imports exactly once")
            _MARKER.write_text("x", encoding="utf-8")


            def command_output(argv, cwd="", timeout=None):
                return ""


            def reads_git_config(project_dir, command_runner=command_output):
                return command_runner(["git", "config"], project_dir)


            def check(command, tier_cfg, project_dir):
                return "allow", ""
            """,
        )
        healthy = self.write_floor(
            "healthy_candidate",
            STUB_DISPATCH.format(version="1.0.0", decide='    return "allow", ""'),
        )
        result = self.run_script(floor, 2, candidate=healthy)
        self.assertEqual(result.returncode, replay.EXIT_TOOL_FAILURE, result.stderr)
        # The parent preflight passed — this is the worker path, not the
        # preflight path, which is the whole point of the case.
        self.assertNotIn("cannot replay:", result.stderr)
        self.assertIn("replay aborted:", result.stderr)
        self.assertIn("replay worker could not start", result.stderr)
        self.assertIn("this floor imports exactly once", result.stderr)
        # No table: a run that lost its workers must never print numbers.
        self.assertNotIn("block rate by tier", result.stdout)


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
        # ...and the unit it is in, which the banner must not mislabel.
        self.assertEqual(
            replay.toolfail_headline(result, replay.count_toolfails(result)),
            ({"baseline": 7, "candidate": 1}, "tier x command replays"),
        )

    def test_the_distinct_command_count_ignores_how_many_tiers_failed(self):
        # One command failing at four tiers is one command, not four.
        verdicts = [
            [(replay.TOOLFAIL, "harness")] * 4,
            [("allow", "")] * 4,
            [("allow", ""), (replay.TOOLFAIL, "harness"), ("deny", "x"), ("allow", "")],
        ]
        self.assertEqual(replay.count_toolfail_commands(verdicts), 2)
        self.assertEqual(replay.count_toolfail_commands([[("allow", "")]]), 0)

    def test_the_headline_prefers_the_recorded_command_count(self):
        result = {
            "tier_order": [1, 2],
            "run": {"toolfail_commands": {"baseline": 3, "candidate": 0}},
            "tiers": {},
        }
        self.assertEqual(
            replay.toolfail_headline(result, {"baseline": 6, "candidate": 0}),
            ({"baseline": 3, "candidate": 0}, "commands"),
        )

    def test_the_banner_counts_commands_not_tier_pairs(self):
        # The whole point of this instrument is that a printed number means
        # what it says; "1 command" was reported as "4 commands" because
        # unique_toolfail is per tier and the four default tiers were summed.
        corpus = self.write_corpus("git push", "git status")
        path = self.dir / "spawning.py"
        path.write_text(textwrap.dedent(SPAWNING_FLOOR).lstrip(), encoding="utf-8")
        json_path = self.dir / "toolfail.json"
        code, text, err = self.run_main(
            "--from-corpus",
            str(corpus),
            "--baseline",
            str(path),
            "--candidate",
            str(path),
            "--project-dir",
            str(self.dir),
            "--json",
            str(json_path),
            "--quiet",
        )
        self.assertEqual(code, replay.EXIT_TOOL_FAILURE)
        result = json.loads(json_path.read_text(encoding="utf-8"))
        run = result["run"]
        # Four default tiers, one failing command: the inflation factor.
        self.assertEqual(len(result["tier_order"]), 4)
        self.assertEqual(run["toolfails"], {"baseline": 4, "candidate": 4})
        self.assertEqual(run["toolfail_commands"], {"baseline": 1, "candidate": 1})
        for stream in (text, err):
            self.assertIn("baseline 1 / candidate 1 commands got no verdict", stream)
            # The per-tier total is still shown, labelled, so the reason rows
            # below it (which are per tier) still add up to something stated.
            self.assertIn("(4 / 4 tier x command replays over 4 tier(s).)", stream)
            self.assertIn("by reason (tier x command replays):", stream)
        self.assertIn(
            "(baseline 1 / candidate 1 commands)",
            text,
        )


class CorpusIntegrityExitTests(EndToEndTestCase):
    """A corpus that came up short must not print as a completed measurement.

    Driven through a real transcript scan rather than `--from-corpus`, because
    the whole point is the path from a filesystem that would not cooperate to
    an exit code a gate can read.
    """

    def scan_scenario(self, *extra, break_a_transcript=True):
        codex = self.dir / "codex-sessions"
        codex.mkdir()
        (codex / "rollout.jsonl").write_text(
            "".join(
                json.dumps(
                    {
                        "payload": {
                            "type": "function_call",
                            "name": "shell_command",
                            "arguments": json.dumps({"command": command}),
                        }
                    }
                )
                + "\n"
                for command in ("git status", "git push")
            ),
            encoding="utf-8",
        )
        if break_a_transcript:
            # A directory named like a transcript: the walk finds it, the open
            # fails with OSError on every supported platform. A real filesystem
            # reaching the counter, not an injected object.
            (codex / "locked.jsonl").mkdir()
        claude = self.dir / "claude-projects"
        claude.mkdir()
        floor = self.write_dispatch("floor", "1.0.0", 'return "allow", ""')
        json_path = self.dir / "run.json"
        code, out, err = self.run_main(
            "--codex-root",
            str(codex),
            "--claude-root",
            str(claude),
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
            *extra,
        )
        return code, out, err, json.loads(json_path.read_text(encoding="utf-8"))

    def test_an_unreadable_transcript_exits_four_with_a_banner(self):
        code, out, err, result = self.scan_scenario()
        self.assertEqual(code, replay.EXIT_CORPUS_INCOMPLETE)
        self.assertNotIn(replay.EXIT_CORPUS_INCOMPLETE, (0, 1))
        # Loud on both streams: a gate may capture only one of them.
        self.assertIn("CORPUS INCOMPLETE", out)
        self.assertIn("CORPUS INCOMPLETE", err)
        # ...and flagged in the ledger, so the row is not read as one of the
        # ~20 "records this corpus deliberately does not model" rows.
        self.assertIn("file-unreadable: 1   <== CORPUS INCOMPLETE", out)
        self.assertEqual(
            result["run"]["corpus_integrity"], {"unparsed-file-unreadable": 1}
        )

    def test_the_banner_labels_the_deltas_subset_only(self):
        _, out, _, _ = self.scan_scenario()
        # The first version of this banner said the deltas "are still sound",
        # which is only true of the subset that was read: a command in the
        # unread transcript is in no bucket, so a regression it would have
        # shown is simply absent from `newly_blocked`.
        self.assertIn("SUBSET-ONLY", out)
        self.assertIn("is not reported", out)
        self.assertIn("ABSOLUTE rate", out)
        self.assertNotIn("DELTAS are still sound", out)

    def test_an_incomplete_corpus_has_no_route_back_to_exit_zero(self):
        # A gate keying on exit 0 must not pass over a scan that omitted the
        # transcripts holding the regression it exists to catch. The downgrade
        # flag that used to allow that is gone; there is no argv that restores
        # it.
        code, out, _, _ = self.scan_scenario()
        self.assertEqual(code, replay.EXIT_CORPUS_INCOMPLETE)
        self.assertIn("CORPUS INCOMPLETE", out)

    def test_the_downgrade_flag_is_gone_rather_than_ignored(self):
        # Rejected by argparse, not silently accepted: a caller whose gate
        # passed on exit 0 because of it has to find out.
        with self.assertRaises(SystemExit):
            self.scan_scenario("--allow-partial-corpus")

    def test_a_complete_scan_exits_zero_with_no_banner(self):
        # The negative control: the same scan without the broken transcript
        # must not learn to cry wolf.
        code, out, _, result = self.scan_scenario(break_a_transcript=False)
        self.assertEqual(code, 0)
        self.assertNotIn("CORPUS INCOMPLETE", out)
        self.assertEqual(result["run"]["corpus_integrity"], {})

    def test_a_tool_failure_still_wins_the_exit_code(self):
        # Precedence: no verdict at all (3) is more fundamental than a short
        # corpus (4). Both banners still print, because a caller reading only
        # one of them would fix only one of the two problems.
        spawning = self.dir / "spawning.py"
        spawning.write_text(textwrap.dedent(SPAWNING_FLOOR).lstrip(), encoding="utf-8")
        code, out, err, _ = self.scan_scenario("--baseline", str(spawning))
        self.assertEqual(code, replay.EXIT_TOOL_FAILURE)
        self.assertIn("CORPUS INCOMPLETE", out)
        self.assertIn("REPLAY TOOL FAILURE", err)
        # ...and the loser must not claim the exit code it did not get. A
        # banner saying "Exiting 4" on a run that returns 3 sends the reader
        # after the wrong failure.
        self.assertIn(f"Exiting {replay.EXIT_TOOL_FAILURE}.", out)
        self.assertNotIn(f"Exiting {replay.EXIT_CORPUS_INCOMPLETE}.", out)

    def test_a_crashing_floor_and_a_short_corpus_agree_on_the_exit_code(self):
        # The other overlap: `check() RAISED` (2) outranks the short corpus (4),
        # so both banners must name 2.
        crashing = self.write_dispatch("crashing", "1.0.0", 'raise ValueError("boom")')
        code, out, _, _ = self.scan_scenario("--baseline", str(crashing))
        self.assertEqual(code, replay.EXIT_ERRORS_PRESENT)
        self.assertIn("check() RAISED", out)
        self.assertIn("CORPUS INCOMPLETE", out)
        self.assertEqual(out.count(f"Exiting {replay.EXIT_ERRORS_PRESENT}."), 2)
        self.assertNotIn(f"Exiting {replay.EXIT_CORPUS_INCOMPLETE}.", out)

    def test_allow_errors_hands_the_exit_code_back_to_the_corpus(self):
        # With the crash censused rather than fatal, 4 is what is left, and
        # the corpus banner has to say so.
        crashing = self.write_dispatch("crashing", "1.0.0", 'raise ValueError("boom")')
        code, out, _, _ = self.scan_scenario(
            "--baseline", str(crashing), "--allow-errors"
        )
        self.assertEqual(code, replay.EXIT_CORPUS_INCOMPLETE)
        self.assertIn(f"Exiting {replay.EXIT_CORPUS_INCOMPLETE}.", out)


class UnreadableCorpusTests(EndToEndTestCase):
    """Nothing extracted because nothing could be read is not an empty corpus.

    Every transcript failing to open produces an empty corpus AND a full
    integrity ledger. `main()` returned 1 from its `if not corpus` branch before
    the integrity classification ran, so the run had neither the banner nor
    exit 4 and was indistinguishable from a genuinely empty transcript tree —
    the exact exit-code ambiguity the new code claims to remove.
    """

    def run_scan(self, codex, claude, *extra):
        floor = self.write_dispatch("floor", "1.0.0", 'return "allow", ""')
        return self.run_main(
            "--codex-root",
            str(codex),
            "--claude-root",
            str(claude),
            "--baseline",
            str(floor),
            "--candidate",
            str(floor),
            "--tier",
            "2",
            "--project-dir",
            str(self.dir),
            "--quiet",
            *extra,
        )

    def test_a_wholly_unreadable_tree_exits_four_not_one(self):
        codex = self.dir / "codex-sessions"
        codex.mkdir()
        # Every discovered "transcript" is a directory: the walk finds them,
        # every open fails, and the corpus comes out empty.
        for name in ("a.jsonl", "b.jsonl"):
            (codex / name).mkdir()
        claude = self.dir / "claude-projects"
        claude.mkdir()
        code, out, err = self.run_scan(codex, claude)
        self.assertEqual(code, replay.EXIT_CORPUS_INCOMPLETE)
        self.assertNotEqual(code, 1)
        self.assertIn("CORPUS INCOMPLETE", out)
        self.assertIn("CORPUS INCOMPLETE", err)
        self.assertIn("2  file-unreadable", out)
        self.assertIn("broken scan, not an empty corpus", err)

    def test_a_genuinely_empty_tree_still_exits_one(self):
        # The negative control that keeps 4 meaning something: readable and
        # empty is a different answer from unreadable.
        codex = self.dir / "codex-sessions"
        codex.mkdir()
        claude = self.dir / "claude-projects"
        claude.mkdir()
        code, out, err = self.run_scan(codex, claude)
        self.assertEqual(code, 1)
        self.assertNotIn("CORPUS INCOMPLETE", out)
        self.assertIn("nothing to replay", err)

    def test_a_missing_root_is_corpus_incompleteness(self):
        # A root that was asked for and is not there withholds an entire
        # runtime's transcripts — the largest silent shortfall available.
        codex = self.dir / "codex-sessions"
        codex.mkdir()
        (codex / "rollout.jsonl").write_text(
            json.dumps(
                {
                    "payload": {
                        "type": "function_call",
                        "name": "shell_command",
                        "arguments": json.dumps({"command": "git status"}),
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )
        code, out, _ = self.run_scan(codex, self.dir / "no-such-claude-tree")
        self.assertEqual(code, replay.EXIT_CORPUS_INCOMPLETE)
        self.assertIn("claude-root-missing", out)

    def test_none_declares_a_runtime_deliberately_unscanned(self):
        # Otherwise a machine that runs only one of the two runtimes could
        # never get a clean exit, and a permanently red gate teaches people to
        # ignore it.
        codex = self.dir / "codex-sessions"
        codex.mkdir()
        (codex / "rollout.jsonl").write_text(
            json.dumps(
                {
                    "payload": {
                        "type": "function_call",
                        "name": "shell_command",
                        "arguments": json.dumps({"command": "git status"}),
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )
        code, out, _ = self.run_scan(codex, "none")
        self.assertEqual(code, 0)
        self.assertNotIn("CORPUS INCOMPLETE", out)
        self.assertIsNone(replay.transcript_root("none"))
        self.assertIsNone(replay.transcript_root(""))
        self.assertEqual(replay.transcript_root("x"), Path("x"))


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

    def test_a_mid_file_read_error_is_counted_not_swallowed(self):
        """The open succeeded; the read fails partway through the file.

        Injected, because there is no portable way to make a real file raise on
        its second read. What this proves is the branch's accounting and that
        the records read before the failure are still yielded — not that any
        particular filesystem reaches it.
        """
        good = json.dumps({"payload": {"type": "function_call"}}) + "\n"

        class FailingHandle:
            def __init__(self, error):
                self.error = error
                self.lines = iter([good])

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                line = next(self.lines, None)
                if line is None:
                    raise self.error
                return line

        class FailingPath:
            def __init__(self, error):
                self.error = error

            def open(self, encoding=None, errors=None):
                return FailingHandle(self.error)

        for error in (OSError("device read error"), UnicodeError("bad decode")):
            with self.subTest(error=type(error).__name__):
                stats = Counter()
                records = list(replay.iter_jsonl(FailingPath(error), stats))
                # Truncated, not lost: the prefix is real data.
                self.assertEqual(len(records), 1)
                self.assertEqual(stats["unparsed-file-read-error"], 1)

    def test_every_integrity_key_is_one_the_extractor_actually_writes(self):
        # A key renamed in one place and not the other would silently stop
        # triggering the banner, which is the whole failure mode being fixed.
        stats = Counter()
        with tempfile.TemporaryDirectory() as tmp:
            list(replay.iter_jsonl(Path(tmp), stats))

        class Unwalkable:
            def rglob(self, pattern):
                raise PermissionError("locked")

        replay.iter_transcripts(Unwalkable(), stats)
        for key in ("unparsed-file-unreadable", "unparsed-transcript-tree-unwalkable"):
            self.assertIn(key, replay.CORPUS_INTEGRITY_KEYS)
            self.assertEqual(stats[key], 1)
        self.assertIn("unparsed-file-read-error", replay.CORPUS_INTEGRITY_KEYS)

    def test_a_missing_verdict_aborts_instead_of_being_defaulted(self):
        with self.assertRaises(replay.ReplayHarnessError) as caught:
            replay.assert_every_command_replayed(
                [[("allow", "")], None], [[("allow", "")], [("allow", "")]]
            )
        self.assertIn("1 of 2", str(caught.exception))
        # The complete case must stay silent.
        replay.assert_every_command_replayed([[("allow", "")]], [[("allow", "")]])

    def test_a_short_batch_reaches_the_guard_through_replay(self):
        """The guard's real trigger, exercised where it actually sits.

        Not an OOM-killed worker: `Pool.imap_unordered` blocks forever on a
        result that never arrives, so that shape hangs and never reaches here
        (see COVERAGE LIMITS). What does reach it is bookkeeping coming up
        short, so that is what is injected — a `_worker_run` that returns a
        batch shorter than the chunk it was handed, exactly what a chunking or
        result-mapping refactor would produce.
        """
        with tempfile.TemporaryDirectory() as tmp:
            floor = Path(tmp) / "floor.py"
            floor.write_text(
                STUB_DISPATCH.format(version="1.0.0", decide='    return "allow", ""'),
                encoding="utf-8",
            )
            real_worker_run = replay._worker_run

            def short_batch(chunk):
                batch, reads = real_worker_run(chunk)
                return batch[:-1], reads

            replay._worker_run = short_batch
            try:
                with self.assertRaises(replay.ReplayHarnessError) as caught:
                    replay.replay(
                        ["git status", "git log"],
                        floor,
                        floor,
                        (2,),
                        tmp,
                        jobs=1,
                        progress=False,
                    )
            finally:
                replay._worker_run = real_worker_run
        self.assertIn("1 of 2", str(caught.exception))
        self.assertIn("not usable", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
