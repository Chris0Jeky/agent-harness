#!/usr/bin/env python3
"""Harness dispatcher — the shared Claude/Codex deny floor for all tiers.

Canonical copy: agent-harness/templates/hooks/dispatch.py
Runtime copies are installed through explicit sync commands or repo-owned adapters.
`harness sync-global` installs the shared bytes; Codex wiring remains project-local.

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

FLOOR_VERSION = "1.4.6 (2026-07-14)"

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
_LITERAL_OPEN_BRACE = "__HARNESS_LITERAL_OPEN_BRACE_2D91__"
_LITERAL_CLOSE_BRACE = "__HARNESS_LITERAL_CLOSE_BRACE_2D91__"
_INERT_QUOTED_PREFIX = "__HARNESS_INERT_QUOTED_31C7_"
_INVALID_INERT_QUOTED = "__HARNESS_INVALID_INERT_QUOTED__"
_QUOTED_GROUP_LITERAL_PREFIX = "__HARNESS_QUOTED_GROUP_LITERAL__"


def restore_quoted_literal_markers(value: str) -> str:
    """Restore punctuation protected from shell expansion analysis."""
    return (
        value.replace(_LITERAL_COMMA, ",")
        .replace(_LITERAL_OPEN_BRACE, "{")
        .replace(_LITERAL_CLOSE_BRACE, "}")
    )


def has_shell_expansion_marker(value: str) -> bool:
    """Keep $ and backtick visible because escaping differs across runtimes."""
    return any(char in {"$", "`"} for char in value)


def has_cmd_expansion_marker(value: str) -> bool:
    """Return whether cmd.exe can expand an environment reference."""
    return bool(re.search(r"%[^%]+%|![^!]+!", value))


def boolean_flag_is_true(token: str, names: set[str]) -> bool:
    """Recognize Go/strconv boolean spellings accepted by GitHub CLI flags."""
    lowered = token.lower()
    for name in names:
        if lowered == name:
            return True
        if lowered.startswith(f"{name}="):
            return lowered.split("=", 1)[1] in {"1", "t", "true"}
    return False


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
        token = match.group(0)
        if (
            token.startswith('"')
            and has_cmd_expansion_marker(token[1:-1])
            and re.search(r"(?:\d*|&)?>{1,2}(?:\||&)?\s*$", text[: match.start()])
        ):
            return token
        value = inert_quoted_value(token)
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


_CMD_NESTED_COMMAND = re.compile(
    r"^(?:/(?:d|q|a|u|s|e:(?:on|off)|f:(?:on|off)|v:(?:on|off)|"
    r"t:[0-9a-f]{2}))*/(?P<mode>[ck])(?P<tail>.*)$",
    re.IGNORECASE,
)


def cmd_nested_script(toks: list[str]) -> tuple[bool, str | None]:
    """Decode cmd.exe setup-switch clusters ending in /c or /k."""
    for index, token in enumerate(toks[1:], start=1):
        match = _CMD_NESTED_COMMAND.fullmatch(token)
        if match is None:
            continue
        tail = match.group("tail")
        parts = ([tail] if tail else []) + toks[index + 1 :]
        return True, " ".join(parts) or None
    return False, None


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


_POWERSHELL_TYPE_PREFIX = re.compile(r"^(?:\[[^\[\]\r\n]+\])+")


def powershell_assignment_rhs(raw: list[str]) -> str | None:
    """Return a PowerShell assignment RHS; None means this is not an assignment."""
    if not raw:
        return None
    parts = list(raw)
    while parts and re.fullmatch(r"\[[^\[\]\r\n]+\]", parts[0]):
        parts.pop(0)
    if not parts:
        return None
    parts[0] = _POWERSHELL_TYPE_PREFIX.sub("", parts[0])
    attached = re.fullmatch(r"\$(?:env:)?[A-Za-z_][A-Za-z0-9_:{}]*=(.*)", parts[0])
    if attached:
        rhs_parts = [attached.group(1), *parts[1:]]
        return " ".join(part for part in rhs_parts if part)
    if (
        len(parts) > 1
        and parts[1] == "="
        and re.fullmatch(r"\$(?:env:)?[A-Za-z_][A-Za-z0-9_:{}]*", parts[0])
    ):
        return " ".join(parts[2:])
    return None


def inert_powershell_scriptblock(value: str) -> bool:
    """A bare scriptblock assigned as data is not executed by PowerShell."""
    candidate = value.strip()
    return candidate.startswith("{") and candidate.endswith("}")


_POWERSHELL_SCRIPTBLOCK_ASSIGNMENT = re.compile(
    r"(?i)(?:\[[^\[\]\r\n]+\]\s*)*" r"\$(?:env:)?[A-Za-z_][A-Za-z0-9_:{}]*\s*=\s*\{"
)


def mask_inert_powershell_assignment_scriptblocks(command: str) -> str:
    """Hide assigned scriptblock bodies while retaining later invocations."""
    result = []
    cursor = 0
    while True:
        match = _POWERSHELL_SCRIPTBLOCK_ASSIGNMENT.search(command, cursor)
        if match is None:
            result.append(command[cursor:])
            break
        opening = match.end() - 1
        depth = 1
        closing = opening + 1
        while closing < len(command) and depth:
            if command[closing] == "{":
                depth += 1
            elif command[closing] == "}":
                depth -= 1
            closing += 1
        if depth:
            result.append(command[cursor:])
            break
        suffix = closing
        while suffix < len(command) and command[suffix].isspace():
            suffix += 1
        if suffix < len(command) and command[suffix] not in ";|&\r\n":
            result.append(command[cursor:closing])
            cursor = closing
            continue
        result.append(command[cursor : opening + 1])
        result.append("__HARNESS_INERT_SCRIPTBLOCK__")
        result.append("}")
        cursor = closing
    return "".join(result)


def has_dynamic_shell_token(token: str) -> bool:
    lowered = token.lower()
    if lowered.endswith(":$false") or lowered.endswith(":$true"):
        return False
    return bool(re.search(r"\$|%[^%]+%|![^!]+!|`", token))


def powershell_start_process_command(toks: list[str]) -> tuple[str | None, str]:
    """Recover a bounded literal Start-Process child command."""
    parameters = {
        "argumentlist": "arguments",
        "filepath": "path",
        "loaduserprofile": "switch",
        "nonewwindow": "switch",
        "passthru": "switch",
        "usenewenvironment": "switch",
        "wait": "switch",
        "windowstyle": "value",
    }
    opaque_parameters = {
        "credential",
        "environment",
        "redirectstandarderror",
        "redirectstandardinput",
        "redirectstandardoutput",
        "verb",
        "workingdirectory",
    }

    def parameter_name(token: str) -> tuple[str | None, str | None]:
        raw = token.lstrip("-")
        name, separator, attached = raw.partition(":")
        matches = [
            candidate
            for candidate in parameters.keys() | opaque_parameters
            if candidate.startswith(name.lower())
        ]
        if len(matches) != 1:
            return None, None
        return matches[0], attached if separator else None

    def argument_parts(value: str) -> list[str] | None:
        parts = [
            restore_quoted_literal_markers(part) for part in value.split(",") if part
        ]
        if any(re.search(r"\s", part) for part in parts):
            return None
        return parts

    executable = None
    child_args: list[str] = []
    index = 1
    while index < len(toks):
        token = toks[index]
        if token.startswith("@") or has_dynamic_shell_token(token):
            return (
                None,
                "Dynamic or splatted Start-Process arguments cannot be inspected safely.",
            )
        if token.startswith("-"):
            name, attached = parameter_name(token)
            if name is None:
                return (
                    None,
                    "An unknown or ambiguous Start-Process parameter is opaque.",
                )
            if name in opaque_parameters:
                return (
                    None,
                    f"Start-Process -{name} changes child execution outside floor inspection.",
                )
            kind = parameters[name]
            if kind == "switch":
                if attached not in {None, "true", "false", "$true", "$false"}:
                    return None, "A bound Start-Process switch value is opaque."
                index += 1
                continue
            if attached is None:
                if index + 1 >= len(toks):
                    return None, f"Start-Process -{name} is missing its value."
                attached = toks[index + 1]
                index += 2
            else:
                index += 1
            if (
                not attached
                or attached.startswith(("@", "("))
                or has_dynamic_shell_token(attached)
            ):
                return None, f"Start-Process -{name} has an opaque value."
            if kind == "path":
                if executable is not None:
                    return None, "Start-Process has multiple executable paths."
                executable = attached
            elif kind == "arguments":
                parts = argument_parts(attached)
                if parts is None:
                    return (
                        None,
                        "Whitespace-bearing Start-Process arguments cannot be reconstructed safely.",
                    )
                child_args.extend(parts)
            continue
        if executable is None:
            executable = token
        else:
            parts = argument_parts(token)
            if parts is None:
                return (
                    None,
                    "Whitespace-bearing Start-Process arguments cannot be reconstructed safely.",
                )
            child_args.extend(parts)
        index += 1
    if not executable:
        return None, "Start-Process has no literal executable path."
    return shlex.join([executable, *child_args]), ""


_DOWNLOADER_CLUSTER_PREFIXES = {
    # Short switches in these sets take no value, so a later output switch in
    # the same argv token still owns the remaining suffix.
    "curl": frozenset("aqfGgI0k46jlLMnNZ#pJORSis231BvV"),
    "wget": frozenset("VhbdqvFncNS46xErkKmpHL"),
}


def downloader_output_binding(head: str, token: str) -> tuple[str | None, str | None]:
    """Return a clustered downloader output switch and its attached value."""
    if not token.startswith("-") or token.startswith("--"):
        return None, None
    markers = {"o", "c", "D"} if head == "curl" else {"o", "O", "a"}
    prefix_flags = _DOWNLOADER_CLUSTER_PREFIXES.get(head)
    if prefix_flags is None:
        return None, None
    body = token[1:]
    for index, character in enumerate(body):
        if character in markers:
            return character, body[index + 1 :] or None
        if character not in prefix_flags:
            return None, None
    return None, None


def curl_uses_remote_name(token: str) -> bool:
    """Return whether a curl short-option cluster enables remote-name output."""
    if not token.startswith("-") or token.startswith("--"):
        return token == "--remote-name"
    for character in token[1:]:
        if character == "O":
            return True
        if character not in _DOWNLOADER_CLUSTER_PREFIXES["curl"]:
            return False
    return False


_QUOTED_HEREDOC = re.compile(
    r"<<(?P<tabs>-)?\s*(?:'(?P<single>[^']+)'|\"(?P<double>[^\"]+)\")"
)


def inert_heredoc_receiver(prefix: str, suffix: str) -> bool:
    """Return whether a quoted heredoc is data for a known non-executing sink."""
    suffix_flow = quote_aware_segments_with_operators("true " + suffix)
    if suffix_flow and suffix_flow[0][1] in {"|", "|&"}:
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
        if len(value) >= 2 and (value[0], value[-1]) in {("(", ")"), ("{", "}")}:
            value = f"{_QUOTED_GROUP_LITERAL_PREFIX}{value}"
        value = (
            value.replace(",", _LITERAL_COMMA)
            .replace("{", _LITERAL_OPEN_BRACE)
            .replace("}", _LITERAL_CLOSE_BRACE)
        )
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
    normalized = restore_quoted_literal_markers(target).replace("\\", "/")
    if _SECRET_PATH.search(normalized):
        return True
    basename = normalized.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(probe, basename) for probe in _SECRET_GLOB_PROBES)


_BRACE_SEQUENCE = re.compile(
    r"\{(?P<start>[A-Za-z]|-?\d+)\.\.(?P<end>[A-Za-z]|-?\d+)"
    r"(?:\.\.(?P<step>-?\d+))?\}"
)


def brace_sequence_alternatives(match: "re.Match[str]") -> list[str] | None:
    """Expand one bounded Bash alpha/numeric sequence; None means fail closed."""
    start_text = match.group("start")
    end_text = match.group("end")
    if start_text.isalpha() != end_text.isalpha():
        return []
    supplied_step = int(match.group("step") or "1")
    if supplied_step == 0:
        return None
    start = ord(start_text) if start_text.isalpha() else int(start_text)
    end = ord(end_text) if end_text.isalpha() else int(end_text)
    step = abs(supplied_step) if start <= end else -abs(supplied_step)
    stop = end + (1 if step > 0 else -1)
    values = list(range(start, stop, step))
    if len(values) > 64:
        return None
    if start_text.isalpha():
        return [chr(value) for value in values]
    width = max(len(start_text.lstrip("-")), len(end_text.lstrip("-")))
    zero_padded = start_text.lstrip("-").startswith("0") or end_text.lstrip(
        "-"
    ).startswith("0")
    if not zero_padded:
        return [str(value) for value in values]
    return [f"{value:0{width}d}" for value in values]


def brace_expansion_mentions_secret_path(token: str) -> bool:
    """Expand bounded, unquoted Bash comma/sequence braces on destinations."""
    variants = [token]
    expanded = False
    while True:
        next_variants = []
        changed = False
        for variant in variants:
            comma_match = re.search(r"\{([^{}]*,[^{}]*)\}", variant)
            sequence_match = _BRACE_SEQUENCE.search(variant)
            matches = [match for match in (comma_match, sequence_match) if match]
            if not matches:
                next_variants.append(variant)
                continue
            match = min(matches, key=lambda candidate: candidate.start())
            changed = True
            expanded = True
            alternatives = (
                match.group(1).split(",")
                if match is comma_match
                else brace_sequence_alternatives(match)
            )
            if alternatives is None:
                return True
            if len(next_variants) + len(alternatives) > 64:
                return True
            next_variants.extend(
                variant[: match.start()] + alternative + variant[match.end() :]
                for alternative in alternatives
            )
        variants = next_variants
        if not changed:
            break
    return expanded and any(is_secret_path(variant) for variant in variants)


def token_mentions_secret_path(token: str) -> bool:
    """Return True when a shell token embeds a secret-looking path.

    Output options and language APIs commonly bind the path to punctuation
    (``of=.env``, ``-OutFile:.env``, ``WriteAllText('.env', ...)``).  Split
    those syntactic wrappers before applying the canonical path predicate.
    """
    if brace_expansion_mentions_secret_path(token):
        return True
    literal_comma = _LITERAL_COMMA in token
    normalized = restore_quoted_literal_markers(token)
    candidates = [normalized]
    wrapper_pattern = r"[=:()]" if literal_comma else r"[=,:()]"
    candidates.extend(
        part.strip("'\"[]{}() ;")
        for part in re.split(wrapper_pattern, normalized)
        if part
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
        executable = t.lstrip("({").rstrip(")}")
        if not executable:
            i += 1
            continue
        base = _EXE_SUFFIX.sub("", executable.replace("\\", "/").split("/")[-1]).lower()
        if base.startswith("git-") and len(base) > len("git-"):
            return "git", ["git", base[len("git-") :], *toks[i + 1 :]]
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


def git_option_values(
    args: list[str], long_option: str, short_options: set[str] | None = None
) -> list[str | None]:
    """Return values for a Git option, including attached/abbreviated spellings."""
    short_options = short_options or set()
    values: list[str | None] = []
    index = 0
    while index < len(args):
        token = args[index]
        lowered = token.lower()
        if token == "--":
            break
        option_name, separator, attached = lowered.partition("=")
        if option_name == long_option or git_option_abbreviates(
            option_name, long_option
        ):
            if separator:
                values.append(attached)
                index += 1
            else:
                values.append(args[index + 1] if index + 1 < len(args) else None)
                index += 2
            continue
        matched_short = next(
            (short for short in short_options if lowered.startswith(short)), None
        )
        if matched_short is None:
            index += 1
            continue
        if lowered == matched_short:
            values.append(args[index + 1] if index + 1 < len(args) else None)
            index += 2
        else:
            values.append(token[len(matched_short) :].lstrip("=") or None)
            index += 1
    return values


def git_option_is_present(
    args: list[str], long_option: str, short_options: set[str] | None = None
) -> bool:
    return bool(git_option_values(args, long_option, short_options))


_BUILTIN_GIT_MERGE_STRATEGIES = {
    "octopus",
    "ort",
    "ours",
    "recursive",
    "resolve",
    "subtree",
}


def dangerous_git_process_launcher(subcommand: str, args: list[str]) -> str | None:
    """Return a reason when Git argv can select an arbitrary child process."""
    if subcommand in {"clone", "fetch", "ls-remote", "pull"} and (
        git_option_is_present(
            args,
            "--upload-pack",
            {"-u"} if subcommand == "clone" else None,
        )
    ):
        return "A custom git upload-pack program can execute outside floor inspection."
    if subcommand == "archive" and git_option_is_present(args, "--exec"):
        return "A custom git archive program can execute outside floor inspection."
    if subcommand == "rebase" and git_option_is_present(args, "--exec", {"-x"}):
        return "A git rebase exec command is opaque to floor inspection."
    if subcommand == "bisect" and args and args[0].lower() == "run":
        return "A git bisect run command is opaque to floor inspection."
    if subcommand == "submodule" and args:
        action_index = 0
        while action_index < len(args) and args[action_index].startswith("-"):
            option = args[action_index].lower()
            if option not in {"-q", "--quiet", "--cached"}:
                return "Opaque leading git submodule options are floor-blocked."
            action_index += 1
        action = args[action_index].lower() if action_index < len(args) else ""
        if action == "foreach":
            return "A git submodule foreach command is opaque to floor inspection."
        if action == "set-url":
            return "Git submodule destination mutation is floor-blocked."
    if subcommand in {"merge", "rebase"}:
        strategies = git_option_values(args, "--strategy", {"-s"})
        if any(
            strategy is None or strategy.lower() not in _BUILTIN_GIT_MERGE_STRATEGIES
            for strategy in strategies
        ):
            return "A custom Git merge strategy can execute outside floor inspection."
    diff_args = None
    if subcommand in {"diff", "format-patch", "log", "show", "whatchanged"}:
        diff_args = args
    elif subcommand == "stash" and args and args[0].lower() == "show":
        diff_args = args[1:]
    if diff_args is not None and any(
        token.lower() == "--ext-diff"
        or git_option_abbreviates(token.lower().split("=", 1)[0], "--ext-diff")
        for token in diff_args
    ):
        return "Git external-diff execution is floor-blocked."
    return None


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


def git_environment_name(token: str) -> str:
    """Normalize shell/provider spellings of an environment variable name."""
    candidate = token.strip("'\"")
    if "=" in candidate:
        candidate = candidate.split("=", 1)[0]
    lowered = candidate.lower()
    for prefix in ("$env:", "${env:", "env:", "environment::"):
        if lowered.startswith(prefix):
            candidate = candidate[len(prefix) :]
            break
    return candidate.rstrip("}").upper()


_GIT_TRACE_TARGET_ENVIRONMENT = {
    "GIT_TRACE",
    "GIT_TRACE_FSMONITOR",
    "GIT_TRACE_PACK_ACCESS",
    "GIT_TRACE_PACKET",
    "GIT_TRACE_PACKFILE",
    "GIT_TRACE_PERFORMANCE",
    "GIT_TRACE_REFS",
    "GIT_TRACE_SETUP",
    "GIT_TRACE_SHALLOW",
    "GIT_TRACE_CURL",
    "GIT_TRACE2",
    "GIT_TRACE2_EVENT",
    "GIT_TRACE2_PERF",
}
_GIT_TRACE_DISCLOSURE_ENVIRONMENT = {
    "GIT_TRACE2_CONFIG_PARAMS",
    "GIT_TRACE2_ENV_VARS",
    "GIT_TRACE_REDACT",
}
_GIT_TRACE_ENVIRONMENT = (
    _GIT_TRACE_TARGET_ENVIRONMENT | _GIT_TRACE_DISCLOSURE_ENVIRONMENT
)


def dangerous_git_trace_setting(name: str, value: str) -> bool:
    """Return whether one Git trace setting can write or disclose secrets."""
    normalized_name = git_environment_name(name)
    normalized_value = restore_quoted_literal_markers(value).strip("'\"")
    if normalized_name in _GIT_TRACE_TARGET_ENVIRONMENT:
        expanded = expand_environment_references(normalized_value)
        return (
            expanded is None
            or has_dynamic_shell_token(expanded)
            or token_mentions_secret_path(expanded)
        )
    if normalized_name in {"GIT_TRACE2_CONFIG_PARAMS", "GIT_TRACE2_ENV_VARS"}:
        return bool(normalized_value)
    if normalized_name == "GIT_TRACE_REDACT":
        return normalized_value.lower() in {"0", "false", "no", "off"}
    return False


def git_trace_environment_mutations(raw: list[str]) -> list[tuple[str, str]]:
    """Return trace environment name/value mutations from one shell segment."""
    if not raw:
        return []
    mutations: list[tuple[str, str]] = []

    def record_attached(token: str) -> bool:
        if "=" not in token:
            return False
        name_token, value = token.split("=", 1)
        name = git_environment_name(name_token)
        if name not in _GIT_TRACE_ENVIRONMENT:
            return False
        mutations.append((name, value))
        return True

    first = raw[0].lower()
    if _ASSIGN.match(raw[0]) or first.startswith(("$env:", "${env:")):
        index = 0
        while index < len(raw):
            if record_attached(raw[index]):
                index += 1
                continue
            if _ASSIGN.match(raw[index]):
                index += 1
                continue
            name = git_environment_name(raw[index])
            if (
                name in _GIT_TRACE_ENVIRONMENT
                and index + 2 < len(raw)
                and raw[index + 1] == "="
            ):
                mutations.append((name, raw[index + 2]))
            break
        return mutations

    if first in {"env", "export", "set"}:
        index = 1
        while index < len(raw):
            if record_attached(raw[index]):
                index += 1
                continue
            index += 1
        return mutations

    if first == "setx":
        for index, token in enumerate(raw[1:], start=1):
            name = git_environment_name(token)
            if name not in _GIT_TRACE_ENVIRONMENT:
                continue
            value = ""
            for candidate in raw[index + 1 :]:
                if candidate.lower() == "/m":
                    continue
                if candidate.startswith("/"):
                    value = "$HARNESS_OPAQUE_SETX_VALUE"
                    break
                value = candidate
                break
            mutations.append((name, value))
        return mutations

    if first in {"set-item", "new-item", "si", "ni"}:
        path_value = None
        assigned_value = None
        positional = []
        index = 1
        while index < len(raw):
            token = raw[index]
            if token.startswith("-"):
                parameter, separator, bound = token.lstrip("-").partition(":")
                parameter = parameter.lower()
                role = None
                if parameter and any(
                    name.startswith(parameter) for name in {"path", "literalpath"}
                ):
                    role = "path"
                elif parameter and "value".startswith(parameter):
                    role = "value"
                if role:
                    value = (
                        bound
                        if separator
                        else (raw[index + 1] if index + 1 < len(raw) else "")
                    )
                    if role == "path":
                        path_value = value
                    else:
                        assigned_value = value
                    index += 1 if separator else 2
                    continue
                index += 1
                continue
            positional.append(token)
            index += 1
        if path_value is None and positional:
            path_value = positional.pop(0)
        if assigned_value is None and positional:
            assigned_value = positional[0]
        name = git_environment_name(path_value or "")
        if name in _GIT_TRACE_ENVIRONMENT:
            mutations.append((name, assigned_value or ""))
        return mutations

    environment_call = re.search(
        r"(?i)(?:\[(?:system\.)?environment\])::setenvironmentvariable\("
        r"\s*([^,]+)\s*,\s*([^,)]+)",
        restore_quoted_literal_markers(" ".join(raw)),
    )
    if environment_call:
        name = git_environment_name(environment_call.group(1))
        if name in _GIT_TRACE_ENVIRONMENT:
            mutations.append((name, environment_call.group(2)))
    return mutations


def dangerous_git_trace_environment_mutation(raw: list[str]) -> bool:
    """Return whether a segment establishes an unsafe Git trace setting."""
    return any(
        dangerous_git_trace_setting(name, value)
        for name, value in git_trace_environment_mutations(raw)
    )


def has_dangerous_git_trace_environment(raw: list[str]) -> bool:
    """Inspect inherited and command-scoped Git trace settings."""
    if any(
        dangerous_git_trace_setting(name, value)
        for name, value in os.environ.items()
        if name.upper() in _GIT_TRACE_ENVIRONMENT
    ):
        return True
    return dangerous_git_trace_environment_mutation(raw)


def is_git_config_environment_name(token: str) -> bool:
    """Return whether a variable can inject arbitrary Git configuration."""
    name = git_environment_name(token)
    return name.startswith("GIT_CONFIG") and name != "GIT_CONFIG_NOSYSTEM"


def has_git_config_environment(raw: list[str]) -> bool:
    """Detect per-command or inherited Git config environment injection."""

    if any(is_git_config_environment_name(name) for name in os.environ):
        return True
    for token in raw:
        base = _EXE_SUFFIX.sub("", token.replace("\\", "/").split("/")[-1]).lower()
        if base == "git":
            break
        assignment = _ASSIGN.match(token)
        if assignment:
            name = token.split("=", 1)[0]
            if is_git_config_environment_name(name):
                return True
    return False


_GIT_PROCESS_ENVIRONMENT = {
    "GIT_ASKPASS",
    "GIT_EDITOR",
    "GIT_EXEC_PATH",
    "GIT_EXTERNAL_DIFF",
    "GIT_PAGER",
    "GIT_PROXY_COMMAND",
    "GIT_SEQUENCE_EDITOR",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GIT_TEMPLATE_DIR",
    "GIT_WEB_BROWSER",
    "SSH_ASKPASS",
}
_GIT_PROCESS_COMMAND_ENVIRONMENT = _GIT_PROCESS_ENVIRONMENT | {
    "EDITOR",
    "PAGER",
    "VISUAL",
}

_GIT_EDITOR_SUBCOMMANDS = {
    "am",
    "cherry-pick",
    "commit",
    "config",
    "merge",
    "notes",
    "rebase",
    "revert",
    "tag",
}
_GIT_EXTERNAL_DIFF_SUBCOMMANDS = {
    "diff",
    "diff-files",
    "diff-index",
    "diff-tree",
    "format-patch",
    "log",
    "range-diff",
    "show",
    "stash",
    "whatchanged",
}
_GIT_PAGER_SUBCOMMANDS = {
    "blame",
    "branch",
    "diff",
    "grep",
    "help",
    "log",
    "range-diff",
    "reflog",
    "shortlog",
    "show",
    "tag",
    "whatchanged",
}


def git_pager_is_reachable(
    subcommand: str, args: list[str], global_args: list[str]
) -> bool:
    """Return whether this invocation can launch Git's configured pager."""
    forced = None
    index = 0
    while index < len(global_args):
        token = global_args[index]
        lowered = token.lower().split("=", 1)[0]
        if token == "-P" or lowered == "--no-pager":
            forced = False
        elif token == "-p" or lowered == "--paginate":
            forced = True
        index += 2 if token in _GIT_VALUE_OPTS else 1
    if forced is not None:
        return forced
    if subcommand == "config":
        return any(
            token.lower().split("=", 1)[0]
            in {"-l", "--list", "--get-all", "--get-regexp", "--get-urlmatch"}
            for token in args
        )
    return subcommand in _GIT_PAGER_SUBCOMMANDS


