#!/usr/bin/env python3
"""Harness dispatcher — the deny floor (PreToolUse) for all tiers.

Canonical copy: agent-harness/templates/hooks/dispatch.py
Deployed copies: ~/.claude/hooks/dispatch.py (global) and per-repo .claude/hooks/.
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
import ntpath
import os
import re
import shlex
import sys
import tempfile

FLOOR_VERSION = "1.3.1 (2026-07-13)"

# --- helpers ---------------------------------------------------------------

_SINGLE_Q = re.compile(r"'[^']*'")
_DOUBLE_Q = re.compile(r'"(?:\\.|[^"\\])*"')
_QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")


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


def quote_aware_segments(command: str) -> list[list[str]]:
    """Tokenize executable argv while protecting quoted operator characters.

    This preserves quoted flags and paths for policy checks without mistaking
    inert commit messages or quoted separators for additional commands.
    """
    quoted: dict[str, str] = {}

    def protect(match: "re.Match[str]") -> str:
        placeholder = f"__HARNESS_QUOTED_{len(quoted)}__"
        token = match.group(0)
        try:
            value = shlex.split(token, posix=True)[0]
        except (IndexError, ValueError):
            value = token[1:-1]
        quoted[placeholder] = value
        return placeholder

    protected = _QUOTED.sub(protect, command)
    lexer = shlex.shlex(protected, posix=True, punctuation_chars=";&|<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        raw_tokens = list(lexer)
    except ValueError:
        return []

    separators = set(";&|\n")
    result: list[list[str]] = []
    current: list[str] = []
    for raw_token in raw_tokens:
        if raw_token and all(char in separators for char in raw_token):
            if current:
                result.append(current)
                current = []
            continue
        token = raw_token
        for placeholder, value in quoted.items():
            replacement = value
            if raw_token == placeholder and value in (">", ">>"):
                replacement = f"__HARNESS_LITERAL_REDIRECT_{len(value)}__"
            token = token.replace(placeholder, replacement)
        current.append(token)
    if current:
        result.append(current)
    return result


def norm_path(p: str) -> str:
    return p.replace("\\", "/").rstrip("/").lower()


def is_absolute(p: str) -> bool:
    return bool(re.match(r"^([a-zA-Z]:[\\/]|[\\/]|~)", p))


def canonical_path(path: str) -> tuple[str, str]:
    """Return (path flavor, canonical absolute path) for containment checks.

    Native paths resolve symlinks/junctions. Foreign Windows paths still receive
    boundary-aware lexical normalization so the smoke matrix is portable.
    """
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    raw = os.path.expandvars(os.path.expanduser(path.strip("\"'")))
    windows_path = bool(re.match(r"^[A-Za-z]:[\\/]", raw))
    if windows_path:
        if os.name == "nt":
            canonical = os.path.realpath(os.path.abspath(raw))
        else:
            canonical = ntpath.abspath(raw)
        return "windows", ntpath.normcase(ntpath.normpath(canonical))

    canonical = os.path.realpath(os.path.abspath(raw))
    flavor = "windows" if os.name == "nt" else "posix"
    path_module = ntpath if flavor == "windows" else os.path
    return flavor, path_module.normcase(path_module.normpath(canonical))


def is_within_path(target: str, root: str) -> bool:
    """Return whether target resolves to root or a descendant of root."""
    if not root:
        return False
    try:
        target_flavor, canonical_target = canonical_path(target)
        root_flavor, canonical_root = canonical_path(root)
        if target_flavor != root_flavor:
            return False
        path_module = ntpath if target_flavor == "windows" else os.path
        common = path_module.commonpath([canonical_target, canonical_root])
        return path_module.normcase(common) == path_module.normcase(canonical_root)
    except (OSError, ValueError):
        return False


def is_within_project(target: str, project_dir: str) -> bool:
    return is_within_path(target, project_dir)


def is_within_temp(target: str) -> bool:
    if not is_within_path(target, tempfile.gettempdir()):
        return False
    try:
        target_flavor, canonical_target = canonical_path(target)
        root_flavor, canonical_root = canonical_path(tempfile.gettempdir())
    except (OSError, ValueError):
        return False
    return target_flavor == root_flavor and canonical_target != canonical_root


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


_POWERSHELL_ENV = re.compile(
    r"\$(?:env:([A-Za-z_][A-Za-z0-9_]*)|\{env:([A-Za-z_][A-Za-z0-9_]*)\})",
    re.IGNORECASE,
)
_PERCENT_ENV = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")
_POSIX_ENV = re.compile(r"\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})")
_FILESYSTEM_PROVIDER = re.compile(
    r"^(?:(?:Microsoft\.PowerShell\.Core\\)?FileSystem)::(.*)$",
    re.IGNORECASE,
)


def environment_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None and name.upper() == "HOME":
        value = os.environ.get("USERPROFILE")
    return value


def expand_environment_references(path: str) -> str | None:
    """Expand shell environment references or return None when unresolved."""
    unresolved = False

    def replace(match: "re.Match[str]") -> str:
        nonlocal unresolved
        name = next(group for group in match.groups() if group is not None)
        value = environment_value(name)
        if value is None:
            unresolved = True
            return match.group(0)
        return value

    expanded = _POWERSHELL_ENV.sub(replace, path)
    expanded = _PERCENT_ENV.sub(replace, expanded)
    expanded = _POSIX_ENV.sub(replace, expanded)
    if unresolved:
        return None
    return os.path.expanduser(expanded)


def resolve_delete_operand(
    target: str,
    command_cwd: str,
    *,
    powershell_semantics: bool,
    cwd_uncertain: bool,
) -> str | None:
    """Resolve a recursive-delete operand for canonical containment checks."""
    raw = target
    if re.search(r"\$\(|@\(|`|[<>]\(|\{[^{}]*(?:,|\.\.)[^{}]*\}", raw):
        return None
    if powershell_semantics:
        filesystem_match = _FILESYSTEM_PROVIDER.match(raw)
        if filesystem_match:
            raw = filesystem_match.group(1)
        elif "::" in raw:
            return None
        else:
            drive_match = re.match(r"^([A-Za-z][A-Za-z0-9_.-]*):(.*)$", raw)
            if drive_match and len(drive_match.group(1)) > 1:
                return None

    expanded = expand_environment_references(raw)
    if expanded is None:
        return None
    if re.search(r"\$|%[A-Za-z_][A-Za-z0-9_]*%|@\(", expanded):
        return None

    drive, drive_tail = ntpath.splitdrive(expanded)
    if drive and not drive_tail.startswith(("/", "\\")):
        if not command_cwd or cwd_uncertain:
            return None
        cwd_drive, _ = ntpath.splitdrive(command_cwd)
        if not cwd_drive or cwd_drive.lower() != drive.lower():
            return None
        return ntpath.join(command_cwd, drive_tail)

    if is_absolute(expanded):
        return expanded
    if not command_cwd or cwd_uncertain:
        return None
    try:
        cwd_flavor, canonical_cwd = canonical_path(command_cwd)
    except (OSError, ValueError):
        return None
    path_module = ntpath if cwd_flavor == "windows" else os.path
    return path_module.join(canonical_cwd, expanded)


def is_powershell_recurse_flag(token: str) -> bool:
    if not token.startswith("-"):
        return False
    name, _, value = token.lstrip("-").partition(":")
    if value.lower() in ("false", "$false", "0"):
        return False
    return bool(name) and "recurse".startswith(name.lower())


def recursive_delete_decision(
    head: str,
    toks: list[str],
    project_dir: str,
    command_cwd: str,
    cwd_uncertain: bool,
) -> tuple[str, str] | None:
    """Check POSIX, PowerShell, and cmd recursive-delete spellings."""
    if head == "rm":
        flags_str = "".join(t.lstrip("-") for t in toks[1:] if t.startswith("-"))
        targets = [t for t in toks[1:] if not t.startswith("-")]
        if "r" in flags_str.lower() and "f" in flags_str.lower():
            if not targets:
                return "deny", "rm -rf with no clear target."
            decision = check_delete_targets(
                targets,
                project_dir,
                command_cwd,
                powershell_semantics=False,
                cwd_uncertain=cwd_uncertain,
                label="rm -rf",
            )
            if decision:
                return decision

    powershell_heads = {"remove-item", "ri", "rm", "del", "erase", "rd", "rmdir"}
    if head not in powershell_heads:
        return None
    powershell_recurse = any(is_powershell_recurse_flag(token) for token in toks[1:])
    cmd_recurse = head in {"del", "erase", "rd", "rmdir"} and any(
        token.lower() == "/s" for token in toks[1:]
    )
    if not (powershell_recurse or cmd_recurse):
        return None
    cmd_flags = {"/s", "/q", "/f"}
    targets = [
        token
        for token in toks[1:]
        if not token.startswith("-") and token.lower() not in cmd_flags
    ]
    return check_delete_targets(
        targets,
        project_dir,
        command_cwd,
        powershell_semantics=True,
        cwd_uncertain=cwd_uncertain,
        label="recursive Remove-Item",
    )


def check_delete_targets(
    targets: list[str],
    project_dir: str,
    command_cwd: str,
    *,
    powershell_semantics: bool,
    cwd_uncertain: bool,
    label: str,
) -> tuple[str, str] | None:
    for target in targets:
        if target == "*":
            return "deny", f"{label} * is floor-blocked: enumerate and delete explicitly."
        resolved = resolve_delete_operand(
            target,
            command_cwd,
            powershell_semantics=powershell_semantics,
            cwd_uncertain=cwd_uncertain,
        )
        if resolved is None:
            return "deny", f"Cannot safely resolve {label} target: {target}"
        normalized = norm_path(resolved)
        if DANGEROUS_ROOTS.match(normalized) or ENV_ROOTS.match(normalized):
            return "deny", f"{label} {target}: refusing a filesystem/home root."
        if not (is_within_project(resolved, project_dir) or is_within_temp(resolved)):
            return "deny", f"{label} outside the project: {target}"
    return None


def declared_project_dirs(start_dir: str) -> list[str]:
    """Return every ancestor carrying a tier declaration, nearest first."""
    if not start_dir:
        return []
    current = os.path.realpath(os.path.abspath(start_dir))
    declared = []
    while True:
        tier_path = os.path.join(current, ".claude", "tier.json")
        try:
            os.lstat(tier_path)
        except FileNotFoundError:
            pass
        else:
            declared.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            return declared
        current = parent


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_tier(project_dir: str) -> dict:
    """Read and validate tier authority; absent -> sandbox defaults.

    A present but unreadable or invalid declaration is a safety failure and must
    propagate to the PRE-path fail-closed handler.
    """
    cfg = {"tier": 1, "flags": {}}
    if not project_dir:
        return cfg
    path = os.path.join(project_dir, ".claude", "tier.json")
    try:
        os.lstat(path)
    except FileNotFoundError:
        return cfg
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh, object_pairs_hook=reject_duplicate_keys)
    if not isinstance(data, dict):
        raise ValueError("tier.json must contain an object")
    tier = data.get("tier")
    flags = data.get("flags", {})
    if type(tier) is not int or tier not in range(5):
        raise ValueError("tier.json tier must be an integer from 0 through 4")
    if not isinstance(flags, dict):
        raise ValueError("tier.json flags must be an object")
    if any(not isinstance(key, str) or type(value) is not bool for key, value in flags.items()):
        raise ValueError("tier.json flags must map string names to booleans")
    cfg["tier"] = tier
    cfg["flags"] = flags
    return cfg


def resolve_context(env_project_dir: str, payload_cwd: str) -> tuple[str, dict]:
    """Resolve deletion scope and the strictest applicable tier posture.

    The payload cwd anchors project containment. Tier declarations from both the
    cwd and explicit environment chains are merged so a nested or stale context
    cannot downgrade an outer T4 or tightening overlay.
    """
    payload_projects = declared_project_dirs(payload_cwd)
    env_projects = declared_project_dirs(env_project_dir)
    if payload_cwd:
        project_dir = payload_projects[0] if payload_projects else os.path.realpath(
            os.path.abspath(payload_cwd)
        )
    elif env_project_dir:
        project_dir = env_projects[0] if env_projects else os.path.realpath(
            os.path.abspath(env_project_dir)
        )
    else:
        project_dir = ""

    declared = []
    seen = set()
    for path in payload_projects + env_projects:
        key = os.path.normcase(os.path.realpath(path))
        if key not in seen:
            seen.add(key)
            declared.append(path)

    configs = [load_tier(path) for path in declared]
    if not configs:
        return project_dir, {"tier": 1, "flags": {}}

    flags = {}
    for cfg in configs:
        for key, value in cfg.get("flags", {}).items():
            if key == "relaxed_work_loss_guards":
                continue
            if isinstance(value, bool):
                flags[key] = bool(flags.get(key)) or value
            elif key not in flags:
                flags[key] = value
    flags["relaxed_work_loss_guards"] = all(
        bool(cfg.get("flags", {}).get("relaxed_work_loss_guards")) for cfg in configs
    )
    return project_dir, {
        "tier": max(cfg.get("tier", 1) for cfg in configs),
        "flags": flags,
    }


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


def check(
    command: str,
    tier_cfg: dict,
    project_dir: str,
    command_cwd: str,
    _depth: int = 0,
):
    """Return (decision, reason). decision in {'allow', 'ask', 'deny'}."""
    if _depth > 4:
        return "deny", "Nested shell depth exceeds the deny-floor inspection limit."
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
    if re.search(
        r"\|\s*(Remove-Item|ri|rm|del|erase|rd|rmdir)\b",
        sanitized,
        re.IGNORECASE,
    ):
        return "deny", "Piping into Remove-Item/del deletes whatever upstream matched. Enumerate first, delete explicitly."

    execution_segments = [(raw, True, "") for raw in quote_aware_segments(command)]
    execution_segments.extend(
        (tokens(segment), False, segment) for segment in segments(sanitized)
    )
    cwd_uncertain = False
    previous_quote_aware = True
    for raw, quote_aware, segment_text in execution_segments:
        if previous_quote_aware and not quote_aware:
            cwd_uncertain = False
        previous_quote_aware = quote_aware
        if not raw:
            continue
        # Normalize away wrappers / VAR=val / path + .exe so `env git`, `git.exe`,
        # `/usr/bin/git`, `sudo.exe` all resolve to their real head (bypass fix).
        head, toks = command_head(raw)
        if not toks:
            continue

        if head == "sudo":
            return "deny", "sudo is blocked at the floor. If elevation is truly needed, the human runs it."

        if head in {
            "cd", "chdir", "pushd", "popd", "push-location", "pop-location",
            "set-location", "sl",
        }:
            cwd_uncertain = True

        nested_script = None
        if head == "cmd":
            for index, token in enumerate(toks[1:], start=1):
                if token.lower() in ("/c", "/k") and index + 1 < len(toks):
                    nested_script = " ".join(toks[index + 1:])
                    break
        elif head in {"bash", "sh", "zsh", "pwsh", "powershell"}:
            for index, token in enumerate(toks[1:], start=1):
                option = token.lstrip("-").lower()
                is_command = token == "-c" or (
                    head in {"bash", "sh", "zsh"}
                    and bool(re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", token))
                ) or (
                    head in {"pwsh", "powershell"}
                    and bool(option)
                    and "command".startswith(option)
                )
                if is_command and index + 1 < len(toks):
                    nested_script = " ".join(toks[index + 1:])
                    break
        if nested_script:
            nested_decision = check(
                nested_script,
                tier_cfg,
                project_dir,
                command_cwd,
                _depth + 1,
            )
            if nested_decision[0] != "allow":
                return nested_decision

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

        delete_decision = recursive_delete_decision(
            head,
            toks,
            project_dir,
            command_cwd,
            cwd_uncertain,
        )
        if delete_decision:
            return delete_decision

        # ---- secret-file mutation ----
        secret_rx = re.compile(r"(^|[\\/])\.env(\.[\w.]+)?$|credential|secrets?\.|id_rsa|\.pem$",
                               re.IGNORECASE)
        if head in ("rm", "del", "mv", "set-content", "sc"):
            for target in (t for t in toks[1:] if not t.startswith("-")):
                if secret_rx.search(target):
                    return "deny", f"Mutating a secret-looking file ({target}) is floor-blocked. The human manages secrets."
        if quote_aware:
            for index, token in enumerate(raw[:-1]):
                if token in (">", ">>") and secret_rx.search(raw[index + 1]):
                    return "deny", f"Redirecting output into a secret-looking file ({raw[index + 1]}) is floor-blocked."
        else:
            redir = re.search(r">{1,2}\s*(\S+)", segment_text)
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
    if runtime == "codex" and decision == "ask":
        decision = "deny"
        reason = f"Codex does not support ask decisions; conservative deny. {reason}"
    if decision == "allow":
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
    runtime = "claude"
    if "--event" in sys.argv:
        try:
            event = sys.argv[sys.argv.index("--event") + 1]
        except IndexError:
            pass
    if "--runtime" in sys.argv:
        try:
            runtime = sys.argv[sys.argv.index("--runtime") + 1].lower()
        except IndexError:
            runtime = "invalid"
    if event != "pre":
        sys.exit(0)  # global layer wires only the floor; other events are repo-tier

    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Cannot even identify the command — denying here would brick every session.
        sys.exit(0)

    try:
        if not isinstance(payload, dict):
            raise ValueError("hook payload must be an object")
        if payload.get("tool_name") != "Bash":
            sys.exit(0)
        tool_input = payload.get("tool_input")
        if tool_input is None:
            tool_input = {}
        if not isinstance(tool_input, dict):
            raise ValueError("Bash tool_input must be an object")
        command = tool_input.get("command")
        payload_cwd = payload.get("cwd")
        if command is None:
            command = ""
        if payload_cwd is None:
            payload_cwd = ""
        if not isinstance(command, str):
            raise ValueError("Bash command must be a string")
        if not isinstance(payload_cwd, str):
            raise ValueError("hook cwd must be a string")
        if not command.strip():
            sys.exit(0)
        env_project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or ""
        if runtime not in ("claude", "codex"):
            raise ValueError("unsupported hook runtime")
        if not payload_cwd and not env_project_dir:
            raise ValueError("hook authority context is missing")
        project_dir, tier_cfg = resolve_context(
            env_project_dir,
            payload_cwd,
        )
        decision, reason = check(
            command,
            tier_cfg,
            project_dir,
            payload_cwd or env_project_dir,
        )
    except Exception as exc:  # fail CLOSED after a Bash payload is identified
        respond("deny", f"dispatcher error ({exc.__class__.__name__}) — floor unavailable; fix ~/.claude/hooks before proceeding.")
        return
    respond(decision, reason, runtime)


if __name__ == "__main__":
    main()
