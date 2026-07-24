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
import shlex
import shutil
import subprocess
import sys
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CODEX_PROJECT_ROOT_MARKERS = [".git"]

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


def git_common_dir(path: Path) -> Path:
    """Return the shared Git directory for the checkout containing ``path``."""
    result = run(["git", "rev-parse", "--git-common-dir"], path)
    if result.returncode or not result.stdout.strip():
        raise HarnessError(f"cannot resolve Git common directory: {path}")
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = path / common_dir
    return common_dir.resolve()


def git_dir(path: Path) -> Path:
    """Return Git's own directory for the checkout containing ``path``."""
    result = run(["git", "rev-parse", "--git-dir"], path)
    if result.returncode or not result.stdout.strip():
        raise HarnessError(f"cannot resolve Git directory: {path}")
    directory = Path(result.stdout.strip())
    if not directory.is_absolute():
        directory = path / directory
    return directory.resolve()


def root_checkout(path: Path) -> tuple[Path, Path]:
    """Resolve a requested checkout and its authoritative root checkout.

    Codex loads project hooks from the checkout that owns Git's common
    directory. A linked worktree has its own ``.git`` file, so locating the
    requested worktree alone would silently audit an inactive hook source.
    """
    requested_checkout = git_root(path)
    common_dir = git_common_dir(requested_checkout)
    if git_dir(requested_checkout) == common_dir:
        return requested_checkout, requested_checkout

    result = run(["git", "worktree", "list", "--porcelain"], requested_checkout)
    if result.returncode:
        raise HarnessError(
            f"cannot list Git worktrees while resolving root checkout: {requested_checkout}"
        )
    for line in result.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        candidate = Path(line.removeprefix("worktree ")).resolve()
        if not (candidate / ".git").exists():
            continue
        try:
            if git_dir(candidate) == common_dir:
                return requested_checkout, candidate
        except HarnessError:
            continue
    raise HarnessError(
        "cannot resolve root checkout from Git common directory: " f"{common_dir}"
    )


def codex_hook_source_status(
    requested_checkout: Path, authoritative_checkout: Path
) -> tuple[Path, bool, str]:
    """Return one active Codex layer's hook path and copy status."""
    authoritative_hooks = authoritative_checkout / ".codex" / "hooks.json"
    if requested_checkout == authoritative_checkout:
        return (
            authoritative_hooks,
            True,
            f"normal checkout; Codex source: {authoritative_hooks}",
        )

    ignored_hooks = requested_checkout / ".codex" / "hooks.json"
    source_prefix = (
        "linked worktree; Codex uses root checkout source: " f"{authoritative_hooks}"
    )
    if not authoritative_hooks.is_file():
        if ignored_hooks.is_file():
            return (
                authoritative_hooks,
                False,
                f"{source_prefix}; ignored worktree copy {ignored_hooks} exists "
                "but the authoritative root source is absent",
            )
        return (
            authoritative_hooks,
            True,
            f"{source_prefix}; neither checkout declares hooks in this layer",
        )
    if ignored_hooks.is_file():
        if authoritative_hooks.read_bytes() != ignored_hooks.read_bytes():
            return (
                authoritative_hooks,
                False,
                f"{source_prefix}; ignored worktree copy differs: {ignored_hooks}",
            )
        return (
            authoritative_hooks,
            True,
            f"{source_prefix}; identical worktree copy is ignored: {ignored_hooks}",
        )
    return authoritative_hooks, True, f"{source_prefix}; no worktree-local copy"


def toml_config(config_path: Path) -> dict[str, Any] | None:
    """Return one TOML config document, or ``None`` when it is absent."""
    if not config_path.is_file():
        return None
    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise HarnessError(f"invalid Codex config {config_path}: {exc}") from exc


def inline_hooks_from_config(config_path: Path) -> Any | None:
    """Return a config layer's inline hooks table, if it declares one."""
    config = toml_config(config_path)
    if config is None:
        return None
    return config.get("hooks")


def codex_system_config_path() -> Path:
    """Return Codex's inspectable system config location for this platform."""
    if os.name == "nt":
        return (
            Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
            / "OpenAI"
            / "Codex"
            / "config.toml"
        )
    return Path("/etc/codex/config.toml")


