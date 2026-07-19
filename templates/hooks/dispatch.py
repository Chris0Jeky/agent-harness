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

FLOOR_VERSION = "1.5.2 (2026-07-19)"

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


def powershell_job_scriptblocks(toks: list[str]) -> tuple[list[str] | None, str]:
    """Recover literal background-job scriptblocks for recursive inspection."""
    if not toks:
        return None, "A background-job payload cannot be inspected safely."

    start_job = toks[0].lower() in {"start-job", "sajb"}
    script_parameters = {"scriptblock"}
    if start_job:
        script_parameters.add("command")
    initialization_parameters = {"initializationscript"}
    opaque_parameters = {
        "definitionname",
        "definitionpath",
        "filepath",
        "literalpath",
        "pspath",
        "type",
    }
    value_parameters = {
        "argumentlist",
        "authentication",
        "credential",
        "erroraction",
        "ea",
        "errorvariable",
        "ev",
        "informationaction",
        "infa",
        "informationvariable",
        "iv",
        "inputobject",
        "name",
        "outbuffer",
        "ob",
        "outvariable",
        "ov",
        "pipelinevariable",
        "pv",
        "progressaction",
        "proga",
        "psversion",
        "warningaction",
        "wa",
        "warningvariable",
        "wv",
        "workingdirectory",
    }
    if not start_job:
        value_parameters.update({"streaminghost", "throttlelimit"})
    switch_parameters = {
        "confirm",
        "debug",
        "runas32",
        "verbose",
        "whatif",
    }
    parameter_names = (
        script_parameters
        | initialization_parameters
        | opaque_parameters
        | value_parameters
        | switch_parameters
    )

    def parameter(token: str) -> tuple[str | None, str | None]:
        raw = token.lstrip("-")
        name, separator, attached = raw.partition(":")
        lowered = name.lower()
        if lowered in parameter_names:
            return lowered, attached if separator else None
        matches = [
            candidate for candidate in parameter_names if candidate.startswith(lowered)
        ]
        if len(matches) != 1:
            return None, None
        return matches[0], attached if separator else None

    def literal_scriptblock(
        index: int,
        attached: str | None,
    ) -> tuple[str | None, int, str]:
        if attached is None:
            if index >= len(toks):
                return None, index, "A background-job scriptblock is missing."
            first = toks[index]
            index += 1
        else:
            first = attached
        if not first.startswith("{"):
            return (
                None,
                index,
                "A dynamic background-job scriptblock cannot be inspected safely.",
            )
        chunks = [first]
        depth = first.count("{") - first.count("}")
        if depth < 0:
            return None, index, "A background-job scriptblock is malformed."
        while depth > 0 and index < len(toks):
            chunk = toks[index]
            chunks.append(chunk)
            depth += chunk.count("{") - chunk.count("}")
            index += 1
        if depth != 0:
            return None, index, "A background-job scriptblock is malformed."
        literal = " ".join(chunks)
        body = unwrap_powershell_scriptblock(literal)
        if body == literal:
            return None, index, "A background-job scriptblock is malformed."
        return body, index, ""

    scripts: list[str] = []
    main_script_seen = False
    index = 1
    while index < len(toks):
        token = toks[index]
        if token.startswith("@"):
            return None, "A splatted background-job payload cannot be inspected safely."
        if token.startswith("-"):
            name, attached = parameter(token)
            if name is None:
                return None, "A background-job parameter cannot be inspected safely."
            index += 1
            if name in opaque_parameters:
                return None, "A file-backed or registered background job is opaque."
            if name in script_parameters | initialization_parameters:
                body, index, error = literal_scriptblock(index, attached)
                if body is None:
                    return None, error
                if name in script_parameters:
                    if main_script_seen:
                        return None, "A background job has multiple primary payloads."
                    main_script_seen = True
                scripts.append(body)
                continue
            if name in value_parameters:
                if attached is None:
                    if index >= len(toks):
                        return None, "A background-job parameter value is missing."
                    index += 1
                continue
            continue
        if main_script_seen:
            return (
                None,
                "A background-job positional payload cannot be inspected safely.",
            )
        body, index, error = literal_scriptblock(index, None)
        if body is None:
            return None, error
        main_script_seen = True
        scripts.append(body)

    if not main_script_seen:
        return None, "A background job has no inspectable primary scriptblock."
    return scripts, ""


