"""Floor 1.8.0: branch history proceeds, tags and --mirror stay guarded (#356 step 2).

The owner retired the client floor's branch-history families on 2026-10-04: every
floored repository protects its default branch server-side with a ruleset, so
force, lease, `+refspec`, branch deletion and `--prune` proceed at every tier,
`sensitive_data` included. The ruleset protects the default branch only, so one
narrow guard stays: a forced or deleting update of a TAG, and `git push --mirror`
(`[tag-guard]`), double-checked under the core posture like local destruction.

A bare destination (`v1.0`) resolves against the remote's refs, which the floor
approximates by the local tags; these tests pin that lookup against real
repositories as well as the pure classification helpers.
"""

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch = load_module("dispatch_tag_guard", DISPATCH_PATH)
floor_environment = load_module(
    "floor_environment_tag_guard", ROOT / "tests" / "floor_environment.py"
)


def _private(*_args, **_kwargs):
    return False, "tag-guard-stub-private"


def git(repo: str, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"},
    )


class HelperTests(unittest.TestCase):
    def test_history_options_and_their_abbreviations(self):
        option = dispatch.git_push_history_option
        self.assertEqual(option("--force"), "--force")
        self.assertEqual(option("--force-with-lease=main:abc"), "--force-with-lease")
        self.assertEqual(option("--forc"), "--force")
        self.assertEqual(option("--mirr"), "--mirror")
        self.assertEqual(option("--m"), "--mirror")
        self.assertEqual(option("--dele"), "--delete")
        self.assertEqual(option("--pru"), "--prune")
        self.assertIsNone(option("--follow-tags"))
        self.assertIsNone(option("--no-force"))
        self.assertIsNone(option("-f"))

    def test_tag_destinations_by_spelling(self):
        may_be_tag = dispatch.git_push_ref_may_be_tag
        for destination in (
            "refs/tags/v1",
            "refs/Tags/v1",
            "tags/v1",
            "refs/tags/*",
            "refs/*",
            "*",
            "refs/t*/x",
        ):
            with self.subTest(destination=destination):
                self.assertTrue(may_be_tag(destination, set()))
        for destination in (
            "refs/heads/main",
            "refs/heads/*",
            "refs/notes/commits",
            "heads/main",
            "remotes/origin/main",
            "HEAD",
            "feature/x",
        ):
            with self.subTest(destination=destination):
                self.assertFalse(may_be_tag(destination, set()))

    def test_a_bare_name_is_a_tag_when_local_tags_say_so_or_cannot_be_read(self):
        may_be_tag = dispatch.git_push_ref_may_be_tag
        self.assertTrue(may_be_tag("v1.0", {"v1.0"}))
        self.assertFalse(may_be_tag("v1.0", {"v2.0"}))
        self.assertTrue(may_be_tag("feature/x", None))
        self.assertFalse(may_be_tag("refs/heads/feature/x", None))

    def test_history_targets(self):
        targets = dispatch.git_push_history_targets
        self.assertEqual(targets(["main"], False, False, False), [])
        self.assertEqual(targets(["main"], True, False, False), [("main", "force")])
        self.assertEqual(
            targets(["+HEAD:refs/tags/v1"], False, False, False),
            [("refs/tags/v1", "force")],
        )
        self.assertEqual(targets([":v1"], False, False, False), [("v1", "delete")])
        self.assertEqual(
            targets(["+v1", "main:v2"], False, True, False),
            [("v1", "delete"), ("v2", "delete")],
        )
        self.assertEqual(
            targets(["tag", "v1"], True, False, False), [("refs/tags/v1", "force")]
        )
        self.assertEqual(targets(["tag", "v1"], False, False, False), [])
        self.assertEqual(targets([":", "+:", "^refs/tags/x"], True, False, False), [])
        self.assertEqual(
            targets(["refs/tags/*:refs/tags/*"], False, False, True),
            [("refs/tags/*", "prune")],
        )
        self.assertEqual(targets(["main:"], True, False, False), [("main", "force")])
        # a colon-less HEAD pushes the current branch
        self.assertEqual(targets(["HEAD", "@"], True, False, False), [])

    def test_option_walk_honours_values_and_negation(self):
        flags = dispatch.git_push_history_flags
        self.assertEqual(flags(["-o", "--mirror", "origin", "main"]), set())
        self.assertEqual(flags(["--force", "--no-force", "origin"]), set())
        self.assertEqual(flags(["--no-force", "--force", "origin"]), {"--force"})
        self.assertEqual(flags(["origin", "main", "-fd"]), {"--force", "--delete"})
        self.assertEqual(flags(["--", "--mirror"]), set())
        self.assertEqual(flags(["--push-option", "--prune", "origin"]), set())

    def test_git_booleans(self):
        true = dispatch.git_config_bool_is_true
        for value in ("", "true", "YES", "on", "1", "2", "-1", "1k"):
            with self.subTest(value=value):
                self.assertTrue(true(value))
        for value in ("false", "no", "off", "0", "+0", "maybe"):
            with self.subTest(value=value):
                self.assertFalse(true(value))

    def test_bare_names(self):
        # git also tries refs/tags/<name> for heads/x, remotes/x and HEAD, so a
        # local tag of that name decides them (review of #466).
        bare = dispatch.git_push_ref_is_bare_name
        for name in ("v1.0", "feature/x", "heads/x", "remotes/o/x", "HEAD"):
            with self.subTest(name=name):
                self.assertTrue(bare(name))
        for name in ("refs/heads/x", "tags/v1", "a*"):
            with self.subTest(name=name):
                self.assertFalse(bare(name))


