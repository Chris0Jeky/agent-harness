#!/usr/bin/env python3
"""Harness dispatcher — the shared Claude/Codex deny floor for all tiers.

Canonical copy: agent-harness/templates/hooks/dispatch.py
Deployed copies: ~/.claude/hooks/dispatch.py and ~/.codex/hooks/dispatch.py.
`harness audit` diffs deployed copies against the canonical one.

Contract (BLUEPRINT §2, SPECS §5-6):
- Blocks only the IRREVERSIBLE at every tier: force-push in all spellings, rm -rf outside
  the project, pipe-to-shell installs, sudo, secret-file mutation, PowerShell pipe-deletes.
- Work-loss guards (reset --hard, clean -f, checkout -- ., restore .) are tier-dependent:
  allow at T1-T2, ask at T3, deny at T4 or wave_mode. A repo whose declared posture is
  relaxed-git (tier.json flag `relaxed_work_loss_guards`) keeps them allow below T4/wave_mode;
  the flag is IGNORED at T4 and under wave_mode (other agents' work is in the blast radius).
- NEVER inspects commit-message / PR-body text: quoted strings are stripped before matching.
- Failure behavior: stdin that cannot be parsed -> allow (we cannot even identify the
  command; denying would brick every session). Exceptions during RULE EVALUATION -> deny
  (fail closed). Changes to this file are T4-class work: top model + review + smoke tests.

A change here must keep `smoke_test.py` green: python smoke_test.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

FLOOR_VERSION = "1.4.0 (2026-07-13)"

# --- helpers ---------------------------------------------------------------

_SINGLE_Q = re.compile(r"'[^']*'")
_DOUBLE_Q = re.compile(r'"(?:\\.|[^"\\])*"')


def strip_quotes(text: str) -> str:
    """Remove INERT quoted substrings so message/body text can never trip a rule.

    Single-quoted text never expands -> always stripped. Double-quoted text is
    stripped only when it contains no unescaped $ or backtick; if it does, the
    shell EXECUTES the substitution, so the text must stay visible for scanning.
    (Semantics ported from wealthlens-hq's earned pre_tool_use hardening: the
    naive strip-all-quotes let `git commit -m "wip $(rm -rf /)"` fail open.)
    """
    text = _SINGLE_Q.sub(" ", text)

    def _dq(m: "re.Match[str]") -> str:
        return m.group(0) if re.search(r"(?<!\\)[$`]", m.group(0)) else " "

    return _DOUBLE_Q.sub(_dq, text)


def norm_path(p: str) -> str:
    return p.replace("\\", "/").rstrip("/").lower()


def is_absolute(p: str) -> bool:
    return bool(re.match(r"^([a-zA-Z]:[\\/]|[\\/]|~)", p))


def resolved_path(path: str, base: str) -> str:
    """Resolve traversal and env/home spellings without requiring the target to exist."""
    expanded = path.replace("$env:USERPROFILE", os.environ.get("USERPROFILE", ""))
    expanded = os.path.expanduser(os.path.expandvars(expanded))
    if not os.path.isabs(expanded):
        expanded = os.path.join(base or os.getcwd(), expanded)
    return os.path.normcase(os.path.realpath(os.path.abspath(expanded)))


def within(candidate: str, root: str) -> bool:
    """Return true only for a real path-component containment relationship."""
    try:
        return os.path.commonpath((candidate, root)) == root
    except ValueError:  # different Windows drives
        return False


def allowed_recursive_delete(target: str, project_dir: str) -> bool:
    candidate = resolved_path(target, project_dir)
    roots = []
    if project_dir:
        roots.append(resolved_path(project_dir, project_dir))
    roots.append(resolved_path(tempfile.gettempdir(), project_dir))
    if os.name != "nt":
        roots.append(resolved_path("/tmp", project_dir))
    return any(within(candidate, root) for root in roots)


DANGEROUS_ROOTS = re.compile(r"^(/|~|~/|[a-zA-Z]:/?|/c/users/[^/]+|c:/users/[^/]+)$")

# Env-var spellings of the home / user-profile root. Git Bash expands $HOME,
# ${HOME}, and "$HOME" to the home dir, so `rm -rf $HOME` is byte-identical in
# effect to the denied `rm -rf ~`. Matched AFTER norm_path (lowercased, trailing
# slash stripped); double-quoted "$HOME" survives strip_quotes because it holds a $.
ENV_ROOTS = re.compile(r'^"?(\$\{?home\}?|\$env:userprofile|%userprofile%)"?$', re.IGNORECASE)

# git global options that consume a SEPARATE value token (git -C <dir> push ...).
# If we do not skip the value, the first non-dash token (the value) is misread as
# the subcommand and every push/reset/clean/checkout/restore rule is skipped.
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                   "--super-prefix", "--config-env"}

# Command wrappers to skip so the REAL command head is matched (env git push …,
# nice -n 5 git …). VAR=value assignment prefixes are skipped the same way.
_WRAPPERS = {"env", "command", "builtin", "nice", "nohup", "time", "stdbuf", "xargs"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_EXE_SUFFIX = re.compile(r"\.(exe|cmd|bat|com|ps1)$", re.IGNORECASE)


def command_head(toks):
    """Normalize toks to (head, command_toks): strip leading VAR=val assignments
    and known wrappers, drop the head's directory + .exe/.cmd suffix. So
    `env FOO=bar /usr/bin/git.exe push` and `git push` both resolve head='git'
    with command_toks starting at the git invocation."""
    i = 0
    while i < len(toks):
        t = toks[i]
        if _ASSIGN.match(t):
            i += 1
            continue
        base = _EXE_SUFFIX.sub("", t.replace("\\", "/").split("/")[-1]).lower()
        if base in _WRAPPERS:
            i += 1
            while i < len(toks) and _ASSIGN.match(toks[i]):  # env VAR=val ...
                i += 1
            continue
        return base, toks[i:]
    return "", []


def git_subcommand(toks):
    """Return the git subcommand, skipping global options AND their value tokens.
    toks starts at the git invocation (toks[0] is git[.exe])."""
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in _GIT_VALUE_OPTS:
            i += 2  # skip the option and its separate value
            continue
        if t.startswith("-"):
            i += 1  # valueless global option, or --opt=value (glued)
            continue
        return t.lower()
    return ""


def command_output(argv: list[str], cwd: str) -> str:
    try:
        proc = subprocess.run(argv, cwd=cwd or None, capture_output=True, text=True, timeout=3,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def push_remote(args: list[str], project_dir: str) -> str:
    """Resolve the destination token/remote URL for a git push."""
    remote = ""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--repo" and i + 1 < len(args):
            remote = args[i + 1]
            break
        if arg.startswith("--repo="):
            remote = arg.split("=", 1)[1]
            break
        if not arg.startswith("-"):
            remote = arg
            break
        i += 1
    if not remote:
        branch = command_output(["git", "branch", "--show-current"], project_dir)
        if branch:
            remote = command_output(["git", "config", f"branch.{branch}.remote"], project_dir)
        remote = remote or "origin"
    if re.match(r"^(https?://|ssh://|git@|file://|[a-zA-Z]:[\\/]|[./~])", remote):
        return remote
    return command_output(["git", "remote", "get-url", remote], project_dir)


def public_remote_status(args: list[str], project_dir: str) -> tuple[bool | None, str]:
    """Return (is_public, label); None means privacy could not be established."""
    remote = push_remote(args, project_dir)
    if not remote:
        return None, "unresolved push remote"
    normalized = remote.lower()
    if normalized.startswith("file://") or re.match(r"^([a-zA-Z]:[\\/]|[./~])", remote):
        return False, remote
    if "github.com" not in normalized:
        return None, remote
    visibility = command_output(
        ["gh", "repo", "view", remote, "--json", "visibility", "--jq", ".visibility"],
        project_dir,
    ).upper()
    if visibility == "PUBLIC":
        return True, remote
    if visibility in {"PRIVATE", "INTERNAL"}:
        return False, remote
    return None, remote


def load_tier(project_dir: str) -> dict:
    """Read the runtime-neutral tier file, then the legacy Claude location."""
    cfg = {"tier": 1, "flags": {}}
    if not project_dir:
        return cfg
    paths = (
        os.path.join(project_dir, ".agent-harness", "tier.json"),
        os.path.join(project_dir, ".claude", "tier.json"),
    )
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            cfg["tier"] = int(data.get("tier", 1))
            cfg["flags"] = data.get("flags", {}) or {}
            break
        except (OSError, ValueError):
            continue
    return cfg


def segments(sanitized: str):
    """Split a sanitized command line into per-command segments.

    Splits on chains (; newline | || &&) AND on substitution/subshell delimiters
    ($( ), <( ), backticks, parens) so an inner command is checked exactly like a
    top-level one — `git commit $(git push --force ...)` must not fail open.
    """
    return [s.strip() for s in re.split(r"[;\n()`|]|&&", sanitized) if s.strip()]


def tokens(segment: str):
    return segment.split()


# --- rules ------------------------------------------------------------------


def check(command: str, tier_cfg: dict, project_dir: str, remote_resolver=public_remote_status):
    """Return (decision, reason). decision in {'allow', 'ask', 'deny'}."""
    tier = tier_cfg.get("tier", 1)
    flags = tier_cfg.get("flags", {})
    wave = bool(flags.get("wave_mode"))
    sensitive = bool(flags.get("sensitive_data"))
    strict = tier >= 4 or wave  # work-loss guards become walls
    # Declared relaxed-git posture (BLUEPRINT §2): work-loss guards stay allow below
    # T4/wave_mode. Never weakens `strict` — the flag is ignored where guards are walls.
    relaxed = bool(flags.get("relaxed_work_loss_guards")) and not strict

    sanitized = strip_quotes(command)

    # Pipe rules run on the full sanitized text (the pipe IS the signal).
    if re.search(r"\b(curl|wget|iwr|irm)\b[^|;&]*\|\s*(sh|bash|zsh|pwsh|powershell|iex)\b",
                 sanitized, re.IGNORECASE):
        return "deny", "Piping a download straight into a shell is irreversible-by-design. Download, inspect, then run."
    if re.search(r"\|\s*(Remove-Item|del|rd)\b", sanitized, re.IGNORECASE):
        return "deny", "Piping into Remove-Item/del deletes whatever upstream matched. Enumerate first, delete explicitly."

    for seg in segments(sanitized):
        raw = tokens(seg)
        if not raw:
            continue
        # Normalize away wrappers / VAR=val / path + .exe so `env git`, `git.exe`,
        # `/usr/bin/git`, `sudo.exe` all resolve to their real head (bypass fix).
        head, toks = command_head(raw)
        if not toks:
            continue

        if head == "sudo":
            return "deny", "sudo is blocked at the floor. If elevation is truly needed, the human runs it."

        # ---- git rules ----
        if head == "git":
            sub = git_subcommand(toks)
            # Args AFTER the subcommand, robust to leading global options
            # (git -C <dir> push --force -> args = [--force, ...], not misaligned).
            args = toks[toks.index(sub) + 1:] if sub in toks else []

            if sub == "push":
                for t in args:
                    if t == "--force" or (t.startswith("--force=")):
                        return "deny", "Force-push rewrites shared history. Use --force-with-lease on your own branch, or merge instead."
                    if t == "--force-with-lease" or t.startswith("--force-with-lease="):
                        if strict:
                            return "deny", "T4/wave: no force variants at all — other work rides on these refs."
                        continue
                    if re.match(r"^-[a-zA-Z]*f[a-zA-Z]*$", t):
                        return "deny", "git push -f is a force-push. Use --force-with-lease on your own branch, or merge instead."
                    if t.startswith("+") and len(t) > 1:
                        return "deny", "A +refspec is a forced update in disguise."
                if sensitive:
                    is_public, remote = remote_resolver(args, project_dir)
                    if is_public is True:
                        return "deny", f"sensitive_data repo: refusing a push to public remote {remote}."
                    if is_public is None:
                        return "deny", f"sensitive_data repo: could not verify push remote privacy ({remote})."

            if sub == "reset" and "--hard" in args:
                if strict:
                    return "deny", "T4/wave: hard reset discards work that may not be yours. Inspect state; ask."
                if tier >= 3 and not relaxed:
                    return "ask", "T3: git reset --hard discards uncommitted work. Confirm you want this."

            if sub == "clean" and any(re.match(r"^-[a-zA-Z]*f", t) for t in args):
                if strict:
                    return "deny", "T4/wave: git clean -f deletes untracked files that may belong to another agent."
                if tier >= 3 and not relaxed:
                    return "ask", "T3: git clean -f deletes untracked files. Confirm."

            if sub == "checkout" and "--" in args:
                after = args[args.index("--") + 1:]
                if "." in after:
                    if strict:
                        return "deny", "T4/wave: checkout -- . wipes all local modifications."
                    if tier >= 3 and not relaxed:
                        return "ask", "T3: checkout -- . wipes local modifications. Confirm."

            if sub == "restore" and "." in args and "--staged" not in args:
                if strict:
                    return "deny", "T4/wave: git restore . wipes all local modifications."
                if tier >= 3 and not relaxed:
                    return "ask", "T3: git restore . wipes local modifications. Confirm."

        # ---- rm rules ----
        if head == "rm":
            flags_str = "".join(t.lstrip("-") for t in toks[1:] if t.startswith("-"))
            targets = [t for t in toks[1:] if not t.startswith("-")]
            if "r" in flags_str and "f" in flags_str:
                if not targets:
                    return "deny", "rm -rf with no clear target."
                for target in targets:
                    nt = norm_path(target)
                    if target == "*":
                        return "deny", "rm -rf * is a floor rule: enumerate and delete explicitly."
                    if DANGEROUS_ROOTS.match(nt) or ENV_ROOTS.match(nt):
                        return "deny", f"rm -rf {target}: refusing a filesystem/home root."
                    expanded = os.path.expanduser(os.path.expandvars(target))
                    if is_absolute(target) or os.path.isabs(expanded):
                        if not allowed_recursive_delete(target, project_dir):
                            return "deny", f"rm -rf on an absolute path outside the project: {target}"

        # ---- PowerShell explicit recursive delete on outside-project absolute path ----
        if head in ("remove-item", "ri"):
            if any(re.match(r"^-recurse", t, re.IGNORECASE) for t in toks[1:]):
                for target in (t for t in toks[1:] if not t.startswith("-")):
                    nt = norm_path(target)
                    if is_absolute(target) and DANGEROUS_ROOTS.match(nt):
                        return "deny", f"Recursive Remove-Item on {target}: refusing a root."
                    if is_absolute(target) and not allowed_recursive_delete(target, project_dir):
                        return "deny", f"Recursive Remove-Item outside the project: {target}"

        # ---- secret-file mutation ----
        secret_rx = re.compile(r"(^|[\\/])\.env(\.[\w.]+)?$|credential|secrets?\.|id_rsa|\.pem$",
                               re.IGNORECASE)
        if head in ("rm", "del", "mv", "set-content", "sc"):
            for target in (t for t in toks[1:] if not t.startswith("-")):
                if secret_rx.search(target):
                    return "deny", f"Mutating a secret-looking file ({target}) is floor-blocked. The human manages secrets."
        redir = re.search(r">{1,2}\s*(\S+)", seg)
        if redir and secret_rx.search(redir.group(1)):
            return "deny", f"Redirecting output into a secret-looking file ({redir.group(1)}) is floor-blocked."

        # ---- sensitive_data overlay ----
        if sensitive and head == "gh":
            if len(toks) >= 3 and toks[1] in ("repo", "gist") and toks[2] == "create":
                if any(t in ("--public", "-p") for t in toks):
                    return "deny", "sensitive_data repo: creating PUBLIC repos/gists is blocked."

    return "allow", ""


# --- entry ------------------------------------------------------------------


def respond(decision: str, reason: str, runtime: str = "claude"):
    if decision == "allow":
        sys.exit(0)
    if decision == "ask" and runtime == "codex":
        # Codex 0.144 parses permissionDecision=ask but currently treats it as a
        # hook failure and continues. Emit supported model-visible context instead.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": f"[floor {FLOOR_VERSION}] WARNING: {reason}",
            }
        }))
        sys.exit(0)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": f"[floor {FLOOR_VERSION}] {reason}",
        }
    }))
    sys.exit(0)


def main():
    event = "pre"
    if "--event" in sys.argv:
        try:
            event = sys.argv[sys.argv.index("--event") + 1]
        except IndexError:
            pass
    if event != "pre":
        sys.exit(0)  # global layer wires only the floor; other events are repo-tier

    runtime = "claude"
    if "--runtime" in sys.argv:
        try:
            runtime = sys.argv[sys.argv.index("--runtime") + 1].lower()
        except IndexError:
            pass

    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Cannot even identify the command — denying here would brick every session.
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command.strip():
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""

    try:
        decision, reason = check(command, load_tier(project_dir), project_dir)
    except Exception as exc:  # fail CLOSED during rule evaluation
        respond("deny", f"dispatcher error ({exc.__class__.__name__}) — floor unavailable; fix the installed dispatcher before proceeding.", runtime)
        return
    respond(decision, reason, runtime)


if __name__ == "__main__":
    main()