_POWERSHELL_COMMON_TOKEN_PARAMETERS = {
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


def skip_powershell_literal_block(
    toks: list[str], index: int, opening: str
) -> int | None:
    """Skip a literal { ... } block; return the next index, None when unbalanced."""
    depth = opening.count("{") - opening.count("}")
    if depth < 0:
        return None
    while depth > 0:
        if index >= len(toks):
            return None
        depth += toks[index].count("{") - toks[index].count("}")
        index += 1
    return index


def resolve_powershell_parameter(
    token: str, parameter_names: set[str]
) -> tuple[str | None, str | None, bool]:
    """Resolve one -Parameter token to (name, bound value, had separator)."""
    name_text, separator, attached = token.lstrip("-").partition(":")
    lowered = name_text.lower()
    if lowered in parameter_names:
        return lowered, attached if separator else None, bool(separator)
    matches = [
        candidate for candidate in parameter_names if candidate.startswith(lowered)
    ]
    if len(matches) != 1:
        return None, None, bool(separator)
    return matches[0], attached if separator else None, bool(separator)


def powershell_invoke_command_opacity(toks: list[str]) -> str | None:
    """Reject Invoke-Command payloads whose program text is not a literal block.

    Literal `{ ... }` bodies are inspected as their own segments by the
    sanitized pass, so only dynamic, file-backed, splatted, or ambiguous
    payload shapes need to fail closed here.
    """
    script_parameters = {"scriptblock"}
    opaque_parameters = {"filepath"}
    value_parameters = _POWERSHELL_COMMON_TOKEN_PARAMETERS | {
        "applicationname",
        "argumentlist",
        "authentication",
        "certificatethumbprint",
        "computername",
        "cn",
        "configurationname",
        "connectionuri",
        "containerid",
        "credential",
        "hostname",
        "inputobject",
        "jobname",
        "keyfilepath",
        "options",
        "port",
        "session",
        "sessionname",
        "sessionoption",
        "subsystem",
        "throttlelimit",
        "username",
        "vmid",
        "vmname",
    }
    switch_parameters = {
        "allowredirection",
        "asjob",
        "confirm",
        "debug",
        "enablenetworkaccess",
        "hidecomputername",
        "indisconnectedsession",
        "nonewscope",
        "remotedebug",
        "runasadministrator",
        "usessl",
        "usewindowspowershell",
        "verbose",
        "whatif",
    }
    parameter_names = (
        script_parameters | opaque_parameters | value_parameters | switch_parameters
    )
    index = 1
    while index < len(toks):
        token = toks[index]
        if token.startswith("@"):
            return "A splatted Invoke-Command payload cannot be inspected safely."
        if token.startswith("-"):
            name, attached, separator = resolve_powershell_parameter(
                token, parameter_names
            )
            if name is None:
                return "An Invoke-Command parameter cannot be inspected safely."
            index += 1
            if name in opaque_parameters:
                return "A file-backed Invoke-Command payload is opaque."
            if name in script_parameters:
                if attached is None:
                    attached = toks[index] if index < len(toks) else ""
                    index += 1
                if not attached.startswith("{"):
                    return (
                        "A dynamic Invoke-Command scriptblock cannot be "
                        "inspected safely."
                    )
                next_index = skip_powershell_literal_block(toks, index, attached)
                if next_index is None:
                    return "An Invoke-Command scriptblock is malformed."
                index = next_index
                continue
            if name in value_parameters and not separator:
                index += 1
            continue
        if token.startswith("{"):
            next_index = skip_powershell_literal_block(toks, index + 1, token)
            if next_index is None:
                return "An Invoke-Command scriptblock is malformed."
            index = next_index
            continue
        # The positional payload of Invoke-Command is the ScriptBlock, so any
        # non-literal-block positional — a variable, a `(...)`/`@(...)`
        # subexpression such as [scriptblock]::Create(...), or a bareword — is
        # a dynamic scriptblock source the floor cannot inspect.
        return "A dynamic Invoke-Command scriptblock cannot be inspected safely."
    return None


def powershell_pipeline_scriptblock_opacity(head: str, toks: list[str]) -> str | None:
    """Reject pipeline scriptblock consumers whose payload is not a literal block.

    ForEach-Object/Where-Object execute scriptblocks for pipeline input, so a
    variable-stored block (or a member-name invocation) runs program text the
    floor never saw. Literal blocks stay allowed: their bodies are inspected
    as their own segments by the sanitized pass.
    """
    foreach = head in {"foreach-object", "%", "foreach"}
    # Only the `foreach` KEYWORD (never the % / ForEach-Object cmdlet aliases)
    # forms a loop statement, and only with a real `( <var> in ... )` header.
    # A parenthesized argument to % / ForEach-Object is a dynamic scriptblock
    # EXPRESSION and must fall through to the opacity checks below.
    if head == "foreach" and len(toks) > 1 and toks[1].startswith("("):
        header = " ".join(toks[1:])
        if re.search(r"\bin\b", header, re.IGNORECASE):
            return None  # `foreach ($item in ...)` statement; body splits elsewhere
    script_parameters = (
        {"begin", "end", "parallel", "process", "remainingscripts"}
        if foreach
        else {"filterscript"}
    )
    member_parameters = {"membername"} if foreach else set()
    value_parameters = _POWERSHELL_COMMON_TOKEN_PARAMETERS | (
        {"argumentlist", "inputobject", "throttlelimit", "timeoutseconds"}
        if foreach
        else {"inputobject"}
    )
    switch_parameters = (
        {"asjob", "confirm", "debug", "usenewrunspace", "verbose", "whatif"}
        if foreach
        else set()
    )
    parameter_names = (
        script_parameters | member_parameters | value_parameters | switch_parameters
    )
    index = 1
    while index < len(toks):
        token = toks[index]
        if token.startswith("@"):
            return "A splatted pipeline scriptblock cannot be inspected safely."
        if token.startswith("-"):
            name, attached, separator = resolve_powershell_parameter(
                token, parameter_names
            )
            if name is None:
                if foreach:
                    return "A pipeline cmdlet parameter cannot be inspected safely."
                index += 1  # Where-Object comparison operators are inert
                continue
            index += 1
            if name in member_parameters:
                return (
                    "ForEach-Object member invocation can execute uninspected "
                    "methods. Use an explicit scriptblock instead."
                )
            if name in script_parameters:
                if attached is None:
                    attached = toks[index] if index < len(toks) else ""
                    index += 1
                if not attached.startswith("{"):
                    return "A dynamic pipeline scriptblock cannot be inspected safely."
                next_index = skip_powershell_literal_block(toks, index, attached)
                if next_index is None:
                    return "A pipeline scriptblock is malformed."
                index = next_index
                continue
            if name in value_parameters and not separator:
                index += 1
            continue
        if token.startswith("{"):
            next_index = skip_powershell_literal_block(toks, index + 1, token)
            if next_index is None:
                return "A pipeline scriptblock is malformed."
            index = next_index
            continue
        # A `(...)`/`@(...)` subexpression (e.g. [scriptblock]::Create(...))
        # builds a scriptblock at runtime whose body the floor never sees.
        if token.startswith(("(", "@(")):
            return "A dynamic pipeline scriptblock cannot be inspected safely."
        if has_dynamic_shell_token(token):
            return "A dynamic pipeline scriptblock cannot be inspected safely."
        if foreach:
            return (
                "ForEach-Object member invocation can execute uninspected "
                "methods. Use an explicit scriptblock instead."
            )
        return None  # Where-Object property comparisons are inert data
    return None


def powershell_literal_scriptblock_bodies(toks: list[str]) -> list[str]:
    """Return the restored inner text of each literal `{ ... }` scriptblock in a
    pipeline cmdlet's argv, so quoted evaluator payloads inside the block (which
    the sanitized segment pass masks) can be recursively inspected."""
    bodies: list[str] = []
    index = 0
    while index < len(toks):
        token = toks[index]
        if token.startswith("{"):
            end = skip_powershell_literal_block(toks, index + 1, token)
            if end is None:
                break
            block = " ".join(toks[index:end]).strip()
            if block.startswith("{"):
                block = block[1:]
            if block.endswith("}"):
                block = block[:-1]
            bodies.append(restore_quoted_literal_markers(block.strip()))
            index = end
            continue
        index += 1
    return bodies


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
    markers = {"o", "c", "D"} if head == "curl" else {"o", "O", "a", "P"}
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


_WGET_EXECUTE_OUTPUT_COMMANDS = {
    "dirprefix",
    "logfile",
    "outputdocument",
    "savecookies",
    "warcfile",
}


def wget_execute_output_bindings(
    toks: list[str],
) -> tuple[list[tuple[str, str]] | None, str]:
    """Recover output-bearing wgetrc assignments passed through -e/--execute."""
    bindings: list[tuple[str, str]] = []
    prefix_flags = _DOWNLOADER_CLUSTER_PREFIXES["wget"]
    index = 1
    while index < len(toks):
        token = toks[index]
        directive = None
        consumes_next = False
        if token.startswith("--"):
            option, separator, attached = token.partition("=")
            lowered = option.lower()
            if len(lowered) >= len("--exe") and "--execute".startswith(lowered):
                directive = attached if separator else None
                consumes_next = not separator
        elif token.startswith("-"):
            body = token[1:]
            for offset, character in enumerate(body):
                if character == "e":
                    directive = body[offset + 1 :] or None
                    consumes_next = directive is None
                    break
                if character not in prefix_flags:
                    break

        if directive is None and consumes_next:
            if index + 1 >= len(toks):
                return None, "wget -e/--execute is missing its directive."
            directive = toks[index + 1]
            index += 1
        if directive is not None or consumes_next:
            restored = restore_quoted_literal_markers(directive or "").strip()
            if not restored or is_dynamic_value(restored):
                return None, "A dynamic or empty wget -e directive is opaque."
            assignment = re.fullmatch(r"([A-Za-z0-9_-]+)\s*=\s*(.*?)\s*", restored)
            if assignment is None or not assignment.group(2):
                return None, "A malformed wget -e directive is opaque."
            name = re.sub(r"[_-]", "", assignment.group(1).lower())
            if name in _WGET_EXECUTE_OUTPUT_COMMANDS:
                bindings.append((name, assignment.group(2)))
        index += 1
    return bindings, ""


_WGET_SERVER_NAME_DIRECTIVES = {"trustservernames", "contentdisposition"}


def wget_uses_server_named_output(toks: list[str]) -> bool:
    """Return whether wget lets the server pick the local output filename."""
    for token in toks[1:]:
        lowered = token.lower().split("=", 1)[0]
        if lowered in {"--trust-server-names", "--content-disposition"}:
            return True
    prefix_flags = _DOWNLOADER_CLUSTER_PREFIXES["wget"]
    index = 1
    while index < len(toks):
        token = toks[index]
        directive = None
        consumes_next = False
        if token.startswith("--"):
            option, separator, attached = token.partition("=")
            if len(option) >= len("--exe") and "--execute".startswith(option.lower()):
                directive = attached if separator else None
                consumes_next = not separator
        elif token.startswith("-"):
            for offset, character in enumerate(token[1:]):
                if character == "e":
                    directive = token[1:][offset + 1 :] or None
                    consumes_next = directive is None
                    break
                if character not in prefix_flags:
                    break
        if directive is None and consumes_next:
            if index + 1 >= len(toks):
                break
            directive = toks[index + 1]
            index += 1
        if directive:
            restored = restore_quoted_literal_markers(directive).strip()
            assignment = re.fullmatch(r"([A-Za-z0-9_-]+)\s*=\s*(.*?)\s*", restored)
            if assignment is not None:
                name = re.sub(r"[_-]", "", assignment.group(1).lower())
                value = assignment.group(2).strip().strip("'\"").lower()
                if name in _WGET_SERVER_NAME_DIRECTIVES and value not in {
                    "off",
                    "0",
                    "no",
                    "false",
                    "",
                }:
                    return True
        index += 1
    return False


_CURL_LONG_OPTIONS_WITH_VALUE = frozenset(
    {
        "--abstract-unix-socket",
        "--alt-svc",
        "--aws-sigv4",
        "--cacert",
        "--capath",
        "--cert",
        "--cert-type",
        "--ciphers",
        "--config",
        "--connect-timeout",
        "--connect-to",
        "--continue-at",
        "--cookie",
        "--cookie-jar",
        "--create-file-mode",
        "--crlfile",
        "--curves",
        "--data",
        "--data-ascii",
        "--data-binary",
        "--data-raw",
        "--data-urlencode",
        "--delegation",
        "--dns-interface",
        "--dns-ipv4-addr",
        "--dns-ipv6-addr",
        "--dns-servers",
        "--doh-url",
        "--dump-header",
        "--ech",
        "--egd-file",
        "--engine",
        "--etag-compare",
        "--etag-save",
        "--expect100-timeout",
        "--form",
        "--form-string",
        "--ftp-account",
        "--ftp-alternative-to-user",
        "--ftp-method",
        "--ftp-port",
        "--ftp-ssl-ccc-mode",
        "--happy-eyeballs-timeout-ms",
        "--haproxy-clientip",
        "--header",
        "--help",
        "--hostpubmd5",
        "--hostpubsha256",
        "--hsts",
        "--interface",
        "--ip-tos",
        "--ipfs-gateway",
        "--json",
        "--keepalive-cnt",
        "--keepalive-time",
        "--key",
        "--key-type",
        "--knownhosts",
        "--krb",
        "--krb4",
        "--libcurl",
        "--limit-rate",
        "--local-port",
        "--login-options",
        "--mail-auth",
        "--mail-from",
        "--mail-rcpt",
        "--max-filesize",
        "--max-redirs",
        "--max-time",
        "--netrc-file",
        "--noproxy",
        "--oauth2-bearer",
        "--output",
        "--output-dir",
        "--parallel-max",
        "--parallel-max-host",
        "--pass",
        "--pinnedpubkey",
        "--preproxy",
        "--proto",
        "--proto-default",
        "--proto-redir",
        "--proxy",
        "--proxy-cacert",
        "--proxy-capath",
        "--proxy-cert",
        "--proxy-cert-type",
        "--proxy-ciphers",
        "--proxy-crlfile",
        "--proxy-header",
        "--proxy-key",
        "--proxy-key-type",
        "--proxy-pass",
        "--proxy-pinnedpubkey",
        "--proxy-service-name",
        "--proxy-tls13-ciphers",
        "--proxy-tlsauthtype",
        "--proxy-tlspassword",
        "--proxy-tlsuser",
        "--proxy-user",
        "--proxy1.0",
        "--pubkey",
        "--quote",
        "--random-file",
        "--range",
        "--rate",
        "--referer",
        "--request",
        "--request-target",
        "--resolve",
        "--retry",
        "--retry-delay",
        "--retry-max-time",
        "--sasl-authzid",
        "--service-name",
        "--sigalgs",
        "--socks4",
        "--socks4a",
        "--socks5",
        "--socks5-gssapi-service",
        "--socks5-hostname",
        "--speed-limit",
        "--speed-time",
        "--ssl-sessions",
        "--stderr",
        "--telnet-option",
        "--tftp-blksize",
        "--time-cond",
        "--tls-max",
        "--tls13-ciphers",
        "--tlsauthtype",
        "--tlspassword",
        "--tlsuser",
        "--trace",
        "--trace-ascii",
        "--trace-config",
        "--unix-socket",
        "--upload-file",
        "--upload-flags",
        "--url",
        "--url-query",
        "--user",
        "--user-agent",
        "--variable",
        "--vlan-priority",
        "--write-out",
    }
)
_CURL_SHORT_OPTIONS_WITH_VALUE = frozenset("AEKCbcdDFHhmoPQreTtUuwXxyYz")
_CURL_SIDE_OUTPUT_OPTIONS = frozenset(
    {
        "--alt-svc",
        "--cookie-jar",
        "--dump-header",
        "--etag-save",
        "--hsts",
        "--libcurl",
        "--ssl-sessions",
        "--stderr",
        "--trace",
        "--trace-ascii",
    }
)
_CURL_GLOBAL_SIDE_OUTPUT_OPTIONS = frozenset(
    {"--libcurl", "--stderr", "--trace", "--trace-ascii"}
)
_CURL_OUTPUT_GLOB = re.compile(r"#(?:\d+|<[A-Za-z0-9]+>)")
_CURL_URL_BRACE_GLOB = re.compile(
    r"\{(?:<(?P<name>[A-Za-z0-9]+)>)?(?P<values>[^{}]*,[^{}]*)\}"
)
_CURL_URL_RANGE_GLOB = re.compile(
    r"\[(?:<(?P<name>[A-Za-z0-9]+)>)?"
    r"(?P<start>[A-Za-z]|\d+)-(?P<end>[A-Za-z]|\d+)"
    r"(?::(?P<step>\d+))?\]"
)


def curl_url_range_values(match: "re.Match[str]") -> list[str] | None:
    """Expand one bounded curl alpha/numeric URL range."""
    start_text = match.group("start")
    end_text = match.group("end")
    if start_text.isalpha() != end_text.isalpha():
        return None
    supplied_step = int(match.group("step") or "1")
    if supplied_step < 1:
        return None
    start = ord(start_text) if start_text.isalpha() else int(start_text)
    end = ord(end_text) if end_text.isalpha() else int(end_text)
    step = supplied_step if start <= end else -supplied_step
    values = list(range(start, end + (1 if step > 0 else -1), step))
    if len(values) > 64:
        return None
    if start_text.isalpha():
        return [chr(value) for value in values]
    width = max(len(start_text), len(end_text))
    zero_padded = start_text.startswith("0") or end_text.startswith("0")
    return [f"{value:0{width}d}" if zero_padded else str(value) for value in values]


def curl_url_glob_variants(
    url: str,
) -> list[tuple[str, dict[str, str]]] | None:
    """Expand bounded curl URL globs and retain output-template captures."""
    completed: list[tuple[str, dict[str, str]]] = []

    def expand(value: str, captures: dict[str, str], component: int) -> bool:
        matches = [
            match
            for match in (
                _CURL_URL_BRACE_GLOB.search(value),
                _CURL_URL_RANGE_GLOB.search(value),
            )
            if match is not None
        ]
        if not matches:
            completed.append((value, captures))
            return len(completed) <= 64
        match = min(matches, key=lambda candidate: candidate.start())
        if match.re is _CURL_URL_BRACE_GLOB:
            alternatives = match.group("values").split(",")
        else:
            alternatives = curl_url_range_values(match)
        if alternatives is None or not alternatives or len(alternatives) > 64:
            return False
        name = match.group("name")
        for alternative in alternatives:
            next_captures = dict(captures)
            next_captures[str(component)] = alternative
            if name:
                next_captures[name] = alternative
            next_value = value[: match.start()] + alternative + value[match.end() :]
            if not expand(next_value, next_captures, component + 1):
                return False
        return True

    restored = restore_quoted_literal_markers(url)
    return completed if expand(restored, {}, 1) else None


def curl_literal_path_mentions_secret(target: str) -> bool:
    """Match a curl-resolved literal path without reapplying shell glob rules."""
    normalized = restore_quoted_literal_markers(target).replace("\\", "/")
    return bool(_SECRET_PATH.search(normalized))


def curl_output_glob_targets(
    target: str,
    url: str | None,
    globbing: bool,
) -> list[str] | None:
    """Resolve curl #N/#<name> output templates for one URL."""
    restored = restore_quoted_literal_markers(target)
    if not globbing or not _CURL_OUTPUT_GLOB.search(restored):
        return [restored]
    if url is None:
        return None
    variants = curl_url_glob_variants(url)
    if variants is None:
        return None
    results = []
    for _expanded_url, captures in variants:
        results.append(
            _CURL_OUTPUT_GLOB.sub(
                lambda match: captures.get(
                    (
                        match.group(0)[2:-1]
                        if match.group(0).startswith("#<")
                        else match.group(0)[1:]
                    ),
                    match.group(0),
                ),
                restored,
            )
        )
    return results


def curl_remote_name_mentions_secret(url: str, globbing: bool) -> bool:
    """Apply curl's URL-derived filename rules before secret-path matching."""
    variants = curl_url_glob_variants(url) if globbing else [(url, {})]
    if variants is None:
        return True
    for expanded_url, _captures in variants:
        restored = restore_quoted_literal_markers(expanded_url)
        without_fragment = restored.split("#", 1)[0]
        without_query = without_fragment.split("?", 1)[0]
        path = without_query.rstrip("/\\")
        basename = re.split(r"[/\\]", path)[-1]
        if curl_literal_path_mentions_secret(basename):
            return True
    return False


def curl_write_out_risk(format_value: str | None) -> str:
    """Inspect curl write-out file switches without misreading escaped percent signs."""
    if format_value is None:
        return ""
    format_value = restore_quoted_literal_markers(format_value)
    if is_dynamic_value(format_value) or format_value.startswith("@"):
        return "A dynamic curl write-out format cannot be inspected safely."
    index = 0
    while index < len(format_value):
        if format_value[index] != "%":
            index += 1
            continue
        if index + 1 < len(format_value) and format_value[index + 1] == "%":
            index += 2
            continue
        marker = "%output{"
        if not format_value.startswith(marker, index):
            index += 1
            continue
        end = format_value.find("}", index + len(marker))
        if end < 0:
            return (
                "An incomplete curl write-out output target cannot be inspected safely."
            )
        target = format_value[index + len(marker) : end]
        if target.startswith(">>"):
            target = target[2:]
        if (
            is_dynamic_value(target)
            or _CURL_OUTPUT_GLOB.search(target)
            or token_mentions_secret_path(target)
        ):
            return (
                "curl write-out to an opaque or secret-looking file is floor-blocked."
            )
        index = end + 1
    return ""


def curl_side_output_risk(option: str, target: str | None) -> str:
    """Inspect a curl cache/log/code-generation output target."""
    if target is None or target in {"", "-", "%"}:
        return ""
    if is_dynamic_value(target) or re.match(r"^[<>]?\(", target):
        return f"A dynamic curl {option} destination cannot be inspected safely."
    if token_mentions_secret_path(target):
        return f"curl {option} output to a secret-looking file is floor-blocked."
    return ""


def curl_expanded_value_is_dynamic(target: str | None) -> bool:
    """Return whether a curl --expand-* value has unresolved interpolation."""
    if target is None:
        return True
    restored = restore_quoted_literal_markers(target)
    return bool(re.search(r"(?<!\\)\{\{", restored))


def curl_unproven_output_risk(toks: list[str]) -> str:
    """Return a deny reason when native curl can write an unproven path.

    Named without secret-ish keywords: CodeQL's name heuristic classifies any
    `*secret*` function's return as sensitive data, flagging the reason echo in
    respond() as clear-text logging (agent-harness#10, false positive)."""

    args = toks[1:]
    if not args or not (
        args[0].lower() == "--disable"
        or (args[0].startswith("-q") and not args[0].startswith("--"))
    ):
        return (
            "curl may load an ambient config with opaque output sinks; use "
            "-q/--disable as the first argument (and curl.exe in Windows PowerShell)."
        )

    selectors: list[tuple[str, str | None]] = []
    urls: list[str | None] = []
    remote_name_all = False
    remote_header_name = False
    output_dir: str | None = None
    output_dir_dynamic = False
    globbing = True
    side_outputs: dict[str, tuple[str, str | None, bool]] = {}
    global_side_outputs: dict[str, tuple[str, str | None, bool]] = {}
    write_out: tuple[str | None, bool] | None = None

    def remember_side_output(
        option: str,
        target: str | None,
        dynamic: bool = False,
    ) -> None:
        key = "--trace" if option in {"--trace", "--trace-ascii"} else option
        outputs = (
            global_side_outputs
            if option in _CURL_GLOBAL_SIDE_OUTPUT_OPTIONS
            else side_outputs
        )
        outputs[key] = (option, target, dynamic)

    def inspect_side_outputs(
        outputs: dict[str, tuple[str, str | None, bool]],
    ) -> str:
        for option, target, dynamic in outputs.values():
            if dynamic:
                return f"An expanded curl {option} target is opaque."
            reason = curl_side_output_risk(option, target)
            if reason:
                return reason
        return ""

    def inspect_group() -> str:
        reason = inspect_side_outputs(side_outputs)
        if reason:
            return reason
        if write_out is not None:
            format_value, dynamic = write_out
            if dynamic:
                return "An expanded curl write-out format cannot be inspected safely."
            reason = curl_write_out_risk(format_value)
            if reason:
                return reason
        for url_index, url in enumerate(urls):
            selector, target = (
                selectors[url_index]
                if url_index < len(selectors)
                else ("remote" if remote_name_all else "stdout", None)
            )
            writes_file = selector == "remote" or (
                selector == "file" and target is not None
            )
            if writes_file and output_dir is not None:
                if (
                    output_dir_dynamic
                    or is_dynamic_value(output_dir)
                    or re.match(r"^[<>]?\(", output_dir)
                    or token_mentions_secret_path(output_dir)
                ):
                    return "A curl output directory cannot be inspected safely."
            if selector == "remote":
                if remote_header_name:
                    return (
                        "curl remote-header output has a server-controlled filename "
                        "that cannot be inspected safely."
                    )
                if url is None:
                    return "A dynamic curl URL has an opaque remote-name destination."
                if curl_remote_name_mentions_secret(url, globbing):
                    return "A remote-name download would create a secret-looking file."
                continue
            if selector == "file" and target is not None:
                if is_dynamic_value(target) or re.match(r"^[<>]?\(", target):
                    return "A dynamic download destination cannot be inspected safely."
                resolved_targets = curl_output_glob_targets(target, url, globbing)
                if resolved_targets is None:
                    return "A curl output glob cannot be inspected safely."
                if any(
                    token_mentions_secret_path(resolved_target)
                    for resolved_target in resolved_targets
                ):
                    return "Downloading into a secret-looking file is floor-blocked."
        return ""

    def next_value(index: int, attached: str | None) -> tuple[str | None, int]:
        if attached is not None:
            return attached, index
        if index + 1 < len(args):
            return args[index + 1], index + 1
        return None, index

    def reset_group():
        nonlocal selectors, urls, remote_name_all
        nonlocal remote_header_name, output_dir, output_dir_dynamic, globbing
        nonlocal side_outputs, write_out
        selectors = []
        urls = []
        remote_name_all = False
        remote_header_name = False
        output_dir = None
        output_dir_dynamic = False
        globbing = True
        side_outputs = {}
        write_out = None

    def set_remote_name_selector(entry: tuple[str, str | None]) -> None:
        # -O and --no-remote-name toggle the NEXT URL's output mode; when several
        # stack before a URL, the last wins. Collapse a still-pending toggle from
        # this same pair so a later -O is not masked by an earlier
        # --no-remote-name. `remote-off` is a distinct no-file tag so an unrelated
        # --out-null stdout selector is never collapsed away.
        if len(selectors) > len(urls) and selectors[-1] in {
            ("remote", None),
            ("remote-off", None),
        }:
            selectors[-1] = entry
        else:
            selectors.append(entry)

    index = 0
    options_ended = False
    while index < len(args):
        token = args[index]
        lowered = token.lower()

        if options_ended:
            urls.append(None if is_dynamic_value(token) else token)
            index += 1
            continue
        if token == "--":
            options_ended = True
            index += 1
            continue
        if lowered == "--next":
            reason = inspect_group()
            if reason:
                return reason
            reset_group()
            index += 1
            continue

        raw_option, separator, raw_bound_value = token.partition("=")
        option = raw_option.lower()
        expanded = option.startswith("--expand-")
        canonical_option = "--" + option[len("--expand-") :] if expanded else option
        bound_value = raw_bound_value if separator else None

        if canonical_option == "--config":
            return "curl config files are opaque to the deny floor."
        if canonical_option in {"--remote-name-all", "--no-remote-name-all"}:
            remote_name_all = canonical_option == "--remote-name-all"
            index += 1
            continue
        if canonical_option in {"--remote-name", "--no-remote-name"}:
            set_remote_name_selector(
                ("remote", None)
                if canonical_option == "--remote-name"
                else ("remote-off", None)
            )
            index += 1
            continue
        if canonical_option in {
            "--remote-header-name",
            "--no-remote-header-name",
        }:
            remote_header_name = canonical_option == "--remote-header-name"
            index += 1
            continue
        if canonical_option in {"--globoff", "--no-globoff"}:
            globbing = canonical_option == "--no-globoff"
            index += 1
            continue
        if canonical_option in {"--out-null", "--no-out-null"}:
            selectors.append(("stdout", None))
            index += 1
            continue
        if canonical_option == "--output":
            target, index = next_value(index, bound_value)
            if expanded and curl_expanded_value_is_dynamic(target):
                return "An expanded curl output destination cannot be inspected safely."
            selectors.append(("stdout", None) if target == "-" else ("file", target))
            index += 1
            continue
        if canonical_option == "--output-dir":
            output_dir, index = next_value(index, bound_value)
            output_dir_dynamic = expanded and curl_expanded_value_is_dynamic(output_dir)
            index += 1
            continue
        if canonical_option == "--url":
            target, index = next_value(index, bound_value)
            restored_target = (
                restore_quoted_literal_markers(target) if target is not None else ""
            )
            if (
                target is None
                or is_dynamic_value(target)
                or (expanded and curl_expanded_value_is_dynamic(restored_target))
            ):
                return "A dynamic curl URL may activate opaque URL-file output."
            if restored_target.startswith("@"):
                return "A curl URL file has opaque remote-name destinations."
            urls.append(target)
            index += 1
            continue
        if canonical_option == "--write-out":
            target, index = next_value(index, bound_value)
            write_out = (
                target,
                expanded and curl_expanded_value_is_dynamic(target),
            )
            index += 1
            continue
        if canonical_option in _CURL_SIDE_OUTPUT_OPTIONS:
            target, index = next_value(index, bound_value)
            remember_side_output(
                canonical_option,
                target,
                expanded and curl_expanded_value_is_dynamic(target),
            )
            index += 1
            continue
        if canonical_option in _CURL_LONG_OPTIONS_WITH_VALUE:
            _target, index = next_value(index, bound_value)
            index += 1
            continue

        if token.startswith("--"):
            index += 1
            continue

        if token.startswith("-") and not token.startswith("--"):
            body = token[1:]
            offset = 0
            while offset < len(body):
                marker = body[offset]
                if marker == ":":
                    reason = inspect_group()
                    if reason:
                        return reason
                    reset_group()
                    offset += 1
                    continue
                if marker == "K":
                    return "curl config files are opaque to the deny floor."
                if marker == "O":
                    set_remote_name_selector(("remote", None))
                    offset += 1
                    continue
                if marker == "J":
                    remote_header_name = True
                    offset += 1
                    continue
                if marker == "g":
                    globbing = False
                    offset += 1
                    continue
                if marker in _CURL_SHORT_OPTIONS_WITH_VALUE:
                    attached = body[offset + 1 :] or None
                    target, index = next_value(index, attached)
                    if marker == "o":
                        selectors.append(
                            ("stdout", None) if target == "-" else ("file", target)
                        )
                    elif marker in {"c", "D"}:
                        remember_side_output(
                            "--cookie-jar" if marker == "c" else "--dump-header",
                            target,
                        )
                    elif marker == "w":
                        write_out = (target, False)
                    break
                offset += 1
            index += 1
            continue

        urls.append(None if is_dynamic_value(token) else token)
        index += 1

    reason = inspect_group()
    return reason or inspect_side_outputs(global_side_outputs)


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
    r"(^|[\\/])\.env(rc)?(\.[\w.]+)?([\\/]|$)|credential|secrets?\."
    r"|(^|[\\/._-])id_(?:rsa|dsa|ecdsa|ed25519)"
    r"|\.pem$",
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
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "key.pem",
}