def project_root_markers_from_config(
    config_path: Path,
) -> list[tuple[str, list[str]]]:
    """Return every stored marker declaration with Codex-compatible shapes."""
    config = toml_config(config_path)
    if config is None:
        return []

    declarations: list[tuple[str, list[str]]] = []

    def walk(value: Any, keys: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_keys = (*keys, key)
                if key == "project_root_markers":
                    if not isinstance(child, list) or any(
                        not isinstance(marker, str) for marker in child
                    ):
                        location = ".".join(child_keys)
                        raise HarnessError(
                            f"{location} in {config_path} must be an array of strings"
                        )
                    declarations.append((".".join(child_keys), child))
                else:
                    walk(child, child_keys)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*keys, f"[{index}]"))

    walk(config)
    return declarations


def codex_project_root_marker_status(codex_home: Path) -> tuple[bool, str]:
    """Fail closed when inspectable config can move Codex's project root.

    Codex determines its project root before loading project-local layers. The
    Git-root audit below is exact only for the default ``[\".git\"]`` marker
    topology, so any stored base, system, or profile override is an explicit
    static-verification boundary rather than a guessed layer walk.
    """
    config_paths = [
        codex_system_config_path(),
        codex_home / "config.toml",
        *sorted(codex_home.glob("*.config.toml")),
    ]
    declarations: list[tuple[Path, str, list[str]]] = []
    for config_path in config_paths:
        declarations.extend(
            (config_path, location, markers)
            for location, markers in project_root_markers_from_config(config_path)
        )

    nondefault = [
        (config_path, location, markers)
        for config_path, location, markers in declarations
        if markers != DEFAULT_CODEX_PROJECT_ROOT_MARKERS
    ]
    qualifier = (
        "invocation CLI and managed cloud overrides are not statically inspectable; "
        "confirm the active topology in new-session /hooks"
    )
    if nondefault:
        detail = "; ".join(
            f"{config_path}:{location} declares {markers!r}"
            for config_path, location, markers in nondefault
        )
        return (
            False,
            "non-default project_root_markers prevent static Git-root proof: "
            f"{detail}; {qualifier}",
        )
    return (
        True,
        f"default {DEFAULT_CODEX_PROJECT_ROOT_MARKERS!r} marker topology; "
        f"{len(declarations)} explicit inspectable declaration(s); {qualifier}",
    )


def inline_hooks_document(config_path: Path) -> str:
    """Convert inline TOML hooks to the hooks.json document shape."""
    hooks = inline_hooks_from_config(config_path)
    if hooks is None:
        return ""
    try:
        return json.dumps({"hooks": hooks})
    except (TypeError, ValueError) as exc:
        raise HarnessError(
            f"unsupported inline hooks value in {config_path}: {exc}"
        ) from exc


def codex_inline_hook_source_status(
    requested_layer: Path, authoritative_layer: Path
) -> tuple[bool, str]:
    """Report inline-hook mapping for one normal or linked project layer."""
    authoritative_config = authoritative_layer / ".codex" / "config.toml"
    authoritative_hooks = inline_hooks_from_config(authoritative_config)
    if requested_layer == authoritative_layer:
        if authoritative_hooks is None:
            return True, f"no inline hooks in {authoritative_config}"
        return True, f"inline hooks source: {authoritative_config}"

    ignored_config = requested_layer / ".codex" / "config.toml"
    ignored_hooks = inline_hooks_from_config(ignored_config)
    source_prefix = f"root-checkout inline hooks source: {authoritative_config}"
    if authoritative_hooks is None:
        if ignored_hooks is not None:
            return (
                False,
                f"{source_prefix}; ignored worktree inline hooks in "
                f"{ignored_config} exist but the authoritative root source is absent",
            )
        return True, f"{source_prefix}; neither checkout declares inline hooks"
    if ignored_hooks is not None:
        if ignored_hooks != authoritative_hooks:
            return (
                False,
                f"{source_prefix}; ignored worktree inline hooks differ: "
                f"{ignored_config}",
            )
        return (
            True,
            f"{source_prefix}; identical worktree inline hooks are ignored: "
            f"{ignored_config}",
        )
    return True, f"{source_prefix}; no worktree-local inline hooks"


def codex_project_layer_dirs(
    requested_path: Path, requested_checkout: Path
) -> list[Path]:
    """Return active ``.codex`` layer directories from checkout root to cwd."""
    requested_path = requested_path.resolve()
    try:
        relative_path = requested_path.relative_to(requested_checkout)
    except ValueError as exc:
        raise HarnessError(
            f"requested path is outside its Git checkout: {requested_path}"
        ) from exc

    directories = [requested_checkout]
    current = requested_checkout
    for component in relative_path.parts:
        current /= component
        directories.append(current)
    return [directory for directory in directories if (directory / ".codex").is_dir()]