def git_network_helper_is_reachable(subcommand: str, args: list[str]) -> bool:
    """Return whether Git can use an SSH, proxy, or askpass helper."""
    if subcommand in {"clone", "fetch", "ls-remote", "pull", "push"}:
        return True
    if subcommand == "archive":
        return git_option_is_present(args, "--remote")
    if subcommand == "remote":
        action = next(
            (token.lower() for token in args if not token.startswith("-")), ""
        )
        return action in {"prune", "show", "update"} or (
            action == "set-head"
            and any(token.lower() in {"-a", "--auto"} for token in args)
        )
    if subcommand == "submodule":
        action = next(
            (token.lower() for token in args if not token.startswith("-")), ""
        )
        return action in {"add", "update"}
    return False


def git_editor_is_reachable(subcommand: str, args: list[str]) -> bool:
    """Return whether Git can launch the editor selected by GIT_EDITOR."""
    lowered = [token.lower().split("=", 1)[0] for token in args]
    if subcommand == "add":
        return any(token in {"-e", "--edit"} for token in lowered)
    if subcommand == "config":
        return any(token in {"-e", "--edit"} for token in lowered)
    return subcommand in _GIT_EDITOR_SUBCOMMANDS


def git_template_is_reachable(subcommand: str, args: list[str]) -> bool:
    """Return whether Git can copy from its configured template directory."""
    if subcommand in {"clone", "init"}:
        return True
    if subcommand != "submodule":
        return False
    action = next((token.lower() for token in args if not token.startswith("-")), "")
    return action in {"add", "update"}