def is_secret_path(target: str) -> bool:
    normalized = restore_quoted_literal_markers(target).replace("\\", "/")
    if _SECRET_PATH.search(normalized):
        return True
    basename = normalized.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(probe, basename) for probe in _SECRET_GLOB_PROBES)


_SECRET_FILENAME = re.compile(
    r"^(?:\.env(?:\.[\w.]+)?"
    r"|id_(?:rsa|dsa|ecdsa|ed25519)(?:[._-][\w.]+)?"
    r"|.+\.pem"
    r"|credentials?\.[\w.]+"
    r"|secrets?\.[\w.]+)$",
    re.IGNORECASE,
)


def brace_expand_variants(token: str) -> tuple[list[str], bool]:
    """Expand bounded Bash comma/sequence braces.

    Returns (variants, overflow). overflow=True means the expansion is
    unbounded or too large, so callers should fail closed.
    """
    variants = [token]
    while True:
        next_variants: list[str] = []
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
            alternatives = (
                match.group(1).split(",")
                if match is comma_match
                else brace_sequence_alternatives(match)
            )
            if alternatives is None:
                return [], True
            if len(next_variants) + len(alternatives) > 64:
                return [], True
            next_variants.extend(
                variant[: match.start()] + alternative + variant[match.end() :]
                for alternative in alternatives
            )
        variants = next_variants
        if not changed:
            break
    return variants, False


def _single_token_is_secret_filename(token: str) -> bool:
    normalized = (
        restore_quoted_literal_markers(token).replace("\\", "/").strip("'\"[]{}() ")
    )
    basename = normalized.rsplit("/", 1)[-1].lower()
    if any(fnmatch.fnmatchcase(probe, basename) for probe in _SECRET_GLOB_PROBES):
        return True
    return bool(_SECRET_FILENAME.match(basename))


def token_is_secret_filename(token: str) -> bool:
    """Stricter than ``token_mentions_secret_path``: match a secret FILE basename
    rather than any substring, for contexts (git refs/branches) where a loose
    ``credential`` substring would wrongly flag a branch like ``fix/credential-x``.

    Bash brace lists still expand (``{.env,README}`` -> ``.env``) so the strict
    predicate cannot be evaded by wrapping the secret name in a brace group.
    """
    variants, overflow = brace_expand_variants(token)
    if overflow:
        return True
    return any(_single_token_is_secret_filename(variant) for variant in variants)


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


def gnu_time_unproven_output(raw: list[str]) -> str | None:
    """Return 'dynamic'/'secret' when a GNU `time -o <file>` wrapper writes its
    timing report to a dynamic or secret-looking path, else None. `time` is a
    wrapper stripped before head resolution, so its -o value is inspected here."""
    index = 0
    while index < len(raw) and _ASSIGN.match(raw[index]):
        index += 1
    if index >= len(raw):
        return None
    base = _EXE_SUFFIX.sub("", raw[index].replace("\\", "/").split("/")[-1]).lower()
    if base != "time":
        return None
    index += 1
    while index < len(raw):
        token = raw[index]
        lowered = token.lower()
        value = None
        if lowered in {"-o", "--output"}:
            value = raw[index + 1] if index + 1 < len(raw) else None
            index += 2
        elif lowered.startswith("--output="):
            value = token.split("=", 1)[1]
            index += 1
        elif token.startswith("-o") and len(token) > 2:
            value = token[2:]
            index += 1
        else:
            index += 1
            continue
        if value is not None:
            if is_dynamic_value(value):
                return "dynamic"
            if token_mentions_secret_path(value):
                return "secret"
    return None


def _sed_edits_in_place(token: str) -> bool:
    """True when a sed argument requests in-place editing (-i / --in-place /
    bundled -ni). A value-taking flag (-e/-f/-l) consumes the rest of a short
    cluster, so an `i` after one (e.g. `-e'insert'`) is that value, not -i."""
    if token.startswith("--in-place"):
        return True
    if not token.startswith("-") or token.startswith("--"):
        return False
    for char in token[1:]:
        if char == "i":
            return True
        if char in "efl":  # -e/-f/-l take a value that consumes the cluster tail
            return False
    return False


def _chmod_loosens_access(mode: str) -> bool:
    """True when a chmod mode grants group/other read or write (exposing a
    secret). Owner-only/tightening modes (600, 400, 700, u+x, go-rwx) return
    False; an unparseable symbolic clause fails closed (True)."""
    if not mode:
        return False
    if re.fullmatch(r"[0-7]{3,4}", mode):
        # The last two octal digits are the group and other permissions; the
        # read (4) and write (2) bits there expose the file beyond its owner.
        return any(int(digit) & 0o6 for digit in mode[-2:])
    for clause in mode.split(","):
        match = re.match(r"^([ugoa]*)([-+=])([rwxXst]*)$", clause)
        if match is None:
            return True  # unrecognized symbolic clause: fail closed
        who, operator, perms = match.groups()
        if operator in {"+", "="} and ("r" in perms or "w" in perms):
            # An empty `who` means "all"; g/o/a each grant beyond the owner.
            if who == "" or any(target in who for target in "goa"):
                return True
    return False


def _command_option_value(token: str) -> tuple[bool, str | None]:
    """Recognize a `-c` / `--command` option (as flock and script use it),
    including the glued `--command=VALUE` form and unambiguous getopt_long
    abbreviations (`--com`, `--comm`, ...). Returns (matched, attached_value):
    attached is the glued value, or None when a separate value token follows."""
    if token.lower() == "-c":
        return True, None
    # getopt short options glue their value: `-c'rm -rf ~'` -> `-crm -rf ~`. Match
    # the exact lowercase `-c` (short options are case-sensitive; `-C` is not this
    # option) with a glued value, but never a long `--…` token.
    if token[:2] == "-c" and len(token) > 2 and not token.startswith("--"):
        return True, token[2:]
    name, separator, value = token.partition("=")
    lowered = name.lower()
    # `--command` is the only long option in these tools beginning `--com`, so any
    # `--com..`-through-`--command` prefix is an unambiguous abbreviation of it.
    if lowered.startswith("--com") and "--command".startswith(lowered):
        return True, (value if separator else None)
    return False, None


def _is_launcher_value_long(name: str, value_long: set) -> bool:
    """True when a --long option name is a value-taking option or an unambiguous
    getopt_long PREFIX abbreviation of one (`--int` -> --interval). Over-matching
    an ambiguous prefix only fails closed (skips a value that may be a positional
    -> the child is inspected, never allowed through)."""
    name = name.lower()
    return name in value_long or (
        len(name) >= 3 and any(option.startswith(name) for option in value_long)
    )


def _scan_launcher_options(
    toks: list[str],
    value_short: set,
    value_long: set,
    start: int = 1,
) -> tuple[int, set]:
    """Cluster-aware option scan for a positional-child launcher. Advances from
    `start` over options, arity-skipping value-taking short letters — whether
    separate (`-c 0-3`), glued (`-c0-3`), or in a CLUSTER (`-ac0-3`, `-aT 5000`)
    — and value-taking long options (`--x val` / `--x=val`). Returns
    (index_at_first_positional, set_of_value_short_letters_consumed)."""
    consumed: set = set()
    index = start
    while index < len(toks):
        token = toks[index]
        if token == "--":
            return index + 1, consumed
        if token.startswith("--"):
            name = token.lower().split("=", 1)[0]
            if "=" not in token and _is_launcher_value_long(name, value_long):
                index += 2  # separate long value (incl. prefix abbreviation)
            else:
                index += 1  # valueless long, or --opt=value (value glued)
            continue
        if token.startswith("-") and len(token) > 1:
            take_next = False
            for position, char in enumerate(token[1:]):
                if char in value_short:
                    consumed.add(char)
                    # A value-taking letter takes the cluster tail as its value
                    # if any remains, else the next token.
                    take_next = position == len(token[1:]) - 1
                    break
            index += 2 if take_next else 1
            continue
        return index, consumed
    return index, consumed


def _launcher_child_command(head: str, toks: list[str]) -> str | None:
    """Return a child command string for watch/flock/coproc/chrt/taskset, "" for
    none, or None when the child is opaque and the launcher must be denied."""
    if head == "watch":
        index, _ = _scan_launcher_options(toks, {"n"}, {"--interval"})
        child = toks[index:]
    elif head == "flock":

        def _flock_command(tok: str, follow: str | None) -> str | None:
            # Resolve a flock -c/--command (incl. --command=VALUE, getopt_long
            # abbreviations, and a -c inside a short cluster) to its child string.
            matched, attached = _command_option_value(tok)
            if matched:
                value = attached if attached is not None else follow
                return restore_quoted_literal_markers(value) if value else "\0"
            # -c bundled in a short cluster (`-nc'cmd'` / `-nc cmd`): the command
            # is the cluster tail after `c`, or the next token if `c` is last.
            if tok.startswith("-") and not tok.startswith("--") and "c" in tok[1:]:
                tail = tok[1:]
                cut = tail.index("c")
                if all(
                    ch in {"w", "E", "s", "x", "u", "n", "o", "F", "v"}
                    for ch in tail[:cut]
                ):
                    glued = tail[cut + 1 :]
                    value = glued if glued else follow
                    return restore_quoted_literal_markers(value) if value else "\0"
            return None

        index = 1
        while index < len(toks):
            token = toks[index]
            lowered = token.lower()
            follow = toks[index + 1] if index + 1 < len(toks) else None
            resolved = _flock_command(token, follow)
            if resolved is not None:
                return None if resolved == "\0" else resolved
            if token == "--":
                index += 1
                break
            # -w and -E take a value (case-sensitive short flags); cluster-aware.
            if token.startswith("-") and not token.startswith("--"):
                take_next = False
                for position, char in enumerate(token[1:]):
                    if char in {"w", "E"}:
                        take_next = position == len(token[1:]) - 1
                        break
                index += 2 if take_next else 1
                continue
            if _is_launcher_value_long(
                lowered.split("=", 1)[0], {"--timeout", "--conflict-exit-code"}
            ):
                index += 1 if "=" in token else 2  # glued value vs separate value
                continue
            if token.startswith("--"):
                index += 1  # valueless long flag (--verbose/--shared/...); step over
                continue
            break  # a non-option token: this is the lockfile/fd
        # toks[index] is the lock file/fd; the child command follows it. The
        # documented `flock [options] <file> -c <command>` form puts -c AFTER the
        # lockfile, so the child string can hide behind a post-lockfile -c.
        child = toks[index + 1 :]
        if child:
            resolved = _flock_command(child[0], child[1] if len(child) > 1 else None)
            if resolved is not None:
                return None if resolved == "\0" else resolved
    elif head in {"chrt", "taskset"}:
        # `chrt [opts] <prio> cmd` / `taskset [opts] <mask> cmd` run a child after
        # one scheduling positional. `-p`/--pid operates on an existing PID (no
        # child). taskset's -c/--cpu-list SUPPLIES the mask (no positional mask).
        if any(token in {"-p", "--pid"} for token in toks[1:]):
            return ""
        if head == "chrt":
            index, _ = _scan_launcher_options(
                toks,
                {"T", "D", "P"},
                {"--sched-runtime", "--sched-deadline", "--sched-period"},
            )
            child = toks[index + 1 :]  # skip the priority positional
        else:
            index, consumed = _scan_launcher_options(toks, {"c"}, {"--cpu-list"})
            # -c OR --cpu-list (incl. prefix abbreviation, glued or separate)
            # supplies the mask, so the first non-option is the child; otherwise
            # skip the positional mask before the child.
            mask_from_option = "c" in consumed or any(
                _is_launcher_value_long(token.split("=", 1)[0], {"--cpu-list"})
                for token in toks[1:index]
                if token.startswith("--")
            )
            child = toks[index:] if mask_from_option else toks[index + 1 :]
    else:  # coproc
        child = toks[1:]
        if any(token in {"{", "}"} or token.endswith("{") for token in child):
            return None  # compound coproc block is opaque
    if not child:
        return ""
    return shlex.join(restore_quoted_literal_markers(token) for token in child)


