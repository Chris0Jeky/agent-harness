from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
            path=str(repo),
            tier=2,
            push="free",
            merge="free",
            human_todo=None,
            sensitive_data=True,
            relaxed_work_loss_guards=False,
            dry_run=False,
        )
        self.assertEqual(harness.seed_repo(args), 0)
        data = json.loads(
            (repo / ".agent-harness" / "tier.json").read_text(encoding="utf-8")
        )
        self.assertEqual(data["name"], "daily-driver")
        self.assertTrue(data["flags"]["sensitive_data"])

    def test_seed_refuses_overwrite(self) -> None:
        repo = self.make_repo()
        target = repo / ".agent-harness" / "tier.json"
        target.parent.mkdir()
        target.write_text("{}", encoding="utf-8")
        args = SimpleNamespace(
            path=str(repo),
            tier=1,
            push="free",
            merge="free",
            human_todo=None,
            sensitive_data=False,
            relaxed_work_loss_guards=False,
            dry_run=False,
        )
        with self.assertRaises(harness.HarnessError):
            harness.seed_repo(args)

    def test_seed_refuses_legacy_tier_override(self) -> None:
        repo = self.make_repo()
        target = repo / ".claude" / "tier.json"
        target.parent.mkdir()
        target.write_text("{}", encoding="utf-8")
        args = SimpleNamespace(
            path=str(repo),
            tier=2,
            push="free",
            merge="free",
            human_todo=None,
            sensitive_data=False,
            relaxed_work_loss_guards=False,
            dry_run=False,
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
        (repo / "AGENTS.md").write_text(
            "See C:/Users/jekyt/source/repo\n", encoding="utf-8"
        )
        result = harness.audit_repo(repo)
        self.assertTrue(
            any("stale jekyt-profile" in issue for issue in result["issues"])
        )

    def test_remove_managed_floor_preserves_unrelated_hooks(self) -> None:
        dispatcher = Path(self.temp.name) / "codex" / "hooks" / "dispatch.py"
        managed_handler = harness.canonical_legacy_codex_floor_handler(dispatcher)
        current = json.dumps(
            {
                "hooks": {
                    "SessionStart": [{"hooks": [{"command": "keep"}]}],
                    "PreToolUse": [
                        {
                            "hooks": [
                                managed_handler,
                                {"command": "python keep_unrelated.py"},
                            ]
                        }
                    ],
                }
            }
        )
        result = json.loads(harness.remove_managed_codex_floor(current, dispatcher))
        self.assertEqual(
            result["hooks"]["SessionStart"][0]["hooks"][0]["command"], "keep"
        )
        self.assertEqual(
            result["hooks"]["PreToolUse"][0]["hooks"],
            [{"command": "python keep_unrelated.py"}],
        )

    def test_remove_managed_floor_deletes_empty_document(self) -> None:
        dispatcher = Path(self.temp.name) / "codex" / "hooks" / "dispatch.py"
        managed_handler = harness.canonical_legacy_codex_floor_handler(dispatcher)
        current = json.dumps({"hooks": {"PreToolUse": [{"hooks": [managed_handler]}]}})
        self.assertEqual(harness.remove_managed_codex_floor(current, dispatcher), "")

    def test_remove_managed_floor_retains_unowned_dispatcher(self) -> None:
        managed = Path(self.temp.name) / "codex" / "hooks" / "dispatch.py"
        current = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "command": "python D:/custom/dispatch.py --event pre --runtime codex"
                                }
                            ]
                        }
                    ]
                }
            }
        )
        self.assertEqual(len(harness.managed_codex_floor_groups(current)), 1)
        self.assertEqual(harness.remove_managed_codex_floor(current, managed), current)

    def test_remove_managed_floor_retains_partial_or_chained_handler(self) -> None:
        managed = Path(self.temp.name) / "codex" / "hooks" / "dispatch.py"
        canonical = harness.canonical_legacy_codex_floor_handler(managed)
        for handler in (
            {"command": canonical["command"]},
            {
                **canonical,
                "commandWindows": (
                    f"{canonical['commandWindows']}; Write-Output custom"
                ),
            },
            {
                **canonical,
                "command": (f"echo {managed} --event pre --runtime codex"),
            },
        ):
            with self.subTest(handler=handler):
                current = json.dumps({"hooks": {"PreToolUse": [{"hooks": [handler]}]}})
                self.assertEqual(
                    harness.remove_managed_codex_floor(current, managed), current
                )

    def test_global_floor_detection_is_fail_closed(self) -> None:
        encoded_script = "$d='D:/custom/dispatch.py'; & $d --event pre"
        encoded = base64.b64encode(encoded_script.encode("utf-16-le")).decode("ascii")
        for handler in (
            {"command": "python D:/custom/dispatch.py --event pre"},
            {"command": "powershell .codex/invoke_deny_floor.ps1"},
            {"command": "python D:/custom/dispatch.py --event=pre --runtime=codex"},
            {"commandWindows": f"powershell -EncodedCommand {encoded}"},
        ):
            with self.subTest(handler=handler):
                current = json.dumps({"hooks": {"PreToolUse": [{"hooks": [handler]}]}})
                self.assertEqual(len(harness.managed_codex_floor_groups(current)), 1)

    def test_global_floor_detection_decodes_powershell_abbreviations(self) -> None:
        encoded_script = (
            "$d='$HOME/.claude/hooks/dispatch.py'; " "& $d --event pre --runtime codex"
        )
        encoded = base64.b64encode(encoded_script.encode("utf-16-le")).decode("ascii")
        for flag in ("-E", "-Ec", "-En", "-Enco", "-EncodedCommand"):
            with self.subTest(flag=flag):
                handler = {"commandWindows": f"powershell {flag} {encoded}"}
                current = json.dumps({"hooks": {"PreToolUse": [{"hooks": [handler]}]}})
                self.assertIn(
                    "dispatch.py",
                    harness.decode_windows_hook_command(handler["commandWindows"]),
                )
                self.assertEqual(len(harness.managed_codex_floor_groups(current)), 1)
                self.assertEqual(len(harness.repo_codex_floor_candidates(current)), 1)

        malformed = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"hooks": [{"commandWindows": "powershell -Ec not-base64"}]}
                    ]
                }
            }
        )
        self.assertEqual(len(harness.managed_codex_floor_groups(malformed)), 1)
        self.assertEqual(len(harness.repo_codex_floor_candidates(malformed)), 1)
        self.assertEqual(harness.repo_codex_floor_groups(malformed), [])

    def test_hooks_helpers_reject_wrong_shapes(self) -> None:
        for current in ("[]", "null", '"text"', "1"):
            with self.subTest(current=current):
                with self.assertRaises(harness.HarnessError):
                    harness.managed_codex_floor_groups(current)
                with self.assertRaises(harness.HarnessError):
                    harness.repo_codex_floor_groups(current)
                with self.assertRaises(harness.HarnessError):
                    harness.remove_managed_codex_floor(current)
        with self.assertRaises(harness.HarnessError):
            harness.managed_codex_floor_groups(
                json.dumps({"hooks": {"PreToolUse": [{"hooks": None}]}})
            )
        wrong = (
            {"hooks": {"PreToolUse": [{}]}},
            {"hooks": {"PreToolUse": [{"matcher": 7, "hooks": []}]}},
            {
                "hooks": {
                    "PreToolUse": [{"hooks": [{"type": 7, "command": "echo safe"}]}]
                }
            },
        )
        for document in wrong:
            with self.subTest(document=document):
                with self.assertRaises(harness.HarnessError):
                    harness.repo_codex_floor_groups(json.dumps(document))

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
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [{"hooks": [{"command": "keep"}]}],
                        "PreToolUse": [
                            {
                                "hooks": [
                                    harness.canonical_legacy_codex_floor_handler(
                                        codex_home / "hooks" / "dispatch.py"
                                    )
                                ]
                            }
                        ],
                    }
                }
            ),
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

    def test_sync_global_refuses_retained_custom_floor(self) -> None:
        root = Path(self.temp.name)
        config_root = root / "config"
        codex_source = config_root / "codex"
        (codex_source / "skills" / "sample").mkdir(parents=True)
        (codex_source / "AGENTS.md").write_text("# laws\n", encoding="utf-8")
        (codex_source / "skills" / "sample" / "SKILL.md").write_text(
            "# sample\n", encoding="utf-8"
        )
        codex_home = root / "codex-home"
        codex_home.mkdir()
        original = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "command": (
                                        "python D:/custom/dispatch.py --event pre "
                                        "--runtime codex"
                                    )
                                }
                            ]
                        }
                    ]
                }
            }
        )
        hooks_path = codex_home / "hooks.json"
        hooks_path.write_text(original, encoding="utf-8")
        args = SimpleNamespace(
            config_root=str(config_root),
            codex_home=str(codex_home),
            claude_home=str(root / "claude-home"),
            skills_home=str(root / "skills-home"),
            apply=True,
        )
        with self.assertRaises(harness.HarnessError):
            harness.sync_global(args)
        self.assertEqual(hooks_path.read_text(encoding="utf-8"), original)

    def test_sync_global_preserves_same_second_backup_sets(self) -> None:
        root = Path(self.temp.name)
        config_root = root / "config"
        codex_source = config_root / "codex"
        source_skill = codex_source / "skills" / "sample"
        source_skill.mkdir(parents=True)
        (codex_source / "AGENTS.md").write_text("canonical laws\n", encoding="utf-8")
        (source_skill / "SKILL.md").write_text("canonical skill\n", encoding="utf-8")

        codex_home = root / "codex-home"
        claude_home = root / "claude-home"
        skills_home = root / "skills-home"
        (claude_home / "hooks").mkdir(parents=True)
        (skills_home / "sample").mkdir(parents=True)
        codex_home.mkdir()
        (codex_home / "AGENTS.md").write_text("original laws\n", encoding="utf-8")
        (claude_home / "hooks" / "dispatch.py").write_text(
            "original dispatcher\n", encoding="utf-8"
        )
        (claude_home / "hooks" / "smoke_test.py").write_text(
            "original smoke\n", encoding="utf-8"
        )
        (skills_home / "sample" / "SKILL.md").write_text(
            "original skill\n", encoding="utf-8"
        )
        args = SimpleNamespace(
            config_root=str(config_root),
            codex_home=str(codex_home),
            claude_home=str(claude_home),
            skills_home=str(skills_home),
            apply=True,
        )
        frozen = datetime(2026, 7, 14, 4, 0, tzinfo=timezone.utc)

        class FrozenDatetime:
            @classmethod
            def now(cls, _tz: object) -> datetime:
                return frozen

        with mock.patch.object(harness, "datetime", FrozenDatetime):
            self.assertEqual(harness.sync_global(args), 0)
            (codex_home / "AGENTS.md").write_text(
                "intermediate laws\n", encoding="utf-8"
            )
            (skills_home / "sample" / "SKILL.md").write_text(
                "intermediate skill\n", encoding="utf-8"
            )
            self.assertEqual(harness.sync_global(args), 0)

        first = codex_home / "backups" / "20260714T040000Z"
        second = codex_home / "backups" / "20260714T040000Z-01"
        self.assertEqual(
            (first / "AGENTS.md").read_text(encoding="utf-8"), "original laws\n"
        )
        self.assertEqual(
            (second / "AGENTS.md").read_text(encoding="utf-8"),
            "intermediate laws\n",
        )
        first_skill = skills_home / ".harness-backups" / first.name / "sample"
        second_skill = skills_home / ".harness-backups" / second.name / "sample"
        self.assertEqual(
            (first_skill / "SKILL.md").read_text(encoding="utf-8"),
            "original skill\n",
        )
        self.assertEqual(
            (second_skill / "SKILL.md").read_text(encoding="utf-8"),
            "intermediate skill\n",
        )

    def test_repo_floor_finds_direct_and_hardened_adapters(self) -> None:
        direct = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        "python $HOME/.claude/hooks/dispatch.py "
                        "--event pre --runtime codex"
                    ),
                    "commandWindows": (
                        "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
                        "--event=pre --runtime=codex"
                    ),
                }
            ],
        }
        wrapped = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        "dispatcher=$HOME/.claude/hooks/dispatch.py; "
                        "/bin/sh .codex/invoke_deny_floor.sh"
                    ),
                    "commandWindows": (
                        "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
                        "& .codex/invoke_deny_floor.ps1"
                    ),
                }
            ],
        }
        current = json.dumps({"hooks": {"PreToolUse": [direct, wrapped]}})
        self.assertEqual(harness.repo_codex_floor_groups(current), [direct, wrapped])

    def test_repo_floor_decodes_windows_command_and_binds_pin(self) -> None:
        pin = "a" * 64
        windows_script = (
            f"$expected='{pin}';"
            "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py';"
            "& .codex/invoke_deny_floor.ps1"
        )
        encoded = base64.b64encode(windows_script.encode("utf-16-le")).decode("ascii")
        group = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        f"expected={pin}; dispatcher=$HOME/.claude/hooks/dispatch.py; "
                        "/bin/sh .codex/invoke_deny_floor.sh"
                    ),
                    "commandWindows": f"powershell -EncodedCommand {encoded}",
                }
            ],
        }
        current = json.dumps({"hooks": {"PreToolUse": [group]}})
        self.assertEqual(harness.repo_codex_floor_groups(current, pin), [group])
        self.assertEqual(harness.repo_codex_floor_groups(current, "b" * 64), [])

    def test_repo_floor_requires_both_platforms_and_positive_matcher(self) -> None:
        handler = {
            "type": "command",
            "command": (
                "python $HOME/.claude/hooks/dispatch.py --event pre --runtime codex"
            ),
            "commandWindows": "Write-Output floor-disabled",
        }
        for matcher in ("^NotBash$", "^(?!Bash$).*$", "bash"):
            with self.subTest(matcher=matcher):
                current = json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [{"matcher": matcher, "hooks": [handler]}]
                        }
                    }
                )
                self.assertEqual(harness.repo_codex_floor_groups(current), [])
        current = json.dumps(
            {"hooks": {"PreToolUse": [{"matcher": "^Bash$", "hooks": [handler]}]}}
        )
        self.assertEqual(harness.repo_codex_floor_groups(current), [])

    def test_repo_floor_requires_single_handler_group_and_pin(self) -> None:
        pin = "c" * 64
        valid = {
            "type": "command",
            "command": (
                "python $HOME/.claude/hooks/dispatch.py --event pre --runtime codex"
            ),
            "commandWindows": (
                "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
                "--event pre --runtime codex"
            ),
        }
        pin_only = {
            "type": "command",
            "command": f"echo {pin}",
            "commandWindows": f"Write-Output {pin}",
        }
        group = {"matcher": "^Bash$", "hooks": [valid, pin_only]}
        current = json.dumps({"hooks": {"PreToolUse": [group]}})
        self.assertEqual(harness.repo_codex_floor_groups(current), [])
        self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

        duplicate = {"matcher": "^Bash$", "hooks": [valid, dict(valid)]}
        duplicate_text = json.dumps({"hooks": {"PreToolUse": [duplicate]}})
        self.assertEqual(harness.repo_codex_floor_groups(duplicate_text), [])
        self.assertEqual(len(harness.repo_codex_floor_candidates(duplicate_text)), 2)

        broken = {
            "type": "command",
            "command": valid["command"],
            "commandWindows": "Write-Output disabled",
        }
        mixed = {"matcher": "^Bash$", "hooks": [valid, broken]}
        mixed_text = json.dumps({"hooks": {"PreToolUse": [mixed]}})
        self.assertEqual(harness.repo_codex_floor_groups(mixed_text), [])
        self.assertEqual(len(harness.repo_codex_floor_candidates(mixed_text)), 2)

    def test_repo_floor_rejects_non_floor_sibling_handler(self) -> None:
        pin = "7" * 64
        floor = {
            "type": "command",
            "command": (
                f"expected={pin}; python $HOME/.claude/hooks/dispatch.py "
                "--event pre --runtime codex"
            ),
            "commandWindows": (
                f"$expected='{pin}'; py -3 "
                "$env:USERPROFILE/.claude/hooks/dispatch.py "
                "--event pre --runtime codex"
            ),
        }
        single = {"matcher": "^Bash$", "hooks": [floor]}
        single_text = json.dumps({"hooks": {"PreToolUse": [single]}})
        self.assertEqual(harness.repo_codex_floor_groups(single_text, pin), [single])

        sibling = {
            "type": "command",
            "command": "python .codex/audit_command.py",
            "commandWindows": "py -3 .codex/audit_command.py",
        }
        combined = {"matcher": "^Bash$", "hooks": [floor, sibling]}
        combined_text = json.dumps({"hooks": {"PreToolUse": [combined]}})
        self.assertEqual(len(harness.repo_codex_floor_candidates(combined_text)), 1)
        self.assertEqual(harness.repo_codex_floor_groups(combined_text, pin), [])

    def test_repo_floor_rejects_data_only_markers(self) -> None:
        pin = "d" * 64
        marker_text = f"{pin} .claude/hooks/dispatch.py invoke_deny_floor"
        encoded = base64.b64encode(marker_text.encode("utf-16-le")).decode("ascii")
        group = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "type": "command",
                    "command": f"echo '{marker_text}'",
                    "commandWindows": f"echo -EncodedCommand {encoded}",
                }
            ],
        }
        current = json.dumps({"hooks": {"PreToolUse": [group]}})
        self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

    def test_repo_floor_rejects_commented_and_chained_markers(self) -> None:
        pin = "e" * 64
        marker = (
            "python $HOME/.claude/hooks/dispatch.py "
            f"--event pre --runtime codex expected={pin}"
        )
        carriers = (
            (
                f"python -c pass # {marker}",
                f"py -3 -c pass # {marker}",
            ),
            (
                f"python -c pass; echo {marker}",
                f"py -3 -c pass; Write-Output {marker}",
            ),
        )
        for command, command_windows in carriers:
            with self.subTest(command=command):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "commandWindows": command_windows,
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

    def test_repo_floor_rejects_posix_invocation_control_operators(self) -> None:
        pin = "1" * 64
        invocation = (
            "python $HOME/.claude/hooks/dispatch.py " "--event pre --runtime codex"
        )
        windows = (
            "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        suffixes = (
            "< /dev/null",
            "> /dev/null",
            ">> /dev/null",
            "2> /dev/null",
            "| cat",
            "&& true",
            "|| true",
            "<<< '{}'",
        )
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"expected={pin}; {invocation} {suffix}",
                            "commandWindows": f"$expected='{pin}'; {windows}",
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

    def test_repo_floor_rejects_windows_invocation_control_operators(self) -> None:
        pin = "2" * 64
        posix = "python $HOME/.claude/hooks/dispatch.py " "--event pre --runtime codex"
        invocation = (
            "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        suffixes = (
            "< $null",
            "> $null",
            ">> $null",
            "2> $null",
            "| Out-Null",
            "&& exit 0",
            "|| exit 0",
            "<<< '{}'",
            "& Write-Output bypass",
        )
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"expected={pin}; {posix}",
                            "commandWindows": (
                                f"$expected='{pin}'; {invocation} {suffix}"
                            ),
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

    def test_repo_floor_allows_standalone_invocations_with_literal_controls(
        self,
    ) -> None:
        pin = "3" * 64
        posix = (
            f"expected='{pin}'\n"
            "python $HOME/.claude/hooks/dispatch.py "
            "--event pre --runtime codex # > /dev/null | cat && true"
        )
        windows = (
            f"$expected='{pin}'\n"
            "& py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex # > $null | Out-Null && exit 0"
        )
        group = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "type": "command",
                    "command": posix,
                    "commandWindows": windows,
                }
            ],
        }
        current = json.dumps({"hooks": {"PreToolUse": [group]}})
        self.assertEqual(harness.repo_codex_floor_groups(current, pin), [group])
        for windows in (False, True):
            with self.subTest(windows=windows):
                self.assertTrue(
                    harness.is_safe_floor_invocation_segment(
                        "python 'literal < > | && || <<<'", windows=windows
                    )
                )

    def test_repo_floor_rejects_extra_executable_segments(self) -> None:
        pin = "5" * 64
        posix_invocation = (
            "python $HOME/.claude/hooks/dispatch.py --event pre --runtime codex"
        )
        windows_invocation = (
            "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        valid_posix = f"expected={pin}; {posix_invocation}"
        valid_windows = f"$expected='{pin}'; {windows_invocation}"
        invalid_pairs = (
            (f"echo before; {valid_posix}", valid_windows),
            (f"{valid_posix}; echo after", valid_windows),
            (valid_posix, f"Write-Output before; {valid_windows}"),
            (valid_posix, f"{valid_windows}; Write-Output after"),
            (f"{valid_posix}; {posix_invocation}", valid_windows),
            (valid_posix, f"{valid_windows}; {windows_invocation}"),
            (f"{posix_invocation}; expected={pin}", valid_windows),
            (valid_posix, f"{windows_invocation}; $expected='{pin}'"),
        )
        for command, command_windows in invalid_pairs:
            with self.subTest(command=command, command_windows=command_windows):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "commandWindows": command_windows,
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

    def test_repo_floor_rejects_command_substitution_in_invocation(self) -> None:
        pin = "7" * 64
        good_posix = (
            "python $HOME/.claude/hooks/dispatch.py --event pre --runtime codex"
        )
        good_windows = (
            "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        invalid_pairs = (
            (
                f"expected={pin}; {good_posix} $(rm -rf /critical/outside)",
                f"$expected='{pin}'; {good_windows}",
            ),
            (
                f"expected={pin}; {good_posix} `rm -rf /critical/outside`",
                f"$expected='{pin}'; {good_windows}",
            ),
            (
                f"expected={pin}; {good_posix}",
                f"$expected='{pin}'; {good_windows} $(Remove-Item x)",
            ),
        )
        for command, command_windows in invalid_pairs:
            with self.subTest(command=command, command_windows=command_windows):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "commandWindows": command_windows,
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])
        self.assertFalse(
            harness.is_safe_floor_invocation_segment(
                "python dispatch.py $(rm -rf x)", windows=False
            )
        )
        self.assertFalse(
            harness.is_safe_floor_invocation_segment(
                "python dispatch.py `rm x`", windows=False
            )
        )

    def test_repo_floor_requires_dispatcher_as_python_script_operand(self) -> None:
        pin = "8" * 64
        good_posix = (
            "python $HOME/.claude/hooks/dispatch.py --event pre --runtime codex"
        )
        good_windows = (
            "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        invalid_pairs = (
            (
                f"expected={pin}; python -c pass $HOME/.claude/hooks/dispatch.py "
                "--event pre --runtime codex",
                f"$expected='{pin}'; {good_windows}",
            ),
            (
                f"expected={pin}; python -m http.server "
                "$HOME/.claude/hooks/dispatch.py --event pre --runtime codex",
                f"$expected='{pin}'; {good_windows}",
            ),
            (
                f"expected={pin}; {good_posix}",
                f"$expected='{pin}'; py -3 -c pass "
                "$env:USERPROFILE/.claude/hooks/dispatch.py "
                "--event pre --runtime codex",
            ),
        )
        for command, command_windows in invalid_pairs:
            with self.subTest(command=command, command_windows=command_windows):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "commandWindows": command_windows,
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

    def test_repo_floor_rejects_non_inert_setup_segments(self) -> None:
        pin = "6" * 64
        posix_invocation = (
            "python $HOME/.claude/hooks/dispatch.py --event pre --runtime codex"
        )
        windows_invocation = (
            "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        valid_posix = f"expected={pin}; {posix_invocation}"
        valid_windows = f"$expected='{pin}'; {windows_invocation}"
        invalid_pairs = (
            (f"note=unused; {valid_posix}", valid_windows),
            (valid_posix, f"$note='unused'; {valid_windows}"),
            (
                "dispatcher=$(printf $HOME/.claude/hooks/dispatch.py); "
                f"expected={pin}; exec python3 $dispatcher --event pre --runtime codex",
                valid_windows,
            ),
            (
                valid_posix,
                "$d=Write-Output $env:USERPROFILE/.claude/hooks/dispatch.py; "
                f"$expected='{pin}'; & $d --event pre --runtime codex",
            ),
        )
        for command, command_windows in invalid_pairs:
            with self.subTest(command=command, command_windows=command_windows):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "commandWindows": command_windows,
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

    def test_repo_floor_rejects_windows_here_string_and_extra_call_operator(
        self,
    ) -> None:
        pin = "4" * 64
        posix = (
            f"expected={pin}; python $HOME/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        invalid_windows = (
            (
                f"$expected='{pin}'; & py -3 "
                "$env:USERPROFILE/.claude/hooks/dispatch.py "
                "--event pre --runtime codex @'payload'@"
            ),
            (
                f"$expected='{pin}'; & & py -3 "
                "$env:USERPROFILE/.claude/hooks/dispatch.py "
                "--event pre --runtime codex"
            ),
        )
        for command_windows in invalid_windows:
            with self.subTest(command_windows=command_windows):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": posix,
                            "commandWindows": command_windows,
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

    def test_repo_owns_current_pinned_codex_floor_adapter(self) -> None:
        # agent-harness is an active Codex checkout, so it owns exactly one
        # project floor adapter pinned to the current dispatcher. This test
        # keeps the pin from silently drifting when dispatch.py changes.
        repo_root = Path(harness.__file__).resolve().parent
        adapter = repo_root / ".codex" / "hooks.json"
        self.assertTrue(
            adapter.is_file(),
            "agent-harness must own a .codex/hooks.json project floor adapter",
        )
        text = adapter.read_text(encoding="utf-8")
        pin = harness.normalized_text_sha256(
            repo_root / "templates" / "hooks" / "dispatch.py"
        )
        self.assertEqual(
            len(harness.repo_codex_floor_candidates(text)),
            1,
            "adapter must expose exactly one candidate floor handler",
        )
        self.assertEqual(
            len(harness.repo_codex_floor_groups(text, pin)),
            1,
            "adapter pin must match the current normalized dispatcher hash; "
            "refresh .codex/hooks.json after editing templates/hooks/dispatch.py",
        )

    def test_repo_floor_rejects_non_blocking_handler_shapes(self) -> None:
        pin = "9" * 64
        posix = f"expected={pin}; python $HOME/.claude/hooks/dispatch.py --event pre --runtime codex"
        windows = (
            f"$expected='{pin}'; py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        base_handler = {
            "type": "command",
            "command": posix,
            "commandWindows": windows,
        }
        # The canonical shape (positive timeout, synchronous) still certifies.
        good = {**base_handler, "timeout": 5}
        good_doc = json.dumps(
            {"hooks": {"PreToolUse": [{"matcher": "^Bash$", "hooks": [good]}]}}
        )
        self.assertEqual(len(harness.repo_codex_floor_groups(good_doc, pin)), 1)
        # A handler Codex would not run as a blocking gate must never certify.
        for bad_field in (
            {"async": True},
            {"background": True},
            {"nonBlocking": True},
            {"timeout": 0},
            {"timeout": -1},
            {"timeout": "5"},
            {"timeout": True},
        ):
            with self.subTest(bad_field=bad_field):
                handler = {**base_handler, **bad_field}
                doc = json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [{"matcher": "^Bash$", "hooks": [handler]}]
                        }
                    }
                )
                self.assertEqual(harness.repo_codex_floor_groups(doc, pin), [])

    def test_repo_floor_requires_bound_pin_and_executable_variable_flow(self) -> None:
        pin = "f" * 64
        posix = (
            f"expected='{pin}'; dispatcher=$HOME/.claude/hooks/dispatch.py; "
            'exec python3 "$dispatcher" --event pre --runtime codex'
        )
        windows = (
            f"$expected='{pin}';"
            "$d=Join-Path $env:USERPROFILE '.claude\\hooks\\dispatch.py';"
            "$p=Join-Path $env:SystemRoot 'py.exe';"
            "& $p -3 $d --event pre --runtime codex"
        )
        group = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "type": "command",
                    "command": posix,
                    "commandWindows": windows,
                }
            ],
        }
        current = json.dumps({"hooks": {"PreToolUse": [group]}})
        self.assertEqual(harness.repo_codex_floor_groups(current, pin), [group])

        loose_pin = json.loads(current)
        loose_pin["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = (
            "python $HOME/.claude/hooks/dispatch.py --event pre --runtime codex " + pin
        )
        self.assertEqual(
            harness.repo_codex_floor_groups(json.dumps(loose_pin), pin), []
        )

    def test_repo_floor_rejects_non_command_handler(self) -> None:
        handler = {
            "type": "prompt",
            "command": (
                "python $HOME/.claude/hooks/dispatch.py --event pre --runtime codex"
            ),
            "commandWindows": (
                "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
                "--event pre --runtime codex"
            ),
        }
        current = json.dumps(
            {"hooks": {"PreToolUse": [{"matcher": "^Bash$", "hooks": [handler]}]}}
        )
        self.assertEqual(harness.repo_codex_floor_groups(current), [])

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
