#!/usr/bin/env python3
"""Harness dispatcher — the shared Claude/Codex deny floor for all tiers.

Canonical copy: agent-harness/templates/hooks/dispatch.py
Runtime copies are installed through explicit runtime-specific sync commands or
repo-owned adapters. `harness sync-global` reports drift for the global Codex copy.

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

import base64
import binascii
import codecs
import fnmatch
import json
import ntpath
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

FLOOR_VERSION = "1.4.2 (2026-07-14)"

# --- helpers ---------------------------------------------------------------

_QUOTED = re.compile(
    r"\$'(?:\\.|[^'\\])*'|\$\"(?:\\.|[^\"\\])*\"|'[^']*'|\"(?:\\.|[^\"\\])*\""
)
_CWD_REFERENCE = re.compile(
    r"(?:\$(?:\{(?:PWD|OLDPWD)\}|(?:PWD|OLDPWD)(?![A-Za-z0-9_])|"
    r"\{env:(?:PWD|OLDPWD)\}|env:(?:PWD|OLDPWD)(?![A-Za-z0-9_]))|%CD%)",
    re.IGNORECASE,
)
_LITERAL_COMMA = "__HARNESS_LITERAL_COMMA_8F3A__"
_INERT_QUOTED_PREFIX = "__HARNESS_INERT_QUOTED_31C7_"
_INVALID_INERT_QUOTED = "__HARNESS_INVALID_INERT_QUOTED__"


def has_shell_expansion_marker(value: str) -> bool:
    """Keep $ and backtick visible because escaping differs across runtimes."""
    return any(char in {"$", "`"} for char in value)


def inert_quoted_value(token: str) -> str | None:
    """Return an inert quote's shell value; None means expansion stays visible."""
    if token.startswith("$'"):
        try:
            return codecs.decode(token[2:-1], "unicode_escape")
        except (UnicodeDecodeError, ValueError):
            return _INVALID_INERT_QUOTED
    if token.startswith('$"'):
        if has_shell_expansion_marker(token[2:-1]):
            return None
        token = token[1:]
    elif token.startswith('"') and has_shell_expansion_marker(token[1:-1]):
        return None
    if token.startswith("'"):
        return token[1:-1]
    try:
        return shlex.split(token, posix=True)[0]
    except (IndexError, ValueError):
        return _INVALID_INERT_QUOTED


def inert_placeholder_prefix(text: str) -> str:
    """Choose a deterministic placeholder namespace absent from original input."""
    index = 0
    while True:
        candidate = f"{_INERT_QUOTED_PREFIX}{index}_"
        if candidate not in text:
            return candidate
        index += 1


def decode_inert_git_token(token: str, placeholders: dict[str, str]) -> str:
    """Recover only placeholders proven to originate in this inspection pass."""
    for placeholder, value in placeholders.items():
        token = token.replace(placeholder, value)
    return token


def strip_quotes(text: str) -> tuple[str, dict[str, str]]:
    """Remove INERT quoted substrings so message/body text can never trip a rule.

    Each replacement is recorded in a per-call namespace absent from the original
    command. Git structural parsing can therefore recover adjacent/mixed quoted
    fragments without treating attacker-supplied marker text as provenance.
    Double/locale-quoted text with expansion stays visible for safety scanning.
    (Semantics ported from wealthlens-hq's earned pre_tool_use hardening: the
    naive strip-all-quotes let `git commit -m "wip $(rm -rf /)"` fail open.)
    """
    prefix = inert_placeholder_prefix(text)
    placeholders: dict[str, str] = {}

    def replace(match: "re.Match[str]") -> str:
        value = inert_quoted_value(match.group(0))
        if value is None:
            return match.group(0)
        placeholder = f"{prefix}{len(placeholders)}__"
        placeholders[placeholder] = value
        return placeholder

    return _QUOTED.sub(replace, text), placeholders


def remove_shell_line_continuations(text: str) -> str:
    return re.sub(r"\\\r?\n", "", text)


def powershell_unescape(text: str) -> str:
    """Conservatively expose tokens hidden with PowerShell backtick escapes."""
    escapes = {
        "0": "\0",
        "a": "\a",
        "b": "\b",
        "e": "\x1b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
    }
    result = []
    index = 0
    while index < len(text):
        if text[index] != "`" or index + 1 >= len(text):
            result.append(text[index])
            index += 1
            continue
        next_char = text[index + 1]
        if next_char == "\r" and index + 2 < len(text) and text[index + 2] == "\n":
            index += 3
            continue
        if next_char == "\n":
            index += 2
            continue
        unicode_match = re.match(r"u\{([0-9A-Fa-f]{1,6})\}", text[index + 1 :])
        if unicode_match:
            try:
                result.append(chr(int(unicode_match.group(1), 16)))
            except ValueError:
                result.append("\ufffd")
            index += 1 + len(unicode_match.group(0))
            continue
        result.append(escapes.get(next_char.lower(), next_char))
        index += 2
    return "".join(result)


def cmd_unescape(text: str) -> str:
    """Expose cmd.exe caret-escaped command and option characters."""
    text = re.sub(r"\^(?:\r\n|\r|\n)", "", text)
    return re.sub(r"\^(.)", r"\1", text, flags=re.DOTALL)


_LITERAL_CALL_OPERATOR = re.compile(
    r"(?:^|(?<=[;|{}\n]))\s*[&.]\s*\(\s*(['\"])([A-Za-z0-9_.\\/-]+)\1\s*\)"
)


def normalize_literal_call_operators(text: str) -> str:
    """Expose PowerShell &('command') / .('command') literal invocations."""
    return _LITERAL_CALL_OPERATOR.sub(lambda match: f" {match.group(2)}", text)


def is_dynamic_value(text: str) -> bool:
    candidate = text.strip()
    return bool(
        re.fullmatch(
            r"(?:\$\{?[A-Za-z_][A-Za-z0-9_:]*\}?|%[^%]+%|![^!]+!)",
            candidate,
        )
    )


def has_dynamic_shell_token(token: str) -> bool:
    lowered = token.lower()
    if lowered.endswith(":$false") or lowered.endswith(":$true"):
        return False
    return bool(re.search(r"\$|%[^%]+%|![^!]+!|`", token))


_QUOTED_HEREDOC = re.compile(
    r"<<(?P<tabs>-)?\s*(?:'(?P<single>[^']+)'|\"(?P<double>[^\"]+)\")"
)


def inert_heredoc_receiver(prefix: str, suffix: str) -> bool:
    """Return whether a quoted heredoc is data for a known non-executing sink."""
    suffix_flow = quote_aware_segments_with_operators("true " + suffix)
    if suffix_flow and suffix_flow[0][1] == "|":
        return False
    parsed = quote_aware_segments(prefix)
    if not parsed:
        return False
    head, toks = command_head(parsed[-1])
    if head == "cat":
        return ">" not in prefix and ">" not in suffix
    if head == "git" and git_subcommand(toks) == "commit":
        return ("-F" in toks or "--file" in toks) and "-" in toks
    if head == "gh" and len(toks) >= 3 and toks[1:3] == ["pr", "create"]:
        return "--body-file" in toks and "-" in toks
    return False


def strip_quoted_heredoc_bodies(command: str) -> str:
    """Remove inert bodies whose quoted delimiter disables shell expansion."""
    lines = command.splitlines(keepends=True)
    result = []
    pending: list[tuple[str, bool, bool]] = []
    in_body: tuple[str, bool, bool] | None = None
    for line in lines:
        if in_body:
            delimiter, strip_tabs, inert = in_body
            candidate = line.rstrip("\r\n")
            if strip_tabs:
                candidate = candidate.lstrip("\t")
            if candidate == delimiter:
                result.append("\n" if inert else line)
                in_body = pending.pop(0) if pending else None
            else:
                result.append("\n" if inert else line)
            continue
        result.append(line)
        for match in _QUOTED_HEREDOC.finditer(line):
            pending.append(
                (
                    match.group("single") or match.group("double"),
                    bool(match.group("tabs")),
                    inert_heredoc_receiver(line[: match.start()], line[match.end() :]),
                )
            )
        if pending:
            in_body = pending.pop(0)
    return "".join(result)


def quote_aware_segments_with_operators(command: str) -> list[tuple[list[str], str]]:
    """Tokenize executable argv while protecting quoted operator characters.

    This preserves quoted flags and paths for policy checks without mistaking
    inert commit messages or quoted separators for additional commands.
    """
    quoted: dict[str, str] = {}

    def protect(match: "re.Match[str]") -> str:
        placeholder = f"__HARNESS_QUOTED_{len(quoted)}__"
        token = match.group(0)
        if token.startswith("$'"):
            try:
                value = codecs.decode(token[2:-1], "unicode_escape")
            except (UnicodeDecodeError, ValueError):
                value = "__HARNESS_UNRESOLVED_ANSI_C_QUOTE__"
        elif token.startswith('$"'):
            if has_shell_expansion_marker(token[2:-1]):
                value = "__HARNESS_UNRESOLVED_LOCALE_QUOTE__"
            else:
                try:
                    value = shlex.split(token[1:], posix=True)[0]
                except (IndexError, ValueError):
                    value = "__HARNESS_UNRESOLVED_LOCALE_QUOTE__"
        else:
            try:
                value = shlex.split(token, posix=True)[0]
            except (IndexError, ValueError):
                value = token[1:-1]
        value = value.replace(",", _LITERAL_COMMA)
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
    result: list[tuple[list[str], str]] = []
    current: list[str] = []
    for raw_token in raw_tokens:
        if raw_token and all(char in separators for char in raw_token):
            if current:
                result.append((current, raw_token))
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
        result.append((current, ""))
    return result


def quote_aware_segments(command: str) -> list[list[str]]:
    return [
        segment for segment, _operator in quote_aware_segments_with_operators(command)
    ]


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