def parse_alias_definitions(head: str, toks: list[str]) -> dict[str, str]:
    """Return {name: body} for a Bash `alias name=body` or PowerShell
    Set-Alias/New-Alias definition, so a later invocation can be resolved to the
    real command instead of an uninspected alias head."""
    aliases: dict[str, str] = {}
    if head == "alias":
        for token in toks[1:]:
            if token.startswith("-"):
                continue
            name, separator, body = token.partition("=")
            if separator and name:
                aliases[name.lower()] = restore_quoted_literal_markers(body)
    elif head in {"set-alias", "sal", "new-alias", "nal"}:
        name = None
        value = None
        positionals: list[str] = []
        index = 1
        while index < len(toks):
            token = toks[index]
            option = token.lstrip("-/").split(":", 1)[0].lower()
            if token.startswith("-") and option:
                is_name = "name".startswith(option)
                is_value = "value".startswith(option)
                if is_name or is_value:
                    if ":" in token:
                        bound = token.split(":", 1)[1]
                        index += 1
                    else:
                        bound = toks[index + 1] if index + 1 < len(toks) else None
                        index += 2
                    if is_name:
                        name = bound
                    else:
                        value = bound
                    continue
                index += 1
                continue
            positionals.append(token)
            index += 1
        if name is None and positionals:
            name = positionals[0]
        if value is None and len(positionals) > 1:
            value = positionals[1]
        if name and value:
            aliases[name.lower()] = restore_quoted_literal_markers(value)
    return aliases


def _trap_handler_decision(toks: list[str], recurse):
    """Return a decision tuple when a Bash trap installs an executable handler,
    else None. `trap 'cmd' SIG` runs `cmd` when the signal fires."""
    args = toks[1:]
    if args and args[0] in {"-p", "--print", "-l", "--list"}:
        return None  # printing/listing traps executes nothing
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        return None
    handler = restore_quoted_literal_markers(args[0])
    if handler in {"", "-"}:
        return None  # reset to default disposition, nothing runs
    if is_dynamic_value(handler):
        return "deny", "A dynamic trap handler cannot be inspected safely."
    decision = recurse(handler)
    if decision[0] != "allow":
        return decision
    return None


def _ssh_runs_local_child(toks: list[str]) -> bool:
    """True when ssh argv selects a locally-executed child via ProxyCommand,
    LocalCommand, or a `Match exec` predicate, which OpenSSH runs through the
    user's shell. OpenSSH parses an -o value like a config line, so keyword and
    value may be separated by `=` OR whitespace (`-o "ProxyCommand cmd"` ==
    `-o ProxyCommand=cmd`)."""
    local_child = re.compile(r"(?:proxy|local)command[=\s]|match\s+.*\bexec\b")
    index = 1
    while index < len(toks):
        token = toks[index]
        lowered = token.lower()
        if token == "-o":
            value = (toks[index + 1] if index + 1 < len(toks) else "").lower()
            if local_child.match(value):
                return True
            index += 2
            continue
        if lowered.startswith("-o") and len(token) > 2:
            if local_child.match(lowered[2:]):
                return True
        index += 1
    return False


def _is_target_directory_long_option(option: str) -> bool:
    """Match --target-directory and its unambiguous GNU prefix abbreviations."""
    # cp/mv's only --t* option is --target-directory (--no-target-directory
    # carries the distinct --no- prefix), so any --t.. prefix is unambiguous.
    return (
        option.startswith("--t")
        and len(option) >= 3
        and "--target-directory".startswith(option)
    )


def gnu_target_directory_values(toks: list[str]) -> list[str]:
    """Return GNU coreutils -t/--target-directory destinations from an argv."""
    values: list[str] = []
    index = 1
    while index < len(toks):
        token = toks[index]
        if token == "--":
            break
        option = token.split("=", 1)[0]
        if (token == "--target-directory" or token == "-t") or (
            "=" not in token and _is_target_directory_long_option(option)
        ):
            if index + 1 < len(toks):
                values.append(toks[index + 1])
            index += 2
            continue
        if token.startswith("--target-directory=") or (
            "=" in token and _is_target_directory_long_option(option)
        ):
            values.append(token.split("=", 1)[1])
        elif token.startswith("-t") and len(token) > 2 and not token.startswith("--"):
            values.append(token[2:].lstrip("="))
        index += 1
    return values


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
    grep_option_args = args[: args.index("--")] if "--" in args else args
    if subcommand == "grep" and any(
        token == "-O"
        or token.startswith("-O")
        or git_option_abbreviates(
            token.lower().split("=", 1)[0],
            "--open-files-in-pager",
        )
        for token in grep_option_args
    ):
        return "Git grep pager execution is floor-blocked."
    if subcommand in {
        "clone",
        "fetch",
        "ls-remote",
        "pull",
        "remote",
        "push",
        "submodule",
    } and any(re.match(r"(?i)^ext::", token) for token in args):
        # git-remote-ext runs the command embedded in an ext:: URL to connect
        # (submodule add clones a command-line/user-protocol URL too).
        return "A git ext:: transport runs an arbitrary command; floor-blocked."
    if subcommand in {"clone", "fetch", "ls-remote", "pull"} and (
        git_option_is_present(
            args,
            "--upload-pack",
            {"-u"} if subcommand == "clone" else None,
        )
    ):
        return "A custom git upload-pack program can execute outside floor inspection."
    if subcommand == "clone":
        # clone --config takes effect before fetch: core.sshCommand and friends
        # run during the clone itself, exactly like a global `git -c` override.
        for config in git_option_values(args, "--config", {"-c"}):
            if config is None or has_dynamic_shell_token(config.split("=", 1)[0]):
                return "A git clone --config value is opaque to floor inspection."
            if protected_git_config_key(config.split("=", 1)[0].lower()):
                return "Git clone --config can inject execution or destination config."
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
            candidate = candidate.lstrip("\\/")
            if re.match(r"(?i)^\.(?:[\\/])?GIT_", candidate):
                candidate = re.sub(r"^\.(?:[\\/])?", "", candidate, count=1)
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


_POWERSHELL_PROVIDER_WRITERS = {
    "ac",
    "add-content",
    "clear-content",
    "clc",
    "new-item",
    "ni",
    "sc",
    "set-content",
    "set-item",
    "si",
}
_POWERSHELL_PROVIDER_VALUE_PARAMETERS = {
    "credential",
    "encoding",
    "erroraction",
    "errorvariable",
    "exclude",
    "filter",
    "include",
    "informationaction",
    "informationvariable",
    "itemtype",
    "name",
    "outbuffer",
    "outvariable",
    "pipelinevariable",
    "progressaction",
    "stream",
    "warningaction",
    "warningvariable",
}
_POWERSHELL_PROVIDER_SWITCH_PARAMETERS = {
    "asbytestream",
    "confirm",
    "debug",
    "force",
    "nonewline",
    "passthru",
    "verbose",
    "whatif",
}


def powershell_provider_assignment(raw: list[str]) -> tuple[str, str] | None:
    """Return the path/value written by a PowerShell provider cmdlet."""
    if not raw or raw[0].lower() not in _POWERSHELL_PROVIDER_WRITERS:
        return None
    path_value = None
    assigned_value = None
    positional = []
    opaque_parameter = False
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
            value_parameters = [
                name
                for name in _POWERSHELL_PROVIDER_VALUE_PARAMETERS
                if name.startswith(parameter)
            ]
            switch_parameters = [
                name
                for name in _POWERSHELL_PROVIDER_SWITCH_PARAMETERS
                if name.startswith(parameter)
            ]
            if len(value_parameters) == 1 and not switch_parameters:
                index += 1 if separator else 2
                continue
            if len(switch_parameters) == 1 and not value_parameters:
                index += 1
                continue
            opaque_parameter = True
            index += 1
            continue
        positional.append(token)
        index += 1
    if path_value is None and positional:
        path_value = positional.pop(0)
    if assigned_value is None and positional:
        assigned_value = positional[0]
    if opaque_parameter:
        path_value = "$HARNESS_OPAQUE_POWERSHELL_PROVIDER_PATH"
    return path_value or "", assigned_value or ""


def powershell_provider_copy_or_rename(
    raw: list[str],
) -> tuple[str, str, str] | None:
    """Return operation/source/destination for PowerShell copy or rename."""
    if not raw:
        return None
    first = raw[0].lower()
    if first in {"copy-item", "copy", "cp", "cpi"}:
        operation = "copy"
        destination_parameters = {"destination"}
    elif first in {"rename-item", "ren", "rni"}:
        operation = "rename"
        destination_parameters = {"newname"}
    else:
        return None
    source = None
    destination = None
    positional = []
    opaque_parameter = False
    value_parameters = (
        _POWERSHELL_PROVIDER_VALUE_PARAMETERS
        | _POWERSHELL_COMMON_VALUE_PARAMETERS
        | {
            "fromsession",
            "tosession",
        }
    )
    switch_parameters = _POWERSHELL_PROVIDER_SWITCH_PARAMETERS | {
        "container",
        "recurse",
    }
    index = 1
    while index < len(raw):
        token = raw[index]
        if token.startswith("-"):
            parameter, separator, bound = token.lstrip("-").partition(":")
            parameter = parameter.lower()
            role = None
            if parameter and any(
                name.startswith(parameter) for name in {"path", "literalpath", "pspath"}
            ):
                role = "source"
            elif parameter and any(
                name.startswith(parameter) for name in destination_parameters
            ):
                role = "destination"
            if role:
                value = (
                    bound
                    if separator
                    else (raw[index + 1] if index + 1 < len(raw) else "")
                )
                if role == "source":
                    source = value
                else:
                    destination = value
                index += 1 if separator else 2
                continue
            matching_values = [
                name for name in value_parameters if name.startswith(parameter)
            ]
            matching_switches = [
                name for name in switch_parameters if name.startswith(parameter)
            ]
            if len(matching_values) == 1 and not matching_switches:
                index += 1 if separator else 2
                continue
            if len(matching_switches) == 1 and not matching_values:
                index += 1
                continue
            opaque_parameter = True
            index += 1
            continue
        positional.append(token)
        index += 1
    if source is None and positional:
        source = positional.pop(0)
    if destination is None and positional:
        destination = positional[0]
    if opaque_parameter:
        destination = "$HARNESS_OPAQUE_POWERSHELL_PROVIDER_DESTINATION"
    return operation, source or "", destination or ""


def powershell_environment_provider_path(value: str) -> bool:
    """Return whether a path names PowerShell's Environment provider."""
    lowered = restore_quoted_literal_markers(value).lower().strip("'\"")
    return lowered.startswith(("env:", "environment::"))


def dotnet_environment_mutations(raw: list[str]) -> list[tuple[str, str]]:
    """Return every .NET environment setter name/value pair in a segment."""
    return [
        (match.group(1), match.group(2))
        for match in re.finditer(
            r"(?i)(?:\[(?:system\.)?environment\])::setenvironmentvariable\("
            r"\s*([^,]+)\s*,\s*([^,)]+)",
            restore_quoted_literal_markers(" ".join(raw)),
        )
    ]


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

    provider_assignment = powershell_provider_assignment(raw)
    if provider_assignment is not None:
        path_value, assigned_value = provider_assignment
        name = git_environment_name(path_value)
        if name in _GIT_TRACE_ENVIRONMENT:
            mutations.append((name, assigned_value))
        return mutations

    for name_token, value in dotnet_environment_mutations(raw):
        name = git_environment_name(name_token)
        if name in _GIT_TRACE_ENVIRONMENT:
            mutations.append((name, value))
    return mutations


def dangerous_git_trace_environment_mutation(raw: list[str]) -> bool:
    """Return whether a segment establishes an unsafe Git trace setting."""
    return any(
        dangerous_git_trace_setting(name, value)
        for name, value in git_trace_environment_mutations(raw)
    )


