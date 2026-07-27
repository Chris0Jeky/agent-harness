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