def is_within_path_lexical(target: str, root: str) -> bool:
    """Containment without dereferencing symlinks, for authority ancestry only."""
    try:
        raw_target = os.path.expanduser(target.strip("\"'"))
        raw_root = os.path.expanduser(root.strip("\"'"))
        windows = bool(
            re.match(r"^[A-Za-z]:[\\/]", raw_target)
            and re.match(r"^[A-Za-z]:[\\/]", raw_root)
        )
        path_module = ntpath if windows else os.path
        canonical_target = path_module.normcase(
            path_module.normpath(path_module.abspath(raw_target))
        )
        canonical_root = path_module.normcase(
            path_module.normpath(path_module.abspath(raw_root))
        )
        return (
            path_module.commonpath([canonical_target, canonical_root]) == canonical_root
        )
    except (OSError, ValueError):
        return False


def is_same_path(left: str, right: str) -> bool:
    try:
        left_flavor, canonical_left = canonical_path(left)
        right_flavor, canonical_right = canonical_path(right)
        return left_flavor == right_flavor and canonical_left == canonical_right
    except (OSError, ValueError):
        return False


def is_safe_containment_root(root: str) -> bool:
    """Reject filesystem roots and the user home as deletion boundaries."""
    try:
        flavor, canonical_root = canonical_path(root)
        path_module = ntpath if flavor == "windows" else os.path
        if path_module.dirname(canonical_root) == canonical_root:
            return False
        if DANGEROUS_ROOTS.match(norm_path(canonical_root)):
            return False
        return not is_same_path(canonical_root, os.path.expanduser("~"))
    except (OSError, ValueError):
        return False


def is_within_project(target: str, project_dir: str) -> bool:
    return is_safe_containment_root(project_dir) and is_within_path(target, project_dir)


def is_within_temp(target: str) -> bool:
    temp_dir = tempfile.gettempdir()
    try:
        target_flavor, canonical_target = canonical_path(target)
        root_flavor, canonical_root = canonical_path(temp_dir)
        home_flavor, canonical_home = canonical_path(os.path.expanduser("~"))
    except (OSError, ValueError):
        return False
    if not is_safe_containment_root(canonical_root):
        return False
    if root_flavor == home_flavor and canonical_root == canonical_home:
        return False
    if target_flavor != root_flavor or canonical_target == canonical_root:
        return False
    path_module = ntpath if target_flavor == "windows" else os.path
    try:
        return (
            path_module.commonpath([canonical_target, canonical_root]) == canonical_root
        )
    except ValueError:
        return False


DANGEROUS_ROOTS = re.compile(
    r"^(/|~|~/|[a-zA-Z]:/?|/(?:mnt/)?[a-zA-Z]/users/[^/]+|c:/users/[^/]+)$"
)

# Env-var spellings of the home / user-profile root. Git Bash expands $HOME,
# ${HOME}, and "$HOME" to the home dir, so `rm -rf $HOME` is byte-identical in
# effect to the denied `rm -rf ~`. Matched AFTER norm_path (lowercased, trailing
# slash stripped); double-quoted "$HOME" survives strip_quotes because it holds a $.
ENV_ROOTS = re.compile(
    r'^"?(\$\{?home\}?|\$env:userprofile|%userprofile%)"?$', re.IGNORECASE
)

_SECRET_PATH = re.compile(
    r"(^|[\\/])\.env(\.[\w.]+)?$|credential|secrets?\.|id_rsa|\.pem$",
    re.IGNORECASE,
)
_SECRET_GLOB_PROBES = {
    ".env",
    ".env.local",
    "credentials.json",
    "credential.txt",
    "secret.txt",
    "secrets.json",
    "id_rsa",
    "key.pem",
}


def is_secret_path(target: str) -> bool:
    normalized = target.replace(_LITERAL_COMMA, ",").replace("\\", "/")
    if _SECRET_PATH.search(normalized):
        return True
    basename = normalized.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(probe, basename) for probe in _SECRET_GLOB_PROBES)


def token_mentions_secret_path(token: str) -> bool:
    """Return True when a shell token embeds a secret-looking path.

    Output options and language APIs commonly bind the path to punctuation
    (``of=.env``, ``-OutFile:.env``, ``WriteAllText('.env', ...)``).  Split
    those syntactic wrappers before applying the canonical path predicate.
    """
    normalized = token.replace(_LITERAL_COMMA, ",")
    candidates = [normalized]
    candidates.extend(
        part.strip("'\"[]{}() ;") for part in re.split(r"[=,:()]", normalized) if part
    )
    return any(candidate and is_secret_path(candidate) for candidate in candidates)


# git global options that consume a SEPARATE value token (git -C <dir> push ...).
# If we do not skip the value, the first non-dash token (the value) is misread as
# the subcommand and every push/reset/clean/checkout/restore rule is skipped.
_GIT_VALUE_OPTS = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--config-env",
}

# Command wrappers to skip so the REAL command head is matched (env git push …,
# nice -n 5 git …). VAR=value assignment prefixes are skipped the same way.
_WRAPPERS = {
    "env",
    "command",
    "builtin",
    "exec",
    "nice",
    "nohup",
    "time",
    "timeout",
    "ionice",
    "setsid",
    "chroot",
    "busybox",
    "toybox",
    "stdbuf",
    "xargs",
}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_EXE_SUFFIX = re.compile(r"\.(exe|cmd|bat|com|ps1)$", re.IGNORECASE)
_OPAQUE_WRAPPER = "__harness_opaque_wrapper__"


def _after_separate_value(toks: list[str], index: int) -> int | None:
    return index + 2 if index + 1 < len(toks) else None


def wrapper_command_index(name: str, toks: list[str], index: int) -> int | None:
    """Return a wrapper's executable index; None means options are opaque."""
    current = index + 1
    while current < len(toks):
        token = toks[current]
        lowered = token.lower()
        if token == "--":
            if name == "timeout":
                return current + 2 if current + 2 < len(toks) else len(toks)
            return current + 1

        if name == "env":
            if _ASSIGN.match(token):
                current += 1
                continue
            if lowered in {"-i", "--ignore-environment", "-0", "--null"}:
                current += 1
                continue
            if lowered in {"-u", "--unset"}:
                current = _after_separate_value(toks, current)
                if current is None:
                    return None
                continue
            if lowered.startswith("--unset=") or (
                lowered.startswith("-u") and len(token) > 2
            ):
                current += 1
                continue
            # These options synthesize argv or change cwd, so the execution
            # context cannot be reconstructed safely by the floor.
            if lowered in {"-c", "--chdir", "-s", "--split-string"} or any(
                lowered.startswith(prefix)
                for prefix in ("--chdir=", "--split-string=", "-c", "-s")
            ):
                return None
            if token.startswith("-"):
                return None
            return current

        if name in {"command", "builtin"}:
            if token in {"-v", "-V"}:
                return len(toks)  # lookup only; no wrapped command executes
            if token == "-p":
                current += 1
                continue
            if token.startswith("-"):
                return None
            return current

        if name == "exec":
            if token in {"-c", "-l"}:
                current += 1
                continue
            if token == "-a":
                current = _after_separate_value(toks, current)
                if current is None:
                    return None
                continue
            if token.startswith("-"):
                return None
            return current

        if name == "nice":
            if lowered in {"-n", "--adjustment"}:
                current = _after_separate_value(toks, current)
                if current is None:
                    return None
                continue
            if (
                lowered.startswith("--adjustment=")
                or re.fullmatch(r"-n[+-]?\d+", lowered)
                or re.fullmatch(r"-[+-]?\d+", lowered)
            ):
                current += 1
                continue
            if token.startswith("-"):
                return None
            return current

        if name == "nohup":
            if token.startswith("-"):
                return None
            return current

        if name == "time":
            if lowered in {
                "-p",
                "--portability",
                "-a",
                "--append",
                "-v",
                "--verbose",
                "--quiet",
                "-q",
            }:
                current += 1
                continue
            if lowered in {"-f", "--format", "-o", "--output"}:
                current = _after_separate_value(toks, current)
                if current is None:
                    return None
                continue
            if any(
                lowered.startswith(prefix)
                for prefix in ("--format=", "--output=", "-f", "-o")
            ):
                current += 1
                continue
            if token.startswith("-"):
                return None
            return current

        if name == "timeout":
            if lowered in {"--preserve-status", "--foreground", "--verbose"}:
                current += 1
                continue
            if lowered in {"-s", "--signal", "-k", "--kill-after"}:
                current = _after_separate_value(toks, current)
                if current is None:
                    return None
                continue
            if any(
                lowered.startswith(prefix)
                for prefix in ("--signal=", "--kill-after=", "-s", "-k")
            ):
                current += 1
                continue
            if token.startswith("-"):
                return None
            return current + 1 if current + 1 < len(toks) else len(toks)

        if name == "ionice":
            if token in {"-t"} or lowered in {"--ignore"}:
                current += 1
                continue
            if token in {"-c", "-n"} or lowered in {"--class", "--classdata"}:
                current = _after_separate_value(toks, current)
                if current is None:
                    return None
                continue
            if token in {"-p", "-P", "-u"} or lowered in {
                "--pid",
                "--pgid",
                "--uid",
            }:
                return None
            if any(
                token.startswith(prefix) and len(token) > 2 for prefix in ("-c", "-n")
            ) or any(
                lowered.startswith(prefix) for prefix in ("--class=", "--classdata=")
            ):
                current += 1
                continue
            if token.startswith("-"):
                return None
            return current

        if name == "setsid":
            if lowered in {"-c", "--ctty", "-f", "--fork", "-w", "--wait"}:
                current += 1
                continue
            if token.startswith("-"):
                return None
            return current

        if name == "chroot":
            return None

        if name in {"busybox", "toybox"}:
            if token.startswith("-"):
                return None
            return current

        if name == "stdbuf":
            if lowered in {"-i", "--input", "-o", "--output", "-e", "--error"}:
                current = _after_separate_value(toks, current)
                if current is None:
                    return None
                continue
            if any(
                lowered.startswith(prefix)
                for prefix in (
                    "--input=",
                    "--output=",
                    "--error=",
                    "-i",
                    "-o",
                    "-e",
                )
            ):
                current += 1
                continue
            if token.startswith("-"):
                return None
            return current

        if name == "xargs":
            if token in {"-0", "-r", "-t", "-p", "-x", "-o"} or lowered in {
                "--null",
                "--no-run-if-empty",
                "--verbose",
                "--interactive",
                "--exit",
                "--open-tty",
                "--show-limits",
            }:
                current += 1
                continue
            short_values = {"-a", "-E", "-e", "-I", "-L", "-l", "-n", "-P", "-s", "-d"}
            long_values = {
                "--arg-file",
                "--eof",
                "--replace",
                "--max-lines",
                "--max-args",
                "--max-procs",
                "--max-chars",
                "--delimiter",
            }
            if token in short_values or lowered in long_values:
                current = _after_separate_value(toks, current)
                if current is None:
                    return None
                continue
            if any(
                token.startswith(prefix) and len(token) > 2 for prefix in short_values
            ) or any(lowered.startswith(f"{option}=") for option in long_values):
                current += 1
                continue
            if token.startswith("-"):
                return None
            return current

        return None
    return len(toks)


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
        if base.startswith("microsoft.powershell."):
            for qualified_head in (
                "remove-item",
                "rename-item",
                "set-content",
                "add-content",
                "clear-content",
                "copy-item",
                "move-item",
                "out-file",
                "new-item",
            ):
                if base.endswith(qualified_head):
                    base = qualified_head
                    break
        if base in _WRAPPERS:
            next_index = wrapper_command_index(base, toks, i)
            if next_index is None:
                return _OPAQUE_WRAPPER, toks[i:]
            i = next_index
            continue
        return base, toks[i:]
    return "", []