def codex_hook_sources_status(
    requested_path: Path,
    requested_checkout: Path,
    authoritative_checkout: Path,
) -> tuple[list[Path], bool, str]:
    """Return every active Codex hook source between checkout root and cwd.

    Codex creates one project layer for each ``.codex`` directory on that
    ancestor chain. In a linked worktree, each layer keeps its worktree-local
    config but takes hooks from the same relative directory in the root
    checkout, so every ignored local hook copy must be reconciled separately.
    """
    layer_dirs = codex_project_layer_dirs(requested_path, requested_checkout)
    checkout_kind = (
        "normal checkout"
        if requested_checkout == authoritative_checkout
        else "linked worktree"
    )
    if not layer_dirs:
        return (
            [],
            True,
            f"{checkout_kind}; 0 active Codex hook layer(s) between "
            f"{requested_checkout} and {requested_path.resolve()}",
        )

    hook_paths: list[Path] = []
    statuses: list[str] = []
    source_ok = True
    for layer_dir in layer_dirs:
        relative_dir = layer_dir.relative_to(requested_checkout)
        authoritative_layer = authoritative_checkout / relative_dir
        hooks, layer_ok, detail = codex_hook_source_status(
            layer_dir, authoritative_layer
        )
        inline_ok, inline_detail = codex_inline_hook_source_status(
            layer_dir, authoritative_layer
        )
        hook_paths.append(hooks)
        source_ok = source_ok and layer_ok and inline_ok
        statuses.append(f"{detail}; {inline_detail}")
    return (
        hook_paths,
        source_ok,
        f"{checkout_kind}; {len(layer_dirs)} active Codex hook layer(s); "
        + " | ".join(statuses),
    )


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


# PowerShell's own options. Only these may precede -EncodedCommand without
# changing what actually executes: a code directive (-Command/-File/-cwa), a
# bare positional (binds to the implicit -Command), or any UNKNOWN option would
# slurp/redefine the command line so the encoded payload never runs as
# PowerShell — the decoded inner text would then diverge from runtime.
_POWERSHELL_INERT_SWITCHES = {
    "noprofile",
    "noprofileloadtime",
    "noninteractive",
    "nologo",
    "noexit",
    "sta",
    "mta",
    "interactive",
}
_POWERSHELL_INERT_VALUE_OPTIONS = {
    "executionpolicy",
    "version",
    "windowstyle",
    "inputformat",
    "outputformat",
    "configurationname",
    "psconsolefile",
    "settingsfile",
    "custompipename",
    "workingdirectory",
}


def _is_encoded_switch(token: str) -> bool:
    if not token.startswith(("-", "/")):
        return False
    option = token.lstrip("-/").partition(":")[0].lower()
    return bool(option) and (
        option in {"e", "ec"} or "encodedcommand".startswith(option)
    )


def _powershell_encoded_payload(rest: str) -> str | None:
    """Return the base64 payload of a clean `-EncodedCommand` invocation.

    None -> no -EncodedCommand present (caller keeps the raw command).
    ""   -> an -EncodedCommand is present but the surrounding argv is unsafe (a
            positional / code-directive / unknown option would redefine what
            runs, or a statement follows the payload) -> caller fails closed.
    <b64> -> the clean terminal encoded form (the ONLY trusted decode).
    """
    try:
        tokens = shlex.split(rest, posix=True)
    except ValueError:
        # Unbalanced quotes: if it even mentions an encoded switch, fail closed.
        return "" if re.search(r"(?i)(?:^|\s)[-/]e", rest) else None
    if not any(_is_encoded_switch(token) for token in tokens):
        return None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        raw = token.lstrip("-/")
        option = raw.partition(":")[0].lower()
        separator = ":" in raw
        attached = raw.partition(":")[2]  # original case (base64 is case-sensitive)
        if _is_encoded_switch(token):
            if separator:
                payload, consumed_end = attached, index + 1
            else:
                payload = tokens[index + 1] if index + 1 < len(tokens) else None
                consumed_end = index + 2
            # The payload must be a bare base64 string AND the LAST token, so no
            # sibling statement follows and nothing precedes that would slurp it.
            # It must also appear VERBATIM in the raw argv: if shlex stripped a
            # backslash/quote (`SQ\Bu` -> `SQBu`), the bytes we decode differ
            # from what PowerShell receives, so decode a payload it can't.
            if (
                payload is None
                or consumed_end != len(tokens)
                or not re.fullmatch(r"[A-Za-z0-9+/=]+", payload)
                or payload not in rest
            ):
                return ""
            return payload
        if not token.startswith(("-", "/")):
            return ""  # bare positional binds to the implicit -Command
        if (
            "command".startswith(option)
            or "file".startswith(option)
            or "commandwithargs".startswith(option)
            or option == "cwa"
        ):
            return ""  # code directive redefines execution
        if any(name.startswith(option) for name in _POWERSHELL_INERT_SWITCHES):
            index += 1
            continue
        if any(name.startswith(option) for name in _POWERSHELL_INERT_VALUE_OPTIONS):
            index += 1 if separator else 2  # consume the option's value token
            continue
        return ""  # unknown option
    return ""


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
    encoded_payload = _powershell_encoded_payload(command[executable_match.end() :])
    if encoded_payload is None:
        return command
    if encoded_payload == "":
        return "invoke_deny_floor opaque-encoded-command"
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


