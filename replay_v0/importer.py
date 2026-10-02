"""Build a private, scrubbed replay corpus from local agent transcripts.

Reads Claude Code project transcripts (`tool_use` blocks named Bash or
PowerShell) and Codex session rollouts (`shell_command` / `shell` function
calls), scrubs each command, and writes a charter-shaped corpus that the replay
kernel can load. The output is private: it is written only outside any Git
work tree or to a path that Git ignores, and it must never be committed.

Scrubbing is defence in depth, not anonymisation. Treat the output as private.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import ipaddress
import json
import os
import random
from pathlib import Path
import re
import socket
import subprocess
from typing import Any, Callable, Iterator

from replay_v0.corpus import (
    CHARTER_CASE_VERSION,
    COMMAND_EVENT_VERSION,
)
from replay_v0.digests import sha256_bytes

CORPUS_ID = "private-local"
FALLBACK_TIMESTAMP = "2000-01-01T00:00:00Z"
CODEX_SHELL_CALLS = frozenset({"shell_command", "shell"})
_PLAIN_WORD = re.compile(r"^[A-Za-z0-9_./:=@%+,-]+$")
_FAMILY_WORD = re.compile(r"[^a-z0-9]+")

# Order matters: specific credential shapes before generic ones, paths before
# bare usernames.
_TOKEN_PATTERNS = (
    (
        re.compile(
            r"(?i)(--?(?:password|passwd|passphrase|pass|token|secret|api-?key|client-secret)"
            r"(?:=|\s+))(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
        ),
        r"\1<redacted>",
    ),
    (
        re.compile(
            r"\b(?i:(mysqldump|mysqladmin|mariadb-dump|mysql|mariadb))"
            r"([^;&|\n]*?\s-p)"
            r"(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
        ),
        r"\1\2<redacted>",
    ),
    (
        re.compile(
            r"(?i)\b(sshpass)([^;&|\n]*?\s-p)\s*" r"(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
        ),
        r"\1\2 <redacted>",
    ),
    (
        re.compile(
            r"(?i)\b(redis-cli)([^;&|\n]*?\s-a\s*)" r"(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
        ),
        r"\1\2<redacted>",
    ),
    (
        re.compile(r"((?:^|\s)(?:-u|--user)(?:=|\s+))[^\s:]+:[^\s;&|]+"),
        r"\1<redacted>",
    ),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}"), "<token>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{8,}"), "<token>"),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{12,}"), "<token>"),
    (re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9_-]{16,}"), "<token>"),
    (re.compile(r"\b(?:xapp|xox[abeoprs])-[A-Za-z0-9-]{10,}"), "<token>"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "<token>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "<token>"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
        "<token>",
    ),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 <token>"),
    (
        re.compile(
            r"(?i)\b([A-Za-z_]*(?:token|secret|passw(?:or)?d|api[_-]?key|auth)"
            r"[A-Za-z_]*\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
        ),
        r"\1<redacted>",
    ),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.S,
        ),
        "<private-key>",
    ),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "<hex>"),
    (re.compile(r"[A-Za-z0-9+/]{48,}={0,2}"), "<blob>"),
)
# The leading classes are bounded generously (64 scheme characters, 128 for an
# email local part or scp user). Unbounded, every start inside a long `x.x.x...` run
# scanned to its end: 8.5 s for 40,000 characters (#397).
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]{1,128}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]{0,63}://)[^/\s@]+@")
_GITHUB_REPO = re.compile(r"(?i)(github\.com[:/])[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_REPOS_API = re.compile(r"\b(repos/)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_REPO_FLAG = re.compile(
    r"((?:--repo(?:=|\s+)|-R\s+))[\"']?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+[\"']?"
)
# Only commands whose first operand names a repository. `list` names an owner,
# `rename` names the new name, and the nested commands have different operands.
# Value flags come from `gh repo <command> --help`; unknown flags stop this
# positional pass rather than mistaking an unknown option's value for a repo.
_GH_REPO_VALUE_FLAGS = {
    "archive": "",
    "clone": "-u --upstream-remote-name",
    "create": "-d --description -g --gitignore -h --homepage -l --license "
    "-r --remote -s --source -t --team -p --template",
    "delete": "",
    "edit": "--add-topic --default-branch -d --description -h --homepage "
    "--remove-topic --visibility",
    "fork": "--fork-name --org --remote-name",
    "set-default": "",
    "sync": "-b --branch -s --source",
    "unarchive": "",
    "view": "-b --branch -q --jq --json -t --template",
}
_GH_REPO_BOOL_FLAGS = {
    "archive": "-y --yes",
    "clone": "",
    "create": "--add-readme -c --clone --disable-issues --disable-wiki "
    "--include-all-branches --internal --private --public --push",
    "delete": "--yes",
    "edit": "--accept-visibility-change-consequences --allow-forking "
    "--allow-update-branch --delete-branch-on-merge --enable-advanced-security "
    "--enable-auto-merge --enable-discussions --enable-issues --enable-merge-commit "
    "--enable-projects --enable-rebase-merge --enable-secret-scanning "
    "--enable-secret-scanning-push-protection --enable-squash-merge --enable-wiki --template",
    "fork": "--clone --default-branch-only --remote",
    "set-default": "-u --unset -v --view",
    "sync": "--force",
    "unarchive": "-y --yes",
    "view": "-w --web",
}
_GH_REPO_SELECTOR = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_GH_REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+")
# Keep quotes/whitespace verbatim, including shell operators inside quoted
# option values. This is a bounded command recognizer, not a shell interpreter.
_GH_REPO_PARTS = re.compile(
    r"(?:[^\s;&|'\"]+|'[^']*'|\"(?:\\.|[^\"\\])*\")+|[;&|\n]+|[ \t\r]+|."
)
# Any scheme (https, ssh, git, ...): a private host loses its path too. Paths
# stop at shell control characters so `url;next-command` keeps its command.
_URL_HOST = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]{0,63}://)([A-Za-z0-9.-]+)(:[0-9]+)?"
    r"(/[^\s\"';&|<>()`]*)?"
)
# scp-style remotes, dotted or single-label: `git@code.example.corp:team/x.git`,
# `git@buildhost:team/x.git`.
_SCP_REMOTE = re.compile(
    r"\b[\w.-]{1,128}@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*):(?!//)" r"([^\s\"';&|<>()`]+)"
)
_PUBLIC_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "raw.githubusercontent.com",
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
        "example.com",
        "example.org",
        "localhost",
        "127.0.0.1",
    }
)
_HOME_PATHS = (
    re.compile(
        r"(?i)\b([A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]+)[^\\/\s\"']+"
    ),
    re.compile(r"(/(?:Users|home)/)[^/\s\"']+"),
    re.compile(r"(?i)(/[a-z]/Users/)[^/\s\"']+"),
    re.compile(r"(/mnt/[a-z]/Users/)[^/\s\"']+"),
    re.compile(r"(?i)(%5CUsers%5C)[^%\s\"']+"),
    re.compile(r"(?<![\w~])(~)[A-Za-z_][A-Za-z0-9._-]*"),
)


_HOST_COMMANDS = frozenset(
    {
        "ssh",
        "mosh",
        "sftp",
        "ping",
        "ping6",
        "telnet",
        "nc",
        "ncat",
        "nslookup",
        "dig",
        "host",
        "traceroute",
        "tracert",
        "ssh-keyscan",
        "ssh-copy-id",
    }
)
_SSH_DESTINATION_COMMANDS = frozenset(
    {"ssh", "mosh", "sftp", "ssh-copy-id", "ssh-keyscan"}
)
_SSH_VALUE_FLAGS = frozenset(
    {
        "-B",
        "-b",
        "-c",
        "-D",
        "-E",
        "-e",
        "-F",
        "-I",
        "-i",
        "-J",
        "-L",
        "-l",
        "-m",
        "-O",
        "-o",
        "-p",
        "-Q",
        "-R",
        "-S",
        "-W",
        "-w",
    }
)
_SINGLE_LABEL_HOST = re.compile(r"[A-Za-z0-9_-]+")
_SCP_COMMANDS = frozenset({"scp", "rsync"})
_CONTAINER_COMMANDS = frozenset({"docker", "podman"})
_CONTAINER_SUBCOMMANDS = frozenset({"pull", "push", "run", "tag", "login", "create"})
_DOTTED_HOST = re.compile(r"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}")
_IPV4_LITERAL = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
_SCP_BARE_REMOTE = re.compile(
    r"^([\w.-]+@)?([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*):(?!//)([^\s\"';&|<>()`]+)$"
)
_CONTAINER_IMAGE = re.compile(r"^([^/]+)/(.+)$")


def _command_head(segment: str) -> str:
    match = re.match(r"\s*(\S+)", segment)
    if match is None:
        return ""
    head = match.group(1).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return head.removesuffix(".exe")


def _split_quote(chunk: str) -> tuple[str, str, str]:
    if len(chunk) >= 2 and chunk[0] in "\"'" and chunk[-1] == chunk[0]:
        return chunk[0], chunk[1:-1], chunk[0]
    return "", chunk, ""


def _scrub_gh_repo_segment(parts: list[str]) -> str:
    positions = [i for i, part in enumerate(parts) if not part.isspace()]
    if len(positions) < 4:
        return "".join(parts)
    head = _split_quote(parts[positions[0]])[1]
    head = head.replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
    if head != "gh" or _split_quote(parts[positions[1]])[1] != "repo":
        return "".join(parts)
    command = _split_quote(parts[positions[2]])[1]
    if command == "new":
        command = "create"
    if command not in _GH_REPO_VALUE_FLAGS:
        return "".join(parts)
    values = set(_GH_REPO_VALUE_FLAGS[command].split())
    booleans = set(_GH_REPO_BOOL_FLAGS[command].split()) | {"--help"}
    private_values = {
        "sync": {"--source": "repo", "-s": "repo"},
        "create": {"--template": "repo", "-p": "repo"},
        "fork": {"--org": "owner", "--fork-name": "name"},
    }.get(command, {})

    def redact_value(value: str, kind: str | None) -> str:
        quote, body, tail = _split_quote(value)
        if kind == "repo" and _GH_REPO_SELECTOR.fullmatch(body):
            return f"{quote}<owner>/<repo>{tail}"
        if kind in {"repo", "name", "owner"} and _GH_REPO_NAME.fullmatch(body):
            return f"{quote}<{('owner' if kind == 'owner' else 'repo')}>{tail}"
        return value

    pending: str | None = None
    options = True
    operand_seen = False
    for position in positions[3:]:
        quote, body, tail = _split_quote(parts[position])
        if pending is not None:
            parts[position] = redact_value(parts[position], private_values.get(pending))
            pending = None
            continue
        if options and body == "--":
            if command in {"clone", "fork"}:
                break  # Remaining flags belong to git.
            options = False
            continue
        if options and body.startswith("-"):
            flag, equals, value = body.partition("=")
            if flag in values:
                if equals:
                    parts[position] = (
                        f"{quote}{flag}={redact_value(value, private_values.get(flag))}{tail}"
                    )
                else:
                    pending = flag
            elif flag in booleans:
                continue
            elif not body.startswith("--") and len(body) > 2:
                for offset, shorthand in enumerate(body[1:], start=1):
                    short_flag = "-" + shorthand
                    if short_flag in values:
                        if offset == len(body) - 1:
                            pending = short_flag
                        else:
                            prefix = body[: offset + 1]
                            value = body[offset + 1 :]
                            # pflag accepts both -pVALUE and -p=VALUE.
                            marker = "=" if value.startswith("=") else ""
                            value = value.removeprefix("=")
                            parts[position] = (
                                f"{quote}{prefix}{marker}{redact_value(value, private_values.get(short_flag))}{tail}"
                            )
                        break
                    if short_flag not in booleans:
                        return "".join(parts)
            else:
                break
            continue
        if not operand_seen:
            if _GH_REPO_SELECTOR.fullmatch(body):
                parts[position] = f"{quote}<owner>/<repo>{tail}"
            elif command in {"clone", "create"} and _GH_REPO_NAME.fullmatch(body):
                parts[position] = f"{quote}<repo>{tail}"
            operand_seen = True
        # Keep scanning known gh flags after the first operand. Local directory
        # operands and formatting values retain their distinct roles.
    return "".join(parts)


def _scrub_gh_repo(text: str) -> str:
    output: list[str] = []
    parts: list[str] = []
    for match in _GH_REPO_PARTS.finditer(text):
        part = match.group(0)
        if part[0] in ";&|\n":
            output.extend((_scrub_gh_repo_segment(parts), part))
            parts = []
        else:
            parts.append(part)
    output.append(_scrub_gh_repo_segment(parts))
    return "".join(output)


def _redact_host_token(chunk: str) -> str:
    if "://" in chunk:
        return chunk
    quote, body, _ = _split_quote(chunk)
    if not body or body[0] == "-" or "/" in body or "=" in body:
        return chunk
    if body.startswith("<") and body.endswith(">"):
        return chunk
    user, sep, host = body.rpartition("@")
    if sep:
        if not host or "/" in user or ":" in user:
            return chunk
    else:
        host = body
    if _IPV4_LITERAL.fullmatch(host):
        if host == "127.0.0.1" or host.startswith("0."):
            return chunk
        host = "<ip>"
    elif _DOTTED_HOST.fullmatch(host):
        if host.lower() in _PUBLIC_HOSTS:
            return chunk
        host = "<host>"
    else:
        return chunk
    return f"{quote}{(user + '@' if sep else '')}{host}{quote}"


def _redact_scp_token(chunk: str) -> str:
    quote, body, _ = _split_quote(chunk)
    if not body or body[0] == "-" or "://" in body or "=" in body:
        return chunk
    match = _SCP_BARE_REMOTE.match(body)
    if match is None:
        return chunk
    user, host = match.group(1) or "", match.group(2)
    if host.lower() in _PUBLIC_HOSTS:
        return chunk
    if not user and len(host) == 1:
        return chunk
    return f"{quote}<host>:/<path>{quote}"


def _redact_image_token(chunk: str) -> str:
    quote, body, _ = _split_quote(chunk)
    if not body or body[0] == "-" or "://" in body or "=" in body:
        return chunk
    if body.startswith("<") and body.endswith(">"):
        return chunk
    match = _CONTAINER_IMAGE.match(body)
    if match is None:
        return chunk
    registry, rest = match.group(1), match.group(2)
    if "." not in registry and ":" not in registry:
        return chunk
    if registry.lower() in _PUBLIC_HOSTS:
        return chunk
    return f"{quote}<registry>/{rest}{quote}"


def _redact_login_server(chunk: str) -> str:
    quote, body, _ = _split_quote(chunk)
    if not body or body[0] == "-" or "=" in body or "/" in body or "://" in body:
        return _redact_image_token(chunk)
    if body.startswith("<") and body.endswith(">"):
        return chunk
    if body.startswith("["):
        end = body.find("]")
        if end == -1:
            return chunk
        inner = body[1:end]
        rest = body[end + 1 :]
        if rest:
            if not rest.startswith(":") or not rest[1:].isdigit():
                return chunk
        try:
            address = ipaddress.ip_address(inner)
        except ValueError:
            return chunk
        if address.is_loopback:
            return chunk
        return f"{quote}<registry>{quote}"
    if body == "::1":
        return chunk
    if "::" in body:
        return chunk
    host, sep, port = body.partition(":")
    if sep:
        if not port.isdigit():
            return chunk
    else:
        host = body
    if not host:
        return chunk
    if host.lower() in _PUBLIC_HOSTS:
        return chunk
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback:
            return chunk
        return f"{quote}<registry>{quote}"
    if _DOTTED_HOST.fullmatch(host):
        return f"{quote}<registry>{quote}"
    if _SINGLE_LABEL_HOST.fullmatch(host):
        return f"{quote}<registry>{quote}"
    return chunk


_LOGIN_VALUE_FLAGS = frozenset({"-u", "--username", "-p", "--password"})


def _split_login_parts(segment: str) -> list[str]:
    parts: list[str] = []
    buf = ""
    buf_is_space: bool | None = None
    in_quote: str | None = None
    escaped = False
    for ch in segment:
        if escaped:
            buf += ch
            escaped = False
            continue
        if in_quote is not None:
            buf += ch
            if ch == "\\" and in_quote == '"':
                escaped = True
            elif ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            if buf_is_space:
                parts.append(buf)
                buf = ""
                buf_is_space = None
            buf += ch
            buf_is_space = False
            in_quote = ch
        elif ch.isspace():
            if buf_is_space is False:
                parts.append(buf)
                buf = ""
                buf_is_space = None
            buf += ch
            buf_is_space = True
        else:
            if buf_is_space:
                parts.append(buf)
                buf = ""
                buf_is_space = None
            buf += ch
            buf_is_space = False
            if ch == "\\":
                escaped = True
    if buf:
        parts.append(buf)
    return parts


def _scrub_login_segment(segment: str) -> str:
    parts = _split_login_parts(segment)
    positions = [i for i, part in enumerate(parts) if part and not part.isspace()]
    if len(positions) < 2:
        return segment
    value_flag: str | None = None
    for pos in positions[2:]:
        if value_flag is not None:
            if value_flag in {"-p", "--password"}:
                quote, _, tail = _split_quote(parts[pos])
                parts[pos] = f"{quote}<redacted>{tail}"
            value_flag = None
            continue
        token = parts[pos]
        quote, body, tail = _split_quote(token)
        effective = body if body else token
        if effective.startswith("-"):
            if effective in _LOGIN_VALUE_FLAGS:
                value_flag = effective
            elif effective.startswith("--password="):
                value_quote, _, value_tail = _split_quote(effective.partition("=")[2])
                parts[pos] = (
                    f"{quote}--password={value_quote}<redacted>{value_tail}{tail}"
                )
            elif effective.startswith("-p") and not effective.startswith("--"):
                prefix = "-p=" if effective.startswith("-p=") else "-p"
                parts[pos] = f"{quote}{prefix}<redacted>{tail}"
            continue
        parts[pos] = _redact_login_server(token)
    return "".join(parts)


def _redact_ssh_destination(chunk: str) -> str:
    quote, body, tail = _split_quote(chunk)
    if not body or body[0] == "-" or "/" in body or "=" in body or "://" in body:
        return chunk
    user, sep, host = body.rpartition("@")
    if not sep:
        host = body
    elif not host or "/" in user or ":" in user:
        return chunk
    port = ""
    bracketed = host.startswith("[")
    if bracketed:
        match = re.fullmatch(r"\[([^]\s]+)\](:[0-9]+)?", host)
        if match is None:
            return chunk
        host, port = match.group(1), match.group(2) or ""
    elif host.count(":") == 1:
        host, separator, number = host.partition(":")
        if not number.isdigit():
            return chunk
        port = separator + number
    if host.lower() in _PUBLIC_HOSTS or host.startswith("<"):
        return chunk
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback:
            return chunk
        replacement = "<ip>"
    elif bracketed:
        return chunk
    elif _DOTTED_HOST.fullmatch(host) or _SINGLE_LABEL_HOST.fullmatch(host):
        replacement = "<host>"
    else:
        return chunk
    if bracketed:
        replacement = f"[{replacement}]"
    return f"{quote}{(user + '@' if sep else '')}{replacement}{port}{tail}"


def _redact_ssh_option(value: str, flag: str) -> str:
    quote, body, tail = _split_quote(value)
    if flag == "-J":
        if body.lower() == "none":
            return value
        return (
            quote
            + ",".join(_redact_ssh_destination(host) for host in body.split(","))
            + tail
        )
    if flag == "-b":
        return _redact_ssh_destination(value)
    if flag == "-o":
        match = re.fullmatch(r"(?i)(ProxyJump|HostName|BindAddress)([=\s]+)(.+)", body)
        if match:
            option, separator, argument = match.groups()
            kind = "-J" if option.lower() == "proxyjump" else "-b"
            return (
                f"{quote}{option}{separator}{_redact_ssh_option(argument, kind)}{tail}"
            )
    return value


def _scrub_ssh_segment(segment: str) -> str:
    parts = _split_login_parts(segment)
    positions = [i for i, part in enumerate(parts) if part and not part.isspace()]
    if not positions:
        return segment
    head = (
        _split_quote(parts[positions[0]])[1]
        .replace("\\", "/")
        .rsplit("/", 1)[-1]
        .lower()
        .removesuffix(".exe")
    )
    keyscan = head == "ssh-keyscan"
    values = {"-f", "-O", "-p", "-T", "-t"} if keyscan else _SSH_VALUE_FLAGS | {"-P"}
    booleans = set("46cDHv") if keyscan else set("46AaCfGgKkMNnqsTtVvXxYy")
    options = True
    pending: str | None = None
    for index in positions[1:]:
        quote, token, tail = _split_quote(parts[index])
        if pending is not None:
            if head == "ssh":
                parts[index] = _redact_ssh_option(parts[index], pending)
            pending = None
            continue
        if options and token == "--":
            options = False
            continue
        if options and token.startswith("-"):
            if token.startswith("--"):
                break  # Unknown option grammar is outside the bounded recognizer.
            for offset, letter in enumerate(token[1:], start=1):
                flag = "-" + letter
                if flag in values:
                    if offset == len(token) - 1:
                        pending = flag
                    elif head == "ssh":
                        parts[index] = (
                            f"{quote}{token[:offset + 1]}{_redact_ssh_option(token[offset + 1:], flag)}{tail}"
                        )
                    break
                if letter not in booleans:
                    return "".join(parts)
            continue
        if keyscan:
            parts[index] = (
                quote
                + ",".join(_redact_ssh_destination(host) for host in token.split(","))
                + tail
            )
        else:
            parts[index] = _redact_ssh_destination(parts[index])
            break  # Remote command arguments are not local SSH destinations.
    return "".join(parts)


def _redact_after_command(segment: str, skip: int, func: Callable[[str], str]) -> str:
    parts = re.split(r"(\s+)", segment)
    seen = 0
    for index, part in enumerate(parts):
        if index % 2 == 1 or not part:
            continue
        if seen < skip:
            seen += 1
            continue
        parts[index] = func(part)
    return "".join(parts)


def _scrub_bare_hosts(text: str) -> str:
    segments = [""]
    for match in _GH_REPO_PARTS.finditer(text):
        part = match.group(0)
        if part[0] in ";&|\n":
            segments.extend((part, ""))
        else:
            segments[-1] += part
    for index in range(0, len(segments), 2):
        segment = segments[index]
        head = _command_head(segment)
        if head in _SSH_DESTINATION_COMMANDS:
            segments[index] = _scrub_ssh_segment(segment)
        elif head in _HOST_COMMANDS:
            segments[index] = _redact_after_command(segment, 1, _redact_host_token)
        elif head in _SCP_COMMANDS:
            segments[index] = _redact_after_command(segment, 1, _redact_scp_token)
        elif head in _CONTAINER_COMMANDS:
            words = [
                part
                for position, part in enumerate(re.split(r"(\s+)", segment))
                if position % 2 == 0 and part
            ]
            if len(words) >= 2 and words[1].lower() == "login":
                # `docker login <server>` names the registry with no image path.
                segments[index] = _scrub_login_segment(segment)
            elif len(words) >= 2 and words[1].lower() in _CONTAINER_SUBCOMMANDS:
                segments[index] = _redact_after_command(segment, 2, _redact_image_token)
    return "".join(segments)


def _git_identity() -> set[str]:
    """The local Git user name and email, which often name the account owner."""

    found: set[str] = set()
    for key in ("user.name", "user.email"):
        try:
            result = subprocess.run(
                ["git", "config", "--global", key],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        value = result.stdout.strip()
        if value:
            found.add(value)
            found.update(part for part in re.split(r"[@\s]", value) if part)
    return found


class Scrubber:
    """Replace machine, identity and credential material in command text."""

    def __init__(self, terms: list[str] | None = None) -> None:
        words = {os.environ.get("USERNAME", ""), os.environ.get("USER", "")}
        words.add(Path.home().name)
        words.update(Path.home().name.split())
        try:
            words.add(socket.gethostname())
        except OSError:
            pass
        words.update(_git_identity())
        words.update(terms or [])
        self.terms = sorted(
            (word for word in words if len(word) >= 3), key=len, reverse=True
        )
        # Long terms are replaced anywhere (paths get concatenated or
        # URL-encoded); short ones only as whole words.
        self._term_patterns = [
            re.compile(
                rf"(?i){re.escape(word)}"
                if len(word) >= 5
                else rf"(?i)(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])"
            )
            for word in self.terms
        ]
        self._spaced_term_patterns = [
            pattern
            for word, pattern in zip(self.terms, self._term_patterns)
            if " " in word
        ]

    def scrub(self, text: str) -> str:
        # Names containing a space go first: the home-path rule stops at
        # whitespace. Every other term waits, so the repo and email rules still
        # see whole `owner/repo` and `user@domain` shapes.
        for pattern in self._spaced_term_patterns:
            text = pattern.sub("<redacted>", text)
        text = _scrub_gh_repo(text)
        text = _scrub_bare_hosts(text)
        for pattern, replacement in _TOKEN_PATTERNS[:-2]:
            text = pattern.sub(replacement, text)
        text = _URL_USERINFO.sub(r"\1", text)
        text = _GITHUB_REPO.sub(r"\1<owner>/<repo>", text)
        text = _SCP_REMOTE.sub(self._scp, text)
        # Preserve structured URL/scp matching, but replace complete emails
        # before generic long-token rules can erase only their local part.
        text = _EMAIL.sub("<email>", text)
        for pattern, replacement in _TOKEN_PATTERNS[-2:]:
            text = pattern.sub(replacement, text)
        text = _REPOS_API.sub(r"\1<owner>/<repo>", text)
        text = _REPO_FLAG.sub(r"\1<owner>/<repo>", text)
        text = _URL_HOST.sub(self._host, text)
        for pattern in _HOME_PATHS:
            text = pattern.sub(r"\1<user>", text)
        for pattern in self._term_patterns:
            text = pattern.sub("<redacted>", text)
        return text

    @staticmethod
    def _host(match: re.Match[str]) -> str:
        host = match.group(2).lower()
        if host in _PUBLIC_HOSTS:
            return match.group(0)
        return f"{match.group(1)}<host>" + ("/<path>" if match.group(4) else "")

    @staticmethod
    def _scp(match: re.Match[str]) -> str:
        if match.group(1).lower() in _PUBLIC_HOSTS or (
            match.group(1).lower() == "sha256"
            and re.fullmatch(r"[0-9a-fA-F]{32,}", match.group(2))
        ):
            return match.group(0)
        return "<host>:<path>"


def _iter_jsonl(path: Path, stats: Counter[str]) -> Iterator[dict[str, Any]]:
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        stats["unreadable-files"] += 1
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                stats["unparsed-lines"] += 1
                continue
            if isinstance(record, dict):
                yield record


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        return FALLBACK_TIMESTAMP
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return FALLBACK_TIMESTAMP
    if moment.tzinfo is None:
        return FALLBACK_TIMESTAMP
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def claude_commands(
    root: Path, stats: Counter[str]
) -> Iterator[tuple[str, str, str | None]]:
    """Yield (command, timestamp, cwd) for each Bash/PowerShell tool call."""

    for path in sorted(root.rglob("*.jsonl")):
        stats["claude-files"] += 1
        for record in _iter_jsonl(path, stats):
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") in ("Bash", "PowerShell")
                    and isinstance(block.get("input"), dict)
                    and isinstance(block["input"].get("command"), str)
                ):
                    stats["claude-commands"] += 1
                    cwd = record.get("cwd")
                    yield (
                        block["input"]["command"],
                        _timestamp(record.get("timestamp")),
                        cwd if isinstance(cwd, str) else None,
                    )


def _argv_command(argv: list[object]) -> str | None:
    """Recover a command line from a legacy argv call only when it is unambiguous."""

    if not argv or not all(isinstance(word, str) for word in argv):
        return None
    words = [str(word) for word in argv]
    head = Path(words[0].replace("\\", "/")).name.lower().removesuffix(".exe")
    if head in ("bash", "sh", "zsh") and len(words) >= 3 and words[1] in ("-c", "-lc"):
        return words[2]
    if head in ("powershell", "pwsh") and "-Command" in words:
        rest = words[words.index("-Command") + 1 :]
        return " ".join(rest) or None
    if all(_PLAIN_WORD.fullmatch(word) for word in words):
        return " ".join(words)
    return None


def codex_commands(
    root: Path, stats: Counter[str]
) -> Iterator[tuple[str, str, str | None]]:
    """Yield (command, timestamp, cwd) for each Codex shell function call."""

    for path in sorted(root.rglob("*.jsonl")):
        stats["codex-files"] += 1
        cwd: str | None = None
        for record in _iter_jsonl(path, stats):
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            if isinstance(payload.get("cwd"), str):
                cwd = payload["cwd"]
            if payload.get("type") != "function_call":
                continue
            if payload.get("name") not in CODEX_SHELL_CALLS:
                continue
            try:
                arguments = json.loads(payload.get("arguments") or "")
            except (TypeError, ValueError):
                stats["codex-unparsed-calls"] += 1
                continue
            command = arguments.get("command") if isinstance(arguments, dict) else None
            if isinstance(command, list):
                command = _argv_command(command)
            if not isinstance(command, str):
                stats["codex-unparsed-calls"] += 1
                continue
            stats["codex-commands"] += 1
            yield command, _timestamp(record.get("timestamp")), cwd


def _family(runtime: str, command: str) -> str:
    words = command.split()
    head = words[0] if words else "empty"
    head = Path(head.replace("\\", "/")).name.lower()
    head = _FAMILY_WORD.sub("-", head).strip("-")[:24] or "other"
    if head.startswith("redacted") or head in ("user", "token", "hex", "blob"):
        head = "other"
    return f"{runtime}-{head}"


def output_is_private(output: Path) -> bool:
    """True when `output` is outside every Git work tree or ignored by Git."""

    target = output.resolve()
    for parent in (target, *target.parents):
        if (parent / ".git").exists():
            break
    else:
        return True
    # Every file the importer writes must be ignored, not just one of them.
    for name in ("events.jsonl", "cases.jsonl", "corpus-manifest.json"):
        try:
            result = subprocess.run(
                ["git", "-C", str(parent), "check-ignore", "-q", str(target / name)],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            return False
    return True


def build_private_corpus(
    sources: list[tuple[str, Iterator[tuple[str, str, str | None]]]],
    scrubber: Scrubber,
    *,
    dedupe: bool = True,
    limit: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    events: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    stats: Counter[str] = Counter()
    seen: set[str] = set()
    for runtime, commands in sources:
        for command, timestamp, _cwd in commands:
            if not command.strip():
                stats["empty-commands"] += 1
                continue
            clean = scrubber.scrub(command)
            if dedupe and clean in seen:
                stats["duplicates"] += 1
                continue
            seen.add(clean)
            event_id = f"imp-{runtime}-{len(events) + 1:06d}"
            events.append(
                {
                    "schema_version": COMMAND_EVENT_VERSION,
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "command": clean,
                    "cwd": "project",
                    "source": "historical-redacted",
                }
            )
            cases.append(
                {
                    "schema_version": CHARTER_CASE_VERSION,
                    "event_id": event_id,
                    "case_class": "opaque",
                    "case_family": _family(runtime, clean),
                    "rationale": "Imported from a local transcript; not labelled.",
                    "provenance": "historical-redacted",
                }
            )
            if limit and len(events) >= limit:
                return events, cases, stats
    return events, cases, stats


def _jsonl_bytes(records: list[dict[str, Any]]) -> bytes:
    lines = [
        json.dumps(record, separators=(",", ":"), ensure_ascii=False)
        for record in records
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_corpus(
    output: Path, events: list[dict[str, Any]], cases: list[dict[str, Any]]
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    files = {"events.jsonl": _jsonl_bytes(events), "cases.jsonl": _jsonl_bytes(cases)}
    for name, content in files.items():
        (output / name).write_bytes(content)
    manifest = {
        "schema_version": "corpus-manifest.v1",
        "corpus_id": CORPUS_ID,
        "event_count": len(events),
        "files": [
            {"path": name, "sha256": sha256_bytes(content)}
            for name, content in files.items()
        ],
    }
    (output / "corpus-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def _root(value: str | None, *default: str) -> Path | None:
    if value == "none":
        return None
    return Path(value) if value else Path.home().joinpath(*default)


def run_import(args: argparse.Namespace) -> int:
    output = Path(args.output)
    if not output_is_private(output):
        print(
            "import: refusing to write inside a Git work tree to a path Git does "
            "not ignore; choose an ignored or external --output",
            flush=True,
        )
        return 2
    terms: list[str] = []
    if args.redact_terms:
        terms = [
            line.strip()
            for line in Path(args.redact_terms).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    stats: Counter[str] = Counter()
    sources: list[tuple[str, Iterator[tuple[str, str, str | None]]]] = []
    claude_root = _root(args.claude_root, ".claude", "projects")
    codex_root = _root(args.codex_root, ".codex", "sessions")
    if claude_root is not None and claude_root.is_dir():
        sources.append(("claude", claude_commands(claude_root, stats)))
    if codex_root is not None and codex_root.is_dir():
        sources.append(("codex", codex_commands(codex_root, stats)))
    if not sources:
        print("import: no transcript root found", flush=True)
        return 2
    events, cases, build_stats = build_private_corpus(
        sources,
        Scrubber(terms),
        dedupe=not args.keep_duplicates,
        limit=args.limit,
    )
    stats.update(build_stats)
    if args.sample and args.sample < len(events):
        keep = sorted(random.Random(args.seed).sample(range(len(events)), args.sample))
        events = [events[index] for index in keep]
        cases = [cases[index] for index in keep]
    if not events:
        print("import: no commands found", flush=True)
        return 2
    write_corpus(output, events, cases)
    stats["events-written"] = len(events)
    print(json.dumps(dict(sorted(stats.items())), indent=2))
    return 0