def git_subcommand_index(toks):
    """Return the git subcommand index after global options, or None."""
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in _GIT_VALUE_OPTS:
            i += 2  # skip the option and its separate value
            continue
        if t.startswith("-"):
            i += 1  # valueless global option, or --opt=value (glued)
            continue
        return i
    return None


def git_subcommand(toks):
    """Return the normalized git subcommand after global options."""
    index = git_subcommand_index(toks)
    return toks[index].lower() if index is not None else ""


def git_inline_alias(toks: list[str], subcommand: str) -> str | None:
    """Return an inline `git -c alias.name=...` expansion for this invocation."""
    index = 1
    result = None
    while index < len(toks):
        token = toks[index]
        config_value = None
        if token == "-c" and index + 1 < len(toks):
            config_value = toks[index + 1]
            index += 2
        elif token.startswith("-c") and len(token) > 2:
            config_value = token[2:]
            index += 1
        else:
            index += 1
        if not config_value or "=" not in config_value:
            continue
        key, value = config_value.split("=", 1)
        if key.lower() == f"alias.{subcommand}".lower():
            result = value
    return result


def git_inline_configs(toks: list[str]) -> dict[str, list[str]]:
    """Return every inline git config value, preserving multi-valued keys."""
    result: dict[str, list[str]] = {}
    index = 1
    while index < len(toks):
        token = toks[index]
        config_value = None
        if token == "-c" and index + 1 < len(toks):
            config_value = toks[index + 1]
            index += 2
        elif token.startswith("-c") and len(token) > 2:
            config_value = token[2:]
            index += 1
        else:
            index += 1
        if config_value and "=" in config_value:
            key, value = config_value.split("=", 1)
            result.setdefault(key.lower(), []).append(value)
    return result


def git_config_env_keys(toks: list[str]) -> list[str] | None:
    """Return ``--config-env`` keys; None means malformed/opaque syntax."""
    keys = []
    index = 1
    while index < len(toks):
        token = toks[index]
        config_env = None
        if token == "--config-env":
            if index + 1 >= len(toks):
                return None
            config_env = toks[index + 1]
            index += 2
        elif token.startswith("--config-env="):
            config_env = token.split("=", 1)[1]
            index += 1
        else:
            index += 1
        if config_env is None:
            continue
        if "=" not in config_env:
            return None
        key, variable = config_env.split("=", 1)
        if not key or not variable:
            return None
        keys.append(key.lower())
    return keys


def has_git_config_environment(raw: list[str]) -> bool:
    """Detect per-command or inherited Git config environment injection."""
    if any(name.upper().startswith("GIT_CONFIG") for name in os.environ):
        return True
    for token in raw:
        base = _EXE_SUFFIX.sub("", token.replace("\\", "/").split("/")[-1]).lower()
        if base == "git":
            break
        assignment = _ASSIGN.match(token)
        if assignment:
            name = token.split("=", 1)[0]
            if name.upper().startswith("GIT_CONFIG"):
                return True
    return False


def is_git_config_environment_mutation(raw: list[str]) -> bool:
    """Detect shell commands that establish Git config injection state."""
    if not raw:
        return False
    first = raw[0].lower()
    if re.match(r"^\$env:git_config[a-z0-9_]*=", first, re.IGNORECASE):
        return True
    if first in {"export", "set", "setx"}:
        return any(
            re.fullmatch(r'"?git_config[a-z0-9_]*(?:=.*)?"?', token, re.IGNORECASE)
            for token in raw[1:]
        )
    if first in {"set-item", "new-item", "si", "ni"}:
        return any(
            re.match(r"^(?:env:|environment::)git_config", token, re.IGNORECASE)
            for token in raw[1:]
        )
    return False


def git_option_abbreviates(token: str, dangerous: str) -> bool:
    """Git accepts unambiguous long-option prefixes; fail closed on them."""
    option = token.split("=", 1)[0]
    return option.startswith("--") and len(option) >= 4 and dangerous.startswith(option)


_GIT_PUSH_VALUE_LONG_OPTIONS = {
    "--exec",
    "--push-option",
    "--receive-pack",
    "--recurse-submodules",
    "--repo",
}

_SHARED_BRANCH_NAMES = {
    "dev",
    "develop",
    "development",
    "main",
    "master",
    "prod",
    "production",
    "release",
    "stable",
    "staging",
    "trunk",
}


def force_with_lease_targets_shared(refspecs: list[str]) -> bool:
    """Reject lease updates whose explicit destination is shared or ambiguous."""
    for refspec in refspecs:
        candidate = refspec.lstrip("+")
        if ":" in candidate:
            _source, target = candidate.rsplit(":", 1)
        else:
            target = candidate
        target = target.removeprefix("refs/heads/").strip("/").lower()
        if (
            not target
            or target in {"@", "head"}
            or target in _SHARED_BRANCH_NAMES
            or target.startswith("release/")
        ):
            return True
    return False


def abbreviated_git_push_value_option(token: str) -> bool:
    """Return whether token is a unique prefix of a value-taking push option."""
    option = token.split("=", 1)[0]
    if not option.startswith("--") or option in _GIT_PUSH_VALUE_LONG_OPTIONS:
        return False
    matches = [
        candidate
        for candidate in _GIT_PUSH_VALUE_LONG_OPTIONS
        if candidate.startswith(option)
    ]
    return len(matches) == 1


def git_push_short_option_shape(token: str) -> tuple[str, bool]:
    """Return (flag prefix, consumes-next) for a push short-option token.

    Git permits clusters such as ``-vo value``. The value-taking ``o`` ends
    option parsing for that token; characters after it are the option value.
    """
    if len(token) < 2 or not token.startswith("-") or token.startswith("--"):
        return "", False
    cluster = token[1:]
    value_index = cluster.find("o")
    if value_index < 0:
        return cluster, False
    return cluster[:value_index], value_index == len(cluster) - 1


def git_push_recurse_mode(args: list[str]) -> str | None:
    """Return an explicit push recurse-submodules mode, if present."""
    mode = None
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--no-recurse-submodules":
            mode = "no"
            index += 1
            continue
        if token == "--recurse-submodules" and index + 1 < len(args):
            mode = args[index + 1].lower()
            index += 2
            continue
        if token.startswith("--recurse-submodules="):
            mode = token.split("=", 1)[1].lower()
        index += 1
    return mode


_GIT_CONFIG_READ_FLAGS = {
    "--get",
    "--get-all",
    "--get-regexp",
    "--get-urlmatch",
    "--list",
    "-l",
    "--get-color",
    "--get-colorbool",
}
_GIT_CONFIG_REMOVAL_FLAGS = {"--unset", "--unset-all", "--remove-section"}
_GIT_CONFIG_WRITE_ACTIONS = {
    "--add",
    "--replace-all",
    "--unset",
    "--unset-all",
    "--rename-section",
    "--remove-section",
}
_GIT_CONFIG_VALUE_OPTIONS = {
    "-f",
    "--file",
    "--blob",
    "-t",
    "--type",
    "--default",
    "--comment",
}


def git_config_option_present(tokens: list[str], option: str) -> bool:
    """Return whether config argv contains an exact or accepted long prefix."""
    return any(
        token == option or git_option_abbreviates(token, option) for token in tokens
    )


def git_config_argv_roles(args: list[str]) -> tuple[list[str], list[str]]:
    """Separate parsed options from operands without promoting option values."""
    lowered = [token.lower() for token in args]
    options: list[str] = []
    operands: list[str] = []
    index = 0
    while index < len(lowered):
        token = lowered[index]
        if token == "--":
            operands.extend(lowered[index + 1 :])
            break
        if not token.startswith("-") or token == "-":
            # Git's config parser stops option processing at the first operand.
            operands.extend(lowered[index:])
            break
        options.append(token)
        consumes_next = token in {"-f", "-t"} or (
            "=" not in token
            and any(
                token == option or git_option_abbreviates(token, option)
                for option in _GIT_CONFIG_VALUE_OPTIONS
                if option.startswith("--")
            )
        )
        index += 2 if consumes_next and index + 1 < len(lowered) else 1
    return options, operands