def is_safe_floor_invocation_segment(segment: str, *, windows: bool) -> bool:
    """Require a floor invocation to be an argv-only shell statement."""
    quote = ""
    escaped = False
    saw_non_whitespace = False
    used_call_operator = False
    escape_character = "`" if windows else "\\"

    for index, char in enumerate(segment):
        following = segment[index + 1] if index + 1 < len(segment) else ""
        if escaped:
            escaped = False
            continue
        if quote:
            if char == escape_character and quote != "'":
                escaped = True
                continue
            # Command substitution executes INSIDE double quotes on both shells
            # ("$(cmd)" everywhere; "`cmd`" in POSIX — backtick is the escape
            # char in PowerShell, handled above). Single quotes stay inert.
            if quote == '"':
                if char == "$" and following == "(":
                    return False
                if not windows and char == "`":
                    return False
            if char == quote:
                quote = ""
            continue
        if windows and char == "@" and following in {"'", '"', "("}:
            return False
        if char in {"'", '"'}:
            quote = char
            continue
        if char.isspace():
            continue
        if char in {"<", ">", "|"}:
            return False
        # Command substitution and backticks run BEFORE the dispatcher, so a
        # segment carrying them can have arbitrary pre-dispatch side effects.
        if char == "`":
            return False
        if char == "$" and following == "(":
            return False
        # PowerShell evaluates (…) and @(…) argument subexpressions before the
        # callee runs, so an unquoted paren in a Windows invocation is unsafe.
        if windows and char == "(":
            return False
        if char == "&":
            if windows and not saw_non_whitespace and not used_call_operator:
                used_call_operator = True
                saw_non_whitespace = True
                continue
            return False
        saw_non_whitespace = True

    return not quote and not escaped


def inert_floor_assignment(segment: str, *, windows: bool) -> tuple[str, str] | None:
    """Return one side-effect-free setup assignment, if the segment is one."""
    if not is_safe_floor_invocation_segment(segment, windows=windows):
        return None
    pattern = (
        r"(?is)^\s*\$([a-z_][a-z0-9_]*)\s*=\s*(.+?)\s*$"
        if windows
        else r"(?is)^\s*(?:export\s+)?([a-z_][a-z0-9_]*)=(.+?)\s*$"
    )
    match = re.fullmatch(pattern, segment)
    if match is None:
        return None
    name, value = match.group(1).lower(), match.group(2)
    if "$(" in value or (not windows and "`" in value):
        return None
    if windows and re.fullmatch(
        r"(?is)join-path\s+\$env:[a-z_][a-z0-9_]*\s+(['\"])[^'\"]+\1",
        value,
    ):
        return name, value

    quote = ""
    escaped = False
    escape_character = "`" if windows else "\\"
    for char in value:
        if escaped:
            escaped = False
            continue
        if quote:
            if char == escape_character and quote != "'":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char.isspace() or (windows and char in "(){}[]"):
            return None
    if quote or escaped:
        return None
    return name, value


# The shared deny floor lives at the HOME-anchored global path
# `~/.claude/hooks/dispatch.py` (installed by sync-global), so the dispatcher
# MUST be anchored to a home variable — never a repo-relative, `$PWD`, or
# arbitrary-variable path, which would run a repo-shipped attacker file.
_HOME_VAR = r"(?:~|\$\{?home\}?|\$\{?env:userprofile\}?)"
# The Windows py launcher must be anchored to a system variable, not `$PWD`.
_SYSTEM_VAR = r"\$\{?env:(?:systemroot|windir)\}?"
# A generic variable expansion — only used for the (repo-local, /hooks-reviewed)
# wrapper path, never for the pinned dispatcher or the interpreter.
_FLOOR_VAR = r"\$(?:\{(?:env:)?[a-z_][a-z0-9_]*\}|(?:env:)?[a-z_][a-z0-9_]*)"
_FLOOR_DISPATCH = r"\.claude/hooks/dispatch\.py"
_FLOOR_WRAPPER = r"invoke_deny_floor\.(?:sh|ps1|cmd|bat)"