def git_external_diff_is_reachable(subcommand: str, args: list[str]) -> bool:
    """Return whether Git can invoke the helper selected by GIT_EXTERNAL_DIFF."""
    if subcommand not in _GIT_EXTERNAL_DIFF_SUBCOMMANDS:
        return False
    enabled = True
    for token in args:
        lowered = token.lower()
        if lowered == "--no-ext-diff":
            enabled = False
        elif lowered == "--ext-diff":
            enabled = True
    return enabled


def inherited_git_process_environment_is_reachable(
    name: str,
    subcommand: str,
    args: list[str],
    global_args: list[str],
) -> bool:
    """Scope inherited Git helper variables to commands that can consume them."""
    if name == "GIT_EXEC_PATH":
        return bool(subcommand)
    if name == "GIT_PAGER":
        return git_pager_is_reachable(subcommand, args, global_args)
    if name in {
        "GIT_ASKPASS",
        "GIT_PROXY_COMMAND",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "SSH_ASKPASS",
    }:
        return git_network_helper_is_reachable(subcommand, args)
    if name == "GIT_EDITOR":
        return git_editor_is_reachable(subcommand, args)
    if name == "GIT_SEQUENCE_EDITOR":
        return subcommand == "rebase" and any(
            token.lower() in {"-i", "--interactive"} for token in args
        )
    if name == "GIT_EXTERNAL_DIFF":
        return git_external_diff_is_reachable(subcommand, args)
    if name == "GIT_TEMPLATE_DIR":
        return git_template_is_reachable(subcommand, args)
    if name == "GIT_WEB_BROWSER":
        return subcommand == "instaweb" or (
            subcommand == "help"
            and any(token.lower() in {"-w", "--web"} for token in args)
        )
    return False