@unittest.skipUnless(shutil.which("git"), "git is required")
class LocalTagRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = tempfile.mkdtemp(prefix="floor-tag-guard-")
        git(cls.repo, "init", "-q", "-b", "main")
        git(
            cls.repo,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "init",
        )
        git(cls.repo, "tag", "v1.0")
        git(cls.repo, "tag", "release")
        git(cls.repo, "tag", "v2/rc1")
        git(cls.repo, "branch", "release")
        git(cls.repo, "branch", "feature/x")
        git(cls.repo, "remote", "add", "origin", "https://example.invalid/repo.git")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.repo, ignore_errors=True)

    def decide(self, command, tier=2, flags=None, posture="wall"):
        cfg = {"tier": tier, "flags": flags or {}, "floor_posture": posture}
        return floor_environment.hermetic_check(
            dispatch, command, cfg, self.repo, remote_resolver=_private
        )

    def test_lookup_answers_exact_tag_names_only(self):
        found = dispatch.local_tag_names(
            self.repo, ["v1.0", "release", "v2", "feature/x", "nope"]
        )
        self.assertEqual(found, {"v1.0", "release"})

    def test_lookup_outside_a_repository_reads_as_no_tags(self):
        outside = tempfile.mkdtemp(prefix="floor-tag-guard-norepo-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        self.assertEqual(dispatch.local_tag_names(outside, ["v1.0"]), set())

    def test_forced_or_deleting_pushes_of_a_local_tag_deny(self):
        for command in (
            "git push --force origin v1.0",
            "git push -f origin release",
            "git push origin +v1.0",
            "git push origin :v1.0",
            "git push --delete origin v1.0",
            "git push origin --force main:v1.0",
            "git push --force-with-lease origin HEAD:v1.0",
            "git push --prune origin v1.0",
        ):
            with self.subTest(command=command):
                decision, reason = self.decide(command)
                self.assertEqual(decision, "deny", reason)
                self.assertIn("[tag-guard]", reason)

    def test_branch_history_proceeds_at_every_posture_and_overlay(self):
        for tier, flags in (
            (1, {}),
            (3, {}),
            (4, {}),
            (2, {"wave_mode": True}),
            (2, {"sensitive_data": True}),
        ):
            for command in (
                "git push --force origin feature/x",
                "git push --force-with-lease origin HEAD:main",
                "git push origin +main",
                "git push origin --delete feature/x",
                "git push origin :refs/heads/main",
                "git push --prune origin 'refs/heads/*:refs/heads/*'",
                "git push --force --all origin",
                "git push --force --follow-tags origin feature/x",
                "git push origin v1.0",
            ):
                with self.subTest(tier=tier, flags=flags, command=command):
                    decision, reason = self.decide(command, tier, flags)
                    self.assertEqual(decision, "allow", reason)

    def test_a_repository_override_makes_bare_names_unresolvable(self):
        decision, reason = self.decide(
            "GIT_DIR=/other/repo/.git git push --force origin feature/x"
        )
        self.assertEqual(decision, "deny", reason)
        self.assertIn("[tag-guard]", reason)
        decision, reason = self.decide(
            "GIT_DIR=/other/repo/.git git push --force origin refs/heads/feature/x"
        )
        self.assertNotIn("[tag-guard]", reason)

    def test_tags_selector_and_mirror(self):
        for command in (
            "git push --force --tags origin",
            "git push --prune --tags origin",
            "git push --mirror origin",
            "git push --mirr",
            "git push origin $REF --mirror",
        ):
            with self.subTest(command=command):
                decision, reason = self.decide(command)
                self.assertEqual(decision, "deny", reason)
                self.assertIn("[tag-guard]", reason)
        self.assertEqual(self.decide("git push --tags origin")[0], "allow")


@unittest.skipUnless(shutil.which("git"), "git is required")
class ReviewRoundOneTests(unittest.TestCase):
    """Defects the two review lenses on #466 found, each pinned against a real repo."""

    WALL = {"tier": 2, "flags": {}, "floor_posture": "wall"}
    CORE = {"tier": 2, "flags": {}}

    def repo(self, *config):
        repo = tempfile.mkdtemp(prefix="floor-tag-guard-r1-")
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        git(repo, "init", "-q", "-b", "main")
        git(
            repo,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "init",
        )
        for tag in ("v1", "heads/release", "remotes/release"):
            git(repo, "tag", tag)
        git(repo, "remote", "add", "origin", "https://example.invalid/repo.git")
        for key, value in config:
            git(repo, "config", key, value)
        return repo

    def render(self, command, repo, cfg):
        decision, reason = floor_environment.hermetic_check(
            dispatch, command, cfg, repo, remote_resolver=_private
        )
        masked = None
        if (
            dispatch.floor_posture(cfg) == "core"
            and decision != "allow"
            and not dispatch.verdict_is_core(decision, reason)
        ):
            masked = dispatch.masked_segment_verdict(
                dispatch.core_hint_text(command),
                cfg,
                repo,
                repo,
                dispatch.check,
                accepts=dispatch.verdict_is_core,
            )
        rendered = dispatch.apply_floor_posture(
            decision, reason, command, None, cfg, masked
        )
        if "DOUBLE-CHECK" in rendered[1]:
            return "double-check"
        return rendered[0]

    def check_cases(self, cases):
        for config, command, cfg, expected in cases:
            with self.subTest(config=config, command=command):
                self.assertEqual(
                    self.render(command, self.repo(*config), cfg), expected
                )

    def test_configured_bare_tag_refspecs_are_looked_up(self):
        self.check_cases(
            [
                ([("remote.origin.push", ":v1")], "git push origin", self.WALL, "deny"),
                ([("remote.origin.push", "+v1")], "git push origin", self.WALL, "deny"),
                (
                    [("remote.origin.push", "+main")],
                    "git push origin",
                    self.WALL,
                    "allow",
                ),
            ]
        )

    def test_namespace_looking_tag_names_are_looked_up(self):
        self.check_cases(
            [
                ([], "git push origin --delete heads/release", self.WALL, "deny"),
                ([], "git push --force origin remotes/release", self.WALL, "deny"),
                ([], "git push origin --delete heads/main", self.WALL, "allow"),
                ([], "git push --force origin HEAD", self.WALL, "allow"),
            ]
        )

    def test_one_character_mirror_and_inherited_mirror(self):
        mirror = [("remote.origin.mirror", "true")]
        tag_refspec = [("remote.origin.push", "+refs/tags/*:refs/tags/*")]
        self.check_cases(
            [
                ([], "git push --m origin", self.WALL, "deny"),
                (mirror, "git push --tags origin", self.WALL, "deny"),
                (mirror, "git push origin 2>&1", self.WALL, "deny"),
                ([("remote.origin.mirror", "2")], "git push origin", self.WALL, "deny"),
                (
                    [("remote.origin.mirror", "0")],
                    "git push origin",
                    self.WALL,
                    "allow",
                ),
                ([], "git push --all origin", self.WALL, "allow"),
                (tag_refspec, "git push --tags origin", self.WALL, "allow"),
            ]
        )

    def test_core_double_checks_a_tag_spelling_behind_an_earlier_verdict(self):
        core = self.CORE
        self.check_cases(
            [
                ([], "git push --force origin refs/tags/{v1,v2}", core, "double-check"),
                (
                    [],
                    "git push --delete origin refs/tags/v1 --push-o=x",
                    core,
                    "double-check",
                ),
                (
                    [],
                    "git push --receive-pack=rp --mirror backup",
                    core,
                    "double-check",
                ),
                (
                    [],
                    "git -c remote.backup.mirror=true push backup",
                    core,
                    "double-check",
                ),
                ([], "X=; git push origin $X :refs/tags/v1", core, "double-check"),
                (
                    [],
                    "git -c color.ui=never push --mirror origin",
                    core,
                    "double-check",
                ),
                ([], "git push origin $BRANCH", core, "allow"),
            ]
        )

    def test_option_values_and_cancelled_flags_are_not_tag_guard_verdicts(self):
        wall = self.WALL
        self.check_cases(
            [
                ([], "git push -o --mirror origin main", wall, "allow"),
                ([], "git push --force --no-force origin refs/tags/v1", wall, "allow"),
                ([], "git push --mirror --no-mirror origin main", wall, "allow"),
                ([], "git push --no-force --force origin refs/tags/v1", wall, "deny"),
                ([], "git push origin refs/tags/v1 --force", wall, "deny"),
            ]
        )

    def test_the_tag_hint_stays_linear(self):
        import time

        for text in (
            "git push " * 2500,
            "git push " + "--mi" * 5000,
            "git push " + "tags/" * 4000,
            "git x push --m; " * 1250,
        ):
            started = time.perf_counter()
            dispatch.command_carries_core_hint(text)
            self.assertLess(time.perf_counter() - started, 1.0)


class PostureRenderingTests(unittest.TestCase):
    T3_CORE = {"tier": 3, "flags": {}}
    T3_GUIDE = {"tier": 3, "flags": {}, "floor_posture": "guide"}
    T4 = {"tier": 4, "flags": {}}

    def test_tag_guard_reasons_are_core_and_never_opacity(self):
        for name in (
            "_TAG_GUARD_MIRROR",
            "_TAG_GUARD_FORCE",
            "_TAG_GUARD_DELETE",
            "_TAG_GUARD_PRUNE",
            "_TAG_GUARD_CONFIG",
            "_TAG_GUARD_UNRESOLVED",
        ):
            reason = getattr(dispatch, name)
            with self.subTest(name=name):
                self.assertFalse(dispatch.reason_is_pure_opacity(reason))
                self.assertTrue(dispatch.verdict_is_core("deny", reason))

    def test_core_and_guide_double_check_a_tag_force_and_t4_walls_it(self):
        command = "git push --force origin refs/tags/v1"
        verdict = ("deny", dispatch._TAG_GUARD_FORCE)
        for cfg in (self.T3_CORE, self.T3_GUIDE):
            with self.subTest(cfg=cfg):
                first = dispatch.apply_floor_posture(*verdict, command, None, cfg)
                self.assertEqual(first[0], "deny")
                self.assertIn("DOUBLE-CHECK", first[1])
                key = dispatch.floor_ack_key(verdict[1], command)
                self.assertEqual(
                    dispatch.apply_floor_posture(*verdict, command, key, cfg),
                    ("allow", ""),
                )
        self.assertEqual(
            dispatch.apply_floor_posture(*verdict, command, None, self.T4), verdict
        )


if __name__ == "__main__":
    unittest.main()