# Exact accepted shapes for a value bound to a floor executable. A floor
# variable must match ONE of these whole-value forms — anything else (rebinding,
# glued prefixes/suffixes, quote concatenation, relative dispatcher/interpreter)
# fails closed, because char-level anchoring proved to be repeated whack-a-mole.
_FLOOR_VALUE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        # dispatcher: HOME-anchored only (var+separator, `+`-concat, Join-Path)
        rf"['\"]?{_HOME_VAR}/{_FLOOR_DISPATCH}['\"]?",
        rf"{_HOME_VAR}\+'/{_FLOOR_DISPATCH}'",
        rf"join-path {_HOME_VAR} '{_FLOOR_DISPATCH}'",
        # interpreter (py.exe): SYSTEM-variable anchored, never relative
        rf"['\"]?{_SYSTEM_VAR}/py\.exe['\"]?",
        rf"{_SYSTEM_VAR}\+'/py\.exe'",
        rf"join-path {_SYSTEM_VAR} 'py\.exe'",
        # wrapper: a repo-relative path whose final component is the wrapper
        # script (the project's own adapter, trusted via a /hooks review)
        rf"['\"]?(?:{_FLOOR_VAR}/)?(?:[\w.-]+/)*{_FLOOR_WRAPPER}['\"]?",
    )
)


def value_binds_anchored_floor_path(value: str) -> bool:
    """Return whether an assignment value resolves to a genuine floor path.

    Uses a strict whitelist of the exact known-good value shapes rather than
    char-level boundary heuristics. Any value that does not fully match one of
    the accepted dispatcher/interpreter/wrapper forms is rejected, so a floor
    variable's runtime value can never diverge from the pinned floor via a
    rebind, a glued prefix (``x.claude/...`` / ``evil'.claude/...'``), or
    concatenation past the marker.
    """
    normalized = value.lower().replace("\\", "/")
    return any(pattern.fullmatch(normalized) for pattern in _FLOOR_VALUE_PATTERNS)


def is_inert_floor_setup_segment(
    segment: str, allowed_variables: set[str], *, windows: bool
) -> bool:
    assignment = inert_floor_assignment(segment, windows=windows)
    if assignment is None:
        return False
    name, value = assignment
    if name in allowed_variables:
        # A floor variable may only be (re)bound to the anchored floor path; any
        # other value — an attacker rebind or concatenation past the marker —
        # is rejected so the executed path cannot diverge from the pinned one.
        return value_binds_anchored_floor_path(value)
    literal = value.strip()
    if len(literal) >= 2 and literal[0] == literal[-1] and literal[0] in {"'", '"'}:
        literal = literal[1:-1]
    return bool(re.fullmatch(r"(?i)[0-9a-f]{64}", literal))


def _marker_occurrence_is_anchored(
    normalized: str, marker_index: int, marker_len: int, allow_extension: bool
) -> bool:
    """Reject a marker followed by more path text (e.g. dispatch.py.evil)."""
    rest = normalized[marker_index + marker_len :]
    if allow_extension:
        extension = re.match(r"\.[a-z0-9]+", rest)
        if extension:
            rest = rest[extension.end() :]
    return rest == "" or rest[0] in "'\" \t;+)}&|<>"


def assigned_floor_variables(
    segments: list[str], marker: str, allow_extension: bool = False
) -> set[str]:
    """Find variables whose assignment statement binds a floor path marker.

    The marker must be the END of its path token (optionally followed by one
    file extension for wrapper scripts) so a sibling like `dispatch.py.evil` or
    an attacker-controlled `py.exe.sh` cannot be bound as the floor path.
    """
    result: set[str] = set()
    for segment in segments:
        normalized = segment.lower().replace("\\", "/")
        search_from = 0
        while True:
            marker_index = normalized.find(marker, search_from)
            if marker_index < 0:
                break
            search_from = marker_index + len(marker)
            if not _marker_occurrence_is_anchored(
                normalized, marker_index, len(marker), allow_extension
            ):
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