def has_git_process_environment(
    raw: list[str],
    subcommand: str,
    args: list[str],
    global_args: list[str],
) -> bool:
    """Detect command-scoped or inherited process-launching Git variables."""
    if any(
        inherited_git_process_environment_is_reachable(
            name.upper(), subcommand, args, global_args
        )
        for name in os.environ
        if name.upper() in _GIT_PROCESS_ENVIRONMENT
    ):
        return True
    for token in raw:
        base = _EXE_SUFFIX.sub("", token.replace("\\", "/").split("/")[-1]).lower()
        if base == "git":
            break
        if (
            _ASSIGN.match(token)
            and git_environment_name(token) in _GIT_PROCESS_COMMAND_ENVIRONMENT
        ):
            return True
    return False


def git_process_environment_mutations(raw: list[str]) -> set[str]:
    """Return process-launching Git variables mutated by one shell segment."""
    if not raw:
        return set()
    mutations: set[str] = set()
    first = raw[0].lower()
    if (
        _ASSIGN.match(raw[0])
        and git_environment_name(raw[0]) in _GIT_PROCESS_COMMAND_ENVIRONMENT
    ):
        mutations.add(git_environment_name(raw[0]))
    if (
        git_environment_name(raw[0]) in _GIT_PROCESS_COMMAND_ENVIRONMENT
        and ("=" in raw[0] or (len(raw) > 1 and raw[1] == "="))
        and first.startswith(("$env:", "${env:", "env:", "environment::"))
    ):
        mutations.add(git_environment_name(raw[0]))
    if first in {"export", "set", "setx"}:
        mutations.update(
            name
            for token in raw[1:]
            if (name := git_environment_name(token)) in _GIT_PROCESS_COMMAND_ENVIRONMENT
        )
    if first in {"set-item", "new-item", "si", "ni"}:
        mutations.update(
            name
            for token in raw[1:]
            if (name := git_environment_name(token)) in _GIT_PROCESS_COMMAND_ENVIRONMENT
        )
    return mutations


def is_git_config_environment_mutation(raw: list[str]) -> bool:
    """Detect shell commands that establish Git config injection state."""
    if not raw:
        return False
    first = raw[0].lower()
    if _ASSIGN.match(raw[0]) and is_git_config_environment_name(raw[0]):
        return True
    if first.startswith(("$env:", "${env:")) and is_git_config_environment_name(raw[0]):
        return True
    if first in {"export", "set", "setx"}:
        return any(is_git_config_environment_name(token) for token in raw[1:])
    if first in {"set-item", "new-item", "si", "ni"}:
        return any(is_git_config_environment_name(token) for token in raw[1:])
    return False


