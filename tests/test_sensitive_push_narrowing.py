"""Issue #48: the sensitive-root push deny gains its ratified attribution exemption.

A session rooted in a `sensitive_data` repo carries that overlay into every
push (`load_tier` unions the cwd and CLAUDE_PROJECT_DIR chains), so estate-wide
sessions could never push ANY public repo — a guard with no sanctioned
completion path. The owner-ratified narrowing (issue #48, reaffirmed
2026-07-27) allows exactly the attributable shape: a repository that declares
its OWN tier with `sensitive_data: false`, pushing its OWN named local
branches (or HEAD, or a refspec-less push) to a configured remote NAME.

Because this is a RELAXATION, every case here is pinned in both directions:
the newly-allowed shape allows, and each dangerous neighbour — URL and path
destinations, --repo URLs, selectors, deletions, forces, wildcards, raw SHAs,
remote-tracking refs, tags, undeclared repositories, self-sensitive
repositories, repositories physically nested inside a sensitive root, and
unresolvable working directories — still keeps the context deny. The accepted
residual (a local branch created from fetched foreign objects) is pinned as
ALLOWED on purpose: it is the documented FLOOR_LIMITATIONS.md line, and this
test failing UNEXPECTEDLY would mean the documented behaviour drifted.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"

_spec = importlib.util.spec_from_file_location("dispatch_issue48", DISPATCH_PATH)
dispatch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dispatch)

_env_spec = importlib.util.spec_from_file_location(
    "floor_environment_issue48", ROOT / "tests" / "floor_environment.py"
)
floor_environment = importlib.util.module_from_spec(_env_spec)
_env_spec.loader.exec_module(floor_environment)

GIT = shutil.which("git")

SENSITIVE_CFG = {"tier": 3, "flags": {"sensitive_data": True}}


def _public_resolver(*_args, **_kwargs):
    return True, "example/thing"


def checked(command: str, project_dir: str, **kwargs):
    """The real check() with the host's Git launch configuration removed."""
    return floor_environment.hermetic_check(
        dispatch, command, SENSITIVE_CFG, project_dir, **kwargs
    )