def dangerous_git_index_file_mutation(raw: list[str]) -> bool:
    """True when GIT_INDEX_FILE selects a secret-looking or dynamic path (git
    writes its index there). Checks inherited env and leading assignments."""

    def unsafe(value: str) -> bool:
        expanded = expand_environment_references(
            restore_quoted_literal_markers(value).strip("'\"")
        )
        return (
            expanded is None
            or has_dynamic_shell_token(expanded)
            or token_mentions_secret_path(expanded)
        )

    if any(
        name.upper() == "GIT_INDEX_FILE" and unsafe(value)
        for name, value in os.environ.items()
    ):
        return True
    for token in raw:
        base = _EXE_SUFFIX.sub("", token.replace("\\", "/").split("/")[-1]).lower()
        if base == "git":
            break
        if _ASSIGN.match(token) and git_environment_name(token) == "GIT_INDEX_FILE":
            return unsafe(token.split("=", 1)[1])
    return False


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
_GIT_REPOSITORY_ENVIRONMENT = {"GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"}
_GIT_REPOSITORY_CONTEXT_ENVIRONMENT = {
    "GIT_CONFIG_NOSYSTEM",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "USERPROFILE",
    "XDG_CONFIG_HOME",
}
_GIT_REPOSITORY_COMMAND_ENVIRONMENT = (
    _GIT_REPOSITORY_ENVIRONMENT | _GIT_REPOSITORY_CONTEXT_ENVIRONMENT
)
_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT = "<UNKNOWN_REPOSITORY_ENVIRONMENT>"
_UNKNOWN_GIT_PROCESS_ENVIRONMENT = "<UNKNOWN_PROCESS_ENVIRONMENT>"
_POSIX_ASSIGNMENT_PERSISTING_BUILTINS = {
    ".",
    ":",
    "break",
    "continue",
    "eval",
    "exec",
    "exit",
    "export",
    "readonly",
    "return",
    "set",
    "shift",
    "times",
    "trap",
    "unset",
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
    if subcommand == "stash":
        # Only the read actions paginate; stash push/pop/apply do not.
        action = next(
            (token.lower() for token in args if not token.startswith("-")), ""
        )
        return action in {"list", "show"}
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


_GIT_EDITOR_MESSAGE_SUBCOMMANDS = {
    "commit",
    "merge",
    "tag",
    "notes",
    "revert",
    "cherry-pick",
}


def git_editor_message_is_supplied(subcommand: str, args: list[str]) -> bool:
    """Return whether a message/file/no-edit source prevents the editor opening.

    Case-sensitive: ``-C``/``--reuse-message`` and ``-F``/``--file`` supply a
    message (no editor), while ``-c``/``--reedit-message`` open the editor.
    For ``revert``/``cherry-pick`` the short ``-m`` is the mainline parent
    NUMBER, not a message, and does NOT suppress the default editor — only
    ``--no-edit`` / ``--no-commit`` (``-n``) do.
    """
    if subcommand in {"revert", "cherry-pick"}:
        for token in args:
            name = token.split("=", 1)[0]
            lowered = name.lower()
            if name == "-n":
                return True
            if lowered == "--no-edit" or (
                name.startswith("--")
                and (
                    git_option_abbreviates(lowered, "--no-edit")
                    or git_option_abbreviates(lowered, "--no-commit")
                )
            ):
                return True
        return False
    for token in args:
        name = token.split("=", 1)[0]
        lowered = name.lower()
        if name in {"-m", "-F", "-C"}:
            return True
        # Clustered/attached short forms supply a message: -am, -mWIP, -FNOTES,
        # -CHEAD. The message option letter must be reached through non-value-
        # consuming switch letters only (`-a` --all); a value-consuming option
        # such as -S/-t/-c/-s(strategy) would otherwise swallow a value whose
        # text merely resembles m/F/C. Case-sensitive: -F/-C are message flags
        # while lowercase -c (reedit) opens the editor and must NOT count.
        if re.match(r"^-a?[mFC]", name):
            return True
        if lowered == "--no-edit" or (
            name.startswith("--")
            and (
                git_option_abbreviates(lowered, "--message")
                or git_option_abbreviates(lowered, "--file")
                or git_option_abbreviates(lowered, "--reuse-message")
                or git_option_abbreviates(lowered, "--no-edit")
            )
        ):
            return True
    return False


def git_editor_edit_is_forced(args: list[str]) -> bool:
    """Return whether an explicit --edit/-e forces the editor back on."""
    return any(
        token == "-e"
        or git_option_abbreviates(token.lower().split("=", 1)[0], "--edit")
        for token in args
    )


def git_editor_is_reachable(subcommand: str, args: list[str]) -> bool:
    """Return whether Git can launch the editor selected by GIT_EDITOR."""
    lowered = [token.lower().split("=", 1)[0] for token in args]
    if subcommand == "add":
        return any(
            token == "-e" or git_option_abbreviates(token, "--edit")
            for token in lowered
        )
    if subcommand == "config":
        return any(
            token == "-e" or git_option_abbreviates(token, "--edit")
            for token in lowered
        )
    if subcommand == "branch":
        return any(
            git_option_abbreviates(token, "--edit-description") for token in lowered
        )
    if subcommand not in _GIT_EDITOR_SUBCOMMANDS:
        return False
    # These subcommands open the editor for a message, but a supplied
    # message/file/no-edit source suppresses it unless --edit forces it back.
    if (
        subcommand in _GIT_EDITOR_MESSAGE_SUBCOMMANDS
        and git_editor_message_is_supplied(subcommand, args)
    ):
        return git_editor_edit_is_forced(args)
    return True


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
    # Git documents GIT_EDITOR falling back to EDITOR/VISUAL and GIT_PAGER
    # falling back to PAGER, so inherited fallbacks share the same scope.
    if name in {"EDITOR", "VISUAL"}:
        return git_editor_is_reachable(subcommand, args)
    if name == "PAGER":
        return git_pager_is_reachable(subcommand, args, global_args)
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
        if name.upper() in _GIT_PROCESS_COMMAND_ENVIRONMENT
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


def git_process_environment_mutations(
    raw: list[str],
    environment_provider_context: bool = False,
) -> set[str]:
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
    provider_assignment = powershell_provider_assignment(raw)
    if provider_assignment is not None:
        name = git_environment_name(provider_assignment[0])
        if name in _GIT_PROCESS_COMMAND_ENVIRONMENT:
            mutations.add(name)
    provider_copy = powershell_provider_copy_or_rename(raw)
    if provider_copy is not None:
        _operation, source, destination = provider_copy
        source_is_environment = powershell_environment_provider_path(source)
        if (
            source_is_environment
            or environment_provider_context
            or powershell_environment_provider_path(destination)
        ):
            name = git_environment_name(destination)
            if name in _GIT_PROCESS_COMMAND_ENVIRONMENT:
                mutations.add(name)
            elif has_dynamic_shell_token(destination):
                mutations.add(_UNKNOWN_GIT_PROCESS_ENVIRONMENT)
    mutations.update(
        name
        for name_token, _value in dotnet_environment_mutations(raw)
        if (name := git_environment_name(name_token))
        in _GIT_PROCESS_COMMAND_ENVIRONMENT
    )
    return mutations


def git_repository_environment_name(token: str) -> str:
    """Normalize shell and PowerShell-provider repository selector names."""
    return git_environment_name(token).lstrip("\\/")


def dynamic_environment_name_operand(token: str) -> bool:
    """Return whether a mutation's variable-name operand is shell-derived."""
    candidate = restore_quoted_literal_markers(token).split("=", 1)[0]
    return has_dynamic_shell_token(candidate)


def command_scoped_repository_environment(raw: list[str]) -> set[str]:
    """Return repository selectors scoped to this command and its children."""
    selections = set()
    index = 0
    while index < len(raw):
        token = raw[index]
        if _ASSIGN.match(token):
            name = git_repository_environment_name(token)
            if name in _GIT_REPOSITORY_COMMAND_ENVIRONMENT:
                selections.add(name)
            index += 1
            continue
        executable = token.lstrip("({").rstrip(")}")
        base = _EXE_SUFFIX.sub("", executable.replace("\\", "/").split("/")[-1]).lower()
        if base not in _WRAPPERS:
            break
        next_index = wrapper_command_index(base, raw, index)
        if next_index is None:
            break
        for prefix_token in raw[index + 1 : next_index]:
            if _ASSIGN.match(prefix_token):
                name = git_repository_environment_name(prefix_token)
                if name in _GIT_REPOSITORY_COMMAND_ENVIRONMENT:
                    selections.add(name)
            elif "=" in prefix_token and dynamic_environment_name_operand(prefix_token):
                selections.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)
        index = next_index
    return selections


def git_repository_environment_mutations(raw: list[str]) -> set[str]:
    """Return persistent repository selectors established by one shell segment."""
    if not raw:
        return set()
    mutations = set()
    first = raw[0].lower()
    if command_head(raw)[0] in _POSIX_ASSIGNMENT_PERSISTING_BUILTINS:
        mutations.update(command_scoped_repository_environment(raw))

    if first in {".", "source"} and len(raw) > 1:
        mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)
    script_token = raw[1] if first == "call" and len(raw) > 1 else raw[0]
    script_path = restore_quoted_literal_markers(script_token).strip("'\"").lower()
    if script_path.endswith((".bat", ".cmd", ".ps1")):
        mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)

    if command_head(raw)[0] == "":
        mutations.update(
            name
            for token in raw
            if _ASSIGN.match(token)
            and (name := git_repository_environment_name(token))
            in _GIT_REPOSITORY_COMMAND_ENVIRONMENT
        )

    if first in {"declare", "readonly", "typeset"} and any(
        token == "--export" or (token.startswith("-") and "x" in token.lstrip("-"))
        for token in raw[1:]
    ):
        mutations.update(
            name
            for token in raw[1:]
            if (name := git_repository_environment_name(token))
            in _GIT_REPOSITORY_COMMAND_ENVIRONMENT
        )
        if any(
            dynamic_environment_name_operand(token)
            for token in raw[1:]
            if not token.startswith("-")
        ):
            mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)

    if first == "setenv":
        mutations.update(
            name
            for token in raw[1:]
            if (name := git_repository_environment_name(token))
            in _GIT_REPOSITORY_COMMAND_ENVIRONMENT
        )
        name_operand = next(
            (token for token in raw[1:] if not token.startswith("-")), ""
        )
        if dynamic_environment_name_operand(name_operand):
            mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)

    if first.startswith(("$env:", "${env:")) and (
        "=" in raw[0] or (len(raw) > 1 and raw[1] == "=")
    ):
        if dynamic_environment_name_operand(raw[0]):
            mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)
        name = git_repository_environment_name(raw[0])
        if name in _GIT_REPOSITORY_COMMAND_ENVIRONMENT:
            mutations.add(name)

    if first in {"export", "set", "setx"}:
        mutations.update(
            name
            for token in raw[1:]
            if (name := git_repository_environment_name(token))
            in _GIT_REPOSITORY_COMMAND_ENVIRONMENT
        )
        name_operands = (
            [token for token in raw[1:] if not token.startswith("-")]
            if first == "export"
            else [next((token for token in raw[1:] if not token.startswith("-")), "")]
        )
        if any(dynamic_environment_name_operand(token) for token in name_operands):
            mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)

    provider_assignment = powershell_provider_assignment(raw)
    if provider_assignment is not None:
        path_value, _value = provider_assignment
        if has_dynamic_shell_token(path_value):
            mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)
        name = git_repository_environment_name(path_value)
        if name in _GIT_REPOSITORY_COMMAND_ENVIRONMENT:
            mutations.add(name)

    provider_copy = powershell_provider_copy_or_rename(raw)
    if provider_copy is not None:
        operation, source, destination = provider_copy
        destination_name = git_repository_environment_name(destination)
        source_is_environment = powershell_environment_provider_path(source)
        if operation == "copy":
            if has_dynamic_shell_token(destination):
                mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)
            if destination_name in _GIT_REPOSITORY_COMMAND_ENVIRONMENT:
                mutations.add(destination_name)
        elif (
            source_is_environment
            and destination_name in _GIT_REPOSITORY_COMMAND_ENVIRONMENT
        ):
            mutations.add(destination_name)
        elif has_dynamic_shell_token(source) or (
            source_is_environment and has_dynamic_shell_token(destination)
        ):
            mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)

    for name_token, _value in dotnet_environment_mutations(raw):
        if has_dynamic_shell_token(name_token):
            mutations.add(_UNKNOWN_GIT_REPOSITORY_ENVIRONMENT)
        name = git_repository_environment_name(name_token)
        if name in _GIT_REPOSITORY_COMMAND_ENVIRONMENT:
            mutations.add(name)
    return mutations


def is_git_config_environment_mutation(
    raw: list[str],
    environment_provider_context: bool = False,
) -> bool:
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
    provider_assignment = powershell_provider_assignment(raw)
    if provider_assignment is not None:
        return is_git_config_environment_name(provider_assignment[0])
    provider_copy = powershell_provider_copy_or_rename(raw)
    if provider_copy is not None:
        _operation, source, destination = provider_copy
        source_is_environment = powershell_environment_provider_path(source)
        if environment_provider_context and (
            has_dynamic_shell_token(destination)
            or is_git_config_environment_name(destination)
        ):
            return True
        if source_is_environment and (
            has_dynamic_shell_token(source) or has_dynamic_shell_token(destination)
        ):
            return True
        if source_is_environment or powershell_environment_provider_path(destination):
            return is_git_config_environment_name(destination)
    if any(
        is_git_config_environment_name(name)
        for name, _value in dotnet_environment_mutations(raw)
    ):
        return True
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

# worktree options that consume a SEPARATE value token; skipping them keeps
# the action/path positionals aligned for destination inspection.
_GIT_WORKTREE_VALUE_OPTIONS = {"-b", "-B", "--reason"}