def git_option_abbreviates(
    token: str,
    dangerous: str,
    min_prefix: int = 2,
) -> bool:
    """Git accepts unambiguous long-option prefixes; fail closed on them."""
    option = token.split("=", 1)[0]
    return (
        option.startswith("--")
        and len(option) >= 2 + min_prefix
        and dangerous.startswith(option)
    )


_GIT_PUSH_VALUE_LONG_OPTIONS = {
    "--exec",
    "--push-option",
    "--receive-pack",
    "--recurse-submodules",
    "--repo",
}

_FEATURE_BRANCH_ROOTS = {
    "chore",
    "ci",
    "docs",
    "feat",
    "feature",
    "fix",
    "infra",
    "perf",
    "refactor",
    "security",
    "test",
    "tests",
}
_AUTOMATION_BRANCH_ROOTS = {"dependabot", "renovate"}
_SAFE_BRANCH_SUFFIX = re.compile(r"[A-Za-z0-9._@-]+(?:/[A-Za-z0-9._@-]+)*")


def force_with_lease_target_is_feature(refspec: str) -> bool:
    """Allow leases only when the destination is positively a feature ref."""
    candidate = refspec.lstrip("+")
    if ":" in candidate:
        _source, target = candidate.rsplit(":", 1)
    else:
        target = candidate
    if target.startswith("refs/") and not target.startswith("refs/heads/"):
        return False
    target = target.removeprefix("refs/heads/").strip("/")
    root, separator, suffix = target.partition("/")
    root = root.lower()
    if root in _FEATURE_BRANCH_ROOTS:
        return not separator or bool(_SAFE_BRANCH_SUFFIX.fullmatch(suffix))
    return (
        root in _AUTOMATION_BRANCH_ROOTS
        and bool(separator)
        and bool(_SAFE_BRANCH_SUFFIX.fullmatch(suffix))
    )


def force_with_lease_targets_are_features(refspecs: list[str]) -> bool:
    """Return whether every explicit lease destination is a feature ref."""
    return bool(refspecs) and all(
        force_with_lease_target_is_feature(refspec) for refspec in refspecs
    )


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
_GIT_CONFIG_EDIT_FLAGS = {"-e", "--edit"}
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
    "--value",
}


def git_config_option_present(tokens: list[str], option: str) -> bool:
    """Return whether config argv contains an exact or accepted long prefix."""
    return any(
        token == option or git_option_abbreviates(token, option) for token in tokens
    )


_GIT_CONFIG_READ_ACTIONS = {"get", "get-all", "get-regexp", "get-urlmatch", "list"}
_GIT_CONFIG_WRITE_COMMANDS = {
    "edit",
    "remove-section",
    "rename-section",
    "set",
    "unset",
}


def parse_git_config_args(
    args: list[str],
) -> tuple[str, list[str], list[str], list[str]]:
    """Return command action, options, operands, and explicit file targets."""
    options: list[str] = []
    operands: list[str] = []
    file_targets: list[str] = []
    action = ""
    index = 0
    while index < len(args):
        token = args[index]
        lowered = token.lower()
        if token == "--":
            operands.extend(item.lower() for item in args[index + 1 :])
            break
        if not token.startswith("-") or token == "-":
            if (
                not action
                and not operands
                and lowered in (_GIT_CONFIG_READ_ACTIONS | _GIT_CONFIG_WRITE_COMMANDS)
            ):
                action = lowered
                index += 1
                continue
            # Git's parser stops option processing at the first real operand.
            operands.extend(item.lower() for item in args[index:])
            break
        options.append(lowered)
        if (
            lowered.startswith("-f")
            and not lowered.startswith("--")
            and lowered != "-f"
        ):
            file_targets.append(token[2:])
            index += 1
            continue
        option_name = lowered.split("=", 1)[0]
        value_option = next(
            (
                option
                for option in _GIT_CONFIG_VALUE_OPTIONS
                if option_name == option
                or (
                    option.startswith("--")
                    and git_option_abbreviates(option_name, option)
                )
            ),
            None,
        )
        if value_option is None:
            index += 1
            continue
        if "=" in token and value_option.startswith("--"):
            value = token.split("=", 1)[1]
            index += 1
        elif index + 1 < len(args):
            value = args[index + 1]
            index += 2
        else:
            value = ""
            index += 1
        if value_option in {"-f", "--file"} and value:
            file_targets.append(value)
    return action, options, operands, file_targets


def protected_git_config_section(section: str) -> bool:
    """Return whether a section can alter push destinations or inject config."""
    lowered = section.lower()
    return lowered.startswith(("remote.", "url.", "includeif.")) or lowered == "include"


def executable_git_config_section(section: str) -> bool:
    """Return whether renaming into a section can create an executable config key."""
    root = section.lower().split(".", 1)[0]
    return root in {
        "browser",
        "core",
        "credential",
        "diff",
        "difftool",
        "filter",
        "gc",
        "gpg",
        "guitool",
        "help",
        "hook",
        "imap",
        "include",
        "includeif",
        "instaweb",
        "interactive",
        "man",
        "merge",
        "mergetool",
        "pager",
        "protocol",
        "remote",
        "sequence",
        "sendemail",
        "submodule",
        "tar",
        "trailer",
        "uploadpack",
    }


def executable_git_config_key(token: str) -> bool:
    """Return whether a config key can launch a later process."""
    lowered = token.lower()
    return bool(
        lowered
        in {
            "core.askpass",
            "core.alternaterefscommand",
            "core.editor",
            "core.fsmonitor",
            "core.gitproxy",
            "core.hookspath",
            "core.pager",
            "core.sshcommand",
            "credential.helper",
            "diff.external",
            "gpg.program",
            "gpg.ssh.program",
            "gpg.ssh.defaultkeycommand",
            "gc.recentobjectshook",
            "help.browser",
            "imap.tunnel",
            "include.path",
            "instaweb.browser",
            "instaweb.httpd",
            "interactive.difffilter",
            "man.viewer",
            "protocol.allow",
            "sendemail.smtpserver",
            "sequence.editor",
            "uploadpack.packobjectshook",
            "web.browser",
        }
        or re.fullmatch(r"credential\..+\.helper", lowered)
        or re.fullmatch(r"diff\..+\.(?:command|textconv)", lowered)
        or re.fullmatch(r"filter\..+\.(?:clean|process|smudge)", lowered)
        or re.fullmatch(r"gpg\..+\.program", lowered)
        or re.fullmatch(r"guitool\..+\.cmd", lowered)
        or re.fullmatch(r"hook\..+\.command", lowered)
        or re.fullmatch(r"includeif\..+\.path", lowered)
        or re.fullmatch(r"merge\..+\.driver", lowered)
        or re.fullmatch(r"(?:diff|merge)tool\..+\.(?:cmd|path)", lowered)
        or re.fullmatch(r"(?:browser|man)\..+\.(?:cmd|path)", lowered)
        or re.fullmatch(r"pager\..+", lowered)
        or re.fullmatch(r"protocol\..+\.allow", lowered)
        or re.fullmatch(r"remote\..+\.(?:proxy|receivepack|uploadpack|vcs)", lowered)
        or re.fullmatch(
            r"sendemail(?:\..+)?\."
            r"(?:cccmd|headercmd|sendmailcmd|smtpserver|smtpserveroption|tocmd)",
            lowered,
        )
        or re.fullmatch(r"submodule\..+\.update", lowered)
        or re.fullmatch(r"tar\..+\.command", lowered)
        or re.fullmatch(r"trailer\..+\.(?:cmd|command)", lowered)
    )


def protected_git_config_key(token: str) -> bool:
    """Return whether a config key can affect execution or push destinations."""
    return bool(
        re.fullmatch(r"alias\.[^.]+", token)
        or re.fullmatch(r"remote\..+\.(?:url|pushurl|push|mirror)", token)
        or re.fullmatch(r"url\..+\.(?:insteadof|pushinsteadof)", token)
        or re.fullmatch(r"include(?:if)?\..+", token)
        or re.fullmatch(r"submodule\..+\.url", token)
        or token == "push.recursesubmodules"
        or executable_git_config_key(token)
    )


