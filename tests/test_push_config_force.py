"""Floor v1.6.0: a bare `git push` must not inherit a CONFIGURED force refspec.

Adversarial review of PR #23 found that graduating bare `git push` to allow below
T4 reopened a charter force-push: `remote.<name>.push = +src:dst` silently
force-updates a shared branch on a refspec-less push, and an agent can write
`.git/config` itself. The floor now resolves that config and denies the bare push
when it could force, while still allowing the common non-force bare push.
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


def git(repo: str, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )


@unittest.skipUnless(shutil.which("git"), "git is required")
class PushConfigForceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dispatch = load_module("push_force_dispatch", DISPATCH_PATH)

    def _repo(self, push_refspec: str | None, *, mirror: bool = False) -> str:
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        git(repo, "init", "-q")
        git(repo, "remote", "add", "origin", "https://example.invalid/repo.git")
        if push_refspec is not None:
            git(repo, "config", "remote.origin.push", push_refspec)
        if mirror:
            git(repo, "config", "remote.origin.mirror", "true")
        return repo

    def _decide(self, repo: str, command: str, tier: int = 1):
        return self.dispatch.check(
            command,
            {"tier": tier, "flags": {}},
            repo,
            repo,
            remote_resolver=lambda *a, **k: (False, "stub-private"),
        )

    def test_helper_flags_configured_force(self) -> None:
        repo = self._repo("+HEAD:refs/heads/main")
        self.assertTrue(self.dispatch.configured_bare_push_is_dangerous(repo))

    def test_helper_flags_configured_delete(self) -> None:
        repo = self._repo(":refs/heads/old")
        self.assertTrue(self.dispatch.configured_bare_push_is_dangerous(repo))

    def test_helper_flags_configured_mirror(self) -> None:
        repo = self._repo(None, mirror=True)
        self.assertTrue(self.dispatch.configured_bare_push_is_dangerous(repo))

    def test_helper_ignores_non_force_refspec(self) -> None:
        repo = self._repo("HEAD:refs/heads/main")
        self.assertFalse(self.dispatch.configured_bare_push_is_dangerous(repo))

    def test_helper_ignores_absent_config(self) -> None:
        repo = self._repo(None)
        self.assertFalse(self.dispatch.configured_bare_push_is_dangerous(repo))

    def test_bare_push_denied_when_config_forces(self) -> None:
        for refspec in ("+HEAD:refs/heads/main", ":refs/heads/old"):
            repo = self._repo(refspec)
            for command in ("git push", "git push origin"):
                with self.subTest(refspec=refspec, command=command):
                    decision, reason = self._decide(repo, command)
                    self.assertEqual(decision, "deny", reason)
                    self.assertIn("push-config-force", reason)

    def test_bare_push_denied_when_config_mirrors(self) -> None:
        repo = self._repo(None, mirror=True)
        decision, reason = self._decide(repo, "git push origin")
        self.assertEqual(decision, "deny", reason)
        self.assertIn("push-config-force", reason)

    def test_bare_push_denied_under_git_dir_override(self) -> None:
        # A GIT_DIR override points git at a different repo than the resolver's
        # cwd, so the inherited config cannot be verified -> fail closed.
        repo = self._repo(None)
        for command in (
            "GIT_DIR=/other/repo/.git git push origin",
            "$env:GIT_DIR='/other/repo/.git'; git push",
        ):
            with self.subTest(command=command):
                decision, reason = self._decide(repo, command)
                self.assertEqual(decision, "deny", reason)
                self.assertIn("push-config-unverifiable", reason)

    def test_bare_push_allowed_under_unrelated_env_assignment(self) -> None:
        # A generic PowerShell env assignment (the common wave `$env:WT_PROJECT_DIR`
        # pattern) does not redirect git, so the bare push stays verifiable.
        repo = self._repo(None)
        for command in (
            "$env:WT_PROJECT_DIR='C:/x'; git push",
            "$env:FOO='bar'; git push origin",
        ):
            with self.subTest(command=command):
                decision, reason = self._decide(repo, command)
                self.assertEqual(decision, "allow", reason)

    def test_bare_push_allowed_when_config_is_non_force(self) -> None:
        repo = self._repo("HEAD:refs/heads/main")
        decision, _ = self._decide(repo, "git push origin")
        self.assertEqual(decision, "allow")

    def test_bare_push_allowed_without_push_config(self) -> None:
        repo = self._repo(None)
        decision, _ = self._decide(repo, "git push")
        self.assertEqual(decision, "allow")

    def test_explicit_refspec_overrides_config_force(self) -> None:
        # An explicit command-line refspec (2 positionals) never consults the
        # configured push refspec, so it is not force by virtue of config; the
        # explicit `main` target is a plain fast-forward push.
        repo = self._repo("+HEAD:refs/heads/main")
        decision, _ = self._decide(repo, "git push origin main")
        self.assertEqual(decision, "allow")

    def test_configured_force_still_denied_at_t4(self) -> None:
        repo = self._repo("+HEAD:refs/heads/main")
        decision, reason = self._decide(repo, "git push origin", tier=4)
        self.assertEqual(decision, "deny", reason)


if __name__ == "__main__":
    unittest.main()
