#!/usr/bin/env python3
"""Portable, dependency-free tooling for the cross-runtime agent harness."""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


TIER_NAMES = {0: "tombstone", 1: "sandbox", 2: "daily-driver", 3: "workshop", 4: "live-wire"}
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


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def git_root(path: Path) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], path)
    if result.returncode:
        raise HarnessError(f"not a Git repository: {path}")
    return Path(result.stdout.strip()).resolve()


def tier_path(repo: Path) -> Path | None:
    for candidate in (repo / ".agent-harness" / "tier.json", repo / ".claude" / "tier.json"):
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
                issues.append(f"authority.{key} must be one of {sorted(AUTHORITY_VALUES)}")
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
        checks.append((repo / "CLAUDE.md", CLAUDE_LINE_CAPS[tier], "rotate detail into linked docs"))
    if (repo / "AGENTS.md").is_file():
        checks.append((repo / "AGENTS.md", 80, "move detail to the repo map or domain docs"))
    if (repo / "AGENT_MAP.md").is_file():
        checks.append((repo / "AGENT_MAP.md", 100, "split detail into docs/regions"))
    for skill in (repo / ".agents" / "skills").glob("*/SKILL.md") if (repo / ".agents" / "skills").is_dir() else ():
        checks.append((skill, 80, "split detail into a directly linked reference"))
    issues = []
    for path, cap, remedy in checks:
        actual = line_count(path)
        if actual > cap:
            issues.append(f"{path.relative_to(repo)}: {actual}>{cap} lines; ROTATE: {remedy}")
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
            candidates.extend(p for p in path.rglob("*") if p.is_file() and p.stat().st_size <= 1_000_000)
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(needle.lower() in text.lower() for needle in needles):
            issues.append(f"{path.relative_to(repo)} contains a stale jekyt-profile path")
    return issues


def audit_repo(path: Path) -> dict[str, Any]:
    repo = git_root(path)
    config_path, tier_data = load_tier(repo)
    issues: list[str] = []
    if config_path is None:
        issues.append("missing .agent-harness/tier.json (legacy .claude/tier.json also accepted)")
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
        "model_routing": {"harness_and_review": "sol", "slices": "terra", "maintenance": "luna"},
        "budgets": {"standing_context_tokens": {1: 1000, 2: 3000, 3: 6000, 4: 8000}.get(args.tier, 200)},
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
    return left.is_file() and right.is_file() and filecmp.cmp(left, right, shallow=False)


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


def rendered_hooks(template: Path, dispatch_target: Path) -> str:
    escaped = json.dumps(str(dispatch_target))[1:-1]
    text = template.read_text(encoding="utf-8").replace("{{DISPATCH_PY}}", escaped)
    json.loads(text)
    return text


def merge_hooks(current: str, managed: str) -> str:
    try:
        current_data = json.loads(current) if current.strip() else {"hooks": {}}
        managed_data = json.loads(managed)
    except json.JSONDecodeError as exc:
        raise HarnessError(f"refusing to replace invalid existing hooks.json: {exc}") from exc
    hooks = current_data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HarnessError("existing hooks.json has a non-object hooks field")
    managed_group = managed_data["hooks"]["PreToolUse"][0]
    existing_groups = hooks.setdefault("PreToolUse", [])
    if not isinstance(existing_groups, list):
        raise HarnessError("existing hooks.PreToolUse must be an array")

    def is_managed(group: Any) -> bool:
        if not isinstance(group, dict):
            return False
        for handler in group.get("hooks", []):
            if not isinstance(handler, dict):
                continue
            command = f"{handler.get('command', '')} {handler.get('commandWindows', '')}"
            if "dispatch.py" in command and "--runtime codex" in command and "--event pre" in command:
                return True
        return False

    hooks["PreToolUse"] = [group for group in existing_groups if not is_managed(group)] + [managed_group]
    return json.dumps(current_data, indent=2) + "\n"