def git_config_operation_is_read_only(
    action: str, options: list[str], operands: list[str]
) -> bool:
    """Classify modern command mode and legacy config reads conservatively."""
    if action in _GIT_CONFIG_READ_ACTIONS:
        return True
    if action in _GIT_CONFIG_WRITE_COMMANDS:
        return False
    if any(git_config_option_present(options, flag) for flag in _GIT_CONFIG_EDIT_FLAGS):
        return False
    if any(
        git_config_option_present(options, option) for option in _GIT_CONFIG_READ_FLAGS
    ):
        return True
    if any(
        git_config_option_present(options, option)
        for option in _GIT_CONFIG_REMOVAL_FLAGS | _GIT_CONFIG_WRITE_ACTIONS
    ):
        return False
    return len(operands) <= 1


_GIT_TRACE_TARGET_CONFIG = {
    "trace2.normaltarget": "GIT_TRACE2",
    "trace2.perftarget": "GIT_TRACE2_PERF",
    "trace2.eventtarget": "GIT_TRACE2_EVENT",
}
_GIT_TRACE_DISCLOSURE_CONFIG = {"trace2.configparams", "trace2.envvars"}


def dangerous_git_trace_config_mutation(
    action: str,
    options: list[str],
    operands: list[str],
    file_targets: list[str],
) -> bool:
    """Inspect persistent Trace2 settings without blocking ignored local config."""
    persistent_scope = bool(file_targets) or any(
        git_config_option_present(options, scope) for scope in {"--global", "--system"}
    )
    if not persistent_scope:
        return False
    if action == "rename-section" or git_config_option_present(
        options, "--rename-section"
    ):
        return len(operands) > 1 and operands[1].lower() == "trace2"
    if action in {"unset", "remove-section"} or any(
        git_config_option_present(options, option)
        for option in _GIT_CONFIG_REMOVAL_FLAGS
    ):
        return False
    if git_config_operation_is_read_only(action, options, operands):
        return False
    if len(operands) < 2:
        return False
    key = operands[0].lower()
    value = operands[1]
    trace_environment = _GIT_TRACE_TARGET_CONFIG.get(key)
    if trace_environment:
        return dangerous_git_trace_setting(trace_environment, value)
    if key in _GIT_TRACE_DISCLOSURE_CONFIG:
        return bool(restore_quoted_literal_markers(value).strip("'\""))
    return False


def dangerous_git_config_mutation(args: list[str]) -> bool:
    """Reject writes/removals that can change a later push's behavior."""
    action, options, operands, file_targets = parse_git_config_args(args)
    if action == "edit" or any(
        git_config_option_present(options, flag) for flag in _GIT_CONFIG_EDIT_FLAGS
    ):
        return True
    if dangerous_git_trace_config_mutation(action, options, operands, file_targets):
        return True
    if not git_config_operation_is_read_only(action, options, operands) and any(
        token_mentions_secret_path(target) for target in file_targets
    ):
        return True
    if action:
        if action in _GIT_CONFIG_READ_ACTIONS:
            return False
        if action in {"set", "unset"}:
            return bool(operands and protected_git_config_key(operands[0]))
        if action == "remove-section":
            return bool(
                operands
                and (
                    protected_git_config_section(operands[0])
                    or executable_git_config_section(operands[0])
                )
            )
        return any(
            protected_git_config_section(section)
            or executable_git_config_section(section)
            for section in operands[:2]
        )

    if any(
        git_config_option_present(options, action)
        for action in {"--remove-section", "--rename-section"}
    ) and any(
        protected_git_config_section(section) or executable_git_config_section(section)
        for section in operands
    ):
        return True
    protected_index = next(
        (
            index
            for index, token in enumerate(operands)
            if protected_git_config_key(token)
        ),
        None,
    )
    if protected_index is None:
        return False
    if any(
        git_config_option_present(options, option)
        for option in _GIT_CONFIG_REMOVAL_FLAGS
    ):
        return True
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
    raw = restore_quoted_literal_markers(target)
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


_POWERSHELL_COMMON_VALUE_PARAMETERS = {
    "erroraction",
    "ea",
    "errorvariable",
    "ev",
    "informationaction",
    "infa",
    "informationvariable",
    "iv",
    "outbuffer",
    "ob",
    "outvariable",
    "ov",
    "pipelinevariable",
    "pv",
    "progressaction",
    "proga",
    "warningaction",
    "wa",
    "warningvariable",
    "wv",
}


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


def compound_pipeline_closer(raw: list[str]) -> str | None:
    """Return the closer for a compound command that shares pipeline stdin."""
    if not raw:
        return None
    first = raw[0].lower()
    if first == "{" or first.startswith("{"):
        return "}"
    if first.startswith("("):
        return ")"
    if first in {"if"}:
        return "fi"
    if first in {"for", "select", "until", "while"}:
        return "done"
    if first == "case":
        return "esac"
    return None


def stage_closes_compound(raw: list[str], closer: str) -> bool:
    if closer in {"}", ")"}:
        return any(token.endswith(closer) for token in raw)
    return any(token.lower() == closer for token in raw)


def has_download_pipe_to_shell(command: str) -> bool:
    """Recognize pipeline endpoints after path/wrapper normalization."""
    download_seen = False
    compound_closers: list[str] = []
    for raw_stage, operator_after in quote_aware_segments_with_operators(command):
        if download_seen:
            closer = compound_pipeline_closer(raw_stage)
            if closer is not None:
                compound_closers.append(closer)
        stage = strip_control_prefixes(raw_stage)
        assignment_rhs = powershell_assignment_rhs(stage)
        if assignment_rhs is not None and not inert_powershell_scriptblock(
            assignment_rhs
        ):
            stage = tokens(assignment_rhs)
        if re.search(
            r"<\s*\(\s*(?:(?:env|command)\s+(?:--\s+)?)?"
            r"(?:[^\s()]+[\\/])?"
            r"(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)(?:\.exe)?\b",
            " ".join(raw_stage),
            re.IGNORECASE,
        ):
            download_seen = True
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
        if stage_head in {
            "curl",
            "wget",
            "iwr",
            "irm",
            "invoke-webrequest",
            "invoke-restmethod",
        }:
            download_seen = True
        if compound_closers and stage_closes_compound(
            raw_stage,
            compound_closers[-1],
        ):
            compound_closers.pop()
        if operator_after not in {"|", "|&"} and not compound_closers:
            download_seen = False
    return False


def contains_downloader_command(command: str) -> bool:
    """Return whether an evaluated expression directly invokes a downloader."""
    for segment in segments(command):
        raw = strip_control_prefixes(tokens(segment))
        head, _ = command_head(raw)
        if head in {
            "curl",
            "wget",
            "iwr",
            "irm",
            "invoke-webrequest",
            "invoke-restmethod",
        }:
            return True
    return False


_POSIX_SHELL_HEADS = {"ash", "bash", "dash", "ksh", "sh", "zsh"}