# A BARE interpreter name only (no path separator): `python`/`python3`/`py`,
# resolved via the trusted system PATH. A path-qualified interpreter (`./python3`,
# `tools/py.exe`) would run a repo-shipped attacker binary, so a path-anchored
# interpreter must instead flow through a SYSTEM-anchored floor variable.
_PYTHON_EXECUTABLE_TOKEN = re.compile(r"(?i)^(?:python3?|py)(?:\.exe)?$")


def token_is_python_executable(token: str) -> bool:
    return bool(_PYTHON_EXECUTABLE_TOKEN.fullmatch(token.strip("'\"")))


def token_references_variable(token: str, names: set[str]) -> bool:
    stripped = token.strip("'\"")
    return any(
        re.fullmatch(variable_reference(name), stripped, re.IGNORECASE)
        for name in names
    )


# A clean path component: word chars, dot, dollar/brace/colon (var expansions),
# tilde, dash. Notably EXCLUDES `=`, so a `VAR=path` assignment word never
# matches — an assignment is not an executed command.
_PATH_COMPONENT = r"[\w.$:{}~-]+"
# A literal dispatcher operand must be the HOME-anchored global path — a
# repo-relative / `$PWD` / bare path would run a repo-shipped attacker file.
_DISPATCHER_PATH_TOKEN = re.compile(rf"^{_HOME_VAR}/\.claude/hooks/dispatch\.py$")


def token_is_dispatcher(token: str, dispatcher_variables: set[str]) -> bool:
    normalized = token.strip("'\"").lower().replace("\\", "/")
    # The WHOLE token must be the home-anchored dispatcher path, so a sibling
    # (`dispatch.py.evil`), an assignment word (`x=.../dispatch.py`), or a
    # repo-relative path (`.claude/...`, `$pwd/...`) cannot pass.
    if _DISPATCHER_PATH_TOKEN.fullmatch(normalized):
        return True
    return token_references_variable(token, dispatcher_variables)


def python_script_operand_is_dispatcher(
    tokens: list[str], dispatcher_variables: set[str]
) -> bool:
    """Require the dispatcher to be Python's executed script, not a -c/-m arg."""
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1 < len(tokens) and token_is_dispatcher(
                tokens[index + 1], dispatcher_variables
            )
        if token.startswith("--"):
            index += 1
            continue
        if token.startswith("-") and len(token) > 1:
            short_flags = token[1:]
            # -c cmd / -m mod execute something other than the script operand.
            if "c" in short_flags.lower() or "m" in short_flags.lower():
                return False
            # -W and -X consume the following token as their value.
            if short_flags in {"W", "X"}:
                index += 2
                continue
            index += 1
            continue
        return token_is_dispatcher(token, dispatcher_variables)
    return False


def segment_invokes_direct_floor(
    segment: str, dispatcher_variables: set[str], interpreter_variables: set[str]
) -> bool:
    """Recognize conservative direct dispatcher execution shapes."""
    if not (
        command_has_flag_value(segment, "event", "pre")
        and command_has_flag_value(segment, "runtime", "codex")
    ):
        return False
    stripped = segment.strip()
    stripped = re.sub(r"(?i)^\(\s*", "", stripped)
    stripped = re.sub(r"(?i)^exec\s+", "", stripped)
    stripped = re.sub(r"^&\s+", "", stripped)
    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        return False
    if not tokens:
        return False
    head = tokens[0]
    # Direct execution: the dispatcher script (or a variable bound to it) is the
    # command head, launched via its shebang without a Python operand.
    if token_is_dispatcher(head, dispatcher_variables):
        return True
    # Interpreted execution: a python/py interpreter (literal or a variable
    # bound to py.exe) must run the dispatcher AS its script operand.
    if token_is_python_executable(head) or token_references_variable(
        head, interpreter_variables
    ):
        return python_script_operand_is_dispatcher(tokens, dispatcher_variables)
    return False


_WRAPPER_PATH_TOKEN = re.compile(
    rf"^(?:{_PATH_COMPONENT}/)*invoke_deny_floor\.(?:sh|ps1|cmd|bat)$"
)


def token_is_wrapper(token: str, wrapper_variables: set[str]) -> bool:
    stripped = token.strip("'\"").lower().replace("\\", "/")
    # The WHOLE token must be a clean path whose final component is the wrapper
    # script, so neither `invoke_deny_floor.sh.evil` nor an assignment word
    # (`x=.../invoke_deny_floor.sh`) can pass.
    if _WRAPPER_PATH_TOKEN.fullmatch(stripped):
        return True
    return token_references_variable(token, wrapper_variables)