def sync_global(args: argparse.Namespace) -> int:
    config_root = Path(args.config_root).resolve()
    codex_source = config_root / "codex"
    harness_root = Path(__file__).resolve().parent
    codex_home = Path(args.codex_home or os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
    skills_home = Path(args.skills_home or Path.home() / ".agents" / "skills").resolve()
    required = [codex_source / "AGENTS.md", harness_root / "templates" / "hooks" / "dispatch.py", harness_root / "templates" / "codex" / "hooks.json"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise HarnessError("missing sync sources: " + ", ".join(missing))
    actions = [
        (codex_source / "AGENTS.md", codex_home / "AGENTS.md"),
        (harness_root / "templates" / "hooks" / "dispatch.py", codex_home / "hooks" / "dispatch.py"),
    ]
    if (codex_source / "REPOS.md").is_file():
        actions.append((codex_source / "REPOS.md", codex_home / "REPOS.md"))
    skill_actions = [(skill, skills_home / skill.name) for skill in sorted((codex_source / "skills").iterdir()) if (skill / "SKILL.md").is_file()]
    managed_hook_text = rendered_hooks(harness_root / "templates" / "codex" / "hooks.json", codex_home / "hooks" / "dispatch.py")
    print(f"Codex home: {codex_home}")
    print(f"Skills home: {skills_home}")
    for source, target in actions:
        print(f"{'=' if same_file(source, target) else '->'} {target}")
    current_hooks = (codex_home / "hooks.json").read_text(encoding="utf-8") if (codex_home / "hooks.json").is_file() else ""
    hook_text = merge_hooks(current_hooks, managed_hook_text)
    print(f"{'=' if current_hooks == hook_text else '->'} {codex_home / 'hooks.json'}")
    for source, target in skill_actions:
        equal = tree_digest(source) == tree_digest(target)
        print(f"{'=' if equal else '->'} {target}")
    if not args.apply:
        print("dry run; pass --apply to install")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = codex_home / "backups" / stamp
    for source, target in actions:
        copy_with_backup(source, target, backup_root)
    hooks_target = codex_home / "hooks.json"
    if current_hooks != hook_text:
        if hooks_target.exists():
            backup_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hooks_target, backup_root / "hooks.json")
        hooks_target.parent.mkdir(parents=True, exist_ok=True)
        hooks_target.write_text(hook_text, encoding="utf-8")
    skill_backup = skills_home / ".harness-backups" / stamp
    for source, target in skill_actions:
        if target.exists():
            backup = skill_backup / target.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                shutil.rmtree(backup)
            shutil.copytree(target, backup)
            shutil.rmtree(target)
        shutil.copytree(source, target)
    print(f"installed Codex global layer; backups: {backup_root}")
    print("Open /hooks in a new Codex session and trust the reviewed global hook hash.")
    return 0


def doctor(args: argparse.Namespace) -> int:
    codex_home = Path(args.codex_home or os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
    skills_home = Path(args.skills_home or Path.home() / ".agents" / "skills").resolve()
    checks = []
    codex_command = (["powershell", "-NoProfile", "-Command", "codex --version"]
                     if os.name == "nt" else ["codex", "--version"])
    for label, command in (("python", [sys.executable, "--version"]), ("codex", codex_command), ("git", ["git", "--version"])):
        result = run(command)
        checks.append((label, result.returncode == 0, (result.stdout or result.stderr).strip()))
    checks.extend(
        [
            ("global AGENTS", (codex_home / "AGENTS.md").is_file() and (codex_home / "AGENTS.md").stat().st_size > 0, str(codex_home / "AGENTS.md")),
            ("global hooks", (codex_home / "hooks.json").is_file(), str(codex_home / "hooks.json")),
            ("dispatcher", (codex_home / "hooks" / "dispatch.py").is_file(), str(codex_home / "hooks" / "dispatch.py")),
            ("user skills", skills_home.is_dir() and any(skills_home.glob("*/SKILL.md")), str(skills_home)),
        ]
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

    seed = sub.add_parser("seed", help="create a write-once runtime-neutral tier declaration")
    seed.add_argument("path", nargs="?", default=".")
    seed.add_argument("--tier", type=int, choices=TIER_NAMES, required=True)
    seed.add_argument("--push", choices=sorted(AUTHORITY_VALUES), default="free")
    seed.add_argument("--merge", choices=sorted(AUTHORITY_VALUES), default="free")
    seed.add_argument("--human-todo")
    seed.add_argument("--sensitive-data", action="store_true")
    seed.add_argument("--relaxed-work-loss-guards", action="store_true")
    seed.add_argument("--dry-run", action="store_true")
    seed.set_defaults(func=seed_repo)

    sync = sub.add_parser("sync-global", help="diff or install the versioned Codex global layer")
    sync.add_argument("--config-root", required=True, help="path to the claude-config checkout")
    sync.add_argument("--codex-home")
    sync.add_argument("--skills-home")
    sync.add_argument("--apply", action="store_true")
    sync.set_defaults(func=sync_global)

    check = sub.add_parser("doctor", help="check the live Codex global installation")
    check.add_argument("--codex-home")
    check.add_argument("--skills-home")
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