def protected_git_config_section(section: str) -> bool:
    """Return whether a section can alter push destinations or inject config."""
    lowered = section.lower()
    return lowered.startswith(("remote.", "url.", "includeif.")) or lowered == "include"


def dangerous_git_config_mutation(args: list[str]) -> bool:
    """Reject writes/removals that can change a later push's behavior."""
    options, operands = git_config_argv_roles(args)
    if any(
        git_config_option_present(options, action)
        for action in {"--remove-section", "--rename-section"}
    ) and any(protected_git_config_section(section) for section in operands):
        return True
    protected_index = next(
        (
            index
            for index, token in enumerate(operands)
            if re.fullmatch(r"alias\.[^.]+", token)
            or re.fullmatch(r"remote\.[^.]+\.(?:url|pushurl|push|mirror)", token)
            or re.fullmatch(r"url\..+\.(?:insteadof|pushinsteadof)", token)
            or re.fullmatch(r"include(?:if)?\..+", token)
            or token == "push.recursesubmodules"
        ),
        None,
    )
    if protected_index is None:
        return False
    protected_key = operands[protected_index]
    if any(
        git_config_option_present(options, option)
        for option in _GIT_CONFIG_REMOVAL_FLAGS
    ):
        return protected_key.startswith(("remote.", "url.", "include"))
    if any(
        git_config_option_present(options, option)
        for option in _GIT_CONFIG_WRITE_ACTIONS
    ):
        return True
    if any(
        git_config_option_present(options, option) for option in _GIT_CONFIG_READ_FLAGS
    ):
        return False
    # A lone key is the legacy read form (`git config section.key`).
    return protected_index + 1 < len(operands)


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
    cwd_changed: bool,
) -> str | None:
    """Resolve a recursive-delete operand for canonical containment checks."""
    raw = target.replace(_LITERAL_COMMA, ",")
    if cwd_changed and _CWD_REFERENCE.search(raw):
        return None
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
    if re.search(r"\$|%[^%]+%|![^!]+!|@\(", expanded):
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


def powershell_bound_value(token: str, names: set[str]) -> tuple[bool, str]:
    """Return a colon-bound PowerShell parameter value, including abbreviations."""
    if not token.startswith("-"):
        return False, ""
    name, separator, value = token.lstrip("-").partition(":")
    lowered = name.lower()
    if separator and lowered and any(full.startswith(lowered) for full in names):
        return True, value
    return False, ""


def location_transition(
    head: str,
    toks: list[str],
    command_cwd: str,
    cwd_uncertain: bool,
    cwd_changed: bool,
) -> tuple[str, bool]:
    """Resolve a static location change; dynamic/pop transitions become unknown."""
    if head in {"popd", "pop-location"}:
        return command_cwd, True
    powershell_semantics = head in {
        "push-location",
        "set-location",
        "sl",
    }
    target = None
    for token in toks[1:]:
        is_bound_path, bound_path = powershell_bound_value(
            token,
            {"path", "literalpath"},
        )
        if is_bound_path:
            target = bound_path
            break
        if token in {"--", "/d"} or token.startswith("-"):
            continue
        target = token
        break
    if (
        not target
        or re.fullmatch(r"@[A-Za-z_][A-Za-z0-9_]*", target)
        or re.fullmatch(r"[+-]\d*", target)
        or (
            re.match(r"^[A-Za-z][A-Za-z0-9_.-]+:", target)
            and not _FILESYSTEM_PROVIDER.match(target)
        )
        or ("," in target and _LITERAL_COMMA not in target)
    ):
        return command_cwd, True
    resolved = resolve_delete_operand(
        target,
        command_cwd,
        powershell_semantics=powershell_semantics,
        cwd_uncertain=cwd_uncertain,
        cwd_changed=cwd_changed,
    )
    if resolved is None:
        return command_cwd, True
    return resolved, False


def decode_powershell_command(value: str) -> str:
    """Decode PowerShell -EncodedCommand's strict Base64 UTF-16LE contract."""
    try:
        raw = base64.b64decode(value, validate=True)
        if not raw or len(raw) % 2:
            raise ValueError("encoded command has invalid UTF-16LE length")
        return raw.decode("utf-16-le")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("cannot safely decode PowerShell encoded command") from exc


def unwrap_powershell_scriptblock(script: str) -> str:
    """Expose the executable body of a simple outer PowerShell script block."""
    candidate = script.strip()
    candidate = re.sub(r"^[&.]\s*(?=\{)", "", candidate, count=1)
    if candidate.startswith("{"):
        depth = 0
        quote = None
        escaped = False
        for index, char in enumerate(candidate):
            if escaped:
                escaped = False
                continue
            if char in {"\\", "`"}:
                escaped = True
                continue
            if quote:
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    body = candidate[1:index].strip()
                    suffix = candidate[index + 1 :].strip()
                    if suffix.startswith((";", "|", "&")):
                        return f"{body} {suffix}"
                    return body
    return candidate


def recursive_delete_decision(
    head: str,
    toks: list[str],
    project_dir: str,
    command_cwd: str,
    cwd_uncertain: bool,
    cwd_changed: bool,
    complete_argv: bool,
) -> tuple[str, str] | None:
    """Check POSIX, PowerShell, and cmd recursive-delete spellings."""
    delete_heads = {"rm", "remove-item", "ri", "del", "erase", "rd", "rmdir"}
    if head in delete_heads and any(
        has_dynamic_shell_token(token) for token in toks[1:]
    ):
        return "deny", "Dynamic delete options/targets cannot be inspected safely."
    if head == "rm":

        def has_short_flag(token: str, flag: str) -> bool:
            return (
                token.startswith("-")
                and not token.startswith("--")
                and flag in token[1:].lower()
            )

        def has_long_flag(token: str, name: str) -> bool:
            if not token.startswith("--"):
                return False
            option = token[2:].partition("=")[0].lower()
            return bool(option) and name.startswith(option)

        is_recursive = any(
            has_long_flag(token, "recursive") or has_short_flag(token, "r")
            for token in toks[1:]
        )
        is_force = any(
            has_long_flag(token, "force") or has_short_flag(token, "f")
            for token in toks[1:]
        )
        targets = [t for t in toks[1:] if not t.startswith("-")]
        if is_recursive and is_force:
            if not targets:
                if complete_argv:
                    return "deny", "rm -rf with no clear target."
                return None
            decision = check_delete_targets(
                targets,
                project_dir,
                command_cwd,
                powershell_semantics=False,
                cwd_uncertain=cwd_uncertain,
                cwd_changed=cwd_changed,
                label="rm -rf",
            )
            if decision:
                return decision

    powershell_heads = delete_heads
    if head not in powershell_heads:
        return None
    if any(re.fullmatch(r"@[A-Za-z_][A-Za-z0-9_]*", token) for token in toks[1:]):
        return "deny", "Cannot safely inspect a splatted recursive-delete command."
    powershell_recurse = any(is_powershell_recurse_flag(token) for token in toks[1:])
    cmd_recurse = head in {"del", "erase", "rd", "rmdir"} and any(
        "/s" in token.lower() and bool(re.fullmatch(r"(?:/[sqf])+", token.lower()))
        for token in toks[1:]
    )
    if not (powershell_recurse or cmd_recurse):
        return None
    cmd_flags = {"/s", "/q", "/f"}
    targets = []
    for token in toks[1:]:
        is_bound_path, bound_path = powershell_bound_value(
            token,
            {"path", "literalpath"},
        )
        if is_bound_path:
            targets.extend(bound_path.split(","))
        elif (
            not token.startswith("-")
            and token.lower() not in cmd_flags
            and not re.fullmatch(r"(?:/[sqf])+", token.lower())
        ):
            targets.extend(token.split(","))
    if not any(target for target in targets) and not complete_argv:
        return None
    return check_delete_targets(
        targets,
        project_dir,
        command_cwd,
        powershell_semantics=True,
        cwd_uncertain=cwd_uncertain,
        cwd_changed=cwd_changed,
        label="recursive Remove-Item",
    )


def check_delete_targets(
    targets: list[str],
    project_dir: str,
    command_cwd: str,
    *,
    powershell_semantics: bool,
    cwd_uncertain: bool,
    cwd_changed: bool,
    label: str,
) -> tuple[str, str] | None:
    if not targets:
        return "deny", f"{label} with no clear target."
    for target in targets:
        if not target:
            return "deny", f"{label} with an empty target."
        if target == "*":
            return (
                "deny",
                f"{label} * is floor-blocked: enumerate and delete explicitly.",
            )
        if (
            cwd_changed
            and not is_absolute(target)
            and not is_within_project(command_cwd, project_dir)
        ):
            return "deny", f"{label} uses a relative target after leaving the project."
        resolved = resolve_delete_operand(
            target,
            command_cwd,
            powershell_semantics=powershell_semantics,
            cwd_uncertain=cwd_uncertain,
            cwd_changed=cwd_changed,
        )
        if resolved is None:
            return "deny", f"Cannot safely resolve {label} target: {target}"
        normalized = norm_path(resolved)
        if (
            DANGEROUS_ROOTS.match(normalized)
            or ENV_ROOTS.match(normalized)
            or is_same_path(resolved, os.path.expanduser("~"))
        ):
            return "deny", f"{label} {target}: refusing a filesystem/home root."
        if not (is_within_project(resolved, project_dir) or is_within_temp(resolved)):
            return "deny", f"{label} outside the project: {target}"
    return None


def declared_project_dirs(start_dir: str) -> list[str]:
    """Return every ancestor carrying a tier declaration, nearest first."""
    if not start_dir:
        return []
    # Keep the lexical ancestor chain. Resolving a symlinked cwd first can jump
    # outside the declaring repo and silently discard its tier authority.
    current = os.path.abspath(start_dir)
    declared = []
    while True:
        for authority_dir in (".agent-harness", ".claude"):
            tier_path = os.path.join(current, authority_dir, "tier.json")
            try:
                os.lstat(tier_path)
            except FileNotFoundError:
                continue
            else:
                declared.append(current)
                break
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


