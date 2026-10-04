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
            "@",
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

    def test_bare_names(self):
        bare = dispatch.git_push_ref_is_bare_name
        self.assertTrue(bare("v1.0"))
        self.assertTrue(bare("feature/x"))
        for name in ("refs/heads/x", "tags/v1", "heads/x", "remotes/o/x", "HEAD", "a*"):
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