def has_opaque_posix_shell_input(toks: list[str]) -> bool:
    """Reject shell program text supplied through opaque stdin/file expansion."""
    for index, token in enumerate(toks[1:], start=1):
        if token == "<<<":
            return True
        if token != "<" or index + 1 >= len(toks):
            continue
        candidate_index = index + 1
        if toks[candidate_index] == "<":
            candidate_index += 1
        if candidate_index < len(toks) and toks[candidate_index].lstrip().startswith(
            "("
        ):
            return True
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
    command = mask_inert_powershell_assignment_scriptblocks(command)
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
    if re.search(
        r"(?:^|[;|{}\n])\s*\$\{?(?:env:)?[A-Za-z_][A-Za-z0-9_:]*\}?"
        r"\.(?:Invoke|InvokeReturnAsIs)\s*\(",
        call_normalized,
        re.IGNORECASE,
    ):
        return "deny", "A dynamic scriptblock invocation cannot be inspected safely."
    sanitized, inert_placeholders = strip_quotes(command)
    for full_redirect in re.finditer(r"(?:\d*|&)?>{1,2}(?:\||&)?\s*(\S+)", sanitized):
        redirect_target = full_redirect.group(1).strip("'\"")
        if has_dynamic_shell_token(redirect_target) or re.match(
            r"^[<>]?\(", redirect_target
        ):
            return "deny", "A dynamic redirect target cannot be inspected safely."
        if token_mentions_secret_path(redirect_target):
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
    assignment_command = _QUOTED.sub("__HARNESS_ASSIGNMENT_LITERAL__", command)
    assignment_segments = quote_aware_segments_with_operators(assignment_command)
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
    active_git_process_environment: set[str] = set()
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
            active_git_process_environment = set()
        previous_pass = current_pass
        if not raw:
            continue
        raw = strip_control_prefixes(raw)
        if not raw:
            continue
        if dangerous_git_trace_environment_mutation(raw):
            return (
                "deny",
                "Git trace settings cannot write to or disclose secret material.",
            )
        if is_git_config_environment_mutation(raw):
            return (
                "deny",
                "Mutating Git's config-injection environment is floor-blocked.",
            )
        process_environment_mutations = git_process_environment_mutations(raw)
        if process_environment_mutations & _GIT_PROCESS_ENVIRONMENT:
            return (
                "deny",
                "Mutating a process-launching Git environment variable is floor-blocked.",
            )
        active_git_process_environment.update(process_environment_mutations)
        assignment_rhs = powershell_assignment_rhs(raw)
        if assignment_rhs is not None:
            if current_pass == 0 and segment_index < len(assignment_segments):
                assignment_raw = strip_control_prefixes(
                    assignment_segments[segment_index][0]
                )
                masked_rhs = powershell_assignment_rhs(assignment_raw)
                if (
                    masked_rhs
                    and not is_dynamic_value(masked_rhs)
                    and not inert_powershell_scriptblock(masked_rhs)
                ):
                    assignment_decision = check(
                        masked_rhs,
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
                    if assignment_decision[0] != "allow":
                        return assignment_decision
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
                evaluated = restore_quoted_literal_markers(" ".join(evaluated_args))
                if is_dynamic_value(evaluated):
                    return (
                        "deny",
                        "A dynamic evaluator argument cannot be inspected safely.",
                    )
                if head in {"iex", "invoke-expression"} and contains_downloader_command(
                    evaluated
                ):
                    return (
                        "deny",
                        "Evaluating downloader output directly is floor-blocked.",
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
        if head in {"start-process", "saps"}:
            child_command, error = powershell_start_process_command(toks)
            if child_command is None:
                return "deny", error
            child_decision = check(
                child_command,
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
            if child_decision[0] != "allow":
                return child_decision
            continue
        if head == "start":
            return (
                "deny",
                "A process launcher can conceal an irreversible child command. Run the child directly.",
            )
        if head == "call":
            if len(toks) < 2 or is_dynamic_value(" ".join(toks[1:])):
                return "deny", "A dynamic cmd call target cannot be inspected safely."
            nested_decision = check(
                restore_quoted_literal_markers(" ".join(toks[1:])),
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
        if head == "find":
            if any(token in {"-exec", "-execdir", "-delete"} for token in toks[1:]):
                return (
                    "deny",
                    "find execution/deletion actions are opaque to the deny floor. Enumerate first.",
                )
            for index, token in enumerate(toks[1:], start=1):
                if token not in {"-fprint", "-fprint0", "-fprintf", "-fls"}:
                    continue
                target = toks[index + 1] if index + 1 < len(toks) else ""
                if not target or has_dynamic_shell_token(target):
                    return "deny", "A find output target cannot be inspected safely."
                if token_mentions_secret_path(target):
                    return (
                        "deny",
                        "find output to a secret-looking file is floor-blocked.",
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

        if head in {"source", "."} and has_opaque_posix_shell_input(toks):
            return (
                "deny",
                "Sourcing program text from an opaque input cannot be inspected safely.",
            )

        nested_script = None
        nested_command_requested = False
        if head == "cmd":
            nested_command_requested, nested_script = cmd_nested_script(toks)
        elif head in _POSIX_SHELL_HEADS | {"pwsh", "powershell"}:
            if head in _POSIX_SHELL_HEADS and has_opaque_posix_shell_input(toks):
                return (
                    "deny",
                    "Shell program text from an opaque input source cannot be inspected safely.",
                )
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
                        head in _POSIX_SHELL_HEADS
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
                    nested_command_requested = True
                    if separator:
                        nested_script = bound_value
                    elif index + 1 < len(toks):
                        if head in _POSIX_SHELL_HEADS:
                            script_index = index + 1
                            if toks[script_index] == "--":
                                script_index += 1
                            if script_index < len(toks):
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
        if nested_command_requested and not nested_script:
            return (
                "deny",
                "A nested-shell command without inline program text cannot be inspected safely.",
            )
        if nested_script:
            nested_script = restore_quoted_literal_markers(nested_script)
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
            raw_args = (
                toks[subcommand_index + 1 :] if subcommand_index is not None else []
            )
            inline_configs = git_inline_configs(git_toks)
            config_env_keys = git_config_env_keys(git_toks)
            if subcommand_index is not None and any(
                token.lower().split("=", 1)[0] == "--exec-path"
                or git_option_abbreviates(token.lower().split("=", 1)[0], "--exec-path")
                for token in git_toks[1:subcommand_index]
                if "=" in token
            ):
                return (
                    "deny",
                    "A custom Git executable path can launch uninspected programs.",
                )
            if any(protected_git_config_key(key) for key in inline_configs):
                return (
                    "deny",
                    "Inline Git config can change execution or destination semantics.",
                )
            if config_env_keys and any(
                protected_git_config_key(key) for key in config_env_keys
            ):
                return (
                    "deny",
                    "Git --config-env can inject execution or destination config.",
                )
            if has_git_config_environment(raw):
                return (
                    "deny",
                    "Git config environment injection is opaque to floor inspection.",
                )
            if has_git_process_environment(
                raw,
                sub,
                args,
                git_toks[1:subcommand_index] if subcommand_index is not None else [],
            ):
                return (
                    "deny",
                    "Git process-launch environment overrides are opaque to floor inspection.",
                )
            if has_dangerous_git_trace_environment(raw):
                return (
                    "deny",
                    "Git trace settings cannot write to or disclose secret material.",
                )
            if active_git_process_environment:
                return (
                    "deny",
                    "A prior editor or pager environment mutation can alter Git execution.",
                )
            if sub == "push" and inline_configs:
                return (
                    "deny",
                    "Inline git config can conceal push execution or force semantics.",
                )
            if sub == "push" and (config_env_keys is None or config_env_keys):
                return "deny", "Git --config-env is opaque during a push."
            if sub == "config" and dangerous_git_config_mutation(args):
                return (
                    "deny",
                    "Git execution or push-destination config mutation is floor-blocked.",
                )
            if sub == "remote" and dangerous_git_remote_mutation(args):
                return "deny", "Git remote destination mutation is floor-blocked."
            launcher_reason = dangerous_git_process_launcher(sub, args)
            if launcher_reason:
                return "deny", launcher_reason
            if sub == "archive":
                archive_outputs = git_option_values(args, "--output", {"-o"})
                if any(
                    target is None
                    or has_dynamic_shell_token(target)
                    or token_mentions_secret_path(target)
                    for target in archive_outputs
                ):
                    return (
                        "deny",
                        "Git archive output to an opaque or secret-looking file is floor-blocked.",
                    )

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

            if sub == "lfs":
                lfs_args = [token.lower() for token in args]
                if (
                    lfs_args
                    and lfs_args[0] == "status"
                    and all(
                        token in {"--help", "--json", "--porcelain", "-h"}
                        for token in lfs_args[1:]
                    )
                ):
                    continue
                return (
                    "deny",
                    "Only the read-only git lfs status command is admitted through the floor.",
                )

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
                if any(
                    token in {"--exec", "--receive-pack"}
                    or token.startswith(("--exec=", "--receive-pack="))
                    for token in args
                ):
                    return (
                        "deny",
                        "A custom git receive-pack program can execute commands outside floor inspection.",
                    )
                if not quote_aware and any(
                    re.search(r"[*?\[]", token) for token in raw_args
                ):
                    return (
                        "deny",
                        "Unquoted git-push pathname expansion cannot be inspected safely.",
                    )
                if quote_aware and any(
                    re.search(r"\{[^{}]*,[^{}]*\}", token) for token in args
                ):
                    return (
                        "deny",
                        "Brace-expanded git-push arguments cannot be inspected safely.",
                    )
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
                lease_selectors = []
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
                        if t.startswith("--force-with-lease="):
                            selector = t.split("=", 1)[1].split(":", 1)[0]
                            if selector:
                                lease_selectors.append(selector)
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
                    or not force_with_lease_targets_are_features(positionals[1:])
                    or (
                        lease_selectors
                        and not force_with_lease_targets_are_features(lease_selectors)
                    )
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

            if sub == "reset" and any(
                token == "--hard"
                or git_option_abbreviates(token, "--hard", min_prefix=1)
                for token in args
            ):
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
                t == "--force"
                or git_option_abbreviates(t, "--force", min_prefix=1)
                or bool(re.match(r"^-[a-zA-Z]*f", t))
                for t in args
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

            restore_staged = any(
                token == "--staged"
                or git_option_abbreviates(token, "--staged")
                or bool(re.fullmatch(r"-[A-Za-z]*S[A-Za-z]*", token))
                for token in args
            )
            restore_worktree = any(
                token == "--worktree"
                or git_option_abbreviates(token, "--worktree", min_prefix=1)
                or bool(re.fullmatch(r"-[A-Za-z]*W[A-Za-z]*", token))
                for token in args
            )
            if (
                sub == "restore"
                and "." in args
                and (not restore_staged or restore_worktree)
            ):
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
            value_parameters = set(_POWERSHELL_COMMON_VALUE_PARAMETERS)
            if head in {"new-item", "ni"}:
                path_parameters.add("name")
                value_parameters.update({"itemtype", "type", "value"})
            if head in {
                "set-content",
                "sc",
                "add-content",
                "ac",
                "out-file",
                "tee",
                "tee-object",
            }:
                value_parameters.update(
                    {"value", "inputobject", "encoding", "filter", "include", "exclude"}
                )
            if head in {
                "set-content",
                "sc",
                "add-content",
                "ac",
                "clear-content",
                "clc",
            }:
                value_parameters.add("stream")
            if head == "out-file":
                value_parameters.add("width")
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
                    parameter, separator, _bound_value = token.lstrip("-").partition(
                        ":"
                    )
                    parameter = parameter.lower()
                    if parameter and any(
                        name.startswith(parameter) for name in path_parameters
                    ):
                        if index + 1 < len(toks):
                            explicit_paths.append(toks[index + 1])
                            index += 2
                            continue
                    if parameter and any(
                        name.startswith(parameter) for name in value_parameters
                    ):
                        index += 1 if separator else 2
                        continue
                    index += 1
                    continue
                if token.lower() not in {"/s", "/q", "/f"}:
                    positional_groups.append(
                        [token]
                        if re.search(r"\{[^{}]*,[^{}]*\}", token)
                        else token.split(",")
                    )
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
                if has_dynamic_shell_token(target) or target.startswith("("):
                    return (
                        "deny",
                        "A dynamic secret-mutation target cannot be inspected safely.",
                    )
                if token_mentions_secret_path(target):
                    return (
                        "deny",
                        f"Mutating a secret-looking file ({target}) is floor-blocked. The human manages secrets.",
                    )

        # Common output/mutation tools whose destination syntax differs from
        # the filesystem mutators above. This remains a bounded parser
        # contract; unfamiliar writers are covered by follow-up hardening and
        # OS/runtime permissions, not by claiming this hook is a shell sandbox.
        if head == "dd":
            for token in toks[1:]:
                if not token.lower().startswith("of="):
                    continue
                target = token.split("=", 1)[1]
                if has_dynamic_shell_token(target):
                    return (
                        "deny",
                        "A dynamic dd output target cannot be inspected safely.",
                    )
                if token_mentions_secret_path(target):
                    return (
                        "deny",
                        "dd output to a secret-looking file is floor-blocked.",
                    )
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
        if head in {
            "curl",
            "wget",
            "iwr",
            "irm",
            "invoke-webrequest",
            "invoke-restmethod",
        }:
            long_output_flags = {
                "--output",
                "--output-document",
                "--output-file",
                "--append-output",
                "--cookie-jar",
                "--dump-header",
                "--trace",
                "--trace-ascii",
                "--stderr",
                "--libcurl",
                "--etag-save",
            }
            explicit_output = False
            remote_name_output = head == "wget"
            for index, token in enumerate(toks[1:], start=1):
                lowered = token.lower()
                attached_target = None
                clustered_marker, clustered_target = downloader_output_binding(
                    head,
                    token,
                )
                clustered_output = clustered_marker is not None
                if head == "curl" and curl_uses_remote_name(token):
                    remote_name_output = True
                matched_long = next(
                    (
                        option
                        for option in long_output_flags
                        if lowered == option or lowered.startswith(option + "=")
                    ),
                    None,
                )
                powershell_parameter = lowered.lstrip("-").split(":", 1)[0]
                powershell_outfile = (
                    head in {"iwr", "irm", "invoke-webrequest", "invoke-restmethod"}
                    and len(powershell_parameter) >= 4
                    and "outfile".startswith(powershell_parameter)
                )
                if matched_long and "=" in token:
                    attached_target = token.split("=", 1)[1]
                elif powershell_outfile and ":" in token:
                    attached_target = token.split(":", 1)[1]
                elif clustered_output and clustered_target is not None:
                    attached_target = clustered_target
                if attached_target is not None or clustered_output:
                    explicit_output = explicit_output or bool(
                        head != "wget"
                        or clustered_marker == "O"
                        or matched_long == "--output-document"
                    )
                if attached_target is not None:
                    if has_dynamic_shell_token(attached_target) or re.match(
                        r"^[<>]?\(", attached_target
                    ):
                        return (
                            "deny",
                            "A dynamic download destination cannot be inspected safely.",
                        )
                    if token_mentions_secret_path(attached_target):
                        return (
                            "deny",
                            "Downloading into a secret-looking file is floor-blocked.",
                        )
                if (
                    (matched_long is not None or powershell_outfile or clustered_output)
                    and attached_target is None
                    and clustered_target is None
                    and index + 1 < len(toks)
                ):
                    target = toks[index + 1]
                    if is_dynamic_value(target) or re.match(r"^[<>]?\(", target):
                        return (
                            "deny",
                            "A dynamic download destination cannot be inspected safely.",
                        )
                    if token_mentions_secret_path(target):
                        return (
                            "deny",
                            "Downloading into a secret-looking file is floor-blocked.",
                        )
            if remote_name_output and not (head == "wget" and explicit_output):
                for token in toks[1:]:
                    if "://" in token and token_mentions_secret_path(token):
                        return (
                            "deny",
                            "A remote-name download would create a secret-looking file.",
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
                if token in (">", ">>") and token_mentions_secret_path(raw[index + 1]):
                    return (
                        "deny",
                        f"Redirecting output into a secret-looking file ({raw[index + 1]}) is floor-blocked.",
                    )
        else:
            redir = re.search(r"(?:\d*|&)?>{1,2}(?:\||&)?\s*(\S+)", segment_text)
            if redir and token_mentions_secret_path(redir.group(1)):
                return (
                    "deny",
                    f"Redirecting output into a secret-looking file ({redir.group(1)}) is floor-blocked.",
                )

        # ---- sensitive_data overlay ----
        if sensitive and head == "gh":
            if len(toks) >= 3 and toks[1] in ("repo", "gist") and toks[2] == "create":
                if any(boolean_flag_is_true(t, {"--public", "-p"}) for t in toks):
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
                    clustered_method = re.fullmatch(r"-i*[xX](?:=?([A-Za-z]+))?", token)
                    if clustered_method:
                        method = (
                            clustered_method.group(1)
                            or (toks[index + 1] if index + 1 < len(toks) else "")
                        ).upper()
                    elif lowered in {"-x", "--method"} and index + 1 < len(toks):
                        method = toks[index + 1].upper()
                    elif lowered.startswith("--method="):
                        method = token.split("=", 1)[1].upper()
                    elif lowered in {"-f", "-F", "--raw-field", "--field", "--input"}:
                        has_fields = True
                    elif re.fullmatch(r"-i*[fF].*", token):
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
    event = "invalid"
    runtime = "claude"
    event_options = [
        token
        for token in sys.argv[1:]
        if token == "--event" or token.startswith("--event=")
    ]
    if len(event_options) > 1:
        event = "invalid"
    elif event_options and event_options[0].startswith("--event="):
        event = event_options[0].split("=", 1)[1].lower() or "invalid"
    elif event_options:
        try:
            event = sys.argv[sys.argv.index("--event") + 1].lower()
        except IndexError:
            event = "invalid"
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
        if event != "pre":
            raise ValueError("unsupported or ambiguous hook event")
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
