#!/usr/bin/env python3
"""Portable, dependency-free tooling for the cross-runtime agent harness."""

from __future__ import annotations

import argparse
import base64
import binascii
import filecmp
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

TIER_NAMES = {
    0: "tombstone",
    1: "sandbox",
    2: "daily-driver",
    3: "workshop",
    4: "live-wire",
}
CLAUDE_LINE_CAPS = {0: 3, 1: 40, 2: 100, 3: 150, 4: 150}
AUTHORITY_VALUES = {"free", "gated", "human-only"}
SCAN_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    "AGENT_MAP.md",
    ".agent-harness",
    ".agents",
    ".claude",
    ".codex",
    "scripts/agent",
)


class HarnessError(RuntimeError):
    """A user-actionable harness failure."""


def run(
    command: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def git_root(path: Path) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], path)
    if result.returncode:
        raise HarnessError(f"not a Git repository: {path}")
    return Path(result.stdout.strip()).resolve()


def tier_path(repo: Path) -> Path | None:
    for candidate in (
        repo / ".agent-harness" / "tier.json",
        repo / ".claude" / "tier.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def load_tier(repo: Path) -> tuple[Path | None, dict[str, Any]]:
    path = tier_path(repo)
    if path is None:
        return None, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"invalid tier file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessError(f"tier file must contain an object: {path}")
    return path, data


def validate_tier(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    tier = data.get("tier")
    if tier not in TIER_NAMES:
        issues.append("tier must be an integer from 0 through 4")
    elif data.get("name") != TIER_NAMES[tier]:
        issues.append(f"name must be {TIER_NAMES[tier]!r} for tier {tier}")
    authority = data.get("authority")
    if not isinstance(authority, dict):
        issues.append("authority must be an object")
    else:
        for key in ("push", "merge"):
            if authority.get(key) not in AUTHORITY_VALUES:
                issues.append(
                    f"authority.{key} must be one of {sorted(AUTHORITY_VALUES)}"
                )
    flags = data.get("flags")
    if not isinstance(flags, dict):
        issues.append("flags must be an object")
    elif any(not isinstance(value, bool) for value in flags.values()):
        issues.append("all flag values must be booleans")
    return issues


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def budget_issues(repo: Path, tier: int) -> list[str]:
    checks: list[tuple[Path, int, str]] = []
    if (repo / "CLAUDE.md").is_file():
        checks.append(
            (
                repo / "CLAUDE.md",
                CLAUDE_LINE_CAPS[tier],
                "rotate detail into linked docs",
            )
        )
    if (repo / "AGENTS.md").is_file():
        checks.append(
            (repo / "AGENTS.md", 80, "move detail to the repo map or domain docs")
        )
    if (repo / "AGENT_MAP.md").is_file():
        checks.append((repo / "AGENT_MAP.md", 100, "split detail into docs/regions"))
    for skill in (
        (repo / ".agents" / "skills").glob("*/SKILL.md")
        if (repo / ".agents" / "skills").is_dir()
        else ()
    ):
        checks.append((skill, 80, "split detail into a directly linked reference"))
    issues = []
    for path, cap, remedy in checks:
        actual = line_count(path)
        if actual > cap:
            issues.append(
                f"{path.relative_to(repo)}: {actual}>{cap} lines; ROTATE: {remedy}"
            )
    return issues


def stale_path_issues(repo: Path) -> list[str]:
    needles = ("C:/Users/jekyt", "C:\\Users\\jekyt")
    issues: list[str] = []
    candidates: list[Path] = []
    for raw in SCAN_PATHS:
        path = repo / raw
        if path.is_file():
            candidates.append(path)
        elif path.is_dir():
            candidates.extend(
                p
                for p in path.rglob("*")
                if p.is_file() and p.stat().st_size <= 1_000_000
            )
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(needle.lower() in text.lower() for needle in needles):
            issues.append(
                f"{path.relative_to(repo)} contains a stale jekyt-profile path"
            )
    return issues


def audit_repo(path: Path) -> dict[str, Any]:
    repo = git_root(path)
    config_path, tier_data = load_tier(repo)
    issues: list[str] = []
    if config_path is None:
        issues.append(
            "missing .agent-harness/tier.json (legacy .claude/tier.json also accepted)"
        )
        tier = 1
    else:
        issues.extend(validate_tier(tier_data))
        tier = tier_data.get("tier") if tier_data.get("tier") in TIER_NAMES else 1
    if not (repo / "AGENTS.md").is_file():
        issues.append("missing root AGENTS.md")
    issues.extend(budget_issues(repo, tier))
    issues.extend(stale_path_issues(repo))
    status = run(["git", "status", "--short", "--branch"], repo)
    return {
        "repo": str(repo),
        "tier_file": str(config_path) if config_path else None,
        "tier": tier,
        "git": status.stdout.strip(),
        "issues": issues,
        "ok": not issues,
    }


def seed_repo(args: argparse.Namespace) -> int:
    repo = git_root(Path(args.path))
    target = repo / ".agent-harness" / "tier.json"
    existing = tier_path(repo)
    if existing is not None:
        raise HarnessError(f"refusing to override existing tier declaration {existing}")
    flags = {
        "sensitive_data": bool(args.sensitive_data),
        "wave_mode": False,
        "dormant_production": False,
        "relaxed_work_loss_guards": bool(args.relaxed_work_loss_guards),
    }
    payload = {
        "tier": args.tier,
        "name": TIER_NAMES[args.tier],
        "authority": {"push": args.push, "merge": args.merge},
        "flags": flags,
        "model_routing": {
            "harness_and_review": "sol",
            "slices": "terra",
            "maintenance": "luna",
        },
        "budgets": {
            "standing_context_tokens": {1: 1000, 2: 3000, 3: 6000, 4: 8000}.get(
                args.tier, 200
            )
        },
        "human_todo": args.human_todo,
        "last_reviewed": date.today().isoformat(),
    }
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"created {target}")
    return 0


def same_file(left: Path, right: Path) -> bool:
    return (
        left.is_file() and right.is_file() and filecmp.cmp(left, right, shallow=False)
    )


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        return ""
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def copy_with_backup(source: Path, target: Path, backup_root: Path) -> str:
    if same_file(source, target):
        return "unchanged"
    if target.exists():
        backup = backup_root / target.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return "updated" if (backup_root / target.name).exists() else "created"


def reserve_backup_root(parent: Path, stem: str) -> Path:
    """Atomically reserve a backup directory without replacing an earlier run."""
    parent.mkdir(parents=True, exist_ok=True)
    index = 0
    while True:
        suffix = "" if index == 0 else f"-{index:02d}"
        candidate = parent / f"{stem}{suffix}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            index += 1


def parse_hooks_document(
    current: str,
) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    """Parse the hooks document and reject ambiguous topology shapes."""
    try:
        current_data = json.loads(current) if current.strip() else {"hooks": {}}
    except json.JSONDecodeError as exc:
        raise HarnessError(f"invalid existing hooks.json: {exc}") from exc
    if not isinstance(current_data, dict):
        raise HarnessError("existing hooks.json must contain an object")
    hooks = current_data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HarnessError("existing hooks.json has a non-object hooks field")
    groups = hooks.get("PreToolUse", [])
    if not isinstance(groups, list):
        raise HarnessError("existing hooks.PreToolUse must be an array")
    for group in groups:
        if not isinstance(group, dict):
            raise HarnessError("existing hooks.PreToolUse entries must be objects")
        if "hooks" not in group:
            raise HarnessError("existing PreToolUse groups must contain hooks")
        if "matcher" in group and not isinstance(group["matcher"], str):
            raise HarnessError("existing PreToolUse group matcher must be a string")
        handlers = group["hooks"]
        if not isinstance(handlers, list):
            raise HarnessError("existing PreToolUse group hooks must be an array")
        for handler in handlers:
            if not isinstance(handler, dict):
                raise HarnessError("existing hook handlers must be objects")
            if "type" in handler and not isinstance(handler["type"], str):
                raise HarnessError("existing hook handler type must be a string")
            for field in ("command", "commandWindows"):
                if field in handler and not isinstance(handler[field], str):
                    raise HarnessError(
                        f"existing hook handler {field} must be a string"
                    )
    return current_data, hooks, groups


def command_has_flag_value(command: str, flag: str, value: str) -> bool:
    return bool(
        re.search(
            rf"(?i)(?:^|\s)--{re.escape(flag)}(?:\s+|=)[\"']?"
            rf"{re.escape(value)}[\"']?(?=$|[\s;|&])",
            command,
        )
    )


def command_points_to_dispatcher(
    command: str, managed_dispatcher: Path | None = None
) -> bool:
    normalized = command.lower().replace("\\", "/")
    if managed_dispatcher is None:
        return bool(
            re.search(
                r"(?i)(?:^|[\s\"'=])[^\s\"']*dispatch\.py(?=$|[\s\"';|&])", normalized
            )
        )
    expected = str(managed_dispatcher.resolve()).lower().replace("\\", "/")
    return bool(
        re.search(
            rf"(?:^|[\s\"'=]){re.escape(expected)}(?=$|[\s\"';|&])",
            normalized,
        )
    )


def is_direct_codex_floor_handler(
    handler: dict[str, Any], managed_dispatcher: Path | None = None
) -> bool:
    for field in ("command", "commandWindows"):
        command = handler.get(field, "")
        if (
            command
            and command_points_to_dispatcher(command, managed_dispatcher)
            and command_has_flag_value(command, "runtime", "codex")
            and command_has_flag_value(command, "event", "pre")
        ):
            return True
    return False


def is_global_floor_handler(handler: dict[str, Any]) -> bool:
    """Recognize any global dispatcher/wrapper so doctor cannot false-green."""
    return any(
        command
        and (
            command_points_to_dispatcher(command)
            or "invoke_deny_floor" in command.lower()
        )
        for command in (
            strip_shell_comments(handler.get("command", "")),
            strip_shell_comments(
                decode_windows_hook_command(handler.get("commandWindows", ""))
            ),
        )
    )


def canonical_legacy_codex_floor_handler(managed_dispatcher: Path) -> dict[str, Any]:
    """Render the exact historical global adapter that sync-global once owned."""
    dispatcher = str(managed_dispatcher.resolve())
    return {
        "type": "command",
        "commandWindows": (
            f'C:\\Windows\\py.exe -3 "{dispatcher}" --event pre --runtime codex'
        ),
        "command": f'python3 "{dispatcher}" --event pre --runtime codex',
        "timeout": 5,
        "statusMessage": "Checking irreversible-command policy",
    }


def is_owned_global_floor_handler(
    handler: dict[str, Any], managed_dispatcher: Path
) -> bool:
    """Match only the exact historical managed handler shape."""
    return handler == canonical_legacy_codex_floor_handler(managed_dispatcher)


def managed_codex_floor_groups(current: str) -> list[Any]:
    """Find every direct global Codex floor, including unowned custom copies."""
    _current_data, _hooks, existing_groups = parse_hooks_document(current)

    def is_managed(group: Any) -> bool:
        for handler in group.get("hooks", []):
            if is_global_floor_handler(handler):
                return True
        return False

    return [group for group in existing_groups if is_managed(group)]


def decode_windows_hook_command(command: str) -> str:
    """Expose a PowerShell EncodedCommand payload for topology validation."""
    executable_match = re.match(r'^\s*(?:&\s*)?(?:"([^"]+)"|(\S+))', command)
    if executable_match is None:
        return command
    executable = (executable_match.group(1) or executable_match.group(2)).replace(
        "\\", "/"
    )
    executable = executable.rsplit("/", 1)[-1].lower().removesuffix(".exe")
    if executable not in {"powershell", "pwsh"}:
        return command
    encoded_payload = None
    for match in re.finditer(r"(?i)(?:^|\s)-([a-z]+)(?::|\s+)", command):
        option = match.group(1).lower()
        if option not in {"e", "ec"} and not "encodedcommand".startswith(option):
            continue
        payload_match = re.match(
            r"[\"']?([A-Za-z0-9+/=]+)[\"']?(?=$|\s)", command[match.end() :]
        )
        if payload_match is None:
            return "invoke_deny_floor opaque-encoded-command"
        encoded_payload = payload_match.group(1)
        break
    if encoded_payload is None:
        return command
    try:
        payload = base64.b64decode(encoded_payload, validate=True)
        if not payload or len(payload) % 2:
            return "invoke_deny_floor opaque-encoded-command"
        return payload.decode("utf-16-le")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return "invoke_deny_floor opaque-encoded-command"


def strip_shell_comments(command: str) -> str:
    """Remove unquoted line comments before inspecting topology tokens."""
    result: list[str] = []
    quote = ""
    escaped = False
    in_comment = False
    for index, char in enumerate(command):
        if in_comment:
            if char in "\r\n":
                in_comment = False
                result.append(char)
            continue
        if escaped:
            result.append(char)
            escaped = False
            continue
        if char in {"\\", "`"} and quote != "'":
            result.append(char)
            escaped = True
            continue
        if quote:
            result.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            result.append(char)
            continue
        previous = command[index - 1] if index else ""
        if char == "#" and (not previous or previous.isspace() or previous in ";|&()"):
            in_comment = True
            continue
        result.append(char)
    return "".join(result)


def shell_command_segments(command: str) -> list[str]:
    """Split top-level command statements without splitting quoted data."""
    segments: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for char in command:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char in {"\\", "`"} and quote != "'":
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            continue
        if char in ";\r\n":
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current = []
            continue
        current.append(char)
    segment = "".join(current).strip()
    if segment:
        segments.append(segment)
    return segments


def assigned_floor_variables(segments: list[str], marker: str) -> set[str]:
    """Find variables whose assignment statement binds a floor path marker."""
    result: set[str] = set()
    for segment in segments:
        normalized = segment.lower().replace("\\", "/")
        marker_index = normalized.find(marker)
        if marker_index < 0:
            continue
        prefix = segment[:marker_index]
        matches = list(
            re.finditer(r"(?i)(?:^|[\s{(])\$?([a-z_][a-z0-9_]*)\s*=", prefix)
        )
        if matches:
            result.add(matches[-1].group(1).lower())
    return result


def variable_reference(name: str) -> str:
    return rf"\$(?:\{{{re.escape(name)}\}}|{re.escape(name)}\b)"


def starts_python(segment: str) -> bool:
    return bool(
        re.match(
            r"(?i)^\s*\(?\s*(?:exec\s+)?(?:&\s*)?"
            r"(?:\"(?:[^\"]*[\\/])?(?:python3?|py)(?:\.exe)?\"|"
            r"'(?:[^']*[\\/])?(?:python3?|py)(?:\.exe)?'|"
            r"(?:\S*[\\/])?(?:python3?|py)(?:\.exe)?)(?=\s|$)",
            segment,
        )
    )


def segment_invokes_direct_floor(
    segment: str, dispatcher_variables: set[str], interpreter_variables: set[str]
) -> bool:
    """Recognize conservative direct dispatcher execution shapes."""
    if not (
        command_has_flag_value(segment, "event", "pre")
        and command_has_flag_value(segment, "runtime", "codex")
    ):
        return False
    normalized = segment.lower().replace("\\", "/")
    if starts_python(segment) and ".claude/hooks/dispatch.py" in normalized:
        return True
    for dispatcher in dispatcher_variables:
        dispatcher_ref = variable_reference(dispatcher)
        if starts_python(segment) and re.search(dispatcher_ref, segment, re.IGNORECASE):
            return True
        if re.match(rf"(?i)^\s*&\s*{dispatcher_ref}(?=\s|$)", segment):
            return True
        for interpreter in interpreter_variables:
            interpreter_ref = variable_reference(interpreter)
            if re.match(
                rf"(?i)^\s*&\s*{interpreter_ref}(?=\s|$).*{dispatcher_ref}",
                segment,
            ):
                return True
    return False


def segment_invokes_wrapper(segment: str, wrapper_variables: set[str]) -> bool:
    """Recognize conservative project-wrapper execution shapes."""
    normalized = segment.lower().replace("\\", "/")
    targets = [r"[^\s;]*invoke_deny_floor[^\s;]*"] + [
        variable_reference(name) for name in wrapper_variables
    ]
    for target in targets:
        if re.match(
            rf"(?i)^\s*\(?\s*(?:exec\s+)?(?:/[^\s]*/)?(?:ba)?sh\b.*{target}",
            normalized,
        ):
            return True
        if re.match(rf"(?i)^\s*&\s*{target}", normalized):
            return True
        if re.match(
            rf"(?i)^\s*(?:\$?[a-z_]\w*\s*=\s*)?start-process\b"
            rf".*-argumentlist\b.*-file\b.*{target}",
            normalized,
        ):
            return True
        if re.match(
            rf"(?i)^\s*(?:powershell|pwsh)(?:\.exe)?\b.*-file\b.*{target}",
            normalized,
        ):
            return True
    return False


def command_binds_pin(command: str, expected_pin: str | None) -> bool:
    if expected_pin is None:
        return True
    return bool(
        re.search(
            rf"(?i)\$?[a-z_][a-z0-9_]*\s*=\s*[\"']?"
            rf"{re.escape(expected_pin)}[\"']?(?=$|[\s;}})])",
            command,
        )
    )


def matcher_targets_bash(matcher: Any) -> bool:
    """Accept only bounded matcher forms whose Bash semantics are unambiguous."""
    return isinstance(matcher, str) and matcher in {"", "Bash", "^Bash$"}


def platform_project_floor_command(command: str, expected_pin: str | None) -> bool:
    inspected = strip_shell_comments(command)
    normalized = inspected.lower().replace("\\", "/")
    if ".claude/hooks/dispatch.py" not in normalized:
        return False
    segments = shell_command_segments(inspected)
    dispatcher_variables = assigned_floor_variables(
        segments, ".claude/hooks/dispatch.py"
    )
    wrapper_variables = assigned_floor_variables(segments, "invoke_deny_floor")
    interpreter_variables = assigned_floor_variables(segments, "py.exe")
    invokes_floor = any(
        segment_invokes_direct_floor(
            segment, dispatcher_variables, interpreter_variables
        )
        or segment_invokes_wrapper(segment, wrapper_variables)
        for segment in segments
    )
    return invokes_floor and command_binds_pin(inspected, expected_pin)


def repo_codex_floor_candidates(current: str) -> list[Any]:
    """Return one entry per handler that could create a project floor dispatch."""
    _current_data, _hooks, groups = parse_hooks_document(current)
    result = []
    for group in groups:
        for handler in group.get("hooks", []):
            commands = (
                strip_shell_comments(handler.get("command", "")),
                strip_shell_comments(
                    decode_windows_hook_command(handler.get("commandWindows", ""))
                ),
            )
            if any(
                ".claude/hooks/dispatch.py" in command.lower().replace("\\", "/")
                or "invoke_deny_floor" in command.lower()
                for command in commands
            ):
                result.append(group)
    return result


def repo_codex_floor_groups(current: str, expected_pin: str | None = None) -> list[Any]:
    """Return one group entry per platform-complete project floor handler."""
    _current_data, _hooks, groups = parse_hooks_document(current)

    result = []
    for group in groups:
        if not matcher_targets_bash(group.get("matcher", "")):
            continue
        for handler in group.get("hooks", []):
            if handler.get("type") != "command":
                continue
            command = handler.get("command", "")
            windows_command = decode_windows_hook_command(
                handler.get("commandWindows", "")
            )
            if platform_project_floor_command(
                command, expected_pin
            ) and platform_project_floor_command(windows_command, expected_pin):
                result.append(group)
    return result


def normalized_text_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def remove_managed_codex_floor(
    current: str, managed_dispatcher: Path | None = None
) -> str:
    """Remove the obsolete global Codex floor while preserving unrelated hooks."""
    if not current.strip():
        return ""
    current_data, hooks, existing_groups = parse_hooks_document(current)
    if managed_dispatcher is None:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        managed_dispatcher = codex_home / "hooks" / "dispatch.py"
    retained = []
    removed = False
    for group in existing_groups:
        handlers = group.get("hooks", [])
        retained_handlers = [
            handler
            for handler in handlers
            if not is_owned_global_floor_handler(handler, managed_dispatcher)
        ]
        if len(retained_handlers) == len(handlers):
            retained.append(group)
            continue
        removed = True
        if retained_handlers:
            group["hooks"] = retained_handlers
            retained.append(group)
    if not removed:
        return current
    if retained:
        hooks["PreToolUse"] = retained
    else:
        hooks.pop("PreToolUse", None)
    if not hooks:
        current_data.pop("hooks", None)
    if not current_data:
        return ""
    return json.dumps(current_data, indent=2) + "\n"


def sync_global(args: argparse.Namespace) -> int:
    config_root = Path(args.config_root).resolve()
    codex_source = config_root / "codex"
    harness_root = Path(__file__).resolve().parent
    codex_home = Path(
        args.codex_home or os.environ.get("CODEX_HOME", Path.home() / ".codex")
    ).resolve()
    claude_home = Path(args.claude_home or Path.home() / ".claude").resolve()
    skills_home = Path(args.skills_home or Path.home() / ".agents" / "skills").resolve()
    required = [
        codex_source / "AGENTS.md",
        harness_root / "templates" / "hooks" / "dispatch.py",
        harness_root / "templates" / "hooks" / "smoke_test.py",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise HarnessError("missing sync sources: " + ", ".join(missing))
    actions = [
        (codex_source / "AGENTS.md", codex_home / "AGENTS.md"),
        (
            harness_root / "templates" / "hooks" / "dispatch.py",
            claude_home / "hooks" / "dispatch.py",
        ),
        (
            harness_root / "templates" / "hooks" / "smoke_test.py",
            claude_home / "hooks" / "smoke_test.py",
        ),
    ]
    if (codex_source / "REPOS.md").is_file():
        actions.append((codex_source / "REPOS.md", codex_home / "REPOS.md"))
    skill_actions = [
        (skill, skills_home / skill.name)
        for skill in sorted((codex_source / "skills").iterdir())
        if (skill / "SKILL.md").is_file()
    ]
    print(f"Codex home: {codex_home}")
    print(f"Claude home: {claude_home}")
    print(f"Skills home: {skills_home}")
    for source, target in actions:
        print(f"{'=' if same_file(source, target) else '->'} {target}")
    current_hooks = (
        (codex_home / "hooks.json").read_text(encoding="utf-8")
        if (codex_home / "hooks.json").is_file()
        else ""
    )
    hook_text = remove_managed_codex_floor(
        current_hooks, codex_home / "hooks" / "dispatch.py"
    )
    remaining_global_floors = managed_codex_floor_groups(hook_text)
    if remaining_global_floors:
        raise HarnessError(
            "refusing global sync: an unowned or ambiguous Codex floor remains in "
            f"{codex_home / 'hooks.json'}"
        )
    print(
        f"{'=' if current_hooks == hook_text else '->'} {codex_home / 'hooks.json'}"
        " (no global Codex deny floor)"
    )
    for source, target in skill_actions:
        equal = tree_digest(source) == tree_digest(target)
        print(f"{'=' if equal else '->'} {target}")
    if not args.apply:
        print("dry run; pass --apply to install")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = reserve_backup_root(codex_home / "backups", stamp)
    skill_backup = reserve_backup_root(
        skills_home / ".harness-backups", backup_root.name
    )
    for source, target in actions:
        copy_with_backup(source, target, backup_root)
    hooks_target = codex_home / "hooks.json"
    if current_hooks != hook_text:
        if hooks_target.exists():
            backup_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hooks_target, backup_root / "hooks.json")
        if hook_text:
            hooks_target.parent.mkdir(parents=True, exist_ok=True)
            hooks_target.write_text(hook_text, encoding="utf-8")
        else:
            hooks_target.unlink(missing_ok=True)
    for source, target in skill_actions:
        if target.exists():
            backup = skill_backup / target.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target, backup)
            shutil.rmtree(target)
        shutil.copytree(source, target)
    print(
        "installed shared guidance and dispatcher layer; "
        f"backups: {backup_root}; skill backups: {skill_backup}"
    )
    print(
        "Codex deny-floor trust remains project-local; review each repo's .codex/hooks.json in /hooks."
    )
    return 0