@unittest.skipUnless(GIT, "requires a real git binary")
class SensitivePushNarrowingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="floor-issue48-")
        cls.nonsensitive = os.path.join(cls.root, "nonsensitive")
        cls._make_repo(
            cls.nonsensitive, {"tier": 2, "flags": {"sensitive_data": False}}
        )
        cls.undeclared = os.path.join(cls.root, "undeclared")
        cls._make_repo(cls.undeclared, None)
        cls.self_sensitive = os.path.join(cls.root, "selfsensitive")
        cls._make_repo(
            cls.self_sensitive, {"tier": 2, "flags": {"sensitive_data": True}}
        )
        cls.sensitive_root = os.path.join(cls.root, "sensroot")
        os.makedirs(os.path.join(cls.sensitive_root, ".agent-harness"))
        with open(
            os.path.join(cls.sensitive_root, ".agent-harness", "tier.json"),
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump({"tier": 3, "flags": {"sensitive_data": True}}, handle)
        cls.nested = os.path.join(cls.sensitive_root, "nested")
        cls._make_repo(cls.nested, {"tier": 1, "flags": {"sensitive_data": False}})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    @classmethod
    def _git(cls, cwd, *argv):
        subprocess.run(
            [GIT, *argv],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "floor",
                "GIT_AUTHOR_EMAIL": "floor@test",
                "GIT_COMMITTER_NAME": "floor",
                "GIT_COMMITTER_EMAIL": "floor@test",
            },
        )

    @classmethod
    def _make_repo(cls, path, tier):
        os.makedirs(path, exist_ok=True)
        cls._git(path, "init", "-b", "main")
        with open(os.path.join(path, "seed.txt"), "w", encoding="utf-8") as handle:
            handle.write("seed\n")
        cls._git(path, "add", "seed.txt")
        cls._git(path, "commit", "-m", "seed")
        cls._git(
            path, "remote", "add", "origin", "https://github.com/example/thing.git"
        )
        if tier is not None:
            os.makedirs(os.path.join(path, ".agent-harness"), exist_ok=True)
            with open(
                os.path.join(path, ".agent-harness", "tier.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(tier, handle)

    def narrowing(self, args, cwd):
        with floor_environment.hermetic_environment(dispatch, None):
            return dispatch.sensitive_push_narrowing_status(args, cwd)

    # --- the allowed shape -------------------------------------------------

    def test_named_branch_to_configured_remote_allows(self):
        allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
        self.assertTrue(allowed, detail)

    def test_refspec_less_and_remote_only_allow(self):
        for args in ([], ["origin"]):
            allowed, detail = self.narrowing(args, self.nonsensitive)
            self.assertTrue(allowed, (args, detail))

    def test_head_source_allows(self):
        allowed, detail = self.narrowing(["origin", "HEAD:main"], self.nonsensitive)
        self.assertTrue(allowed, detail)

    def test_end_to_end_check_allows_the_attributable_push(self):
        decision, reason = checked(
            f'git -C "{self.nonsensitive}" push origin main',
            self.sensitive_root,
            remote_resolver=_public_resolver,
        )
        self.assertEqual(decision, "allow", reason)

    def test_documented_residual_local_branch_of_any_provenance_allows(self):
        # FLOOR_LIMITATIONS.md pins this: attribution checks names, not object
        # provenance. If this starts denying, the documented line drifted.
        self._git(self.nonsensitive, "branch", "-f", "imported", "main")
        allowed, detail = self.narrowing(["origin", "imported"], self.nonsensitive)
        self.assertTrue(allowed, detail)

    # --- every dangerous neighbour keeps the deny --------------------------

    def test_url_and_path_destinations_keep_the_deny(self):
        for destination in (
            "https://github.com/example/thing.git",
            "ssh://git@github.com/example/thing.git",
            "git@github.com:example/thing.git",
            "C:/elsewhere/mirror",
            "../mirror",
            "~/mirror",
        ):
            allowed, detail = self.narrowing([destination, "main"], self.nonsensitive)
            self.assertFalse(allowed, destination)
            self.assertIn("URL", detail)

    def test_repo_option_url_keeps_the_deny(self):
        allowed, detail = self.narrowing(
            ["--repo=https://github.com/example/thing.git"], self.nonsensitive
        )
        self.assertFalse(allowed, detail)

    def test_positional_remote_takes_precedence_over_repo_option(self):
        # git: "if both are specified, the command-line argument takes
        # precedence" — so the URL positional decides, not the benign --repo.
        allowed, detail = self.narrowing(
            ["--repo=origin", "https://github.com/example/thing.git", "main"],
            self.nonsensitive,
        )
        self.assertFalse(allowed, detail)

    def test_selectors_deletions_forces_and_wildcards_keep_the_deny(self):
        for args in (
            ["--all", "origin"],
            ["--tags", "origin"],
            ["--mirror", "origin"],
            ["--delete", "origin", "main"],
            ["origin", ":doomed"],
            ["origin", "+main:main"],
            ["origin", "refs/heads/*:refs/heads/*"],
        ):
            allowed, _detail = self.narrowing(args, self.nonsensitive)
            self.assertFalse(allowed, args)

    def test_non_branch_sources_keep_the_deny(self):
        for source in (
            "0123456789abcdef0123456789abcdef01234567",
            "refs/remotes/origin/main",
            "FETCH_HEAD",
            "no-such-branch",
        ):
            allowed, _detail = self.narrowing(
                ["origin", f"{source}:target"], self.nonsensitive
            )
            self.assertFalse(allowed, source)

    def test_undeclared_repository_keeps_the_deny(self):
        allowed, detail = self.narrowing(["origin", "main"], self.undeclared)
        self.assertFalse(allowed)
        self.assertIn("declares no tier", detail)

    def test_self_sensitive_repository_keeps_the_deny(self):
        allowed, detail = self.narrowing(["origin", "main"], self.self_sensitive)
        self.assertFalse(allowed)
        self.assertIn("itself declares sensitive_data", detail)

    def test_repository_nested_inside_a_sensitive_root_keeps_the_deny(self):
        allowed, detail = self.narrowing(["origin", "main"], self.nested)
        self.assertFalse(allowed)
        self.assertIn("inside a sensitive_data root", detail)

    # --- the PR #132 review round: five bypasses of the ratified conditions ---

    def test_repository_redirecting_git_globals_keep_the_deny(self):
        """The review's CRITICAL, and a regression against the pre-#48 floor.

        `--work-tree=<decoy>` leaves `rev-parse --show-toplevel` naming the
        decoy while the git dir, the remote configuration and the OBJECTS all
        still come from the cwd — so a directory holding nothing but a
        `sensitive_data: false` declaration attributed a SENSITIVE repository's
        push to itself. Only `-C <path>` preserves attribution.
        """
        for git_globals in (
            ["--work-tree=" + self.nonsensitive],
            ["--work-tree", self.nonsensitive],
            ["--git-dir=" + os.path.join(self.self_sensitive, ".git")],
            ["-c", "core.worktree=" + self.nonsensitive],
            ["--namespace=x"],
            ["--bare"],
            ["-C"],  # dangling value
        ):
            with floor_environment.hermetic_environment(dispatch, None):
                allowed, detail = dispatch.sensitive_push_narrowing_status(
                    ["origin", "main"], self.nonsensitive, git_globals
                )
            self.assertFalse(allowed, git_globals)
            self.assertIn("unattributable", detail)

    def test_minus_C_global_still_attributes(self):
        with floor_environment.hermetic_environment(dispatch, None):
            allowed, detail = dispatch.sensitive_push_narrowing_status(
                ["origin", "main"], self.nonsensitive, ["-C", self.nonsensitive]
            )
        self.assertTrue(allowed, detail)

    def test_tag_publishing_and_abbreviated_selectors_keep_the_deny(self):
        # git accepts unambiguous long-option prefixes, so `--al` IS `--all`.
        for args in (
            ["--follow-tags", "origin", "main"],
            ["--al", "origin"],
            ["--tag", "origin"],
            ["--branch", "origin"],
            ["-vd", "origin", "main"],
        ):
            allowed, detail = self.narrowing(args, self.nonsensitive)
            self.assertFalse(allowed, args)
            self.assertIn("selector", detail)

    def test_destination_must_resolve_to_a_configured_remote(self):
        # The URL regex is a pre-filter; these spellings escape it, so the
        # condition is proven by asking the repository instead.
        for destination in (
            "git://evil.example/r.git",
            "rsync://evil.example/r.git",
            "evil.example:r.git",
            "ext::sh -c cat",
            "nosuchremote",
        ):
            allowed, detail = self.narrowing([destination, "main"], self.nonsensitive)
            self.assertFalse(allowed, destination)
            self.assertIn("configured remote", detail)

    def test_refspec_less_push_inheriting_a_configured_refspec_keeps_the_deny(self):
        self._git(self.nonsensitive, "config", "remote.origin.push", "refs/*:refs/*")
        try:
            for args in (["origin"], []):
                allowed, detail = self.narrowing(args, self.nonsensitive)
                self.assertFalse(allowed, args)
                self.assertIn("configured push refspec", detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset", "remote.origin.push")
        # and it goes back to allowed once nothing is inherited
        allowed, detail = self.narrowing(["origin"], self.nonsensitive)
        self.assertTrue(allowed, detail)

    def test_an_undeclared_sensitive_data_flag_is_not_an_implicit_false(self):
        implicit = os.path.join(self.root, "implicitflags")
        self._make_repo(implicit, {"tier": 1, "flags": {}})
        allowed, detail = self.narrowing(["origin", "main"], implicit)
        self.assertFalse(allowed)
        self.assertIn("does not declare sensitive_data", detail)

    def test_linked_worktree_outside_a_sensitive_root_keeps_the_deny(self):
        """Same repository, opposite verdict, decided only by where the
        worktree happens to sit — so containment follows the common dir."""
        # The declaration has to be TRACKED, or the linked worktree has no tier
        # file and the deny comes from the wrong condition.
        self._git(self.nested, "add", "-f", ".agent-harness/tier.json")
        self._git(self.nested, "commit", "-m", "track tier")
        outside = os.path.join(self.root, "outside-worktree")
        self._git(self.nested, "worktree", "add", "--detach", outside, "main")
        self._git(outside, "switch", "-c", "wt-feature")
        # Guard the test's own premise: the worktree really is outside.
        self.assertFalse(
            os.path.normcase(os.path.abspath(outside)).startswith(
                os.path.normcase(os.path.abspath(self.sensitive_root))
            )
        )
        allowed, detail = self.narrowing(["origin", "wt-feature"], outside)
        self.assertFalse(allowed)
        self.assertIn("inside a sensitive_data root", detail)

    def test_refspec_destination_outside_refs_heads_keeps_the_deny(self):
        # A valid branch SOURCE can still write a remote tag: `main:refs/tags/v1`
        # publishes a ref class the ratified condition set excludes.
        for refspec in ("main:refs/tags/v1", "main:refs/notes/x", "main:refs/*"):
            allowed, _detail = self.narrowing(["origin", refspec], self.nonsensitive)
            self.assertFalse(allowed, refspec)
        # the ordinary branch-to-branch spellings still allow
        for refspec in ("main", "main:main", "main:refs/heads/other"):
            allowed, detail = self.narrowing(["origin", refspec], self.nonsensitive)
            self.assertTrue(allowed, (refspec, detail))

    def test_the_narrowing_is_observed_inside_nested_commands(self):
        """The 10 recursive `push_narrowing` forwards were entirely unpinned.

        A review mutation that rewired ALL TEN nested forwards to a divergent
        stub left the full unit suite AND the 2237-case smoke matrix green, so
        a future edit dropping one would ship silently — and the verdict inside
        `bash -c` would diverge from the same command typed directly, which is
        the nesting-dependent behaviour this parameter exists to prevent.
        """
        observed = []

        def stub(*_args, **_kwargs):
            observed.append(1)
            return False, "nested-stub-reached"

        for command in (
            f'git -C "{self.nonsensitive}" push origin main',
            f"bash -c 'git -C \"{self.nonsensitive}\" push origin main'",
            f"sh -c 'git -C \"{self.nonsensitive}\" push origin main'",
            f'env FOO=1 git -C "{self.nonsensitive}" push origin main',
            f'true && git -C "{self.nonsensitive}" push origin main',
        ):
            del observed[:]
            decision, reason = checked(
                command,
                self.sensitive_root,
                remote_resolver=_public_resolver,
                push_narrowing=stub,
            )
            self.assertEqual(decision, "deny", command)
            self.assertIn("nested-stub-reached", reason, command)
            self.assertTrue(observed, f"narrowing never reached for: {command}")

    def test_unresolvable_cwd_keeps_the_deny(self):
        allowed, detail = self.narrowing(
            ["origin", "main"], os.path.join(self.root, "missing")
        )
        self.assertFalse(allowed)
        self.assertIn("unresolved pushed repository", detail)

    def test_end_to_end_deny_names_the_failed_condition(self):
        decision, reason = checked(
            f'git -C "{self.undeclared}" push origin main',
            self.sensitive_root,
            remote_resolver=_public_resolver,
        )
        self.assertEqual(decision, "deny")
        self.assertIn("refusing a push to public remote", reason)
        self.assertIn("issue #48 narrowing", reason)

    def test_private_and_unverified_destinations_are_untouched(self):
        decision, _reason = checked(
            "git push origin main",
            self.sensitive_root,
            remote_resolver=lambda *a, **k: (False, "private"),
        )
        self.assertEqual(decision, "allow")
        decision, reason = checked(
            "git push origin main",
            self.sensitive_root,
            remote_resolver=lambda *a, **k: (None, "unverified"),
        )
        self.assertEqual(decision, "deny")
        self.assertIn("could not verify push remote privacy", reason)


if __name__ == "__main__":
    unittest.main()
