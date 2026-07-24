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


if __name__ == "__main__":
    unittest.main()