def command_output(argv: list[str], cwd: str, timeout: float = 3) -> str:
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


_REMOTE_RESOLUTION_BUDGET_SECONDS = 3.5


def command_output_before_deadline(
    command_runner,
    argv: list[str],
    cwd: str,
    deadline: float | None,
) -> str:
    """Run a resolver command without overrunning the hook's aggregate budget."""
    if deadline is None:
        return command_runner(argv, cwd)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return ""
    if command_runner is command_output:
        output = command_runner(argv, cwd, timeout=min(3, remaining))
    else:
        output = command_runner(argv, cwd)
    return output if time.monotonic() <= deadline else ""


def push_remotes(
    args: list[str],
    project_dir: str,
    git_globals: list[str] | None = None,
    command_runner=command_output,
    deadline: float | None = None,
) -> list[str]:
    """Resolve every effective destination URL for a git push."""
    remote = ""
    option_remote = ""
    value_options = (_GIT_PUSH_VALUE_LONG_OPTIONS - {"--repo"}) | {"-o"}
    i = 0
    while i < len(args):
        arg = args[i]
        if abbreviated_git_push_value_option(arg):
            return []
        if arg == "--repo" and i + 1 < len(args):
            option_remote = args[i + 1]
            i += 2
            continue
        if arg.startswith("--repo="):
            option_remote = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--":
            remote = args[i + 1] if i + 1 < len(args) else ""
            break
        _short_flags, short_consumes_next = git_push_short_option_shape(arg)
        if short_consumes_next:
            i += 2
            continue
        if arg in value_options:
            i += 2
            continue
        if arg.startswith(("--exec=", "--receive-pack=", "--push-option=")) or (
            arg.startswith("-o") and len(arg) > 2
        ):
            i += 1
            continue
        if not arg.startswith("-"):
            remote = arg
            break
        i += 1
    if not remote:
        remote = option_remote
    if not remote:
        return []
    if re.match(r"^(https?://|ssh://|git@|file://|[a-zA-Z]:[\\/]|[./~])", remote):
        return [remote]
    output = command_output_before_deadline(
        command_runner,
        [
            "git",
            *(git_globals or []),
            "remote",
            "get-url",
            "--push",
            "--all",
            remote,
        ],
        project_dir,
        deadline,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def dangerous_git_remote_mutation(args: list[str]) -> bool:
    """Reject remote-name or URL changes that can retarget a later push."""
    action = next((token.lower() for token in args if not token.startswith("-")), "")
    return action in {"add", "rename", "remove", "rm", "set-url"}


def push_remote(
    args: list[str], project_dir: str, git_globals: list[str] | None = None
) -> str:
    """Compatibility helper returning the first effective push destination."""
    remotes = push_remotes(args, project_dir, git_globals)
    return remotes[0] if remotes else ""


def github_repo_slug(remote: str) -> str:
    """Return owner/repo for a github.com remote without credentials."""
    patterns = (
        r"^(?:https?|git)://(?:[^/@]+@)?github\.com/([^/?#]+/[^/?#]+)",
        r"^ssh://(?:[^@/]+@)?github\.com[:/]([^/?#]+/[^/?#]+)",
        r"^(?:[^@/]+@)?github\.com:([^/?#]+/[^/?#]+)",
    )
    for pattern in patterns:
        match = re.match(pattern, remote.strip(), re.IGNORECASE)
        if match:
            return match.group(1).removesuffix(".git")
    return ""


def public_remote_status(
    args: list[str],
    project_dir: str,
    git_globals: list[str] | None = None,
    command_runner=command_output,
    deadline: float | None = None,
) -> tuple[bool | None, str]:
    """Classify every push destination; unknown is fail-closed to the caller."""
    if deadline is None:
        deadline = time.monotonic() + _REMOTE_RESOLUTION_BUDGET_SECONDS
    recurse_mode = git_push_recurse_mode(args)
    if recurse_mode is None:
        recurse_mode = command_output_before_deadline(
            command_runner,
            [
                "git",
                *(git_globals or []),
                "config",
                "--get",
                "--default",
                "no",
                "push.recurseSubmodules",
            ],
            project_dir,
            deadline,
        ).lower()
    if recurse_mode not in {"no", "check"}:
        return None, "unverified recursive-submodule push destinations"
    remotes = push_remotes(
        args,
        project_dir,
        git_globals,
        command_runner,
        deadline,
    )
    if not remotes:
        return None, "unresolved push remote"
    for remote in dict.fromkeys(remotes):
        normalized = remote.lower()
        if normalized.startswith("file://") or re.match(
            r"^([a-zA-Z]:[\\/]|[./~])", remote
        ):
            continue
        slug = github_repo_slug(remote)
        if not slug:
            return None, "unverified non-GitHub destination"
        visibility = command_output_before_deadline(
            command_runner,
            [
                "gh",
                "repo",
                "view",
                slug,
                "--json",
                "visibility",
                "--jq",
                ".visibility",
            ],
            project_dir,
            deadline,
        ).upper()
        if visibility == "PUBLIC":
            return True, slug
        if visibility not in {"PRIVATE", "INTERNAL"}:
            return None, slug
    return False, "approved private destinations"


def read_tier_file(path: str) -> dict:
    """Read and strictly validate one tier declaration."""
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
    if any(
        not isinstance(key, str) or type(value) is not bool
        for key, value in flags.items()
    ):
        raise ValueError("tier.json flags must map string names to booleans")
    return {"tier": tier, "flags": flags}


def load_tier(project_dir: str) -> dict:
    """Merge co-located runtime-neutral and legacy authority conservatively.

    A present but unreadable or invalid declaration is a safety failure and must
    propagate to the PRE-path fail-closed handler. During migration neither file
    may mask a stricter tier or overlay in the other.
    """
    if not project_dir:
        return {"tier": 1, "flags": {}}
    configs = []
    for authority_dir in (".agent-harness", ".claude"):
        path = os.path.join(project_dir, authority_dir, "tier.json")
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        configs.append(read_tier_file(path))
    if not configs:
        return {"tier": 1, "flags": {}}

    flags = {}
    for cfg in configs:
        for key, value in cfg["flags"].items():
            if key == "relaxed_work_loss_guards":
                continue
            flags[key] = bool(flags.get(key)) or value
    flags["relaxed_work_loss_guards"] = all(
        bool(cfg["flags"].get("relaxed_work_loss_guards")) for cfg in configs
    )
    return {"tier": max(cfg["tier"] for cfg in configs), "flags": flags}


def resolve_context(env_project_dir: str, payload_cwd: str) -> tuple[str, dict]:
    """Resolve deletion scope and the strictest applicable tier posture.

    The payload cwd anchors project containment. Tier declarations from both the
    cwd and explicit environment chains are merged so a nested or stale context
    cannot downgrade an outer T4 or tightening overlay.
    """
    payload_projects = declared_project_dirs(payload_cwd)
    env_projects = declared_project_dirs(env_project_dir)
    if payload_cwd:
        if payload_projects:
            project_dir = payload_projects[0]
        elif env_project_dir and is_within_path_lexical(payload_cwd, env_project_dir):
            project_dir = os.path.abspath(env_project_dir)
        else:
            project_dir = os.path.realpath(os.path.abspath(payload_cwd))
    elif env_project_dir:
        project_dir = (
            env_projects[0]
            if env_projects
            else os.path.realpath(os.path.abspath(env_project_dir))
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
    return [s.strip() for s in re.split(r"[;\n()`|{}]|&&", sanitized) if s.strip()]


def tokens(segment: str):
    return segment.split()


_CONTROL_PREFIXES = {
    "!",
    "if",
    "then",
    "elif",
    "else",
    "while",
    "until",
    "do",
    "{",
    "try",
    "catch",
    "finally",
    "trap",
    "function",
}
_CONTROL_ONLY = {"fi", "done", "esac", "}"}


def strip_control_prefixes(raw: list[str]) -> list[str]:
    """Expose commands nested behind shell/PowerShell control keywords."""
    result = list(raw)
    while result and result[0].lower() in _CONTROL_PREFIXES:
        result.pop(0)
    if result and result[0].lower() in _CONTROL_ONLY:
        return []
    return result


def has_download_pipe_to_shell(command: str) -> bool:
    """Recognize pipeline endpoints after path/wrapper normalization."""
    download_seen = False
    for stage, operator_after in quote_aware_segments_with_operators(command):
        stage_head, _ = command_head(stage)
        if download_seen and stage_head in {
            "sh",
            "bash",
            "zsh",
            "dash",
            "ash",
            "ksh",
            "fish",
            "csh",
            "tcsh",
            "pwsh",
            "powershell",
            "cmd",
            "source",
            ".",
            "eval",
            "iex",
            "invoke-expression",
            "python",
            "python3",
            "perl",
            "ruby",
            "php",
            "node",
            "lua",
            "r",
            "rscript",
        }:
            return True
        if stage_head in {"curl", "wget", "iwr", "irm"}:
            download_seen = True
        if operator_after not in {"|", "|&"}:
            download_seen = False
    return False


def has_pipe_to_delete(command: str) -> bool:
    """Recognize direct or shell-wrapped pipeline deletion sinks."""
    delete_heads = {"remove-item", "ri", "rm", "del", "erase", "rd", "rmdir"}
    previous_pipe = False
    for stage, operator_after in quote_aware_segments_with_operators(command):
        downstream, _ = command_head(stage)
        if previous_pipe and downstream in delete_heads:
            return True
        if (
            previous_pipe
            and downstream in {"pwsh", "powershell"}
            and any(
                token.lower().replace("\\", "/").split("/")[-1] in delete_heads
                for token in stage[1:]
            )
        ):
            return True
        previous_pipe = operator_after in {"|", "|&"}
    return False


# --- rules ------------------------------------------------------------------


def check(
    command: str,
    tier_cfg: dict,
    project_dir: str,
    command_cwd: str,
    _depth: int = 0,
    _cwd_uncertain: bool = False,
    _cwd_changed: bool = False,
    remote_resolver=public_remote_status,
    _remote_cache: dict | None = None,
    _remote_deadline: float | None = None,
):
    """Return (decision, reason). decision in {'allow', 'ask', 'deny'}."""
    if _remote_cache is None:
        _remote_cache = {}
    if _remote_deadline is None:
        _remote_deadline = time.monotonic() + _REMOTE_RESOLUTION_BUDGET_SECONDS
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

    command = strip_quoted_heredoc_bodies(remove_shell_line_continuations(command))
    unwrapped = unwrap_powershell_scriptblock(command)
    if unwrapped != command.strip():
        return check(
            unwrapped,
            tier_cfg,
            project_dir,
            command_cwd,
            _depth + 1,
            _cwd_uncertain,
            _cwd_changed,
            remote_resolver,
            _remote_cache,
            _remote_deadline,
        )
    call_normalized = normalize_literal_call_operators(command)
    if re.search(
        r"(?:^|[;|{}\n])\s*[&.]\s*(?:\$|%|!|\()",
        call_normalized,
    ):
        return "deny", "A dynamic call-operator target cannot be inspected safely."
    sanitized, inert_placeholders = strip_quotes(command)
    for full_redirect in re.finditer(r"(?:\d*|&)?>{1,2}\|?\s*(\S+)", sanitized):
        redirect_target = full_redirect.group(1).strip("'\"")
        if is_dynamic_value(redirect_target) or redirect_target.startswith("("):
            return "deny", "A dynamic redirect target cannot be inspected safely."
        if is_secret_path(redirect_target):
            return (
                "deny",
                f"Redirecting output into a secret-looking file ({redirect_target}) is floor-blocked.",
            )

    # Pipe rules run on the full sanitized text (the pipe IS the signal).
    if has_download_pipe_to_shell(command):
        return (
            "deny",
            "Piping a download straight into a shell is irreversible-by-design. Download, inspect, then run.",
        )
    if has_pipe_to_delete(command):
        return (
            "deny",
            "Piping into Remove-Item/del deletes whatever upstream matched. Enumerate first, delete explicitly.",
        )

    inspection_variants = [command]
    for normalized in (
        call_normalized,
        powershell_unescape(command),
        cmd_unescape(command),
        cmd_unescape(powershell_unescape(command)),
    ):
        if normalized not in inspection_variants:
            inspection_variants.append(normalized)
    execution_segments = []
    pass_id = 0
    for variant in inspection_variants:
        execution_segments.extend(
            (raw, True, "", operator, pass_id, index)
            for index, (raw, operator) in enumerate(
                quote_aware_segments_with_operators(variant)
            )
        )
        pass_id += 1
    execution_segments.extend(
        (tokens(segment), False, segment, "", pass_id, index)
        for index, segment in enumerate(segments(sanitized))
    )
    initial_cwd = command_cwd
    current_cwd = command_cwd
    cwd_uncertain = _cwd_uncertain
    cwd_changed = _cwd_changed
    cwd_conditionally_changed = False
    previous_pass = None
    for (
        raw,
        quote_aware,
        segment_text,
        operator_after,
        current_pass,
        segment_index,
    ) in execution_segments:
        if previous_pass is not None and current_pass != previous_pass:
            current_cwd = initial_cwd
            cwd_uncertain = _cwd_uncertain
            cwd_changed = _cwd_changed
            cwd_conditionally_changed = False
        previous_pass = current_pass
        if not raw:
            continue
        raw = strip_control_prefixes(raw)
        if not raw:
            continue
        if is_git_config_environment_mutation(raw):
            return (
                "deny",
                "Mutating Git's config-injection environment is floor-blocked.",
            )
        first_token = raw[0]
        inert_powershell_assignment = bool(
            re.match(r"^\$(?:env:)?[A-Za-z_][A-Za-z0-9_:{}]*=", first_token)
            or (
                re.match(r"^\$(?:env:)?[A-Za-z_][A-Za-z0-9_:{}]*$", first_token)
                and len(raw) > 1
                and raw[1] == "="
            )
        )
        if inert_powershell_assignment:
            continue
        compact_cmd = re.fullmatch(
            r"(?i)(rd|rmdir|del|erase)((?:/[A-Za-z]){1,4})",
            raw[0],
        )
        if compact_cmd:
            raw = (
                [compact_cmd.group(1)]
                + re.findall(
                    r"/[A-Za-z]",
                    compact_cmd.group(2),
                )
                + raw[1:]
            )
        # Normalize away wrappers / VAR=val / path + .exe so `env git`, `git.exe`,
        # `/usr/bin/git`, `sudo.exe` all resolve to their real head (bypass fix).
        head, toks = command_head(raw)
        if not toks:
            continue
        if quote_aware and re.match(r"^(?:\$|%[^%]+%$|![^!]+!$|`|\$\()", toks[0]):
            return "deny", "A dynamic executable name cannot be inspected safely."
        if any(
            marker in token
            for token in toks
            for marker in (
                "__HARNESS_UNRESOLVED_ANSI_C_QUOTE__",
                "__HARNESS_UNRESOLVED_LOCALE_QUOTE__",
            )
        ):
            return "deny", "Cannot safely decode an executable shell word."
        if head == _OPAQUE_WRAPPER:
            return "deny", "Cannot safely inspect wrapper options that alter execution."
        if head in {"eval", "iex", "invoke-expression"}:
            evaluated_args = list(toks[1:])
            if evaluated_args and evaluated_args[0] == "--":
                evaluated_args.pop(0)
            if (
                head in {"iex", "invoke-expression"}
                and evaluated_args
                and evaluated_args[0].startswith("-")
                and "command".startswith(evaluated_args[0].lstrip("-").lower())
            ):
                evaluated_args.pop(0)
            if evaluated_args:
                evaluated = " ".join(evaluated_args)
                if is_dynamic_value(evaluated):
                    return (
                        "deny",
                        "A dynamic evaluator argument cannot be inspected safely.",
                    )
                evaluated_decision = check(
                    evaluated,
                    tier_cfg,
                    project_dir,
                    current_cwd,
                    _depth + 1,
                    cwd_uncertain,
                    cwd_changed,
                    remote_resolver,
                    _remote_cache,
                    _remote_deadline,
                )
                if evaluated_decision[0] != "allow":
                    return evaluated_decision
            continue
        if head == "sudo":
            return (
                "deny",
                "sudo is blocked at the floor. If elevation is truly needed, the human runs it.",
            )
        if head in {"start", "start-process", "saps"}:
            return (
                "deny",
                "A process launcher can conceal an irreversible child command. Run the child directly.",
            )
        if head == "call":
            if len(toks) < 2 or is_dynamic_value(" ".join(toks[1:])):
                return "deny", "A dynamic cmd call target cannot be inspected safely."
            nested_decision = check(
                " ".join(toks[1:]),
                tier_cfg,
                project_dir,
                current_cwd,
                _depth + 1,
                cwd_uncertain,
                cwd_changed,
                remote_resolver,
                _remote_cache,
                _remote_deadline,
            )
            if nested_decision[0] != "allow":
                return nested_decision
        if head == "find" and any(
            token in {"-exec", "-execdir", "-delete"} for token in toks[1:]
        ):
            return (
                "deny",
                "find execution/deletion actions are opaque to the deny floor. Enumerate first.",
            )

        if head in {
            "cd",
            "chdir",
            "pushd",
            "popd",
            "push-location",
            "pop-location",
            "set-location",
            "sl",
        }:
            if not quote_aware:
                continue
            if segment_index == 0 and operator_after == "&&":
                current_cwd, cwd_uncertain = location_transition(
                    head,
                    toks,
                    current_cwd,
                    cwd_uncertain,
                    cwd_changed,
                )
                cwd_conditionally_changed = True
            else:
                cwd_uncertain = True
            cwd_changed = True

        nested_script = None
        if head == "cmd":
            for index, token in enumerate(toks[1:], start=1):
                if token.lower() in ("/c", "/k") and index + 1 < len(toks):
                    nested_script = " ".join(toks[index + 1 :])
                    break
        elif head in {"bash", "sh", "zsh", "pwsh", "powershell"}:
            for index, token in enumerate(toks[1:], start=1):
                option_text = token.lstrip("-/")
                option, separator, bound_value = option_text.partition(":")
                option = option.lower()
                is_encoded = (
                    head in {"pwsh", "powershell"}
                    and bool(option)
                    and "encodedcommand".startswith(option)
                )
                if is_encoded:
                    encoded_value = (
                        bound_value
                        if separator
                        else (toks[index + 1] if index + 1 < len(toks) else "")
                    )
                    try:
                        nested_script = decode_powershell_command(encoded_value)
                    except ValueError:
                        return (
                            "deny",
                            "Cannot safely decode PowerShell -EncodedCommand.",
                        )
                    break
                is_command = (
                    token == "-c"
                    or (
                        head in {"bash", "sh", "zsh"}
                        and bool(re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", token))
                    )
                    or (
                        head in {"pwsh", "powershell"}
                        and bool(option)
                        and "command".startswith(option)
                    )
                )
                is_command_with_args = (
                    head in {"pwsh", "powershell"}
                    and bool(option)
                    and (option == "cwa" or "commandwithargs".startswith(option))
                )
                if is_command or is_command_with_args:
                    if separator:
                        nested_script = bound_value
                    elif index + 1 < len(toks):
                        if head in {"bash", "sh", "zsh"}:
                            script_index = index + 1
                            if toks[script_index] == "--" and script_index + 1 < len(
                                toks
                            ):
                                script_index += 1
                            nested_script = toks[script_index]
                        elif is_command_with_args:
                            nested_script = toks[index + 1]
                        else:
                            nested_script = " ".join(toks[index + 1 :])
                    break
            if nested_script is None and head in {"pwsh", "powershell"}:
                default_script = " ".join(toks[1:]).strip()
                if re.match(r"^(?:[&.]\s*)?\{", default_script):
                    nested_script = default_script
        if nested_script:
            if is_dynamic_value(nested_script):
                return (
                    "deny",
                    "A dynamic nested-shell script cannot be inspected safely.",
                )
            if head == "cmd":
                nested_script = cmd_unescape(nested_script)
            elif head in {"pwsh", "powershell"}:
                nested_script = unwrap_powershell_scriptblock(nested_script)
            nested_decision = check(
                nested_script,
                tier_cfg,
                project_dir,
                current_cwd,
                _depth + 1,
                cwd_uncertain,
                cwd_changed,
                remote_resolver,
                _remote_cache,
                _remote_deadline,
            )
            if nested_decision[0] != "allow":
                return nested_decision

        # ---- git rules ----
        if head == "git":
            git_toks = [
                decode_inert_git_token(token, inert_placeholders) for token in toks
            ]
            if any(_INVALID_INERT_QUOTED in token for token in git_toks):
                return "deny", "Cannot safely recover an inert quoted Git argument."
            subcommand_index = git_subcommand_index(git_toks)
            sub = (
                git_toks[subcommand_index].lower()
                if subcommand_index is not None
                else ""
            )
            # Args AFTER the subcommand, robust to leading global options
            # (git -C <dir> push --force -> args = [--force, ...], not misaligned).
            args = (
                git_toks[subcommand_index + 1 :] if subcommand_index is not None else []
            )
            inline_configs = git_inline_configs(git_toks)
            config_env_keys = git_config_env_keys(git_toks)
            if sub == "push" and inline_configs:
                return (
                    "deny",
                    "Inline git config can conceal push execution or force semantics.",
                )
            if sub == "push" and (config_env_keys is None or config_env_keys):
                return "deny", "Git --config-env is opaque during a push."
            if sub == "push" and has_git_config_environment(raw):
                return (
                    "deny",
                    "Git config environment injection is opaque during a push.",
                )
            if sub == "config" and dangerous_git_config_mutation(args):
                return (
                    "deny",
                    "Git alias or push-destination config mutation is floor-blocked.",
                )
            if sub == "remote" and dangerous_git_remote_mutation(args):
                return "deny", "Git remote destination mutation is floor-blocked."

            alias_expansion = git_inline_alias(git_toks, sub)
            if alias_expansion is not None:
                if alias_expansion.lstrip().startswith("!"):
                    return (
                        "deny",
                        "Shell-backed git aliases are opaque to the deny floor.",
                    )
                try:
                    expanded_alias = shlex.split(alias_expansion, posix=True)
                except ValueError:
                    return "deny", "Cannot safely parse an inline git alias."
                alias_decision = check(
                    shlex.join(["git"] + expanded_alias + args),
                    tier_cfg,
                    project_dir,
                    current_cwd,
                    _depth + 1,
                    cwd_uncertain,
                    cwd_changed,
                    remote_resolver,
                    _remote_cache,
                    _remote_deadline,
                )
                if alias_decision[0] != "allow":
                    return alias_decision

            known_git_subcommands = {
                "",
                "add",
                "am",
                "apply",
                "archive",
                "bisect",
                "blame",
                "branch",
                "bundle",
                "cat-file",
                "checkout",
                "cherry",
                "cherry-pick",
                "clean",
                "clone",
                "commit",
                "config",
                "describe",
                "diff",
                "fetch",
                "for-each-ref",
                "format-patch",
                "gc",
                "grep",
                "help",
                "init",
                "log",
                "ls-files",
                "ls-remote",
                "ls-tree",
                "maintenance",
                "merge",
                "mv",
                "name-rev",
                "notes",
                "pull",
                "range-diff",
                "rebase",
                "reflog",
                "remote",
                "reset",
                "restore",
                "rev-parse",
                "revert",
                "rm",
                "shortlog",
                "show",
                "show-ref",
                "stash",
                "status",
                "submodule",
                "switch",
                "tag",
                "version",
                "whatchanged",
                "worktree",
            }
            if sub not in known_git_subcommands | {"push"}:
                return (
                    "deny",
                    "An unknown git alias/subcommand is opaque to the deny floor.",
                )

            if sub == "push":
                if any(has_dynamic_shell_token(token) for token in args):
                    return (
                        "deny",
                        "Dynamic git-push options/refspecs cannot be inspected safely.",
                    )
                if any(abbreviated_git_push_value_option(token) for token in args):
                    return (
                        "deny",
                        "An abbreviated value-taking git-push option is floor-blocked.",
                    )
                recurse_mode = git_push_recurse_mode(args)
                if sensitive and recurse_mode in {"on-demand", "only"}:
                    return (
                        "deny",
                        "sensitive_data repo: recursive submodule pushes have additional destinations.",
                    )
                lease_requested = False
                for t in args:
                    short_flags, _short_consumes_next = git_push_short_option_shape(t)
                    dangerous_options = {
                        "--force",
                        "--force-with-lease",
                        "--delete",
                        "--mirror",
                        "--prune",
                    }
                    if t not in dangerous_options and any(
                        git_option_abbreviates(t, dangerous)
                        for dangerous in dangerous_options
                    ):
                        return (
                            "deny",
                            "An abbreviated destructive git-push option is floor-blocked.",
                        )
                    if t == "--force" or (t.startswith("--force=")):
                        return (
                            "deny",
                            "Force-push rewrites shared history. Use --force-with-lease on your own branch, or merge instead.",
                        )
                    if t == "--force-with-lease" or t.startswith("--force-with-lease="):
                        if strict:
                            return (
                                "deny",
                                "T4/wave: no force variants at all — other work rides on these refs.",
                            )
                        lease_requested = True
                        continue
                    if "f" in short_flags:
                        return (
                            "deny",
                            "git push -f is a force-push. Use --force-with-lease on your own branch, or merge instead.",
                        )
                    if t.startswith("+") and len(t) > 1:
                        return "deny", "A +refspec is a forced update in disguise."
                    if t.startswith(":") and len(t) > 1:
                        return "deny", "A :refspec deletes a remote ref."
                    if t in {"--mirror", "--prune", "--delete"} or ("d" in short_flags):
                        return (
                            "deny",
                            "Mirroring or deleting remote refs is floor-blocked.",
                        )

                push_value_options = _GIT_PUSH_VALUE_LONG_OPTIONS | {"-o"}
                positionals = []
                index = 0
                while index < len(args):
                    token = args[index]
                    if token == "--":
                        positionals.extend(args[index + 1 :])
                        break
                    if token in push_value_options:
                        index += 2
                        continue
                    if token.startswith("--repo="):
                        index += 1
                        continue
                    _short_flags, short_consumes_next = git_push_short_option_shape(
                        token
                    )
                    if short_consumes_next:
                        index += 2
                        continue
                    if token.startswith("--") or (
                        token.startswith("-") and len(token) > 1
                    ):
                        index += 1
                        continue
                    positionals.append(token)
                    index += 1
                explicit_selector = any(token in {"--all", "--tags"} for token in args)
                if len(positionals) < 2 and not explicit_selector:
                    return (
                        "deny",
                        "A git push without an explicit refspec can inherit opaque config.",
                    )
                if lease_requested and (
                    explicit_selector
                    or force_with_lease_targets_shared(positionals[1:])
                ):
                    return (
                        "deny",
                        "Force-with-lease is allowed only for an explicit non-shared feature branch.",
                    )
                if sensitive:
                    if cwd_uncertain:
                        return (
                            "deny",
                            "sensitive_data repo: cannot verify push destination after an uncertain cwd transition.",
                        )
                    resolver_key = (
                        tuple(args),
                        current_cwd,
                        tuple(git_toks[1:subcommand_index]),
                    )
                    if resolver_key not in _remote_cache:
                        resolver_args = (
                            args,
                            current_cwd,
                            git_toks[1:subcommand_index],
                        )
                        if (
                            getattr(remote_resolver, "func", remote_resolver)
                            is public_remote_status
                        ):
                            _remote_cache[resolver_key] = remote_resolver(
                                *resolver_args,
                                deadline=_remote_deadline,
                            )
                        else:
                            _remote_cache[resolver_key] = remote_resolver(
                                *resolver_args
                            )
                    is_public, remote = _remote_cache[resolver_key]
                    if is_public is True:
                        return (
                            "deny",
                            f"sensitive_data repo: refusing a push to public remote {remote}.",
                        )
                    if is_public is None:
                        return (
                            "deny",
                            f"sensitive_data repo: could not verify push remote privacy ({remote}).",
                        )

            if sub == "reset" and "--hard" in args:
                if strict:
                    return (
                        "deny",
                        "T4/wave: hard reset discards work that may not be yours. Inspect state; ask.",
                    )
                if tier >= 3 and not relaxed:
                    return (
                        "ask",
                        "T3: git reset --hard discards uncommitted work. Confirm you want this.",
                    )

            if sub == "clean" and any(
                t == "--force" or bool(re.match(r"^-[a-zA-Z]*f", t)) for t in args
            ):
                if strict:
                    return (
                        "deny",
                        "T4/wave: git clean -f deletes untracked files that may belong to another agent.",
                    )
                if tier >= 3 and not relaxed:
                    return "ask", "T3: git clean -f deletes untracked files. Confirm."

            if sub == "checkout" and "--" in args:
                after = args[args.index("--") + 1 :]
                if "." in after:
                    if strict:
                        return (
                            "deny",
                            "T4/wave: checkout -- . wipes all local modifications.",
                        )
                    if tier >= 3 and not relaxed:
                        return (
                            "ask",
                            "T3: checkout -- . wipes local modifications. Confirm.",
                        )

            if sub == "restore" and "." in args and "--staged" not in args:
                if strict:
                    return (
                        "deny",
                        "T4/wave: git restore . wipes all local modifications.",
                    )
                if tier >= 3 and not relaxed:
                    return (
                        "ask",
                        "T3: git restore . wipes local modifications. Confirm.",
                    )

        delete_decision = recursive_delete_decision(
            head,
            toks,
            project_dir,
            current_cwd,
            cwd_uncertain,
            cwd_changed,
            quote_aware,
        )
        if delete_decision:
            return delete_decision

        # ---- secret-file mutation ----
        secret_mutators = {
            "rm",
            "del",
            "erase",
            "remove-item",
            "ri",
            "mv",
            "move",
            "move-item",
            "mi",
            "rename-item",
            "ren",
            "rni",
            "cp",
            "copy",
            "copy-item",
            "ci",
            "set-content",
            "sc",
            "add-content",
            "ac",
            "clear-content",
            "clc",
            "out-file",
            "tee",
            "tee-object",
            "touch",
            "truncate",
            "new-item",
            "ni",
            "unlink",
        }
        if head in secret_mutators:
            if any(token.startswith("@") for token in toks[1:]):
                return (
                    "deny",
                    "Array/splatted secret-mutation targets cannot be inspected safely.",
                )
            explicit_paths = []
            positional_groups = []
            index = 1
            path_parameters = {"path", "literalpath", "filepath", "destination"}
            while index < len(toks):
                token = toks[index]
                is_bound_path, bound_path = powershell_bound_value(
                    token,
                    path_parameters,
                )
                if is_bound_path:
                    explicit_paths.append(bound_path)
                    index += 1
                    continue
                if token.startswith("-"):
                    parameter = token.lstrip("-").lower()
                    if parameter and any(
                        name.startswith(parameter) for name in path_parameters
                    ):
                        if index + 1 < len(toks):
                            explicit_paths.append(toks[index + 1])
                            index += 2
                            continue
                    if head in {
                        "set-content",
                        "sc",
                        "add-content",
                        "ac",
                        "out-file",
                        "tee",
                        "tee-object",
                    } and parameter in {
                        "value",
                        "inputobject",
                        "encoding",
                        "filter",
                        "include",
                        "exclude",
                    }:
                        index += 2
                        continue
                    index += 1
                    continue
                if token.lower() not in {"/s", "/q", "/f"}:
                    positional_groups.append(token.split(","))
                index += 1

            positional = [item for group in positional_groups for item in group]
            if head in {
                "set-content",
                "sc",
                "add-content",
                "ac",
                "clear-content",
                "clc",
                "out-file",
                "tee-object",
                "new-item",
                "ni",
            }:
                mutation_targets = explicit_paths or (
                    positional_groups[0] if positional_groups else []
                )
            elif head == "tee":
                mutation_targets = explicit_paths + positional
            else:
                mutation_targets = explicit_paths + positional
            for target in mutation_targets:
                if is_dynamic_value(target) or target.startswith("("):
                    return (
                        "deny",
                        "A dynamic secret-mutation target cannot be inspected safely.",
                    )
                if is_secret_path(target):
                    return (
                        "deny",
                        f"Mutating a secret-looking file ({target}) is floor-blocked. The human manages secrets.",
                    )

        # Common output/mutation tools whose destination syntax differs from
        # the filesystem mutators above. This remains a bounded parser
        # contract; unfamiliar writers are covered by follow-up hardening and
        # OS/runtime permissions, not by claiming this hook is a shell sandbox.
        if head == "dd" and any(
            token.lower().startswith("of=") and token_mentions_secret_path(token)
            for token in toks[1:]
        ):
            return "deny", "dd output to a secret-looking file is floor-blocked."
        if (
            head in {"sed", "gsed"}
            and any(
                token == "-i" or token.startswith(("-i", "--in-place"))
                for token in toks[1:]
            )
            and any(token_mentions_secret_path(token) for token in toks[1:])
        ):
            return "deny", "In-place editing of a secret-looking file is floor-blocked."
        if head == "install" and any(
            token_mentions_secret_path(token) for token in toks[1:]
        ):
            return "deny", "Installing over a secret-looking file is floor-blocked."
        if head in {"curl", "wget", "iwr", "invoke-webrequest"}:
            output_flags = {
                "-o",
                "--output",
                "--output-document",
                "-outfile",
                "outfile",
            }
            for index, token in enumerate(toks[1:], start=1):
                lowered = token.lower()
                bound_output = lowered.startswith(
                    ("--output=", "--output-document=", "-outfile:")
                ) or (lowered.startswith("-o") and len(token) > 2 and head == "curl")
                if bound_output and token_mentions_secret_path(token):
                    return (
                        "deny",
                        "Downloading into a secret-looking file is floor-blocked.",
                    )
                if lowered in output_flags and index + 1 < len(toks):
                    target = toks[index + 1]
                    if is_dynamic_value(target) or target.startswith("("):
                        return (
                            "deny",
                            "A dynamic download destination cannot be inspected safely.",
                        )
                    if token_mentions_secret_path(target):
                        return (
                            "deny",
                            "Downloading into a secret-looking file is floor-blocked.",
                        )
        if head == "export-clixml" and any(
            token_mentions_secret_path(token) for token in toks[1:]
        ):
            return "deny", "Serializing into a secret-looking file is floor-blocked."
        if (
            ("::" in head or head.startswith("["))
            and re.search(
                r"(?i)(?:writealltext|writeallbytes|appendalltext|create|delete|move|copy)",
                head,
            )
            and token_mentions_secret_path(" ".join(toks))
        ):
            return "deny", "A file API write to a secret-looking path is floor-blocked."
        if quote_aware:
            for index, token in enumerate(raw[:-1]):
                if token in (">", ">>") and is_secret_path(raw[index + 1]):
                    return (
                        "deny",
                        f"Redirecting output into a secret-looking file ({raw[index + 1]}) is floor-blocked.",
                    )
        else:
            redir = re.search(r"(?:\d*|&)?>{1,2}\|?\s*(\S+)", segment_text)
            if redir and is_secret_path(redir.group(1)):
                return (
                    "deny",
                    f"Redirecting output into a secret-looking file ({redir.group(1)}) is floor-blocked.",
                )

        # ---- sensitive_data overlay ----
        if sensitive and head == "gh":
            if len(toks) >= 3 and toks[1] in ("repo", "gist") and toks[2] == "create":
                if any(t in ("--public", "-p") for t in toks):
                    return (
                        "deny",
                        "sensitive_data repo: creating PUBLIC repos/gists is blocked.",
                    )
            if len(toks) >= 3 and toks[1:3] == ["repo", "edit"]:
                if any(
                    token.lower() == "--visibility=public"
                    or (
                        token.lower() == "public"
                        and index > 0
                        and toks[index - 1].lower() == "--visibility"
                    )
                    for index, token in enumerate(toks)
                ):
                    return (
                        "deny",
                        "sensitive_data repo: PUBLIC visibility changes are blocked.",
                    )
            if len(toks) >= 2 and toks[1] == "api":
                method = None
                has_fields = False
                for index, token in enumerate(toks[2:], start=2):
                    lowered = token.lower()
                    if lowered in {"-x", "--method"} and index + 1 < len(toks):
                        method = toks[index + 1].upper()
                    elif lowered.startswith("-x") and len(token) > 2:
                        method = token[2:].lstrip("=").upper()
                    elif lowered.startswith("--method="):
                        method = token.split("=", 1)[1].upper()
                    elif lowered in {"-f", "-F", "--raw-field", "--field", "--input"}:
                        has_fields = True
                    elif lowered.startswith(("--raw-field=", "--field=", "--input=")):
                        has_fields = True
                if (method and method != "GET") or (method is None and has_fields):
                    return (
                        "deny",
                        "sensitive_data repo: arbitrary gh api mutations are blocked.",
                    )

        if cwd_conditionally_changed and operator_after != "&&":
            cwd_uncertain = True

    return "allow", ""


# --- entry ------------------------------------------------------------------


def respond(decision: str, reason: str, runtime: str = "claude"):
    if runtime == "codex" and decision == "ask":
        decision = "deny"
        reason = f"Codex does not support ask decisions; conservative deny. {reason}"
    if decision == "allow":
        sys.exit(0)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": f"[floor {FLOOR_VERSION}] {reason}",
                }
            }
        )
    )
    sys.exit(0)


