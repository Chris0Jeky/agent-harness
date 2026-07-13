from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import harness


class HarnessTests(unittest.TestCase):
    def make_repo(self) -> Path:
        root = Path(self.temp.name) / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        return root

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_seed_creates_runtime_neutral_tier(self) -> None:
        repo = self.make_repo()
        args = SimpleNamespace(
            path=str(repo), tier=2, push="free", merge="free", human_todo=None,
            sensitive_data=True, relaxed_work_loss_guards=False, dry_run=False,
        )
        self.assertEqual(harness.seed_repo(args), 0)
        data = json.loads((repo / ".agent-harness" / "tier.json").read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "daily-driver")
        self.assertTrue(data["flags"]["sensitive_data"])

    def test_seed_refuses_overwrite(self) -> None:
        repo = self.make_repo()
        target = repo / ".agent-harness" / "tier.json"
        target.parent.mkdir()
        target.write_text("{}", encoding="utf-8")
        args = SimpleNamespace(
            path=str(repo), tier=1, push="free", merge="free", human_todo=None,
            sensitive_data=False, relaxed_work_loss_guards=False, dry_run=False,
        )
        with self.assertRaises(harness.HarnessError):
            harness.seed_repo(args)

    def test_seed_refuses_legacy_tier_override(self) -> None:
        repo = self.make_repo()
        target = repo / ".claude" / "tier.json"
        target.parent.mkdir()
        target.write_text("{}", encoding="utf-8")
        args = SimpleNamespace(
            path=str(repo), tier=2, push="free", merge="free", human_todo=None,
            sensitive_data=False, relaxed_work_loss_guards=False, dry_run=False,
        )
        with self.assertRaises(harness.HarnessError):
            harness.seed_repo(args)

    def test_audit_accepts_minimal_t2_repo(self) -> None:
        repo = self.make_repo()
        (repo / "AGENTS.md").write_text("# Agent guidance\n", encoding="utf-8")
        tier = {
            "tier": 2,
            "name": "daily-driver",
            "authority": {"push": "free", "merge": "free"},
            "flags": {"sensitive_data": False},
        }
        target = repo / ".agent-harness" / "tier.json"
        target.parent.mkdir()
        target.write_text(json.dumps(tier), encoding="utf-8")
        result = harness.audit_repo(repo)
        self.assertTrue(result["ok"], result["issues"])

    def test_audit_finds_stale_profile_path(self) -> None:
        repo = self.make_repo()
        (repo / "AGENTS.md").write_text("See C:/Users/jekyt/source/repo\n", encoding="utf-8")
        result = harness.audit_repo(repo)
        self.assertTrue(any("stale jekyt-profile" in issue for issue in result["issues"]))

    def test_merge_hooks_preserves_unrelated_and_replaces_managed(self) -> None:
        current = json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": "keep"}]}],
                                         "PreToolUse": [{"hooks": [{"command": "old dispatch.py --event pre --runtime codex"}]}]}})
        managed = json.dumps({"hooks": {"PreToolUse": [{"matcher": "^Bash$", "hooks": [{"command": "new dispatch.py --event pre --runtime codex"}]}]}})
        result = json.loads(harness.merge_hooks(current, managed))
        self.assertEqual(result["hooks"]["SessionStart"][0]["hooks"][0]["command"], "keep")
        self.assertEqual(len(result["hooks"]["PreToolUse"]), 1)
        self.assertIn("new dispatch.py", result["hooks"]["PreToolUse"][0]["hooks"][0]["command"])

    def test_missing_command_is_reported_not_raised(self) -> None:
        result = harness.run(["definitely-not-a-real-harness-command"])
        self.assertEqual(result.returncode, 127)


if __name__ == "__main__":
    unittest.main()