# clone options that consume a SEPARATE value token; skipping them keeps the
# repository/destination positionals aligned for destination inspection.
_GIT_CLONE_VALUE_OPTIONS = {
    "-b",
    "--branch",
    "--bundle-uri",
    "-c",
    "--config",
    "--depth",
    "--filter",
    "-j",
    "--jobs",
    "-o",
    "--origin",
    "--reference",
    "--reference-if-able",
    "--revision",
    "--separate-git-dir",
    "--server-option",
    "--shallow-exclude",
    "--shallow-since",
    "--template",
    "-u",
    "--upload-pack",
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
        "alias",
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
    target = powershell_location_target(toks)
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


def powershell_location_target(toks: list[str]) -> str | None:
    """Return a statically named PowerShell location operand when present."""
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
    return target


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

# Windows PowerShell (powershell.exe, 5.1) binds a bare trailing token to an
# implicit -Command, so `powershell git push --force` executes the force-push.
# These are its own options; the first token that is neither locates the payload.
_POWERSHELL_SWITCH_OPTIONS = {
    "noprofile",
    "nologo",
    "noninteractive",
    "noexit",
    "sta",
    "mta",
    "interactive",
}
_POWERSHELL_VALUE_OPTIONS = {
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


def powershell_implicit_command(toks: list[str]) -> str | None:
    """Return the implicit -Command payload of a bare powershell.exe invocation.

    Returns the joined payload string, "" when only known options are present
    (no payload), or None when an unknown/ambiguous option makes the payload
    position unlocatable (caller fails closed).
    """
    index = 1
    while index < len(toks):
        token = toks[index]
        if not token.startswith(("-", "/")):
            return " ".join(toks[index:])
        option, separator, _bound = token.lstrip("-/").lower().partition(":")
        if not option:
            return None
        is_switch = any(name.startswith(option) for name in _POWERSHELL_SWITCH_OPTIONS)
        is_value = any(name.startswith(option) for name in _POWERSHELL_VALUE_OPTIONS)
        if is_switch and not is_value:
            index += 1
            continue
        if is_value and not is_switch:
            index += 1 if separator else 2
            continue
        return None
    return ""


def has_opaque_posix_shell_input(toks: list[str]) -> bool:
    """Reject shell program text supplied through opaque stdin/file expansion."""
    has_command_flag = any(
        token == "-c" or bool(re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", token))
        for token in toks[1:]
    )

    def reads_program_from_stdin(redirect_index: int) -> bool:
        # A shell runs stdin as program text only when neither a -c command
        # string nor a script-file operand (a non-option token before the
        # redirect) supplies the program.
        if has_command_flag:
            return False
        return not any(not toks[i].startswith("-") for i in range(1, redirect_index))

    for index, token in enumerate(toks[1:], start=1):
        if token == "<<<":
            return True
        if token != "<" or index + 1 >= len(toks):
            continue
        candidate_index = index + 1
        if toks[candidate_index] == "<":
            candidate_index += 1
        candidate = toks[candidate_index] if candidate_index < len(toks) else ""
        if candidate.lstrip().startswith("("):
            return True
        # A plain `< file` redirect feeds the file's contents to a shell that
        # reads its program from stdin, which the floor cannot inspect.
        if reads_program_from_stdin(index):
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
    _git_repository_environment: frozenset[str] | None = None,
):
    """Return (decision, reason). decision in {'allow', 'ask', 'deny'}."""
    if _remote_cache is None:
        _remote_cache = {}
    if _remote_deadline is None:
        _remote_deadline = time.monotonic() + _REMOTE_RESOLUTION_BUDGET_SECONDS
    repository_environment_seed = set(_git_repository_environment or ())
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
            frozenset(repository_environment_seed),
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
    environment_provider_context = False
    active_git_process_environment: set[str] = set()
    active_git_repository_environment = set(repository_environment_seed)
    command_aliases: dict[str, str] = {}
    previous_pass = None

    def _recurse_child(child_command: str):
        """Inspect a wrapper/launcher's child command with the live segment cwd
        and Git-env context. Closes over the loop locals, read at call time."""
        return check(
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
            frozenset(effective_git_repository_environment),
        )

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
            environment_provider_context = False
            active_git_process_environment = set()
            active_git_repository_environment = set(repository_environment_seed)
            command_aliases = {}
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
        if dangerous_git_index_file_mutation(raw):
            return (
                "deny",
                "GIT_INDEX_FILE to a secret-looking or dynamic path is floor-blocked.",
            )
        if is_git_config_environment_mutation(raw, environment_provider_context):
            return (
                "deny",
                "Mutating Git's config-injection environment is floor-blocked.",
            )
        process_environment_mutations = git_process_environment_mutations(
            raw, environment_provider_context
        )
        if process_environment_mutations & (
            _GIT_PROCESS_ENVIRONMENT | {_UNKNOWN_GIT_PROCESS_ENVIRONMENT}
        ):
            return (
                "deny",
                "Mutating a process-launching Git environment variable is floor-blocked.",
            )
        active_git_process_environment.update(process_environment_mutations)
        active_git_repository_environment.update(
            git_repository_environment_mutations(raw)
        )
        effective_git_repository_environment = (
            active_git_repository_environment
            | command_scoped_repository_environment(raw)
        )
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
                        frozenset(effective_git_repository_environment),
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
        time_output = gnu_time_unproven_output(raw)
        if time_output == "dynamic":
            return "deny", "A dynamic GNU time -o target cannot be inspected safely."
        if time_output == "secret":
            return (
                "deny",
                "GNU time -o output to a secret-looking file is floor-blocked.",
            )
        head, toks = command_head(raw)
        if not toks:
            continue
        # Resolve a previously-defined alias to its real command so an aliased
        # `gp push --force` / `zap` is inspected, not treated as an unknown head.
        # Bash re-scans the first word after each alias expansion, so an alias
        # chain (`alias b='rm -rf ~'; alias a=b; a`) resolves transitively;
        # resolve in a bounded loop, capped to avoid a self-referential cycle.
        if quote_aware:
            seen_aliases: set[str] = set()
            while (
                head in command_aliases
                and head not in seen_aliases
                and len(seen_aliases) < 16
            ):
                seen_aliases.add(head)
                expansion = command_aliases[head]
                if not expansion or is_dynamic_value(expansion):
                    break
                head, toks = command_head(tokens(expansion) + toks[1:])
                if not toks:
                    break
            if not toks:
                continue
        if quote_aware:
            command_aliases.update(parse_alias_definitions(head, toks))
        # A BASH_ENV startup file is read and executed by a non-interactive bash
        # (`bash -c ...`) before the command body runs, so a leading (or env-set)
        # BASH_ENV assignment injects opaque program text the floor cannot see.
        if head in _POSIX_SHELL_HEADS and any(
            re.match(r"^BASH_ENV=\S", token) for token in raw
        ):
            return (
                "deny",
                "A BASH_ENV startup file runs opaque program text before the shell body.",
            )
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
                    frozenset(effective_git_repository_environment),
                )
                if evaluated_decision[0] != "allow":
                    return evaluated_decision
            continue
        if head in {
            "sudo",
            "su",
            "doas",
            "pkexec",
            "run0",
            "please",
            "runas",
            "runuser",
            "setpriv",
            "sg",
        }:
            return (
                "deny",
                f"{head} is blocked at the floor: privilege/identity elevation conceals "
                "an uninspected child command. If elevation is truly needed, the human runs it.",
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
                frozenset(effective_git_repository_environment),
            )
            if child_decision[0] != "allow":
                return child_decision
            continue
        if head in {"start-job", "sajb", "start-threadjob"}:
            if not quote_aware:
                continue
            job_scripts, error = powershell_job_scriptblocks(toks)
            if job_scripts is None:
                return "deny", error
            for job_script in job_scripts:
                child_decision = check(
                    job_script,
                    tier_cfg,
                    project_dir,
                    current_cwd,
                    _depth + 1,
                    cwd_uncertain,
                    cwd_changed,
                    remote_resolver,
                    _remote_cache,
                    _remote_deadline,
                    frozenset(effective_git_repository_environment),
                )
                if child_decision[0] != "allow":
                    return child_decision
            continue
        if head in {"invoke-command", "icm"}:
            if not quote_aware:
                continue
            invoke_error = powershell_invoke_command_opacity(toks)
            if invoke_error:
                return "deny", invoke_error
            continue
        if head in {"foreach-object", "%", "foreach", "where-object", "?", "where"}:
            if not quote_aware:
                continue
            pipeline_error = powershell_pipeline_scriptblock_opacity(head, toks)
            if pipeline_error:
                return "deny", pipeline_error
            # A literal ForEach-Object block executes its body per pipeline item,
            # so inspect it: a quoted `iex 'git push --force'` inside is masked
            # from the segment pass. Where-Object blocks are filter expressions
            # (property comparisons), not command bodies, so they are left inert.
            if head in {"foreach-object", "%", "foreach"}:
                for body in powershell_literal_scriptblock_bodies(toks):
                    if not body or is_dynamic_value(body):
                        continue
                    body_head, _ = command_head(tokens(body))
                    # Only a command invocation is recursed; a pure expression or
                    # member access (`$_.Name`, `1..3`) is inert output, not a
                    # command, and its head does not start with a letter.
                    if not body_head or not re.match(r"^[A-Za-z]", body_head):
                        continue
                    body_decision = _recurse_child(body)
                    if body_decision[0] != "allow":
                        return body_decision
            continue
        if head == "start":
            return (
                "deny",
                "A process launcher can conceal an irreversible child command. Run the child directly.",
            )
        if head in {"systemd-run", "nsenter", "unshare", "setarch", "capsh"}:
            # These launchers have option grammars where reconstructing which
            # flags consume a value is error-prone, so a child command can hide
            # behind a misparsed option. They are rarely legitimate in an agent
            # shell, so treat them as opaque rather than risk a false allow.
            return (
                "deny",
                f"{head} can launch an uninspected child command; run the child directly.",
            )
        if head == "script":
            # `script -c <cmd> [file]` runs a child command; recurse it (including
            # the glued `--command=` and abbreviated `--com` spellings). Plain
            # `script [file]` only records an interactive session whose commands
            # the floor still inspects as they are typed, so it is allowed.
            for command_index, token in enumerate(toks[1:], start=1):
                matched, attached = _command_option_value(token)
                if not matched:
                    continue
                if attached is not None:
                    value = attached
                elif command_index + 1 < len(toks):
                    value = toks[command_index + 1]
                else:
                    return "deny", "A script -c child command is opaque."
                child = restore_quoted_literal_markers(value)
                if is_dynamic_value(child):
                    return "deny", "A dynamic script -c command cannot be inspected."
                child_decision = _recurse_child(child)
                if child_decision[0] != "allow":
                    return child_decision
                break
            continue
        if head in {"watch", "flock", "coproc", "chrt", "taskset"}:
            child_command = _launcher_child_command(head, toks)
            if child_command is None:
                return (
                    "deny",
                    f"A {head} child command is opaque to floor inspection.",
                )
            if child_command:
                if is_dynamic_value(child_command):
                    return (
                        "deny",
                        f"A dynamic {head} child command cannot be inspected safely.",
                    )
                child_decision = _recurse_child(child_command)
                if child_decision[0] != "allow":
                    return child_decision
            continue
        if head == "trap":
            if not quote_aware:
                continue
            trap_error = _trap_handler_decision(toks, _recurse_child)
            if trap_error is not None:
                return trap_error
            continue
        if head == "ssh":
            if _ssh_runs_local_child(toks):
                return (
                    "deny",
                    "ssh ProxyCommand/LocalCommand runs a local child outside floor "
                    "inspection.",
                )
        if head == "wsl":
            # wsl runs a child command inside the Linux distro; inspect that
            # child so `wsl rm -rf /` / `wsl -e sh -c '...'` are not concealed.
            wsl_value_options = {
                "-d",
                "--distribution",
                "--distribution-id",
                "-u",
                "--user",
                "--cd",
                "--shell-type",
            }
            child_index = 1
            while child_index < len(toks):
                token = toks[child_index]
                if token == "--":
                    child_index += 1
                    break
                if token in wsl_value_options:
                    child_index += 2
                    continue
                if token.startswith("-"):
                    child_index += 1
                    continue
                break
            if child_index < len(toks):
                wsl_child = shlex.join(
                    restore_quoted_literal_markers(token)
                    for token in toks[child_index:]
                )
                if is_dynamic_value(wsl_child):
                    return (
                        "deny",
                        "A dynamic wsl child command cannot be inspected safely.",
                    )
                wsl_decision = check(
                    wsl_child,
                    tier_cfg,
                    project_dir,
                    current_cwd,
                    _depth + 1,
                    cwd_uncertain,
                    cwd_changed,
                    remote_resolver,
                    _remote_cache,
                    _remote_deadline,
                    frozenset(effective_git_repository_environment),
                )
                if wsl_decision[0] != "allow":
                    return wsl_decision
            continue
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
                frozenset(effective_git_repository_environment),
            )
            if nested_decision[0] != "allow":
                return nested_decision
        if head == "find":
            if any(
                token in {"-exec", "-execdir", "-ok", "-okdir", "-delete"}
                for token in toks[1:]
            ):
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
            # A saved provider is not visible to the floor, so Pop-Location
            # conservatively preserves any possible Environment context.
            if head not in {"popd", "pop-location"}:
                location_target = powershell_location_target(toks)
                if location_target is None or has_dynamic_shell_token(location_target):
                    environment_provider_context = True
                elif powershell_environment_provider_path(location_target):
                    environment_provider_context = True
                elif operator_after == "&&":
                    environment_provider_context = False
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
        saw_powershell_file = False
        if head == "cmd":
            nested_command_requested, nested_script = cmd_nested_script(toks)
        elif head in _POSIX_SHELL_HEADS | {"pwsh", "powershell"}:
            if head in _POSIX_SHELL_HEADS and has_opaque_posix_shell_input(toks):
                return (
                    "deny",
                    "Shell program text from an opaque input source cannot be inspected safely.",
                )
            ps_skip_until = 0
            for index, token in enumerate(toks[1:], start=1):
                option_text = token.lstrip("-/")
                option, separator, bound_value = option_text.partition(":")
                option = option.lower()
                if head in {"pwsh", "powershell"}:
                    if index <= ps_skip_until:
                        continue  # consumed as a value-option's value
                    is_terminal = bool(option) and (
                        "command".startswith(option)
                        or "encodedcommand".startswith(option)
                        or "file".startswith(option)
                        or option == "cwa"
                        or "commandwithargs".startswith(option)
                    )
                    if not token.startswith(("-", "/")):
                        break  # the implicit -Command/-File payload begins here
                    if not is_terminal and any(
                        name.startswith(option) for name in _POWERSHELL_VALUE_OPTIONS
                    ):
                        if not separator and index + 1 < len(toks):
                            ps_skip_until = index + 1
                        continue
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
                is_file = (
                    head in {"pwsh", "powershell"}
                    and bool(option)
                    and "file".startswith(option)
                )
                if is_file:
                    saw_powershell_file = True
                    file_value = (
                        bound_value
                        if separator
                        else (toks[index + 1] if index + 1 < len(toks) else "")
                    )
                    if file_value == "-":
                        return (
                            "deny",
                            "PowerShell -File - reads opaque program text from stdin.",
                        )
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
                    and not is_command
                    and bool(option)
                    and (option == "cwa" or "commandwithargs".startswith(option))
                )
                if is_command or is_command_with_args:
                    nested_command_requested = True
                    if head in {"pwsh", "powershell"} and (
                        (separator and bound_value == "-")
                        or (
                            not separator
                            and index + 1 < len(toks)
                            and toks[index + 1] == "-"
                        )
                    ):
                        return (
                            "deny",
                            "PowerShell -Command - reads opaque program text from stdin.",
                        )
                    if separator:
                        nested_script = bound_value
                    elif index + 1 < len(toks):
                        if head in _POSIX_SHELL_HEADS:
                            # Shell options may appear between -c and the command
                            # string (`bash -c -e 'cmd'`); skip them so the real
                            # script is inspected, not an option token.
                            script_index = index + 1
                            while script_index < len(toks):
                                candidate = toks[script_index]
                                if candidate == "--":
                                    script_index += 1
                                    break
                                if candidate.startswith("-") and len(candidate) > 1:
                                    script_index += 1
                                    continue
                                break
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
                elif (
                    head == "powershell"
                    and not nested_command_requested
                    and not saw_powershell_file
                    and len(toks) > 1
                ):
                    # powershell.exe binds a bare payload to an implicit -Command.
                    implicit = powershell_implicit_command(toks)
                    if implicit is None:
                        return (
                            "deny",
                            "A PowerShell invocation whose implicit -Command payload "
                            "cannot be located is opaque.",
                        )
                    if implicit:
                        nested_script = implicit
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
                frozenset(effective_git_repository_environment),
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
            if sub == "apply":
                fake_ancestor_outputs = git_option_values(
                    args,
                    "--build-fake-ancestor",
                )
                if any(
                    target is None
                    or has_dynamic_shell_token(target)
                    or token_mentions_secret_path(target)
                    for target in fake_ancestor_outputs
                ):
                    return (
                        "deny",
                        "Git apply fake-ancestor output to an opaque or secret-looking file is floor-blocked.",
                    )
            if sub == "apply" and any(token == "--unsafe-paths" for token in args):
                return (
                    "deny",
                    "Git apply --unsafe-paths can write outside the working tree; "
                    "floor-blocked.",
                )
            if sub in {"apply", "am"}:
                directory_roots = git_option_values(args, "--directory")
                if any(
                    target is None
                    or has_dynamic_shell_token(target)
                    or token_mentions_secret_path(target)
                    for target in directory_roots
                ):
                    return (
                        "deny",
                        "Git patch application under an opaque or secret-looking directory root is floor-blocked.",
                    )
            if sub in _GIT_EXTERNAL_DIFF_SUBCOMMANDS:
                diff_outputs = git_option_values(args, "--output")
                if sub == "format-patch":
                    diff_outputs = diff_outputs + git_option_values(
                        args, "--output-directory", {"-o"}
                    )
                if any(
                    target is None
                    or has_dynamic_shell_token(target)
                    or token_mentions_secret_path(target)
                    for target in diff_outputs
                ):
                    return (
                        "deny",
                        "Git diff output to an opaque or secret-looking file is floor-blocked.",
                    )
            if sub == "bundle":
                action_index = next(
                    (
                        index
                        for index, token in enumerate(args)
                        if not token.startswith("-")
                    ),
                    None,
                )
                if action_index is not None and args[action_index].lower() == "create":
                    bundle_target = next(
                        (
                            token
                            for token in args[action_index + 1 :]
                            if token == "-" or not token.startswith("-")
                        ),
                        None,
                    )
                    if (
                        bundle_target is None
                        or has_dynamic_shell_token(bundle_target)
                        or token_mentions_secret_path(bundle_target)
                    ):
                        return (
                            "deny",
                            "Git bundle output to an opaque or secret-looking file is floor-blocked.",
                        )
            if sub == "maintenance":
                action = next(
                    (token.lower() for token in args if not token.startswith("-")),
                    "",
                )
                if action in {"register", "unregister"}:
                    config_outputs = git_option_values(args, "--config-file")
                    if any(
                        target is None
                        or has_dynamic_shell_token(target)
                        or token_mentions_secret_path(target)
                        for target in config_outputs
                    ):
                        return (
                            "deny",
                            "Git maintenance config output to an opaque or secret-looking file is floor-blocked.",
                        )
            if sub == "clone":
                separate_git_dirs = git_option_values(args, "--separate-git-dir")
                if any(
                    target is None
                    or has_dynamic_shell_token(target)
                    or token_mentions_secret_path(target)
                    for target in separate_git_dirs
                ):
                    return (
                        "deny",
                        "Git clone separate-git-dir output to an opaque or secret-looking path is floor-blocked.",
                    )
                clone_positionals = []
                index = 0
                while index < len(args):
                    token = args[index]
                    if token == "--":
                        clone_positionals.extend(args[index + 1 :])
                        break
                    if token in _GIT_CLONE_VALUE_OPTIONS:
                        index += 2
                        continue
                    if token.startswith("-"):
                        index += 1
                        continue
                    clone_positionals.append(token)
                    index += 1
                if len(clone_positionals) > 1 and any(
                    has_dynamic_shell_token(target)
                    or token_mentions_secret_path(target)
                    for target in clone_positionals[1:]
                ):
                    return (
                        "deny",
                        "Git clone into an opaque or secret-looking destination is floor-blocked.",
                    )
            if sub == "init":
                init_targets = git_option_values(args, "--separate-git-dir")
                for token in args:
                    if not token.startswith("-"):
                        init_targets.append(token)  # optional [<directory>] operand
                if any(
                    target is None
                    or has_dynamic_shell_token(target)
                    or token_mentions_secret_path(target)
                    for target in init_targets
                ):
                    return (
                        "deny",
                        "Git init into an opaque or secret-looking directory is floor-blocked.",
                    )
            if sub == "stash":
                if any(
                    token == "--pathspec-from-file"
                    or token.startswith("--pathspec-from-file=")
                    for token in args
                ):
                    return (
                        "deny",
                        "Git stash pathspec files are opaque to the deny floor.",
                    )
                stash_pathspecs = args[args.index("--") + 1 :] if "--" in args else []
                # `git stash push [opts] [<pathspec>...]` also takes BARE pathspecs
                # (no `--`); collect them, skipping the action word and -m's value.
                before_sep = args[: args.index("--")] if "--" in args else args
                index = 0
                while index < len(before_sep) and before_sep[index].startswith("-"):
                    index += 1
                if index < len(before_sep) and before_sep[index].lower() in {
                    "push",
                    "save",
                }:
                    index += 1
                while index < len(before_sep):
                    token = before_sep[index]
                    if token in {"-m", "--message"}:
                        index += 2
                        continue
                    if token.startswith("--message=") or token.startswith("-m"):
                        index += 1
                        continue
                    if token.startswith("-"):
                        index += 1
                        continue
                    stash_pathspecs.append(token)
                    index += 1
                if any(
                    has_dynamic_shell_token(pathspec)
                    or token_mentions_secret_path(pathspec)
                    for pathspec in stash_pathspecs
                ):
                    return (
                        "deny",
                        "Git stash of an opaque or secret-looking path is floor-blocked.",
                    )
            if sub == "worktree":
                if any(token.lower() == "remove" for token in args):
                    return "deny", "Git worktree removal is floor-blocked."
                worktree_action = next(
                    (token.lower() for token in args if not token.startswith("-")),
                    "",
                )
                if worktree_action in {"add", "move"}:
                    worktree_positionals = []
                    seen_action = False
                    index = 0
                    while index < len(args):
                        token = args[index]
                        if token in _GIT_WORKTREE_VALUE_OPTIONS:
                            index += 2
                            continue
                        if token.startswith("-"):
                            index += 1
                            continue
                        if not seen_action:
                            seen_action = True  # the action word itself
                            index += 1
                            continue
                        worktree_positionals.append(token)
                        index += 1
                    # add writes its first operand; move writes its second.
                    destination_targets = (
                        worktree_positionals
                        if worktree_action == "add"
                        else worktree_positionals[1:]
                    )
                    if any(
                        has_dynamic_shell_token(target)
                        or token_mentions_secret_path(target)
                        for target in destination_targets
                    ):
                        return (
                            "deny",
                            "Git worktree creation at an opaque or secret-looking destination is floor-blocked.",
                        )
            if sub == "rm":
                lowered_rm_args = [token.lower() for token in args]
                if not any(token in {"-n", "--dry-run"} for token in lowered_rm_args):
                    if any(
                        token == "--pathspec-from-file"
                        or token.startswith("--pathspec-from-file=")
                        for token in lowered_rm_args
                    ):
                        return (
                            "deny",
                            "Git rm pathspec files are opaque to the deny floor.",
                        )
                    rm_pathspecs = [
                        token
                        for token in args
                        if token != "--" and not token.startswith("-")
                    ]
                    if any(
                        has_dynamic_shell_token(pathspec)
                        or token_mentions_secret_path(pathspec)
                        for pathspec in rm_pathspecs
                    ):
                        return (
                            "deny",
                            "Git rm of an opaque or secret-looking path is floor-blocked.",
                        )
            if sub == "mv" and not any(
                token == "-n"
                or token == "--dry-run"
                or git_option_abbreviates(token, "--dry-run")
                for token in args
            ):
                mv_operands = [
                    token
                    for token in args
                    if token != "--" and not token.startswith("-")
                ]
                if any(
                    has_dynamic_shell_token(operand)
                    or token_mentions_secret_path(operand)
                    for operand in mv_operands
                ):
                    return (
                        "deny",
                        "Git mv of an opaque or secret-looking path is floor-blocked.",
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
            restore_mutates_worktree = sub == "restore" and (
                not restore_staged or restore_worktree
            )
            if restore_mutates_worktree:
                if any(
                    token == "--pathspec-from-file"
                    or token.startswith("--pathspec-from-file=")
                    for token in args
                ):
                    return (
                        "deny",
                        "Git restore pathspec files are opaque to the deny floor.",
                    )
                restore_pathspecs = []
                index = 0
                while index < len(args):
                    token = args[index]
                    if token == "--":
                        restore_pathspecs.extend(args[index + 1 :])
                        break
                    if token in {"-s", "--source"}:
                        index += 2
                        continue
                    if token.startswith("--source=") or (
                        token.startswith("-s") and len(token) > 2
                    ):
                        index += 1
                        continue
                    if not token.startswith("-"):
                        restore_pathspecs.append(token)
                    index += 1
                if any(
                    has_dynamic_shell_token(pathspec)
                    or token_mentions_secret_path(pathspec)
                    for pathspec in restore_pathspecs
                ):
                    return (
                        "deny",
                        "Git restore of an opaque or secret-looking path is floor-blocked.",
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
                    frozenset(effective_git_repository_environment),
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
                    option_name = t.split("=", 1)[0]
                    if option_name not in dangerous_options and any(
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
                    repository_environment = effective_git_repository_environment | {
                        name.upper()
                        for name in os.environ
                        if name.upper() in _GIT_REPOSITORY_ENVIRONMENT
                    }
                    if repository_environment:
                        return (
                            "deny",
                            "sensitive_data repo: repository environment overrides make push destination inspection unreliable.",
                        )
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

            clean_forced = sub == "clean" and any(
                t == "--force"
                or git_option_abbreviates(t, "--force", min_prefix=1)
                or bool(re.match(r"^-[a-zA-Z]*f", t))
                for t in args
            )
            clean_interactive = sub == "clean" and any(
                t == "--interactive" or bool(re.match(r"^-[a-zA-Z]*i", t)) for t in args
            )
            if clean_forced or clean_interactive:
                # Secret-looking pathspecs are floor-blocked regardless of tier:
                # `git clean -f .env` (or interactive `-i .env`) removes an
                # untracked secret file.
                clean_pathspecs = []
                after_separator = False
                for token in args:
                    if token == "--":
                        after_separator = True
                        continue
                    if after_separator or not token.startswith("-"):
                        clean_pathspecs.append(token)
                if any(
                    has_dynamic_shell_token(pathspec)
                    or token_mentions_secret_path(pathspec)
                    for pathspec in clean_pathspecs
                ):
                    return (
                        "deny",
                        "Git clean of an opaque or secret-looking path is floor-blocked.",
                    )
            if clean_forced:
                if strict:
                    return (
                        "deny",
                        "T4/wave: git clean -f deletes untracked files that may belong to another agent.",
                    )
                if tier >= 3 and not relaxed:
                    return "ask", "T3: git clean -f deletes untracked files. Confirm."

            if sub == "checkout":
                # Pathspec restores overwrite worktree files, so a secret-looking
                # target is floor-blocked before the tier work-loss guard runs.
                # The `--` form and the bare `git checkout [<tree>] <pathspec>`
                # form both reach the worktree, so both are inspected.
                if any(
                    token == "--pathspec-from-file"
                    or token.startswith("--pathspec-from-file=")
                    for token in args
                ):
                    return (
                        "deny",
                        "Git checkout pathspec files are opaque to the deny floor.",
                    )
                checkout_value_options = {
                    "-b",
                    "-B",
                    "--orphan",
                    "-s",
                    "--source",
                    "--conflict",
                }
                # After `--` every token is an explicit pathspec (dynamic or
                # secret-looking targets both blocked). Before `--` a positional
                # may be a tree-ish/branch, so only a literal secret NAME is
                # blocked there — a dynamic branch switch stays allowed.
                separator_pathspecs = (
                    args[args.index("--") + 1 :] if "--" in args else []
                )
                bare_positionals = []
                index = 0
                while index < len(args):
                    token = args[index]
                    if token == "--":
                        break
                    if token in checkout_value_options:
                        index += 2
                        continue
                    if token.startswith("-"):
                        index += 1
                        continue
                    bare_positionals.append(token)
                    index += 1
                # With a tree-ish plus further bare operands, the operands after
                # the first are pathspecs; a dynamic one may expand to a secret
                # path, so fail closed the same as after `--`.
                bare_pathspecs = (
                    bare_positionals[1:] if len(bare_positionals) > 1 else []
                )
                if (
                    any(
                        has_dynamic_shell_token(pathspec)
                        or token_mentions_secret_path(pathspec)
                        for pathspec in separator_pathspecs
                    )
                    or any(
                        token_is_secret_filename(pathspec)
                        for pathspec in bare_positionals
                    )
                    or any(
                        has_dynamic_shell_token(pathspec) for pathspec in bare_pathspecs
                    )
                ):
                    return (
                        "deny",
                        "Git checkout of an opaque or secret-looking path is floor-blocked.",
                    )

            # A whole-tree pathspec restores every tracked file, discarding all
            # local modifications, whether spelled `.` or the root magic `:/`.
            def _is_whole_tree_pathspec(token: str) -> bool:
                return token == "." or token == ":/" or token.startswith(":(top")

            if sub == "checkout" and "--" in args:
                after = args[args.index("--") + 1 :]
                if any(_is_whole_tree_pathspec(token) for token in after):
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

            if sub == "checkout" and any(
                token == "-f"
                or git_option_abbreviates(token, "--force", min_prefix=1)
                or bool(re.match(r"^-[a-zA-Z]*f", token))  # -f, -fq, -qf clusters
                for token in (args[: args.index("--")] if "--" in args else args)
            ):
                if strict:
                    return (
                        "deny",
                        "T4/wave: git checkout -f throws away local modifications.",
                    )
                if tier >= 3 and not relaxed:
                    return (
                        "ask",
                        "T3: git checkout -f discards local modifications. Confirm.",
                    )

            # git switch documents `-f, --force` as an alias for --discard-changes.
            if sub == "switch" and any(
                token == "-f"
                or token == "--force"
                or git_option_abbreviates(token, "--discard-changes", min_prefix=1)
                or bool(re.match(r"^-[a-zA-Z]*f", token))
                for token in args
            ):
                if strict:
                    return (
                        "deny",
                        "T4/wave: git switch --discard-changes throws away local modifications.",
                    )
                if tier >= 3 and not relaxed:
                    return (
                        "ask",
                        "T3: git switch --discard-changes discards local modifications. Confirm.",
                    )

            if (
                sub == "restore"
                and any(_is_whole_tree_pathspec(token) for token in args)
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
            "cpi",
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
            "ln",
            "mkdir",
            "md",
            "mklink",
        }
        if head in {"rsync", "scp", "sftp"}:
            # SRC... DEST: the final positional is the (local) write target. A
            # value-taking option may TRAIL the destination (`rsync src .env
            # --exclude foo`), so skip such option values before selecting DEST.
            # Short-option ARITIES differ per tool (rsync's -P/-i/-c/-o are flags;
            # scp's take values), so keep the value sets separate.
            transfer_long_value = {
                "--rsh",
                "--temp-dir",
                "--exclude",
                "--include",
                "--exclude-from",
                "--include-from",
                "--files-from",
                "--bwlimit",
                "--rsync-path",
                "--compare-dest",
                "--copy-dest",
                "--link-dest",
                "--log-file",
                "--out-format",
                "--partial-dir",
                "--backup-dir",
                "--chmod",
                "--max-size",
                "--min-size",
                "--timeout",
                "--contimeout",
                "--port",
                "--block-size",
                "--modify-window",
                "--info",
                "--debug",
                "--suffix",
                "--iconv",
                "--protocol",
                "--sockopts",
                "--address",
                "--skip-compress",
                "--compress-level",
                "--filter",
                "--write-batch",
                "--read-batch",
                "--only-write-batch",
                "--password-file",
                "--copy-as",
                "--stop-after",
            }
            if head == "rsync":
                transfer_value_opts = {"-e", "-T", "-B", "-f"} | transfer_long_value
            else:  # scp / sftp
                transfer_value_opts = {
                    "-i",
                    "-P",
                    "-c",
                    "-l",
                    "-o",
                    "-F",
                    "-S",
                    "-J",
                    "-D",
                    "-b",
                    "-R",
                    "-B",
                } | transfer_long_value
            transfer_positionals = []
            index = 1
            while index < len(toks):
                token = toks[index]
                if token in transfer_value_opts:
                    index += 2
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                transfer_positionals.append(token)
                index += 1
            dest = transfer_positionals[-1] if len(transfer_positionals) > 1 else None
            if dest is not None and (
                has_dynamic_shell_token(dest) or token_mentions_secret_path(dest)
            ):
                return (
                    "deny",
                    "A file-transfer destination over a secret-looking or dynamic "
                    "path is floor-blocked.",
                )
        if head == "patch":
            # patch -o/--output FILE and -r/--reject-file FILE write named files.
            for value in git_option_values(
                toks[1:], "--output", {"-o"}
            ) + git_option_values(toks[1:], "--reject-file", {"-r"}):
                if value is not None and (
                    has_dynamic_shell_token(value) or token_mentions_secret_path(value)
                ):
                    return (
                        "deny",
                        "patch output/reject to a secret-looking or dynamic file is "
                        "floor-blocked.",
                    )
        if head == "unzip":
            # -d EXDIR extracts into a named directory; explicit member operands
            # extract to named paths.
            index = 1
            while index < len(toks):
                token = toks[index]
                exdir = None
                if token == "-d":
                    exdir = toks[index + 1] if index + 1 < len(toks) else ""
                    index += 2
                elif token.startswith("-d") and len(token) > 2:
                    exdir = token[2:]
                    index += 1
                else:
                    index += 1
                    continue
                if has_dynamic_shell_token(exdir) or token_mentions_secret_path(exdir):
                    return (
                        "deny",
                        "unzip extraction into a secret-looking or dynamic directory "
                        "is floor-blocked.",
                    )
            positional = [token for token in toks[1:] if not token.startswith("-")]
            # positional[0] is the archive; the rest are selected members.
            if any(token_mentions_secret_path(member) for member in positional[1:]):
                return (
                    "deny",
                    "unzip of a member into a secret-looking path is floor-blocked.",
                )
        if head == "chmod":
            # chmod changes metadata, not content, so `chmod 600 ~/.ssh/id_rsa`
            # (the standard secure-your-key op) must stay allowed. Only deny a
            # mode that LOOSENS a secret file — grants group/other read or write,
            # which exposes the secret. A dynamic target fails closed.
            chmod_positionals = [
                token for token in toks[1:] if not token.startswith("-")
            ]
            mode = chmod_positionals[0] if chmod_positionals else ""
            chmod_files = chmod_positionals[1:]
            if _chmod_loosens_access(mode) and any(
                has_dynamic_shell_token(token) or token_mentions_secret_path(token)
                for token in chmod_files
            ):
                return (
                    "deny",
                    "chmod that grants group/other access to a secret-looking file "
                    "is floor-blocked.",
                )
        if head in secret_mutators:
            if any(token.startswith("@") for token in toks[1:]):
                return (
                    "deny",
                    "Array/splatted secret-mutation targets cannot be inspected safely.",
                )
            # A `(...)`/`$(...)` subexpression that SPANS tokens (unbalanced open
            # paren) is split by the whitespace tokenizer, desynchronizing
            # positional/parameter alignment so a later real target (e.g. a
            # value-parameter fed `(Get-Content foo)`) would go uninspected. A
            # balanced single-token subexpression keeps alignment, so only the
            # unbalanced case fails closed.
            if any(token.count("(") > token.count(")") for token in toks[1:]):
                return (
                    "deny",
                    "A parenthesized secret-mutation subexpression cannot be inspected safely.",
                )
            explicit_paths = []
            positional_groups = []
            index = 1
            path_parameters = {"path", "literalpath", "filepath", "destination"}
            value_parameters = set(_POWERSHELL_COMMON_VALUE_PARAMETERS)
            if head in {"new-item", "ni"}:
                path_parameters.add("name")
                value_parameters.update({"itemtype", "type", "value"})
            if head in {"rename-item", "ren", "rni"}:
                path_parameters.add("newname")
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

        # GNU cp/mv/install/ln bind the destination directory to -t/
        # --target-directory rather than a trailing positional, so that syntax
        # bypasses the positional secret check above.
        if head in {"cp", "mv", "install", "ln"}:
            for target in gnu_target_directory_values(toks):
                if has_dynamic_shell_token(target) or target.startswith("("):
                    return (
                        "deny",
                        "A dynamic GNU target-directory cannot be inspected safely.",
                    )
                if token_mentions_secret_path(target):
                    return (
                        "deny",
                        f"Mutating a secret-looking directory ({target}) is floor-blocked. The human manages secrets.",
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
        if head in {"sed", "gsed"} and any(
            _sed_edits_in_place(token) for token in toks[1:]
        ):
            # Inspect only the FILE operands, not the sed program. `sed SCRIPT
            # FILE...`: the first bare positional is the inline script UNLESS a
            # -e/--expression or -f/--file supplies it, in which case every bare
            # positional is a file. Scanning the script for secret substrings
            # (`/credentials/d`, `s/x/secret.y/`) wrongly denies benign edits.
            sed_script_from_option = False
            sed_operands: list[str] = []
            index = 1
            while index < len(toks):
                token = toks[index]
                lowered = token.lower()
                if lowered in {"-e", "--expression", "-f", "--file"}:
                    sed_script_from_option = True
                    index += 2
                    continue
                if (
                    lowered.startswith(("--expression=", "--file="))
                    or (token.startswith("-e") and len(token) > 2)
                    or (token.startswith("-f") and len(token) > 2)
                ):
                    sed_script_from_option = True
                    index += 1
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                sed_operands.append(token)
                index += 1
            if not sed_script_from_option and sed_operands:
                sed_operands = sed_operands[1:]  # drop the inline script operand
            if any(has_dynamic_shell_token(token) for token in sed_operands):
                return (
                    "deny",
                    "A dynamic sed in-place target cannot be inspected safely.",
                )
            if any(token_mentions_secret_path(token) for token in sed_operands):
                return (
                    "deny",
                    "In-place editing of a secret-looking file is floor-blocked.",
                )
        if head == "install":
            # Inspect only the DESTINATION: `install SRC... DEST` writes DEST
            # (the last positional), `install -d DIR...` creates each positional,
            # and `-t DIR` is covered by the target-directory scan above. Sources
            # are read, not written, so they are not checked here. Option VALUES
            # (`-m 644`, `-o root`) are skipped so a mode is never read as a path.
            install_value_options = {
                "-m",
                "--mode",
                "-o",
                "--owner",
                "-g",
                "--group",
                "-S",
                "--suffix",
                "-t",
                "--target-directory",
            }
            install_positionals = []
            makes_dirs = False
            has_target_dir = False
            index = 1
            while index < len(toks):
                token = toks[index]
                if token in {"-d", "--directory"}:
                    makes_dirs = True
                    index += 1
                    continue
                if token in {"-t", "--target-directory"}:
                    has_target_dir = True
                    index += 2
                    continue
                if token.startswith("--target-directory=") or (
                    token.startswith("-t") and len(token) > 2
                ):
                    has_target_dir = True
                    index += 1
                    continue
                if token in install_value_options:
                    index += 2
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                install_positionals.append(token)
                index += 1
            # With -d every positional is a created directory; with -t every
            # positional is a SOURCE (the destination is the -t value, already
            # checked by gnu_target_directory_values), so nothing here is a dest.
            if makes_dirs:
                install_targets = install_positionals
            elif has_target_dir:
                install_targets = []
            else:
                install_targets = install_positionals[-1:]
            if any(has_dynamic_shell_token(token) for token in install_targets):
                return (
                    "deny",
                    "A dynamic install destination cannot be inspected safely.",
                )
            if any(token_mentions_secret_path(token) for token in install_targets):
                return "deny", "Installing over a secret-looking file is floor-blocked."
        if head in {"tar", "gtar", "bsdtar"}:
            # tar runs an arbitrary child via --to-command (always a command) and
            # via -I/--use-compress-program (a program that may itself be a shell
            # command like `sh -c ...`). Deny --to-command outright; for -I, deny
            # only a command-shaped value (whitespace/metacharacters/dynamic) and
            # allow a bare compressor program name (gzip/zstd/pigz).
            if any(
                token == "--to-command" or token.lower().startswith("--to-command=")
                for token in toks[1:]
            ):
                return "deny", "A tar --to-command child is opaque to floor inspection."
            index = 1
            while index < len(toks):
                token = toks[index]
                value = None
                if token in {"-I", "--use-compress-program"}:
                    value = toks[index + 1] if index + 1 < len(toks) else ""
                    index += 2
                elif token.lower().startswith("--use-compress-program="):
                    value = token.split("=", 1)[1]
                    index += 1
                elif token.startswith("-I") and len(token) > 2:
                    value = token[2:]
                    index += 1
                else:
                    index += 1
                    continue
                if is_dynamic_value(value) or re.search(
                    r"[\s;|&$()<>`]", restore_quoted_literal_markers(value)
                ):
                    return (
                        "deny",
                        "A tar compress-program child command is opaque to floor "
                        "inspection.",
                    )
            # Traditional tar "old option style" makes the first argument a
            # dashless option cluster (`tar cf ARCHIVE files`), accepted by GNU,
            # bsd, and busybox tar. Detect it so write-mode is seen; its ARCHIVE
            # semantics differ from getopt and are handled separately below.
            tar_tokens = list(toks)
            old_style = (
                len(tar_tokens) > 1
                and re.fullmatch(r"[A-Za-z]+", tar_tokens[1])
                and any(function in tar_tokens[1] for function in "crtuxAd")
            )
            if old_style:
                tar_tokens[1] = "-" + tar_tokens[1]
            # GNU tar accepts unambiguous long-option abbreviations (--cr ->
            # --create, --app -> --append), so treat any --prefix of a write mode
            # as a write mode; the check only ever over-approximates to denial.
            tar_write_long = (
                "--create",
                "--append",
                "--update",
                "--concatenate",
                "--catenate",
                "--delete",
            )

            def _is_tar_write_long(token: str) -> bool:
                option = token.split("=", 1)[0].lower()
                return len(option) > 2 and any(
                    name.startswith(option) for name in tar_write_long
                )

            write_mode = any(
                bool(re.match(r"^-[A-Za-z]*[cruA]", token)) or _is_tar_write_long(token)
                for token in tar_tokens[1:]
            )
            if write_mode:
                archive = None
                if old_style:
                    # Old style: each value-taking flag (in letter order) consumes
                    # the next following word POSITIONALLY, so f's archive is the
                    # word whose index equals the count of value-flags before f.
                    # Value words may themselves start with `-` (e.g. `-` = stdin
                    # for -T), so following words are counted unfiltered.
                    cluster = tar_tokens[1][1:]
                    tar_value_letters = set("bCfFgHIKLNTVX")
                    if head == "bsdtar":
                        tar_value_letters.add(
                            "s"
                        )  # bsdtar -s substitution takes a value
                    before_f = 0
                    for character in cluster:
                        if character == "f":
                            following = tar_tokens[2:]
                            if before_f < len(following):
                                archive = following[before_f]
                            break
                        if character in tar_value_letters:
                            before_f += 1
                else:
                    index = 1
                    while index < len(tar_tokens):
                        token = tar_tokens[index]
                        lowered = token.lower()
                        if token == "-f" or lowered == "--file":
                            archive = (
                                tar_tokens[index + 1]
                                if index + 1 < len(tar_tokens)
                                else None
                            )
                            index += 2
                            continue
                        attached_archive = re.match(r"^-[A-Za-z]*f(.+)$", token)
                        if lowered.startswith("--file="):
                            archive = token.split("=", 1)[1]
                        elif attached_archive and not token.startswith("--"):
                            # getopt glues -f's value to the cluster tail:
                            # `-cf.env` means archive `.env`, f need not be last.
                            archive = attached_archive.group(1)
                        elif re.match(r"^-[A-Za-z]*f$", token):
                            archive = (
                                tar_tokens[index + 1]
                                if index + 1 < len(tar_tokens)
                                else None
                            )
                            index += 2
                            continue
                        index += 1
                if archive is not None:
                    if has_dynamic_shell_token(archive):
                        return (
                            "deny",
                            "A dynamic tar archive target cannot be inspected safely.",
                        )
                    if token_mentions_secret_path(archive):
                        return (
                            "deny",
                            "Writing a tar archive over a secret-looking file is floor-blocked.",
                        )
        if head in {
            "curl",
            "wget",
            "iwr",
            "irm",
            "invoke-webrequest",
            "invoke-restmethod",
        }:
            if head == "curl":
                curl_risk = curl_unproven_output_risk(toks)
                if curl_risk:
                    return "deny", curl_risk
            long_output_flags = {
                "--output",
                "--output-document",
                "--output-file",
                "--append-output",
                "--directory-prefix",
                "--save-cookies",
                "--warc-file",
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
            if head == "wget":
                execute_bindings, error = wget_execute_output_bindings(toks)
                if execute_bindings is None:
                    return "deny", error
                for execute_name, execute_target in execute_bindings:
                    if is_dynamic_value(execute_target) or re.match(
                        r"^[<>]?\(", execute_target
                    ):
                        return (
                            "deny",
                            "A dynamic wget -e output target cannot be inspected safely.",
                        )
                    if token_mentions_secret_path(execute_target):
                        return (
                            "deny",
                            "wget -e output to a secret-looking path is floor-blocked.",
                        )
                    explicit_output = (
                        explicit_output or execute_name == "outputdocument"
                    )
            output_tokens = [] if head == "curl" else toks[1:]
            for index, token in enumerate(output_tokens, start=1):
                lowered = token.lower()
                attached_target = None
                clustered_marker, clustered_target = downloader_output_binding(
                    head,
                    token,
                )
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
                    head
                    in {"iwr", "irm", "invoke-webrequest", "invoke-restmethod", "wget"}
                    and len(powershell_parameter) >= 4
                    and "outfile".startswith(powershell_parameter)
                )
                # A PowerShell -OutFile parameter starts with `-O`, so the GNU
                # clustered `-O<file>` parser would otherwise misread `-OutFile`
                # as `-O` + `utFile`; drop that misparse so the real destination
                # operand (`-OutFile .env`) is still inspected as a separate value.
                if powershell_outfile:
                    clustered_marker, clustered_target = None, None
                clustered_output = clustered_marker is not None
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
            if (
                head == "wget"
                and not explicit_output
                and wget_uses_server_named_output(toks)
            ):
                # --trust-server-names / --content-disposition let the redirect
                # target or response header pick the local filename, so the name
                # is unknowable at inspection time. Require an inspected output doc.
                return (
                    "deny",
                    "wget server-selected filenames are opaque; require an inspected --output-document.",
                )
            if remote_name_output and not (head == "wget" and explicit_output):
                for token in toks[1:]:
                    if "://" in token and token_mentions_secret_path(token):
                        return (
                            "deny",
                            "A remote-name download would create a secret-looking file.",
                        )
            if head == "wget" and not explicit_output:
                # -r/-m/-p and -i/--input-file create local files whose names come
                # from discovered links or a URL list, so they can materialize a
                # secret-looking file that is unknowable at inspection time. Match
                # -r/-m/-p only inside a genuine no-value short-flag cluster, so a
                # value like `-U eoutput...` is not misread as a recursive flag.
                no_value_flags = _DOWNLOADER_CLUSTER_PREFIXES["wget"]

                def _wget_recursive(token: str) -> bool:
                    if token.lower() in {
                        "--recursive",
                        "--mirror",
                        "--page-requisites",
                    }:
                        return True
                    if not token.startswith("-") or token.startswith("--"):
                        return False
                    body = token[1:]
                    return (
                        bool(body)
                        and all(char in no_value_flags for char in body)
                        and any(char in "rmp" for char in body)
                    )

                if any(_wget_recursive(token) for token in toks[1:]):
                    return (
                        "deny",
                        "Recursive wget without an inspected --output-document has "
                        "opaque remote-name output.",
                    )
                if any(
                    token in {"-i", "--input-file"}
                    or token.lower().startswith("--input-file=")
                    or (token.startswith("-i") and len(token) > 2)
                    for token in toks[1:]
                ):
                    return (
                        "deny",
                        "wget URL files have opaque remote-name output; require an "
                        "inspected --output-document.",
                    )
        if head in {"export-clixml", "export-csv", "epcsv"} and any(
            token_mentions_secret_path(token) or has_dynamic_shell_token(token)
            for token in toks[1:]
        ):
            return (
                "deny",
                "Serializing into a secret-looking or dynamic file is floor-blocked.",
            )
        if (
            ("::" in head or head.startswith("["))
            and re.search(
                r"(?i)(?:writealltext|writeallbytes|appendalltext|create|delete|move|copy)",
                head,
            )
            and (
                token_mentions_secret_path(" ".join(toks))
                or has_dynamic_shell_token(" ".join(toks))
            )
        ):
            return (
                "deny",
                "A file API write to a secret-looking or dynamic path is floor-blocked.",
            )
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