def shell_script_operand_is_wrapper(
    tokens: list[str], wrapper_variables: set[str]
) -> bool:
    """Require the wrapper to be sh/bash's executed script, not a -c string."""
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1 < len(tokens) and token_is_wrapper(
                tokens[index + 1], wrapper_variables
            )
        if token.startswith("-") and len(token) > 1:
            # -c runs a COMMAND STRING (not a script file); reject it.
            if "c" in token[1:]:
                return False
            index += 1
            continue
        return token_is_wrapper(token, wrapper_variables)
    return False


def powershell_file_operand_is_wrapper(
    tokens: list[str], wrapper_variables: set[str]
) -> bool:
    """Require the wrapper to be the -File operand, not a -Command payload."""
    file_value = None
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token.startswith(("-", "/")):
            option, separator, attached = token.lstrip("-/").lower().partition(":")
            if option and (
                "command".startswith(option)
                or "encodedcommand".startswith(option)
                or option in {"e", "ec", "cwa"}
                or "commandwithargs".startswith(option)
            ):
                return False
            if option and "file".startswith(option) and len(option) >= 1:
                if separator:
                    file_value = attached
                    index += 1
                elif index + 1 < len(tokens):
                    file_value = tokens[index + 1]
                    index += 2
                else:
                    index += 1
                continue
            index += 1
            continue
        index += 1
    return file_value is not None and token_is_wrapper(file_value, wrapper_variables)


def segment_invokes_wrapper(segment: str, wrapper_variables: set[str]) -> bool:
    """Recognize conservative project-wrapper execution shapes.

    The wrapper must be the EXECUTED script operand — a `-c` command string or a
    trailing argument that merely mentions the wrapper path does not qualify.
    """
    stripped = segment.strip()
    stripped = re.sub(r"(?i)^\(\s*", "", stripped)
    stripped = re.sub(r"(?i)^exec\s+", "", stripped)
    stripped = re.sub(r"^&\s+", "", stripped)
    # A bare `VAR=path` assignment is NOT an execution — it sets a variable and
    # runs nothing (exit 0). Do NOT strip an assignment prefix and treat the RHS
    # path as an executed wrapper.
    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        return False
    if not tokens:
        return False
    head = tokens[0]
    # Direct execution: the wrapper (or a variable bound to it) is the head.
    if token_is_wrapper(head, wrapper_variables):
        return True
    normalized_head = head.strip("'\"").replace("\\", "/")
    # The shell/PowerShell interpreter that runs the wrapper must be a bare
    # command name (system PATH) or an absolute path — a repo-relative
    # interpreter (`tools/bash`, `./pwsh`) would be attacker-shipped.
    if "/" in normalized_head and not (
        normalized_head.startswith("/")
        or re.match(r"[a-z]:/", normalized_head, re.IGNORECASE)
    ):
        return False
    head_base = normalized_head.lower().rsplit("/", 1)[-1]
    head_base = re.sub(r"\.(exe|cmd|bat|ps1)$", "", head_base)
    if head_base in {"sh", "bash", "dash", "ash"}:
        return shell_script_operand_is_wrapper(tokens, wrapper_variables)
    if head_base in {"powershell", "pwsh", "start-process", "saps"}:
        return powershell_file_operand_is_wrapper(tokens, wrapper_variables)
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


def platform_project_floor_command(
    command: str, expected_pin: str | None, *, windows: bool = False
) -> bool:
    inspected = strip_shell_comments(command)
    normalized = inspected.lower().replace("\\", "/")
    if ".claude/hooks/dispatch.py" not in normalized:
        return False
    segments = shell_command_segments(inspected)
    dispatcher_variables = assigned_floor_variables(
        segments, ".claude/hooks/dispatch.py"
    )
    wrapper_variables = assigned_floor_variables(
        segments, "invoke_deny_floor", allow_extension=True
    )
    interpreter_variables = assigned_floor_variables(segments, "py.exe")
    invocation_indexes = [
        index
        for index, segment in enumerate(segments)
        if is_safe_floor_invocation_segment(segment, windows=windows)
        # A segment that parses as a bare assignment sets a variable and executes
        # nothing (exit 0); it can never be the floor invocation.
        and inert_floor_assignment(segment, windows=windows) is None
        and (
            segment_invokes_direct_floor(
                segment, dispatcher_variables, interpreter_variables
            )
            or segment_invokes_wrapper(segment, wrapper_variables)
        )
    ]
    if len(invocation_indexes) != 1:
        return False
    invocation_index = invocation_indexes[0]
    if invocation_index != len(segments) - 1:
        return False
    setup_segments = segments[:invocation_index]
    allowed_variables = dispatcher_variables | wrapper_variables | interpreter_variables
    if not all(
        is_inert_floor_setup_segment(segment, allowed_variables, windows=windows)
        for segment in setup_segments
    ):
        return False
    return expected_pin is None or any(
        command_binds_pin(segment, expected_pin) for segment in setup_segments
    )


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