def main():
    event = "pre"
    runtime = "claude"
    if "--event" in sys.argv:
        try:
            event = sys.argv[sys.argv.index("--event") + 1]
        except IndexError:
            pass
    runtime_options = [
        token
        for token in sys.argv[1:]
        if token == "--runtime" or token.startswith("--runtime=")
    ]
    if len(runtime_options) > 1:
        runtime = "invalid"
    elif runtime_options and runtime_options[0].startswith("--runtime="):
        runtime = runtime_options[0].split("=", 1)[1].lower() or "invalid"
    elif runtime_options:
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
        if payload_cwd and not os.path.isabs(payload_cwd):
            raise ValueError("hook cwd must be an absolute path")
        if env_project_dir and not os.path.isabs(env_project_dir):
            raise ValueError("CLAUDE_PROJECT_DIR must be an absolute path")
        if (
            payload_cwd
            and os.path.exists(payload_cwd)
            and not os.path.isdir(payload_cwd)
        ):
            raise ValueError("hook cwd must be a directory")
        if (
            env_project_dir
            and os.path.exists(env_project_dir)
            and not os.path.isdir(env_project_dir)
        ):
            raise ValueError("CLAUDE_PROJECT_DIR must be a directory")
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
        respond(
            "deny",
            f"dispatcher error ({exc.__class__.__name__}) — floor unavailable; fix the installed dispatcher before proceeding.",
            runtime,
        )
        return
    respond(decision, reason, runtime)


if __name__ == "__main__":
    main()