def doctor(args: argparse.Namespace) -> int:
    codex_home = Path(
        args.codex_home or os.environ.get("CODEX_HOME", Path.home() / ".codex")
    ).resolve()
    claude_home = Path(args.claude_home or Path.home() / ".claude").resolve()
    skills_home = Path(args.skills_home or Path.home() / ".agents" / "skills").resolve()
    harness_root = Path(__file__).resolve().parent
    checks = []
    codex_command = (
        ["powershell", "-NoProfile", "-Command", "codex --version"]
        if os.name == "nt"
        else ["codex", "--version"]
    )
    for label, command in (
        ("python", [sys.executable, "--version"]),
        ("codex", codex_command),
        ("git", ["git", "--version"]),
    ):
        result = run(command)
        checks.append(
            (label, result.returncode == 0, (result.stdout or result.stderr).strip())
        )
    hooks_path = codex_home / "hooks.json"
    try:
        global_floor_count = len(
            managed_codex_floor_groups(
                hooks_path.read_text(encoding="utf-8") if hooks_path.is_file() else ""
            )
        )
        global_floor_detail = f"{global_floor_count} managed global floor group(s)"
    except (HarnessError, OSError, UnicodeError) as exc:
        global_floor_count = -1
        global_floor_detail = str(exc)
    checks.extend(
        [
            (
                "global AGENTS",
                (codex_home / "AGENTS.md").is_file()
                and (codex_home / "AGENTS.md").stat().st_size > 0,
                str(codex_home / "AGENTS.md"),
            ),
            ("no global Codex floor", global_floor_count == 0, global_floor_detail),
            (
                "shared dispatcher",
                same_file(
                    harness_root / "templates" / "hooks" / "dispatch.py",
                    claude_home / "hooks" / "dispatch.py",
                ),
                str(claude_home / "hooks" / "dispatch.py"),
            ),
            (
                "shared smoke matrix",
                same_file(
                    harness_root / "templates" / "hooks" / "smoke_test.py",
                    claude_home / "hooks" / "smoke_test.py",
                ),
                str(claude_home / "hooks" / "smoke_test.py"),
            ),
            (
                "user skills",
                skills_home.is_dir() and any(skills_home.glob("*/SKILL.md")),
                str(skills_home),
            ),
        ]
    )
    if args.repo:
        repo_hooks = Path(args.repo).resolve() / ".codex" / "hooks.json"
        try:
            repo_hook_text = (
                repo_hooks.read_text(encoding="utf-8") if repo_hooks.is_file() else ""
            )
            project_floor_groups = repo_codex_floor_groups(repo_hook_text)
            project_floor_count = len(project_floor_groups)
            candidate_floor_count = len(repo_codex_floor_candidates(repo_hook_text))
            expected_pin = normalized_text_sha256(
                harness_root / "templates" / "hooks" / "dispatch.py"
            )
            current_floor_count = len(
                repo_codex_floor_groups(repo_hook_text, expected_pin)
            )
            project_detail = (
                f"{project_floor_count} project floor handler(s); "
                f"{candidate_floor_count} candidate handler(s); "
                f"{current_floor_count} current pinned handler(s); "
                "trust is checked manually in /hooks"
            )
        except (HarnessError, OSError, UnicodeError) as exc:
            project_floor_count = -1
            candidate_floor_count = -1
            current_floor_count = -1
            project_detail = str(exc)
        checks.append(
            (
                "project Codex floor",
                candidate_floor_count == 1
                and project_floor_count == 1
                and current_floor_count == 1,
                project_detail,
            )
        )
    for label, ok, detail in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {label}: {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def audit_command(args: argparse.Namespace) -> int:
    result = audit_repo(Path(args.path))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"repo: {result['repo']}")
        print(f"tier: T{result['tier']} ({result['tier_file'] or 'missing'})")
        print(result["git"])
        if result["issues"]:
            for issue in result["issues"]:
                print(f"[FAIL] {issue}")
        else:
            print("[ok] harness audit")
    return 0 if result["ok"] else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit", help="validate a repository harness")
    audit.add_argument("path", nargs="?", default=".")
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(func=audit_command)

    seed = sub.add_parser(
        "seed", help="create a write-once runtime-neutral tier declaration"
    )
    seed.add_argument("path", nargs="?", default=".")
    seed.add_argument("--tier", type=int, choices=TIER_NAMES, required=True)
    seed.add_argument("--push", choices=sorted(AUTHORITY_VALUES), default="free")
    seed.add_argument("--merge", choices=sorted(AUTHORITY_VALUES), default="free")
    seed.add_argument("--human-todo")
    seed.add_argument("--sensitive-data", action="store_true")
    seed.add_argument("--relaxed-work-loss-guards", action="store_true")
    seed.add_argument("--dry-run", action="store_true")
    seed.set_defaults(func=seed_repo)

    sync = sub.add_parser(
        "sync-global", help="diff or install shared global guidance and floor bytes"
    )
    sync.add_argument(
        "--config-root", required=True, help="path to the claude-config checkout"
    )
    sync.add_argument("--codex-home")
    sync.add_argument("--claude-home")
    sync.add_argument("--skills-home")
    sync.add_argument("--apply", action="store_true")
    sync.set_defaults(func=sync_global)

    check = sub.add_parser(
        "doctor", help="check live global guidance and floor topology"
    )
    check.add_argument("--codex-home")
    check.add_argument("--claude-home")
    check.add_argument("--skills-home")
    check.add_argument(
        "--repo", help="also verify one repo-local Codex floor definition"
    )
    check.set_defaults(func=doctor)
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return int(args.func(args))
    except HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
