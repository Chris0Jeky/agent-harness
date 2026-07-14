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

    def test_remove_managed_floor_preserves_unrelated_hooks(self) -> None:
        current = json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": "keep"}]}],
                                         "PreToolUse": [{"hooks": [{"command": "old dispatch.py --event pre --runtime codex"}]}]}})
        result = json.loads(harness.remove_managed_codex_floor(current))
        self.assertEqual(result["hooks"]["SessionStart"][0]["hooks"][0]["command"], "keep")
        self.assertNotIn("PreToolUse", result["hooks"])

    def test_remove_managed_floor_deletes_empty_document(self) -> None:
        current = json.dumps({
            "hooks": {
                "PreToolUse": [{
                    "hooks": [{
                        "command": "python dispatch.py --event pre --runtime codex"
                    }]
                }]
            }
        })
        self.assertEqual(harness.remove_managed_codex_floor(current), "")

    def test_sync_global_keeps_floor_project_local(self) -> None:
        root = Path(self.temp.name)
        config_root = root / "config"
        codex_source = config_root / "codex"
        (codex_source / "skills" / "sample").mkdir(parents=True)
        (codex_source / "AGENTS.md").write_text("# laws\n", encoding="utf-8")
        (codex_source / "skills" / "sample" / "SKILL.md").write_text(
            "# sample\n", encoding="utf-8"
        )
        codex_home = root / "codex-home"
        claude_home = root / "claude-home"
        skills_home = root / "skills-home"
        codex_home.mkdir()
        (codex_home / "hooks.json").write_text(
            json.dumps({
                "hooks": {
                    "SessionStart": [{"hooks": [{"command": "keep"}]}],
                    "PreToolUse": [{
                        "hooks": [{
                            "command": "python dispatch.py --event pre --runtime codex"
                        }]
                    }],
                }
            }),
            encoding="utf-8",
        )
        args = SimpleNamespace(
            config_root=str(config_root),
            codex_home=str(codex_home),
            claude_home=str(claude_home),
            skills_home=str(skills_home),
            apply=True,
        )
        self.assertEqual(harness.sync_global(args), 0)
        hooks = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
        self.assertIn("SessionStart", hooks["hooks"])
        self.assertNotIn("PreToolUse", hooks["hooks"])
        harness_root = Path(harness.__file__).resolve().parent
        self.assertTrue(
            harness.same_file(
                harness_root / "templates" / "hooks" / "dispatch.py",
                claude_home / "hooks" / "dispatch.py",
            )
        )
        self.assertFalse((codex_home / "hooks" / "dispatch.py").exists())

    def test_repo_floor_finds_direct_and_hardened_adapters(self) -> None:
        direct = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "command": (
                        "python $HOME/.claude/hooks/dispatch.py "
                        "--event pre --runtime codex"
                    )
                }
            ],
        }
        wrapped = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "command": (
                        "dispatcher=$HOME/.claude/hooks/dispatch.py; "
                        "/bin/sh .codex/invoke_deny_floor.sh"
                    )
                }
            ],
        }
        current = json.dumps({"hooks": {"PreToolUse": [direct, wrapped]}})
        self.assertEqual(harness.repo_codex_floor_groups(current), [direct, wrapped])

    def test_normalized_text_hash_ignores_line_endings(self) -> None:
        left = Path(self.temp.name) / "left.txt"
        right = Path(self.temp.name) / "right.txt"
        left.write_bytes(b"one\r\ntwo\r\n")
        right.write_bytes(b"one\ntwo\n")
        self.assertEqual(
            harness.normalized_text_sha256(left),
            harness.normalized_text_sha256(right),
        )

    def test_missing_command_is_reported_not_raised(self) -> None:
        result = harness.run(["definitely-not-a-real-harness-command"])
        self.assertEqual(result.returncode, 127)


if __name__ == "__main__":
    unittest.main()
