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
from unittest import mock

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
        cls.public_sensitive = os.path.join(cls.root, "public-sensitive")
        cls._make_repo(
            cls.public_sensitive,
            {
                "tier": 2,
                "flags": {"sensitive_data": True},
                "public_synthetic_publication": {
                    "remote": "origin",
                    "repository": "example/thing",
                },
            },
        )
        cls._git(cls.public_sensitive, "branch", "feature/demo", "main")
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
    def _git_env(cls):
        return {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "floor",
            "GIT_AUTHOR_EMAIL": "floor@test",
            "GIT_COMMITTER_NAME": "floor",
            "GIT_COMMITTER_EMAIL": "floor@test",
        }

    @classmethod
    def _git(cls, cwd, *argv):
        completed = subprocess.run(
            [GIT, *argv],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            env=cls._git_env(),
        )
        return completed.stdout.strip()

    @classmethod
    def _git_boolean(cls, cwd, key):
        """Real git's own verdict for `key`: True, False, or None if rejected.

        Every issue #201 expectation is measured through this probe first, so
        the tables below cannot drift away from git's C boolean parser.
        """
        completed = subprocess.run(
            [GIT, "config", "--bool", "--get", key],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            env=cls._git_env(),
        )
        if completed.returncode != 0:
            return None
        return {"true": True, "false": False}[completed.stdout.strip()]

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

    def narrowing(self, args, cwd, command_runner=None):
        with floor_environment.hermetic_environment(dispatch, None):
            kwargs = {"command_runner": command_runner} if command_runner else {}
            return dispatch.sensitive_push_narrowing_status(args, cwd, **kwargs)

    def narrowing_with_failed_config_probe(self, args, cwd):
        failed = False

        def fail_once(argv, project_dir):
            nonlocal failed
            if not failed and argv[-3:] == ["config", "--null", "--list"]:
                failed = True
                return ""
            return dispatch.command_output(argv, project_dir)

        result = self.narrowing(args, cwd, fail_once)
        self.assertTrue(failed, "the config-list failure fixture did not fire")
        return result

    # --- the allowed shape -------------------------------------------------

    def test_named_branch_to_configured_remote_allows(self):
        allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
        self.assertTrue(allowed, detail)

    def test_refspec_less_and_remote_only_allow(self):
        for args in ([], ["origin"]):
            allowed, detail = self.narrowing(args, self.nonsensitive)
            self.assertTrue(allowed, (args, detail))

    def test_head_source_allows(self):
        for refspec in ("HEAD", "HEAD:refs/heads/main"):
            allowed, detail = self.narrowing(["origin", refspec], self.nonsensitive)
            self.assertTrue(allowed, (refspec, detail))

    def test_end_to_end_check_allows_the_attributable_push(self):
        decision, reason = checked(
            f'git -C "{self.nonsensitive}" push origin main',
            self.sensitive_root,
            remote_resolver=_public_resolver,
        )
        self.assertEqual(decision, "allow", reason)

    def test_self_sensitive_exact_publication_route_allows(self):
        allowed, detail = self.narrowing(["origin", "main"], self.public_sensitive)
        self.assertTrue(allowed, detail)
        decision, reason = checked(
            f'git -C "{self.public_sensitive}" push origin main',
            self.public_sensitive,
            remote_resolver=_public_resolver,
        )
        self.assertEqual(decision, "allow", reason)

    def test_self_sensitive_route_requires_exactly_one_refspec(self):
        allowed, detail = self.narrowing(
            ["origin", "main", "feature/demo"], self.public_sensitive
        )
        self.assertFalse(allowed, detail)
        self.assertIn("exactly one", detail)

        decision, reason = checked(
            f'git -C "{self.public_sensitive}" push origin main feature/demo',
            self.public_sensitive,
            remote_resolver=_public_resolver,
        )
        self.assertEqual(decision, "deny", reason)
        self.assertIn("exactly one", reason)

    def test_self_sensitive_route_rejects_configured_transport_overrides(self):
        original_url = self._git(self.public_sensitive, "remote", "get-url", "origin")
        try:
            for key, remote_url in (
                ("core.sshCommand", "git@github.com:example/thing.git"),
                ("core.gitProxy", "git://github.com/example/thing.git"),
                ("remote.origin.receivepack", "git@github.com:example/thing.git"),
                ("remote.origin.vcs", "https://github.com/example/thing.git"),
            ):
                with self.subTest(key=key, remote_url=remote_url):
                    self._git(
                        self.public_sensitive,
                        "remote",
                        "set-url",
                        "origin",
                        remote_url,
                    )
                    self._git(self.public_sensitive, "config", key, "synthetic-helper")
                    try:
                        allowed, detail = self.narrowing(
                            ["origin", "main"], self.public_sensitive
                        )
                        self.assertFalse(allowed, detail)
                        self.assertIn("transport/receiver override", detail)

                        decision, reason = checked(
                            f'git -C "{self.public_sensitive}" push origin main',
                            self.public_sensitive,
                            remote_resolver=_public_resolver,
                        )
                        self.assertEqual(decision, "deny", reason)
                        self.assertIn("transport/receiver override", reason)
                    finally:
                        self._git(self.public_sensitive, "config", "--unset-all", key)

            self._git(
                self.public_sensitive,
                "remote",
                "set-url",
                "origin",
                original_url,
            )
            for key in ("remote.backup.receivepack", "remote.backup.vcs"):
                self._git(
                    self.public_sensitive,
                    "config",
                    key,
                    "synthetic-helper",
                )
                try:
                    allowed, detail = self.narrowing(
                        ["origin", "main"], self.public_sensitive
                    )
                    self.assertTrue(allowed, detail)
                finally:
                    self._git(
                        self.public_sensitive,
                        "config",
                        "--unset-all",
                        key,
                    )
        finally:
            self._git(
                self.public_sensitive,
                "remote",
                "set-url",
                "origin",
                original_url,
            )

    def test_self_sensitive_route_rejects_command_line_receiver_overrides(self):
        for args in (
            ["--receive-pack", "synthetic-helper", "origin", "main"],
            ["--receive-pack=synthetic-helper", "origin", "main"],
            ["--exec", "synthetic-helper", "origin", "main"],
            ["--exec=synthetic-helper", "origin", "main"],
        ):
            with self.subTest(args=args):
                allowed, detail = self.narrowing(args, self.public_sensitive)
                self.assertFalse(allowed, detail)
                self.assertIn("transport/receiver override", detail)

    def test_self_sensitive_route_is_explicit_remote_only(self):
        for args in (
            [],
            ["origin"],
            ["--repo=origin"],
            ["main"],
            ["--repo=other", "main"],
        ):
            with self.subTest(args=args):
                allowed, detail = self.narrowing(args, self.public_sensitive)
                self.assertFalse(allowed, detail)

    def test_self_sensitive_route_forbids_force_with_lease(self):
        for option in (
            "--force-with-lease",
            "--force-with-lease=feature/demo",
        ):
            with self.subTest(option=option):
                decision, reason = checked(
                    f'git -C "{self.public_sensitive}" push {option} origin feature/demo',
                    self.public_sensitive,
                    remote_resolver=_public_resolver,
                )
                self.assertEqual(decision, "deny")
                self.assertIn("forbids force-with-lease", reason)

    def test_self_sensitive_route_requires_the_declared_repository(self):
        mismatched = os.path.join(self.root, "public-sensitive-mismatch")
        self._make_repo(
            mismatched,
            {
                "tier": 2,
                "flags": {"sensitive_data": True},
                "public_synthetic_publication": {
                    "remote": "origin",
                    "repository": "example/other",
                },
            },
        )
        allowed, detail = self.narrowing(["origin", "main"], mismatched)
        self.assertFalse(allowed)
        self.assertIn("repository does not match", detail)

    def test_self_sensitive_route_rejects_another_configured_remote(self):
        self._git(
            self.public_sensitive,
            "remote",
            "add",
            "backup",
            "https://github.com/example/thing.git",
        )
        try:
            allowed, detail = self.narrowing(["backup", "main"], self.public_sensitive)
        finally:
            self._git(self.public_sensitive, "remote", "remove", "backup")
        self.assertFalse(allowed)
        self.assertIn("remote does not match", detail)

    def test_self_sensitive_route_validates_pushurl_not_fetch_url(self):
        pushurl = os.path.join(self.root, "public-sensitive-pushurl")
        self._make_repo(
            pushurl,
            {
                "tier": 2,
                "flags": {"sensitive_data": True},
                "public_synthetic_publication": {
                    "remote": "origin",
                    "repository": "example/thing",
                },
            },
        )
        self._git(
            pushurl,
            "remote",
            "set-url",
            "--push",
            "origin",
            "https://github.com/example/other.git",
        )
        allowed, detail = self.narrowing(["origin", "main"], pushurl)
        self.assertFalse(allowed)
        self.assertIn("repository does not match", detail)

    def test_self_sensitive_route_rejects_multiple_push_urls(self):
        multiple = os.path.join(self.root, "public-sensitive-pushurls")
        self._make_repo(
            multiple,
            {
                "tier": 2,
                "flags": {"sensitive_data": True},
                "public_synthetic_publication": {
                    "remote": "origin",
                    "repository": "example/thing",
                },
            },
        )
        self._git(
            multiple,
            "remote",
            "set-url",
            "--add",
            "--push",
            "origin",
            "https://github.com/example/thing.git",
        )
        self._git(
            multiple,
            "remote",
            "set-url",
            "--add",
            "--push",
            "origin",
            "https://github.com/example/thing.git",
        )
        allowed, detail = self.narrowing(["origin", "main"], multiple)
        self.assertFalse(allowed)
        self.assertIn("multiple push URLs", detail)

    def test_self_sensitive_route_needs_unanimous_co_declarations(self):
        legacy = os.path.join(self.public_sensitive, ".claude")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "tier.json"), "w", encoding="utf-8") as handle:
            json.dump({"tier": 2, "flags": {"sensitive_data": True}}, handle)
        try:
            allowed, detail = self.narrowing(["origin", "main"], self.public_sensitive)
        finally:
            shutil.rmtree(legacy)
        self.assertFalse(allowed)
        self.assertIn("itself declares sensitive_data", detail)

    def test_self_sensitive_route_accepts_identical_co_declarations_only(self):
        agreeing = os.path.join(self.root, "public-sensitive-agreeing")
        publication = {"remote": "origin", "repository": "example/thing"}
        declaration = {
            "tier": 2,
            "flags": {"sensitive_data": True},
            "public_synthetic_publication": publication,
        }
        self._make_repo(agreeing, declaration)
        legacy = os.path.join(agreeing, ".claude")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "tier.json"), "w", encoding="utf-8") as handle:
            json.dump(declaration, handle)
        allowed, detail = self.narrowing(["origin", "main"], agreeing)
        self.assertTrue(allowed, detail)

        declaration["public_synthetic_publication"] = {
            "remote": "origin",
            "repository": "example/other",
        }
        with open(os.path.join(legacy, "tier.json"), "w", encoding="utf-8") as handle:
            json.dump(declaration, handle)
        allowed, detail = self.narrowing(["origin", "main"], agreeing)
        self.assertFalse(allowed)
        self.assertIn("itself declares sensitive_data", detail)

    def test_self_sensitive_unknown_visibility_stays_denied(self):
        decision, reason = checked(
            f'git -C "{self.public_sensitive}" push origin main',
            self.public_sensitive,
            remote_resolver=lambda *_args, **_kwargs: (None, "unknown"),
        )
        self.assertEqual(decision, "deny")
        self.assertIn("could not verify push remote privacy", reason)

    def test_publication_route_does_not_relax_other_sensitive_commands(self):
        tier = {
            "tier": 2,
            "flags": {"sensitive_data": True},
            "public_synthetic_publication": {
                "remote": "origin",
                "repository": "example/thing",
            },
        }
        for command in (
            "gh repo create leak --public",
            "gh gist create notes.md --public",
            "gh repo edit --visibility public",
            "gh api -XPOST /user/repos",
        ):
            with self.subTest(command=command):
                decision, _reason = floor_environment.hermetic_check(
                    dispatch, command, tier, self.public_sensitive
                )
                self.assertEqual(decision, "deny")

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

    def test_plain_force_options_stay_denied_before_the_narrowing(self):
        for option in ("--force", "-f"):
            decision, reason = checked(
                f'git -C "{self.nonsensitive}" push {option} origin main',
                self.sensitive_root,
                remote_resolver=_public_resolver,
            )
            self.assertEqual(decision, "deny", option)
            self.assertIn("force-push", reason.lower())

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

    def test_repository_subdirectory_resolves_common_dir_from_git_cwd(self):
        nested_cwd = os.path.join(self.nonsensitive, "nested", "command-cwd")
        os.makedirs(nested_cwd, exist_ok=True)
        for project_dir, git_globals in (
            (nested_cwd, None),
            (self.root, ["-C", nested_cwd]),
        ):
            with self.subTest(project_dir=project_dir, git_globals=git_globals):
                with floor_environment.hermetic_environment(dispatch, None):
                    allowed, detail = dispatch.sensitive_push_narrowing_status(
                        ["origin", "main"], project_dir, git_globals
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

    def test_configured_follow_tags_keeps_the_deny(self):
        self._git(self.nonsensitive, "config", "push.followTags", "true")
        try:
            allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
            self.assertFalse(allowed, detail)
            self.assertIn("followTags", detail)
            allowed, detail = self.narrowing_with_failed_config_probe(
                ["origin", "main"], self.nonsensitive
            )
            self.assertFalse(allowed, detail)
            self.assertIn("configuration", detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset", "push.followTags")
        allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
        self.assertTrue(allowed, detail)
        self._git(self.nonsensitive, "config", "push.followTags", "false")
        try:
            allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
            self.assertTrue(allowed, detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset", "push.followTags")
        self._git(self.nonsensitive, "config", "push.followTags", "not-a-bool")
        try:
            allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
            self.assertFalse(allowed, detail)
            self.assertIn("followTags", detail)
            allowed, detail = self.narrowing(
                ["--no-follow-tags", "origin", "main"], self.nonsensitive
            )
            self.assertFalse(allowed, detail)
            self.assertIn("followTags", detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset", "push.followTags")

    def test_empty_follow_tags_uses_git_false_semantics(self):
        self._git(self.nonsensitive, "config", "push.followTags", "")
        try:
            self.assertEqual(
                self._git(
                    self.nonsensitive,
                    "config",
                    "--bool",
                    "--get",
                    "push.followTags",
                ),
                "false",
            )
            allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
            self.assertTrue(allowed, detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset-all", "push.followTags")

        # A key with no equals/value is different from an explicitly empty
        # value: Git's boolean parser treats the valueless form as true.
        with open(
            os.path.join(self.nonsensitive, ".git", "config"),
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write("\n[push]\n\tfollowTags\n")
        try:
            self.assertEqual(
                self._git(
                    self.nonsensitive,
                    "config",
                    "--bool",
                    "--get",
                    "push.followTags",
                ),
                "true",
            )
            allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
            self.assertFalse(allowed, detail)
            self.assertIn("followTags", detail)
            allowed, detail = self.narrowing(
                ["--no-follow-tags", "origin", "main"], self.nonsensitive
            )
            self.assertTrue(allowed, detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset-all", "push.followTags")

        def add_malformed_record(record, *, terminated=True):
            def runner(argv, project_dir):
                output = dispatch.command_output(argv, project_dir)
                if argv[-3:] == ["config", "--null", "--list"]:
                    return output + record + ("\0" if terminated else "")
                return output

            return runner

        for record in ("unknown.truncated", "push.followTags-truncated"):
            allowed, detail = self.narrowing(
                ["--no-follow-tags", "origin", "main"],
                self.nonsensitive,
                add_malformed_record(record),
            )
            self.assertFalse(allowed, record)
            self.assertIn("malformed", detail)

        allowed, detail = self.narrowing(
            ["--no-follow-tags", "origin", "main"],
            self.nonsensitive,
            add_malformed_record("push.followTags", terminated=False),
        )
        self.assertFalse(allowed, detail)
        self.assertIn("malformed", detail)

    def test_numeric_follow_tags_matches_git_boolean_semantics(self):
        """Issue #201: git's boolean parser also accepts NUMBERS.

        `git_parse_maybe_bool` falls through to `git_parse_int`, i.e. C's
        `strtoimax(value, &end, 0)` plus an optional k/m/g unit factor with the
        product bound to a signed 32-bit int. Zero is false at every base and
        unit; every other valid magnitude, including a negative one, is true.
        The narrowing treated all of them as unknown and denied even under the
        exact `--no-follow-tags`.

        Nothing here is asserted from the table alone: every value is first
        measured through the real git binary in this repository, so a table
        that drifts from git's C parser fails on the git assertion rather than
        silently pinning the wrong contract.
        """
        # Measured on git 2.45.1: leading C whitespace and one leading sign are
        # accepted, 0x/0X is hex, a bare leading 0 is octal, k/m/g multiply by
        # 1024/1024**2/1024**3, and the product must fit a signed 32-bit int.
        true_values = (
            "1",
            "2",
            "-1",
            "+1",
            "010",
            "017",
            "0x1",
            "0xff",
            "0x7fffffff",
            "2147483647",
            "-2147483647",
            "1k",
            "1M",
            "1G",
            "2097151k",
            " 1",
        )
        false_values = ("0", "00", "-0", "+0", "0x0", "0k", "0x0k", " 0")
        # Shapes git itself REJECTS. Python's int() would take several of them
        # ("0b1", "1_000", and — via a different rule — "08"); git does not, so
        # they must stay denied even under the exact CLI negation.
        rejected_values = (
            "08",
            "0x",
            "0xg",
            "0b1",
            "1_000",
            "1.0",
            "1e3",
            "1abc",
            "1kk",
            "2147483648",
            "-2147483648",
            "0x80000000",
            "2097152k",
            "2G",
            "++1",
        )

        for value in true_values:
            with self.subTest(value=value, expected="true"):
                self._git(self.nonsensitive, "config", "push.followTags", value)
                try:
                    self.assertIs(
                        self._git_boolean(self.nonsensitive, "push.followTags"),
                        True,
                        f"git does not read {value!r} as true",
                    )
                    allowed, detail = self.narrowing(
                        ["origin", "main"], self.nonsensitive
                    )
                    self.assertFalse(allowed, detail)
                    self.assertIn("followTags", detail)
                    allowed, detail = self.narrowing(
                        ["--no-follow-tags", "origin", "main"], self.nonsensitive
                    )
                    self.assertTrue(allowed, detail)
                finally:
                    self._git(
                        self.nonsensitive, "config", "--unset-all", "push.followTags"
                    )

        for value in false_values:
            with self.subTest(value=value, expected="false"):
                self._git(self.nonsensitive, "config", "push.followTags", value)
                try:
                    self.assertIs(
                        self._git_boolean(self.nonsensitive, "push.followTags"),
                        False,
                        f"git does not read {value!r} as false",
                    )
                    for args in (
                        ["origin", "main"],
                        ["--no-follow-tags", "origin", "main"],
                    ):
                        allowed, detail = self.narrowing(args, self.nonsensitive)
                        self.assertTrue(allowed, detail)
                finally:
                    self._git(
                        self.nonsensitive, "config", "--unset-all", "push.followTags"
                    )

        for value in rejected_values:
            with self.subTest(value=value, expected="rejected"):
                self._git(self.nonsensitive, "config", "push.followTags", value)
                try:
                    self.assertIsNone(
                        self._git_boolean(self.nonsensitive, "push.followTags"),
                        f"git unexpectedly accepted {value!r}",
                    )
                    for args in (
                        ["origin", "main"],
                        ["--no-follow-tags", "origin", "main"],
                    ):
                        allowed, detail = self.narrowing(args, self.nonsensitive)
                        self.assertFalse(allowed, (args, detail))
                        self.assertIn("followTags", detail)
                finally:
                    self._git(
                        self.nonsensitive, "config", "--unset-all", "push.followTags"
                    )

        # Pre-existing, deliberately unchanged: the floor normalizes with
        # strip().lower() before matching its literal set, so a TRAILING-space
        # "1 " still reads as true here even though git rejects it. Issue #201
        # is strictly additive and did not tighten that; a push carrying such a
        # value dies on git's own "bad boolean config value" instead.
        self._git(self.nonsensitive, "config", "push.followTags", "1 ")
        try:
            self.assertEqual(
                self._git(self.nonsensitive, "config", "push.followTags"), "1"
            )
            self.assertIsNone(self._git_boolean(self.nonsensitive, "push.followTags"))
            allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
            self.assertFalse(allowed, detail)
            allowed, detail = self.narrowing(
                ["--no-follow-tags", "origin", "main"], self.nonsensitive
            )
            self.assertTrue(allowed, detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset-all", "push.followTags")

    def test_numeric_follow_tags_keeps_every_hostile_neighbour_denied(self):
        """Issue #201 widened only the CONFIG grammar, never the argv rules.

        A configured numeric true is proved against real git — including a real
        `git push --dry-run` that plans the annotated tag — and then every
        neighbouring argv shape that is NOT an exact option-position
        `--no-follow-tags` must still deny.
        """
        remote_name = "issue201-numeric"
        remote_path = os.path.join(self.root, remote_name + ".git")
        self._git(self.root, "init", "--bare", remote_path)
        self._git(self.nonsensitive, "remote", "add", remote_name, remote_path)
        self._git(
            self.nonsensitive,
            "tag",
            "-a",
            "issue201-annotated",
            "-m",
            "annotated numeric follow-tags control",
        )
        # 0x2 exercises the hex branch AND the nonzero-is-true rule at once.
        self._git(self.nonsensitive, "config", "push.followTags", "0x2")
        try:
            self.assertIs(self._git_boolean(self.nonsensitive, "push.followTags"), True)
            # Real git: the numeric true really does plan the annotated tag...
            planned = self._git(
                self.nonsensitive,
                "push",
                "--dry-run",
                "--porcelain",
                remote_name,
                "main",
            )
            self.assertIn(
                "refs/tags/issue201-annotated:refs/tags/issue201-annotated",
                planned,
            )
            # ...and the exact option-position negation really does suppress it.
            suppressed = self._git(
                self.nonsensitive,
                "push",
                "--dry-run",
                "--porcelain",
                "--no-follow-tags",
                remote_name,
                "main",
            )
            self.assertIn("refs/heads/main:refs/heads/main", suppressed)
            self.assertNotIn("refs/tags/issue201-annotated", suppressed)

            allowed, detail = self.narrowing(
                ["--no-follow-tags", remote_name, "main"], self.nonsensitive
            )
            self.assertTrue(allowed, detail)

            for args in (
                ["origin", "main"],
                ["--no-follow-tags", "--follow-tags", "origin", "main"],
                ["--no-follow-tags", "--tags", "origin"],
                ["--no-follow-tags", "--delete", "origin", "main"],
                ["--no-follow-tags", "origin", "+main:refs/heads/main"],
                ["--no-follow-tags", "origin", "main:refs/tags/v1"],
                ["--push-option", "--no-follow-tags", "origin", "main"],
                ["-o", "--no-follow-tags", "origin", "main"],
                ["--repo", "--no-follow-tags", "origin", "main"],
                ["origin", "--", "--no-follow-tags"],
            ):
                with self.subTest(args=args):
                    allowed, _detail = self.narrowing(args, self.nonsensitive)
                    self.assertFalse(allowed, args)

            # The malformed-record neighbours stay malformed with a numeric
            # value configured: only push.followTags may be separator-free.
            def add_malformed_record(record):
                def runner(argv, project_dir):
                    output = dispatch.command_output(argv, project_dir)
                    if argv[-3:] == ["config", "--null", "--list"]:
                        return output + record + "\0"
                    return output

                return runner

            allowed, detail = self.narrowing(
                ["--no-follow-tags", remote_name, "main"],
                self.nonsensitive,
                add_malformed_record("push.followTags-truncated"),
            )
            self.assertFalse(allowed, detail)
            self.assertIn("malformed", detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset-all", "push.followTags")
            self._git(self.nonsensitive, "tag", "-d", "issue201-annotated")
            self._git(self.nonsensitive, "remote", "remove", remote_name)

    def test_no_follow_tags_overrides_configured_true_only_in_option_position(self):
        remote_name = "issue196-no-follow"
        remote_path = os.path.join(self.root, remote_name + ".git")
        self._git(self.root, "init", "--bare", remote_path)
        self._git(self.nonsensitive, "remote", "add", remote_name, remote_path)
        self._git(
            self.nonsensitive,
            "tag",
            "-a",
            "issue196-annotated",
            "-m",
            "annotated follow-tags control",
        )
        self._git(self.nonsensitive, "config", "push.followTags", "true")
        self._git(
            self.nonsensitive,
            "update-ref",
            "refs/heads/--no-follow-tags",
            "HEAD",
        )
        try:
            planned = self._git(
                self.nonsensitive,
                "push",
                "--dry-run",
                "--porcelain",
                "--no-follow-tags",
                remote_name,
                "main",
            )
            self.assertIn("refs/heads/main:refs/heads/main", planned)
            self.assertNotIn("refs/tags/issue196-annotated", planned)
            planned_with_later_selector = self._git(
                self.nonsensitive,
                "push",
                "--dry-run",
                "--porcelain",
                "--no-follow-tags",
                "--follow-tags",
                remote_name,
                "main",
            )
            self.assertIn(
                "refs/tags/issue196-annotated:refs/tags/issue196-annotated",
                planned_with_later_selector,
            )

            allowed, detail = self.narrowing(
                ["--no-follow-tags", remote_name, "main"], self.nonsensitive
            )
            self.assertTrue(allowed, detail)

            for args in (
                ["--no-follow-tags", "--follow-tags", "origin", "main"],
                ["--no-follow-tags", "--tags", "origin"],
                ["--no-follow-tags", "--delete", "origin", "main"],
                ["--no-follow-tags", "origin", "+main:refs/heads/main"],
                ["--no-follow-tags", "origin", "main:refs/tags/v1"],
                ["--push-option", "--no-follow-tags", "origin", "main"],
                ["origin", "--", "--no-follow-tags"],
            ):
                with self.subTest(args=args):
                    allowed, _detail = self.narrowing(args, self.nonsensitive)
                    self.assertFalse(allowed, args)
        finally:
            self._git(self.nonsensitive, "config", "--unset-all", "push.followTags")
            self._git(
                self.nonsensitive,
                "update-ref",
                "-d",
                "refs/heads/--no-follow-tags",
            )
            self._git(self.nonsensitive, "tag", "-d", "issue196-annotated")
            self._git(self.nonsensitive, "remote", "remove", remote_name)

    def test_ambiguous_short_branch_name_does_not_change_upstream_key(self):
        self._git(self.nonsensitive, "tag", "-f", "main")
        self._git(self.nonsensitive, "config", "push.default", "upstream")
        self._git(self.nonsensitive, "config", "branch.main.remote", "origin")
        self._git(
            self.nonsensitive,
            "config",
            "branch.main.merge",
            "refs/heads/main",
        )
        try:
            self.assertEqual(
                self._git(
                    self.nonsensitive,
                    "symbolic-ref",
                    "--quiet",
                    "--short",
                    "HEAD",
                ),
                "heads/main",
            )
            allowed, detail = self.narrowing(["origin"], self.nonsensitive)
            self.assertTrue(allowed, detail)

            # HEAD can be a symbolic ref outside refs/heads. It must not borrow
            # branch.main's safe-looking config just because the suffix matches.
            self._git(
                self.nonsensitive,
                "symbolic-ref",
                "HEAD",
                "refs/tags/main",
            )
            allowed, detail = self.narrowing(["origin"], self.nonsensitive)
            self.assertFalse(allowed, detail)
            self.assertIn("upstream", detail)
        finally:
            self._git(
                self.nonsensitive,
                "symbolic-ref",
                "HEAD",
                "refs/heads/main",
            )
            self._git(self.nonsensitive, "tag", "-d", "main")
            self._git(self.nonsensitive, "config", "--unset", "push.default")
            self._git(self.nonsensitive, "config", "--unset", "branch.main.remote")
            self._git(
                self.nonsensitive,
                "config",
                "--unset-all",
                "branch.main.merge",
            )

    def test_tracking_push_default_uses_upstream_branch_validation(self):
        remote_name = "issue196-tracking"
        remote_path = os.path.join(self.root, remote_name + ".git")
        self._git(self.root, "init", "--bare", remote_path)
        self._git(self.nonsensitive, "remote", "add", remote_name, remote_path)
        self._git(self.nonsensitive, "config", "push.default", "tracking")
        self._git(self.nonsensitive, "config", "branch.main.remote", remote_name)
        self._git(
            self.nonsensitive,
            "config",
            "branch.main.merge",
            "refs/heads/main",
        )
        try:
            planned = self._git(
                self.nonsensitive,
                "push",
                "--dry-run",
                "--porcelain",
                remote_name,
            )
            self.assertIn("refs/heads/main:refs/heads/main", planned)
            allowed, detail = self.narrowing([remote_name], self.nonsensitive)
            self.assertTrue(allowed, detail)
            self._git(
                self.nonsensitive,
                "config",
                "branch.main.merge",
                "refs/tags/public-release",
            )
            planned = self._git(
                self.nonsensitive,
                "push",
                "--dry-run",
                "--porcelain",
                remote_name,
            )
            self.assertIn("refs/heads/main:refs/tags/public-release", planned)
            allowed, detail = self.narrowing([remote_name], self.nonsensitive)
            self.assertFalse(allowed, detail)
            self.assertIn("upstream", detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset", "push.default")
            self._git(self.nonsensitive, "config", "--unset", "branch.main.remote")
            self._git(
                self.nonsensitive,
                "config",
                "--unset-all",
                "branch.main.merge",
            )
            self._git(self.nonsensitive, "remote", "remove", remote_name)

    def test_upstream_push_default_cannot_target_a_tag(self):
        self._git(self.nonsensitive, "config", "push.default", "upstream")
        self._git(self.nonsensitive, "config", "branch.main.remote", "origin")
        self._git(
            self.nonsensitive,
            "config",
            "branch.main.merge",
            "refs/tags/public-release",
        )
        try:
            allowed, detail = self.narrowing(["origin"], self.nonsensitive)
            self.assertFalse(allowed, detail)
            self.assertIn("upstream", detail)
            allowed, detail = self.narrowing_with_failed_config_probe(
                ["origin"], self.nonsensitive
            )
            self.assertFalse(allowed, detail)
            self.assertIn("configuration", detail)
            self._git(
                self.nonsensitive,
                "config",
                "branch.main.merge",
                "refs/heads/main",
            )
            allowed, detail = self.narrowing(["origin"], self.nonsensitive)
            self.assertTrue(allowed, detail)
            self._git(
                self.nonsensitive,
                "config",
                "--add",
                "branch.main.merge",
                "refs/tags/other-release",
            )
            allowed, detail = self.narrowing(["origin"], self.nonsensitive)
            self.assertFalse(allowed, detail)
            self.assertIn("upstream", detail)
        finally:
            self._git(self.nonsensitive, "config", "--unset", "push.default")
            self._git(self.nonsensitive, "config", "--unset", "branch.main.remote")
            self._git(
                self.nonsensitive,
                "config",
                "--unset-all",
                "branch.main.merge",
            )

    def test_unqualified_refspec_destination_keeps_the_deny(self):
        allowed, detail = self.narrowing(
            [
                "--force-with-lease=feature/x:0123456789012345678901234567890123456789",
                "origin",
                "main:feature/x",
            ],
            self.nonsensitive,
        )
        self.assertFalse(allowed, detail)
        self.assertIn("refspec", detail)

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

    def test_separate_git_dir_cannot_hide_a_sensitive_primary(self):
        primary = os.path.join(self.sensitive_root, "separate-primary")
        git_dir = os.path.join(self.root, "separate-git-data")
        outside = os.path.join(self.root, "separate-outside-worktree")
        os.makedirs(primary)
        self._git(
            self.root,
            "init",
            "-b",
            "main",
            "--separate-git-dir",
            git_dir,
            primary,
        )
        with open(os.path.join(primary, "seed.txt"), "w", encoding="utf-8") as handle:
            handle.write("seed\n")
        os.makedirs(os.path.join(primary, ".agent-harness"))
        with open(
            os.path.join(primary, ".agent-harness", "tier.json"),
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump({"tier": 2, "flags": {"sensitive_data": False}}, handle)
        self._git(primary, "add", "seed.txt", ".agent-harness/tier.json")
        self._git(primary, "commit", "-m", "seed separate git dir")
        self._git(
            primary,
            "remote",
            "add",
            "origin",
            "https://github.com/example/thing.git",
        )
        self._git(primary, "worktree", "add", "--detach", outside, "main")
        self._git(outside, "switch", "-c", "separate-wt")

        allowed, detail = self.narrowing(["origin", "separate-wt"], outside)
        self.assertFalse(allowed, detail)
        self.assertIn("separate Git directory", detail)
        self._git(outside, "config", "core.worktree", outside)
        allowed, detail = self.narrowing(["origin", "separate-wt"], outside)
        self.assertFalse(allowed, detail)
        self.assertIn("separate Git directory", detail)

    def test_unresolvable_filesystem_identity_keeps_the_deny(self):
        with mock.patch.object(
            dispatch.os.path,
            "samefile",
            side_effect=OSError("filesystem identity unavailable"),
        ):
            allowed, detail = self.narrowing(["origin", "main"], self.nonsensitive)
        self.assertFalse(allowed, detail)
        self.assertIn("separate Git directory", detail)

    def test_primary_separate_git_dir_cannot_qualify_as_a_submodule(self):
        superproject = os.path.join(self.root, "primary-git-dir-superproject")
        primary = os.path.join(self.sensitive_root, "primary-git-dir-checkout")
        module = os.path.join(superproject, "module")
        git_dir = os.path.join(superproject, ".git", "modules", "module")
        self._make_repo(superproject, {"tier": 2, "flags": {"sensitive_data": False}})
        os.makedirs(os.path.dirname(git_dir), exist_ok=True)
        os.makedirs(primary)
        self._git(
            self.root,
            "init",
            "-b",
            "main",
            "--separate-git-dir",
            git_dir,
            primary,
        )
        with open(os.path.join(primary, "seed.txt"), "w", encoding="utf-8") as handle:
            handle.write("seed\n")
        os.makedirs(os.path.join(primary, ".agent-harness"))
        with open(
            os.path.join(primary, ".agent-harness", "tier.json"),
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump({"tier": 2, "flags": {"sensitive_data": False}}, handle)
        self._git(primary, "add", "seed.txt", ".agent-harness/tier.json")
        self._git(primary, "commit", "-m", "seed separate repository")
        self._git(
            primary,
            "remote",
            "add",
            "origin",
            "https://github.com/example/thing.git",
        )
        commit_id = self._git(primary, "rev-parse", "HEAD")
        self._git(
            superproject,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{commit_id},module",
        )
        self._git(superproject, "commit", "-m", "register gitlink")
        os.makedirs(module)
        with open(os.path.join(module, ".git"), "w", encoding="utf-8") as handle:
            handle.write("gitdir: ../.git/modules/module\n")
        self._git(primary, "config", "core.worktree", module)
        self._git(module, "reset", "--hard", "HEAD")

        self.assertTrue(
            os.path.samefile(
                self._git(module, "rev-parse", "--show-superproject-working-tree"),
                superproject,
            )
        )
        self.assertEqual(
            len(
                [
                    line
                    for line in self._git(
                        module, "worktree", "list", "--porcelain"
                    ).splitlines()
                    if line.startswith("worktree ")
                ]
            ),
            1,
            "the primary shape reports no linked worktree",
        )
        active_git_dir = self._git(
            module, "rev-parse", "--path-format=absolute", "--git-dir"
        )
        common_dir = self._git(
            module, "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        self.assertTrue(os.path.samefile(active_git_dir, common_dir))

        allowed, detail = self.narrowing(["origin", "main"], module)
        self.assertFalse(allowed, detail)
        self.assertIn("separate Git directory", detail)
        decision, reason = checked(
            f'git -C "{module}" push origin main',
            self.sensitive_root,
            remote_resolver=_public_resolver,
        )
        self.assertEqual(decision, "deny", reason)

    def test_ordinary_submodule_cannot_prove_a_unique_primary_checkout(self):
        source = os.path.join(self.root, "submodule-source")
        superproject = os.path.join(self.root, "submodule-superproject")
        self._make_repo(source, {"tier": 2, "flags": {"sensitive_data": False}})
        self._git(source, "add", "-f", ".agent-harness/tier.json")
        self._git(source, "commit", "-m", "track submodule tier")
        self._make_repo(superproject, {"tier": 2, "flags": {"sensitive_data": False}})
        self._git(
            superproject,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            source,
            "module",
        )
        submodule = os.path.join(superproject, "module")
        self._git(
            submodule,
            "remote",
            "set-url",
            "origin",
            "https://github.com/example/thing.git",
        )

        common_dir = self._git(submodule, "rev-parse", "--git-common-dir")
        if not os.path.isabs(common_dir):
            common_dir = os.path.join(submodule, common_dir)
        active_git_dir = self._git(
            submodule, "rev-parse", "--path-format=absolute", "--git-dir"
        )
        self.assertTrue(os.path.samefile(active_git_dir, common_dir))
        primary_record = self._git(
            submodule, "worktree", "list", "--porcelain"
        ).splitlines()[0]
        self.assertTrue(
            os.path.samefile(common_dir, primary_record.removeprefix("worktree "))
        )
        self.assertTrue(
            self._git(submodule, "config", "--get", "core.worktree"),
            "ordinary submodule must expose its checkout through core.worktree",
        )
        resolved_core_worktree = os.path.abspath(
            os.path.join(
                common_dir,
                self._git(submodule, "config", "--get", "core.worktree"),
            )
        )
        self.assertTrue(os.path.samefile(resolved_core_worktree, submodule))
        self.assertTrue(
            os.path.samefile(
                self._git(
                    submodule,
                    "rev-parse",
                    "--show-superproject-working-tree",
                ),
                superproject,
            )
        )

        allowed, detail = self.narrowing(["origin", "main"], submodule)
        self.assertFalse(allowed, detail)
        self.assertIn("separate Git directory", detail)

    def test_submodule_in_linked_superproject_cannot_hide_sensitive_primary(self):
        source = os.path.join(self.root, "linked-submodule-source")
        superproject = os.path.join(
            self.sensitive_root, "linked-submodule-superproject"
        )
        outside = os.path.join(self.root, "linked-submodule-outside")
        self._make_repo(source, {"tier": 2, "flags": {"sensitive_data": False}})
        self._git(source, "add", "-f", ".agent-harness/tier.json")
        self._git(source, "commit", "-m", "track linked submodule tier")
        self._make_repo(superproject, {"tier": 2, "flags": {"sensitive_data": False}})
        self._git(superproject, "add", "-f", ".agent-harness/tier.json")
        self._git(
            superproject,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            source,
            "module",
        )
        self._git(superproject, "commit", "-m", "track linked submodule")
        self._git(superproject, "worktree", "add", "--detach", outside, "main")
        self._git(outside, "switch", "-c", "linked-superproject")
        self._git(
            outside,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
            "module",
        )
        submodule = os.path.join(outside, "module")
        self._git(
            submodule,
            "remote",
            "set-url",
            "origin",
            "https://github.com/example/thing.git",
        )

        self.assertTrue(
            os.path.samefile(
                self._git(
                    submodule,
                    "rev-parse",
                    "--show-superproject-working-tree",
                ),
                outside,
            )
        )
        superproject_metadata = self._git(
            outside, "worktree", "list", "--porcelain"
        ).splitlines()[0]
        self.assertTrue(
            os.path.samefile(
                superproject_metadata.removeprefix("worktree "), superproject
            )
        )
        self.assertFalse(os.path.samefile(superproject, outside))

        allowed, detail = self.narrowing(["origin", "main"], submodule)
        self.assertFalse(allowed, detail)
        self.assertIn("separate Git directory", detail)

    def test_a_worktree_cannot_declassify_its_own_sensitive_repository(self):
        """A repo that declares sensitive_data ITSELF stays denied from any of
        its worktrees, nested or outside.

        The first fix round built the containment skip-set from BOTH roots, so
        the primary's own declaration was skipped during the toplevel walk too.
        For the estate's standard `<primary>/.worktrees/<n>` layout that made a
        SENSITIVE repository publicly pushable from its worktree while the same
        push from the primary checkout denied — a new allow, in a fix whose
        whole safety argument was that it could only remove them. The outside
        case was never closed at all despite the docstring claiming it.

        No adversary is needed: a branch that flips the repo's own tier.json to
        false, checked out in a worktree, is enough.
        """
        selfsens = os.path.join(self.root, "declassify")
        self._make_repo(selfsens, {"tier": 3, "flags": {"sensitive_data": True}})
        for label, path in (
            ("nested", os.path.join(selfsens, ".worktrees", "w")),
            ("outside", os.path.join(self.root, "declassify-outside")),
        ):
            self._git(selfsens, "worktree", "add", "--detach", path, "main")
            self._git(path, "switch", "-c", "wt-" + label)
            # the worktree's ON-DISK declaration claims non-sensitive
            os.makedirs(os.path.join(path, ".agent-harness"), exist_ok=True)
            with open(
                os.path.join(path, ".agent-harness", "tier.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"tier": 1, "flags": {"sensitive_data": False}}, handle)
            allowed, detail = self.narrowing(["origin", "wt-" + label], path)
            self.assertFalse(allowed, f"{label} worktree declassified its repo")
            self.assertIn("sensitive_data root", detail)

    def test_a_worktree_of_a_non_sensitive_repo_still_allows(self):
        """The positive control for the case above — the containment fix must
        not deny every worktree. The #132 fix commits themselves live in a
        nested worktree, so an over-broad fix could not publish itself."""
        # TRACK the declaration, as every real estate repo does — otherwise the
        # worktree has no tier.json on disk and the deny comes from the wrong
        # condition, making this control pass for a reason it is not testing.
        self._git(self.nonsensitive, "add", "-f", ".agent-harness/tier.json")
        self._git(self.nonsensitive, "commit", "-m", "track tier")
        wt = os.path.join(self.nonsensitive, ".worktrees", "ok")
        self._git(self.nonsensitive, "worktree", "add", "--detach", wt, "main")
        self._git(wt, "switch", "-c", "wt-ok")
        allowed, detail = self.narrowing(["origin", "wt-ok"], wt)
        self.assertTrue(allowed, detail)

    def test_refspec_destination_outside_refs_heads_keeps_the_deny(self):
        # A valid branch SOURCE can still write a remote tag: `main:refs/tags/v1`
        # publishes a ref class the ratified condition set excludes.
        for refspec in ("main:refs/tags/v1", "main:refs/notes/x", "main:refs/*"):
            allowed, _detail = self.narrowing(["origin", refspec], self.nonsensitive)
            self.assertFalse(allowed, refspec)
        # source-only and fully qualified branch destinations still allow;
        # an unqualified destination can resolve to an existing remote tag.
        for refspec in ("main", "main:refs/heads/other"):
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
        self.assertIn("issue #48 / declared-publication narrowing", reason)

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
