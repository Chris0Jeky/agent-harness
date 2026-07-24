"""Floor v1.6.1: two unresolved P1 findings from PR #23's automated review.

Both let a refspec-less `git push` skip the bare-push guard that #23 added, so a
CONFIGURED force/delete/mirror refspec could still be inherited.

1. `--all` / `--tags` / `--repo` were detected by a FLAT scan of argv. As the
   value of `-o` / `--push-option` those tokens are server-side push-option data,
   not selectors, so `git push -o --all origin` is still refspec-less.
2. `segment_may_mutate_repository_config` recognized only a redirect or a
   PowerShell file cmdlet, so an in-place editor (`sed -i`, `perl -i`,
   `awk -i inplace`, a python one-liner) rewrote `.git/config` invisibly and the
   later push graduated to allow.

The floor never treats message text as a target, so the substring test that
catches an interpreter payload is confined to interpreter heads —
`git commit -m 'touched .git/config'` must stay allowed.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch = load_module("dispatch_push_guard", DISPATCH_PATH)


def stub_resolver(
    args, project_dir, git_globals=None, command_runner=None, deadline=None
):
    """No network during unit tests; treat every remote as private."""
    return False, "unit-test-stub-private"


def check(command: str, tier: int = 1, flags=None):
    tier_cfg = {"tier": tier, "flags": flags or {}}
    project_dir = str(ROOT)
    return dispatch.check(
        command, tier_cfg, project_dir, project_dir, remote_resolver=stub_resolver
    )


class PushOptionPayloadTests(unittest.TestCase):
    """A `-o` value must not be mistaken for a refspec selector."""

    # Tier 4 keeps the strict posture, so the guard's verdict is observable there.
    REFSPEC_LESS = (
        "git push -o --all origin",
        "git push --push-option --all origin",
        "git push -o --tags origin",
        "git push -o --repo origin",
        "git push -o --all --push-option --tags origin",
    )
    GENUINE_SELECTORS = (
        "git push --all origin",
        "git push --tags origin",
        "git push origin main",
        "git push origin HEAD:refs/heads/main",
    )

    def test_push_option_payload_stays_refspec_less(self):
        for command in self.REFSPEC_LESS:
            with self.subTest(command=command):
                decision, _reason = check(command, tier=4)
                self.assertEqual(decision, "deny")

    def test_genuine_selectors_are_still_explicit(self):
        for command in self.GENUINE_SELECTORS:
            with self.subTest(command=command):
                decision, reason = check(command, tier=4)
                self.assertEqual(decision, "allow", reason)


class InPlaceConfigEditTests(unittest.TestCase):
    """An in-place rewrite of .git/config must block the graduated bare push."""

    EDITORS = (
        "sed -i 's/x/y/' .git/config; git push origin",
        "sed --in-place 's/x/y/' .git/config; git push origin",
        "perl -i -pe 's/x/y/' .git/config; git push origin",
        "awk -i inplace '{print}' .git/config; git push origin",
        "python -c \"open('.git/config','a').write('x')\"; git push origin",
        "ed .git/config; git push origin",
    )
    READERS = (
        "cat .git/config; git push origin",
        "grep url .git/config && git push origin",
        "Get-Content .git/config; git push origin",
        "wc -l .git/config; git push origin",
    )

    def test_in_place_editors_block_the_bare_push(self):
        for command in self.EDITORS:
            with self.subTest(command=command):
                decision, _reason = check(command)
                self.assertEqual(decision, "deny")

    def test_reading_config_does_not_block_the_bare_push(self):
        for command in self.READERS:
            with self.subTest(command=command):
                decision, reason = check(command)
                self.assertEqual(decision, "allow", reason)

    def test_message_text_is_never_a_target(self):
        for command in (
            "git commit -m 'touched .git/config'; git push origin",
            'git commit -m "rewrote .git/config by hand"; git push',
            "gh pr create --title x --body 'see .git/config'; git push origin",
        ):
            with self.subTest(command=command):
                decision, reason = check(command)
                self.assertEqual(decision, "allow", reason)

    def test_tracker_classifies_directly(self):
        may = dispatch.segment_may_mutate_repository_config
        self.assertTrue(may(["sed", "-i", "s/x/y/", ".git/config"]))
        self.assertTrue(may(["python", "-c", "open('.git/config','a')"]))
        self.assertTrue(may(["echo", "x", ">", ".git/config"]))
        self.assertTrue(may(["Set-Content", ".git/config", "x"]))
        self.assertFalse(may(["cat", ".git/config"]))
        self.assertFalse(may(["git", "status"]))
        self.assertFalse(may(["grep", "url", ".git/config"]))


class EnumerateTheSafeSetTests(unittest.TestCase):
    """Enumerating the DANGEROUS set fails open on every launcher nobody listed.

    The interpreter-head allowlist caught `python3` and missed `python3.11`,
    `py`, `lua`, `deno`, `Rscript`, `julia`, `tclsh`, `uv run` and `nix-shell` --
    all measured. The predicate now recognizes the PATH anywhere in a token and
    enumerates the SAFE heads instead: noisy, not blind.
    """

    WRITE = "open('.git/config','a').write('x')"
    LAUNCHERS = (
        'python3.11 -c "' + WRITE + '"',
        'py -c "' + WRITE + '"',
        "lua -e \"io.open('.git/config','a'):write('x')\"",
        "deno eval \"Deno.writeTextFileSync('.git/config','x')\"",
        "Rscript -e \"cat('x',file='.git/config')\"",
        'uv run python -c "' + WRITE + '"',
        'nix-shell -p x --run "echo x > .git/config"',
    )
    # Read-only git probes must NOT poison a push. Every git subcommand naming a
    # config path used to be classed a possible writer.
    PROBES = (
        "git status .git/config",
        "git diff .git/config",
        "git log .git/config",
        "git ls-files .git/config",
        "git show .git/config",
        "git rev-parse .git/config",
        "git log --grep '.git/config'",
        "git config -l",
        "git config --get-regexp '^remote\\.'",
        "gh issue comment 5 -b 'about .git/config'",
        # `-C <dir>` only chdirs. The `-c` disqualifier MUST be case-sensitive
        # or every worktree-scoped probe becomes a push deny.
        "git -C /repo status .git/config",
        "git log -c HEAD",
    )
    # New bypasses the git safe set would otherwise introduce.
    VOUCH_GUARDS = (
        "git diff --output=.git/config",
        "git -c core.pager='sh -c x' log .git/config",
        "git --exec-path=/evil status .git/config",
        "echo x > .git/config",
    )
    # PR #31's widened path recognizer.
    WORKTREE_SPELLINGS = (
        "sed -i s/x/y/ .git/config.worktree",
        "sed -i s/x/y/ .git/worktrees/w/config.worktree",
        "sed -i s/x/y/ $GIT_DIR/config",
        "sed -i s/x/y/ $GIT_COMMON_DIR/config",
        "sed -i s/x/y/ /abs/path/.git/config",
    )

    def test_every_launcher_is_caught_without_naming_it(self):
        for command in self.LAUNCHERS:
            with self.subTest(command=command):
                # BOTH push shapes: an explicit refspec does not protect against
                # a rewritten remote.*.pushurl or core.hooksPath.
                self.assertEqual(check(command + "; git push origin")[0], "deny")
                self.assertEqual(check(command + "; git push origin main")[0], "deny")

    def test_a_read_only_probe_does_not_poison_a_push(self):
        for command in self.PROBES:
            with self.subTest(command=command):
                decision, reason = check(command + "; git push origin main")
                self.assertEqual(decision, "allow", reason)

    def test_the_git_vouch_has_guards(self):
        for command in self.VOUCH_GUARDS:
            with self.subTest(command=command):
                self.assertEqual(check(command + "; git push origin main")[0], "deny")

    def test_linked_worktree_config_spellings(self):
        for command in self.WORKTREE_SPELLINGS:
            with self.subTest(command=command):
                self.assertEqual(check(command + "; git push origin main")[0], "deny")

    def test_no_dry_run_carve_out(self):
        # Verified on git 2.45.1: --dry-run still runs the pre-push hook and
        # still runs remote.*.receivepack; it only skips the ref update.
        self.assertEqual(
            check("sed -i s/x/y/ .git/config; git push --dry-run origin main")[0],
            "deny",
        )

    def test_a_write_after_the_push_does_not_retroactively_poison_it(self):
        self.assertEqual(
            check("git push origin main; sed -i s/x/y/ .git/config")[0], "allow"
        )

    def test_ordinary_config_flows_are_unaffected(self):
        for command in (
            "git config user.email a@b.c; git push origin main",
            "git config --global user.name x; git push origin main",
        ):
            with self.subTest(command=command):
                decision, reason = check(command)
                self.assertEqual(decision, "allow", reason)


if __name__ == "__main__":
    unittest.main()