def handler_gates_synchronously(handler: dict[str, Any]) -> bool:
    """Reject handler shapes Codex would not run as a blocking PreToolUse gate.

    Codex skips async handlers, so an async/background floor never denies. A
    non-positive or non-numeric timeout is likewise treated as unusable rather
    than certified, so doctor cannot false-green a hook that will not gate.
    """
    for field in ("async", "background", "nonBlocking", "non_blocking", "detached"):
        if handler.get(field):
            return False
    if "timeout" in handler:
        timeout = handler["timeout"]
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            return False
        if timeout <= 0:
            return False
    return True


def repo_codex_floor_groups(current: str, expected_pin: str | None = None) -> list[Any]:
    """Return one group entry per platform-complete project floor handler."""
    _current_data, _hooks, groups = parse_hooks_document(current)

    result = []
    for group in groups:
        if not matcher_targets_bash(group.get("matcher", "")):
            continue
        handlers = group.get("hooks", [])
        if len(handlers) != 1:
            continue
        handler = handlers[0]
        if handler.get("type") != "command":
            continue
        if not handler_gates_synchronously(handler):
            continue
        command = handler.get("command", "")
        windows_command = decode_windows_hook_command(handler.get("commandWindows", ""))
        if platform_project_floor_command(
            command, expected_pin
        ) and platform_project_floor_command(
            windows_command, expected_pin, windows=True
        ):
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
        try:
            marker_ok, marker_detail = codex_project_root_marker_status(codex_home)
        except (HarnessError, OSError, UnicodeError) as exc:
            marker_ok = False
            marker_detail = str(exc)
        checks.append(("Codex project root markers", marker_ok, marker_detail))
        try:
            requested_path = Path(args.repo).resolve()
            requested_checkout, authoritative_checkout = root_checkout(requested_path)
            repo_hook_paths, source_ok, source_detail = codex_hook_sources_status(
                requested_path, requested_checkout, authoritative_checkout
            )
            json_hook_texts = [
                hooks.read_text(encoding="utf-8")
                for hooks in repo_hook_paths
                if hooks.is_file()
            ]
            inline_hook_texts = [
                document
                for hooks in repo_hook_paths
                if (document := inline_hooks_document(hooks.with_name("config.toml")))
            ]
            repo_hook_texts = json_hook_texts + inline_hook_texts
            project_floor_count = sum(
                len(repo_codex_floor_groups(text)) for text in repo_hook_texts
            )
            candidate_floor_count = sum(
                len(repo_codex_floor_candidates(text)) for text in repo_hook_texts
            )
            expected_pin = normalized_text_sha256(
                harness_root / "templates" / "hooks" / "dispatch.py"
            )
            current_floor_count = sum(
                len(repo_codex_floor_groups(text, expected_pin))
                for text in repo_hook_texts
            )
            canonical_hooks = authoritative_checkout / ".codex" / "hooks.json"
            canonical_root_floor_count = sum(
                len(
                    repo_codex_floor_groups(
                        hooks.read_text(encoding="utf-8"), expected_pin
                    )
                )
                for hooks in repo_hook_paths
                if hooks == canonical_hooks and hooks.is_file()
            )
            project_detail = (
                f"{project_floor_count} project floor handler(s); "
                f"{candidate_floor_count} candidate handler(s); "
                f"{current_floor_count} current pinned handler(s); "
                f"{canonical_root_floor_count} canonical root hooks.json handler(s); "
                f"{source_detail}; trust is checked manually in /hooks"
            )
        except (HarnessError, OSError, UnicodeError) as exc:
            project_floor_count = -1
            candidate_floor_count = -1
            current_floor_count = -1
            canonical_root_floor_count = -1
            source_ok = False
            source_detail = str(exc)
            project_detail = str(exc)
        checks.append(("Codex hook source", source_ok, source_detail))
        checks.append(
            (
                "project Codex floor",
                marker_ok
                and source_ok
                and candidate_floor_count == 1
                and project_floor_count == 1
                and current_floor_count == 1
                and canonical_root_floor_count == 1,
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
