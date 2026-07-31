#!/usr/bin/env python3
"""Portable, dependency-free tooling for the cross-runtime agent harness."""

from __future__ import annotations

import argparse
import base64
import binascii
import ctypes
import filecmp
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tomllib
import uuid
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from time import monotonic
from typing import Any

DEFAULT_CODEX_PROJECT_ROOT_MARKERS = [".git"]

WORKTREE_PLAN_SCHEMA_VERSION = 3
WORKTREE_FINGERPRINT_LEASE_SECONDS = 60.0
WORKTREE_GIT_TIMEOUT_SECONDS = 30.0
WORKTREE_OWNERSHIP_LEASE_SCHEMA_VERSION = 1
WORKTREE_OWNERSHIP_LEASE_SCOPE = "exclusive-plain-worktree-remove"
WORKTREE_OWNERSHIP_LEASE_FILENAME = "agent-harness-closeout-lease.json"
WORKTREE_OWNERSHIP_LOCK_DIRECTORY = "agent-harness-closeout-lease.lock"
WORKTREE_OWNERSHIP_DEFAULT_SECONDS = 300.0
WORKTREE_OWNERSHIP_MAX_SECONDS = 3600.0
WORKTREE_OWNERSHIP_MIN_APPLY_REMAINING_SECONDS = 10.0
WORKTREE_GIT_CONTEXT_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_SYSTEM",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE",
    "GIT_WORK_TREE",
)
WORKTREE_ADMIN_ALLOWED_TOP_LEVEL = frozenset(
    {
        "HEAD",
        "ORIG_HEAD",
        "COMMIT_EDITMSG",
        "commondir",
        "gitdir",
        "index",
        "logs",
        "refs",
        WORKTREE_OWNERSHIP_LEASE_FILENAME,
    }
)

CODEX_HOOK_EVENT_NAMES = (
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "SubagentStart",
    "SubagentStop",
    "Stop",
)
I64_MAX = (1 << 63) - 1
U64_MAX = (1 << 64) - 1
USIZE_MAX = (sys.maxsize * 2) + 1
SERDE_JSON_HANDLER_CONTENT_MAX_CONTAINERS = 121

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


# --- Probe binary resolution -------------------------------------------------
#
# Every helper this file spawns — `git`, `gh`, `powershell`, `taskkill` — used to
# be handed to the operating system as a BARE NAME. On Windows that is a hole:
# `CreateProcess` searches the calling process's current directory before it
# reaches PATH, and `audit`/`doctor` are run from, or against, a repository the
# operator does not fully trust. A repository shipping a `git.exe` therefore got
# to run it inside the auditor. (Measured, not reasoned about: the shadow is
# taken whenever `NoDefaultCurrentDirectoryInExePath` is unset, which is every
# plain PowerShell and cmd session — Git Bash happens to set it, which is why
# this stayed invisible.)
#
# The deny floor closed the identical lane in 1.6.16. This is the harness's own
# implementation of that contract — the two files may not import each other, so
# each carries its own readable copy — and it holds four rules:
#
#   1. A bare argv[0] is resolved against ABSOLUTE PATH entries only. Never the
#      cwd; never a relative entry, including the empty one Windows reads as
#      ".". A name that cannot be resolved is a NAMED failure, not a spawn.
#   2. A non-re-parsing image (`.EXE`/`.COM`) anywhere on PATH outranks a script
#      shim (`.CMD`/`.BAT`) everywhere on PATH. This deliberately inverts the
#      shell's per-directory PATHEXT walk, so a directory early on PATH cannot
#      turn a plain spawn into a `cmd.exe` one that re-reads the command line.
#   3. When a shim is the only answer it may still be spawned — a box whose `gh`
#      is genuinely a `.cmd` must remain auditable — but only with argv that
#      survives `cmd.exe` re-parsing intact.
#   4. An argv[0] that already carries a directory keeps its meaning verbatim;
#      searching for it would change what the caller asked for.
NON_REPARSING_PROBE_SUFFIXES = frozenset({".exe", ".com"})
# Windows' own default, used when PATHEXT is absent or empty. Treating an empty
# PATHEXT as "no suffixes" would leave every probe on that box unresolvable.
DEFAULT_WINDOWS_PATHEXT = ".COM;.EXE;.BAT;.CMD"

# Two populations of token, two opposite rules.
#
# argv[1:] carries text the inspected repository influences — a remote name, a
# repository slug, a ref — so it gets an ALLOWLIST of the characters those
# legitimately hold, and anything else is refused.
#
# argv[0] is this resolver's own output: an absolute PATH directory chosen by
# whoever installed the machine. An allowlist there rejects ordinary installs
# (`Program Files (x86)`, an accented user name) and would make every probe on
# such a box a permanent UNPROVEN, so it gets a DENYLIST in two parts: the
# characters `cmd.exe` acts on even inside quotes, and its token delimiters,
# which split an UNQUOTED command name (`C:\dev\a,b\gh.cmd` runs `C:\dev\a`).
PROBE_SHIM_FATAL_IMAGE_CHARACTERS = re.compile('[&|<>^"%!\r\n]')
PROBE_SHIM_SPLITTING_IMAGE_CHARACTERS = re.compile(r"[,;=()]")
PROBE_SHIM_SAFE_ARGUMENT = re.compile(r"[A-Za-z0-9._:/@~=+\\-]*")

# Keyed by the environment that produced the answer, so an injected PATH never
# reads a resolution made under a different one.
_PROBE_BINARY_CACHE: dict[tuple[str, str, str], str | None] = {}


def reset_probe_binary_cache() -> None:
    """Forget every resolution. For tests that plant binaries as they go."""
    _PROBE_BINARY_CACHE.clear()


def probe_environment(env: Mapping[str, str] | None) -> Mapping[str, str]:
    """The environment a resolution reads; the process's own unless injected."""
    return os.environ if env is None else env


def probe_search_directories(env: Mapping[str, str] | None = None) -> list[str]:
    """The directories a bare probe name may be resolved from.

    Absolute entries only. A relative entry — `tools`, `.`, or the empty string
    Windows reads as the current directory — resolves against the cwd, and the
    cwd is exactly what this resolver exists to keep out of the search.
    """
    raw = probe_environment(env).get("PATH", "")
    return [entry for entry in raw.split(os.pathsep) if entry and os.path.isabs(entry)]


def probe_search_suffixes(env: Mapping[str, str] | None = None) -> list[str]:
    """The suffixes a bare probe name may acquire. None off Windows."""
    if os.name != "nt":
        return []
    raw = probe_environment(env).get("PATHEXT", "") or DEFAULT_WINDOWS_PATHEXT
    return [entry.strip() for entry in raw.split(os.pathsep) if entry.strip()]


def probe_candidate_paths(
    name: str, directories: list[str], suffixes: list[str]
) -> list[str]:
    """The absolute candidates for `name`, in the order they may be tried.

    Two passes, images before shims: every directory is searched for a
    `.EXE`/`.COM` before any directory is allowed to answer with a `.CMD`/`.BAT`.
    PATH order is preserved within a pass, so this only ever demotes a shim —
    it never promotes a directory over one earlier on PATH. Off Windows there
    are no suffixes and the result is plain PATH order.
    """
    if not suffixes:
        return [os.path.join(directory, name) for directory in directories]
    images = [
        suffix for suffix in suffixes if suffix.lower() in NON_REPARSING_PROBE_SUFFIXES
    ]
    shims = [
        suffix
        for suffix in suffixes
        if suffix.lower() not in NON_REPARSING_PROBE_SUFFIXES
    ]
    declared = os.path.splitext(name)[1].lower()
    if declared in {suffix.lower() for suffix in suffixes}:
        # `gh.cmd` names its own suffix, so the verbatim name is a candidate —
        # but it joins the pass that suffix belongs to, so spelling out a shim
        # still cannot outrank a real image found further along PATH.
        target = images if declared in NON_REPARSING_PROBE_SUFFIXES else shims
        target.insert(0, "")
    candidates: list[str] = []
    for pass_suffixes in (images, shims):
        for directory in directories:
            stem = os.path.join(directory, name)
            candidates.extend(stem + suffix for suffix in pass_suffixes)
    return candidates


def probe_candidate_is_runnable(path: str) -> bool:
    """Whether the operating system would actually execute this candidate."""
    if not os.path.isfile(path):
        return False
    return os.name == "nt" or os.access(path, os.X_OK)


def probe_image_reparses(path: str) -> bool:
    """Whether spawning `path` hands the command line to a re-parsing shell.

    Windows runs a `.CMD`/`.BAT` target through `cmd.exe`, which re-reads the
    whole line, so `&`, `|` or `>` inside an argument stop being text. A POSIX
    `#!` script receives its argv as an array and re-parses nothing.
    """
    if os.name != "nt":
        return False
    return os.path.splitext(path)[1].lower() not in NON_REPARSING_PROBE_SUFFIXES


def probe_image_is_quoted(image: str) -> bool:
    """Whether the spawn will wrap argv[0] in quotes, so cmd.exe sees one token.

    Asked of `subprocess` rather than restated here: the quoting rule belongs to
    the module that builds the command line, and a second copy of it can drift.
    """
    return subprocess.list2cmdline([image]).startswith('"')


def probe_shim_hazard(argv: list[str]) -> str:
    """Name why `argv` must not be re-read by `cmd.exe`, or "" when it is safe.

    The causes are kept apart because they mean different things to whoever
    reads the diagnosis: a refused argument is repository-influenced text the
    harness declines to pass on, while a refused image path is the machine's own
    installation layout, which no repository can change.
    """
    if not argv:
        return "the command is empty"
    image = argv[0]
    if PROBE_SHIM_FATAL_IMAGE_CHARACTERS.search(image):
        return "its resolved path holds a cmd.exe metacharacter"
    if not probe_image_is_quoted(
        image
    ) and PROBE_SHIM_SPLITTING_IMAGE_CHARACTERS.search(image):
        return "its resolved path holds an unquoted cmd.exe delimiter"
    if not all(PROBE_SHIM_SAFE_ARGUMENT.fullmatch(token) for token in argv[1:]):
        # Deliberately not echoed: the offending token is repository-influenced
        # text, and this string is recorded in a finding.
        return "an argument holds text cmd.exe would re-read as syntax"
    return ""


def resolve_probe_binary(name: str, env: Mapping[str, str] | None = None) -> str | None:
    """Resolve a probe binary against PATH only — never the cwd, images first.

    Returns the absolute path to spawn, or None when nothing on PATH answers to
    the name. None is a real answer: the caller reports it, rather than falling
    back to the implicit resolution this function exists to replace.
    """
    if os.path.dirname(name):
        return name if os.path.isfile(name) else None
    environment = probe_environment(env)
    key = (name, environment.get("PATH", ""), environment.get("PATHEXT", ""))
    if key in _PROBE_BINARY_CACHE:
        return _PROBE_BINARY_CACHE[key]
    resolved = None
    for candidate in probe_candidate_paths(
        name,
        probe_search_directories(environment),
        probe_search_suffixes(environment),
    ):
        if probe_candidate_is_runnable(candidate):
            resolved = candidate
            break
    _PROBE_BINARY_CACHE[key] = resolved
    return resolved


def probe_spawn_argv(
    argv: list[str], env: Mapping[str, str] | None = None
) -> tuple[list[str], str]:
    """Rewrite a probe's argv onto a resolved image, or say why it was refused.

    Returns `(spawn argv, failure text)` with exactly one side filled in. Every
    spawn in this file goes through here; a caller that skips it is back to the
    implicit, cwd-searching resolution.
    """
    if not argv:
        return [], "empty probe command"
    executable = resolve_probe_binary(argv[0], env)
    if executable is None:
        return [], f"{argv[0]}: no executable of that name on PATH"
    spawned = [executable, *argv[1:]]
    if probe_image_reparses(executable):
        hazard = probe_shim_hazard(spawned)
        if hazard:
            return [], (
                f"{argv[0]}: only a script shim on PATH, and it cannot be "
                f"spawned safely because {hazard}"
            )
    return spawned, ""


def run(
    command: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    spawn_argv, failure = probe_spawn_argv(command)
    if failure:
        # 127 is the shell's own "command not found", and the caller already
        # treats any non-zero return as "this resolver did not answer".
        return subprocess.CompletedProcess(command, 127, "", failure)
    try:
        return subprocess.run(
            spawn_argv, cwd=cwd, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def git_root(path: Path) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], path)
    if result.returncode:
        raise HarnessError(f"not a Git repository: {path}")
    return Path(result.stdout.strip()).resolve()


def path_is_alias(path: Path) -> bool:
    """Match filesystem aliases relevant to Codex cwd preservation."""
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(os.path, "isjunction", None)
        if is_junction and is_junction(path):
            return True
        # Python 3.11 (the CI floor) predates os.path.isjunction. Windows
        # exposes junctions through the reparse tag on lstat instead.
        if os.name == "nt":
            reparse_tag = getattr(path.lstat(), "st_reparse_tag", None)
            # Rust's Windows FileType::is_symlink recognizes every Microsoft
            # name-surrogate reparse tag, not only ordinary symlinks.
            return isinstance(reparse_tag, int) and bool(reparse_tag & 0x20000000)
        return False
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise HarnessError(f"cannot inspect path alias {path}: {exc}") from exc


def codex_should_preserve_logical_path(path: Path) -> bool:
    """Mirror Codex v0.145's nested-symlink cwd preservation predicate."""
    return any(
        path_is_alias(ancestor) and ancestor.parent != ancestor.parent.parent
        for ancestor in (path, *path.parents)
    )


def codex_existing_cwd(path: Path) -> Path:
    """Canonicalize an existing cwd with Codex's nested-alias exception."""
    logical = Path(os.path.abspath(path))
    try:
        canonical = logical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HarnessError(
            f"cannot resolve requested Codex cwd {logical}: {exc}"
        ) from exc
    if canonical != logical and codex_should_preserve_logical_path(logical):
        return logical
    return canonical


def lexical_git_root(path: Path) -> Path | None:
    """Find the default-marker root without resolving path aliases."""
    current = Path(os.path.abspath(path))
    for candidate in (current, *current.parents):
        marker = candidate / ".git"
        try:
            if marker.exists():
                return candidate
        except OSError as exc:
            raise HarnessError(
                f"cannot inspect project root marker {marker}: {exc}"
            ) from exc
    return None


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


# --- Guarded linked-worktree closeout ---------------------------------------


def worktree_git_environment() -> dict[str, str]:
    """Return an environment that cannot redirect Git away from the named repo."""

    environment = os.environ.copy()
    for name in WORKTREE_GIT_CONTEXT_ENV:
        environment.pop(name, None)
    for name in list(environment):
        if name == "GIT_CONFIG_COUNT" or name.startswith(
            ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
        ):
            environment.pop(name, None)
    # Reachability must use the stored commit graph, never replace refs inherited
    # from the caller. Grafts are rejected separately because Git has no
    # equivalent process-level switch for them.
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def worktree_git_runner(
    command: list[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Run one bounded Git command for the guarded worktree workflow."""

    if not command or command[0] != "git":
        return subprocess.CompletedProcess(command, 127, "", "only git is supported")
    spawn_argv, failure = probe_spawn_argv(command, worktree_git_environment())
    if failure:
        return subprocess.CompletedProcess(command, 127, "", failure)
    try:
        return subprocess.run(
            spawn_argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=WORKTREE_GIT_TIMEOUT_SECONDS,
            env=worktree_git_environment(),
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", "command timed out")
    except UnicodeError as exc:
        return subprocess.CompletedProcess(command, 125, "", type(exc).__name__)
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def worktree_git_result(
    command_runner: Any, args: list[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    result = command_runner(["git", *args], cwd)
    if not isinstance(result, subprocess.CompletedProcess):
        raise HarnessError("worktree command runner returned an invalid result")
    return result


def canonical_worktree_path(path: Path, *, strict: bool = True) -> Path:
    """Return the one physical path spelling used by the closeout workflow."""

    absolute = Path(os.path.abspath(path.expanduser()))
    try:
        return absolute.resolve(strict=strict)
    except (OSError, RuntimeError) as exc:
        raise HarnessError(
            f"cannot canonicalize worktree path {absolute}: {exc}"
        ) from exc


def worktree_path_key(path: Path) -> str:
    """Return a comparison key for an already-canonical physical path."""

    return os.path.normcase(str(path))


def same_worktree_path(left: Path, right: Path) -> bool:
    return worktree_path_key(left) == worktree_path_key(right)


def worktree_path_is_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath(
            [worktree_path_key(path), worktree_path_key(parent)]
        ) == worktree_path_key(parent)
    except ValueError:
        return False


def parse_worktree_list(output: str) -> list[dict[str, Any]]:
    """Parse `git worktree list --porcelain -z` without path quoting."""

    records: list[dict[str, Any]] = []
    for raw_record in output.split("\0\0"):
        if not raw_record:
            continue
        record: dict[str, Any] = {
            "path": "",
            "head": "",
            "branch": None,
            "detached": False,
            "bare": False,
            "locked": False,
            "lock_reason": "",
            "prunable": False,
            "prunable_reason": "",
        }
        for field in raw_record.split("\0"):
            if field.startswith("worktree "):
                record["path"] = field.removeprefix("worktree ")
            elif field.startswith("HEAD "):
                record["head"] = field.removeprefix("HEAD ")
            elif field.startswith("branch "):
                record["branch"] = field.removeprefix("branch ")
            elif field == "detached":
                record["detached"] = True
            elif field == "bare":
                record["bare"] = True
            elif field == "locked" or field.startswith("locked "):
                record["locked"] = True
                record["lock_reason"] = field.removeprefix("locked").strip()
            elif field == "prunable" or field.startswith("prunable "):
                record["prunable"] = True
                record["prunable_reason"] = field.removeprefix("prunable").strip()
        if not record["path"]:
            raise HarnessError("git worktree list returned a record without a path")
        records.append(record)
    if not records:
        raise HarnessError("git worktree list returned no worktrees")
    return records


def list_worktrees(primary: Path, command_runner: Any) -> list[dict[str, Any]]:
    result = worktree_git_result(
        command_runner, ["worktree", "list", "--porcelain", "-z"], primary
    )
    if result.returncode:
        raise HarnessError(f"git worktree list failed with exit {result.returncode}")
    return parse_worktree_list(result.stdout)


def canonicalize_worktree_records(
    records: list[dict[str, Any]], *, relative_to: Path
) -> list[dict[str, Any]]:
    canonical_records: list[dict[str, Any]] = []
    for source in records:
        record = source.copy()
        raw_path = Path(record["path"])
        if not raw_path.is_absolute():
            raw_path = relative_to / raw_path
        try:
            canonical = canonical_worktree_path(raw_path)
            record["path"] = str(canonical)
            record["path_key"] = worktree_path_key(canonical)
            record["path_error"] = ""
        except HarnessError as exc:
            record["path"] = str(canonical_worktree_path(raw_path, strict=False))
            record["path_key"] = None
            record["path_error"] = str(exc)
        canonical_records.append(record)
    return canonical_records


def registered_worktree_context(
    path: Path, command_runner: Any
) -> tuple[Path, Path, Path, list[dict[str, Any]]]:
    """Resolve a requested path without trusting configurable core.worktree."""

    requested_input = canonical_worktree_path(path)
    records = canonicalize_worktree_records(
        list_worktrees(requested_input, command_runner), relative_to=requested_input
    )
    if records[0]["bare"] or records[0]["path_key"] is None:
        raise HarnessError("bare or unavailable repositories have no worktree root")
    primary = Path(records[0]["path"])
    matches = [
        Path(record["path"])
        for record in records
        if record["path_key"] is not None
        and worktree_path_is_within(requested_input, Path(record["path"]))
    ]
    if not matches:
        raise HarnessError(
            f"requested path is not inside a registered Git worktree: {requested_input}"
        )
    requested = max(matches, key=lambda item: len(worktree_path_key(item)))
    common_git_dir = resolve_common_git_dir(primary, command_runner)
    return requested, primary, common_git_dir, records


def resolve_worktree_checkout(path: Path, command_runner: Any) -> Path:
    requested, _primary, _common_git_dir, _records = registered_worktree_context(
        path, command_runner
    )
    return requested


def resolve_common_git_dir(primary: Path, command_runner: Any) -> Path:
    result = worktree_git_result(
        command_runner, ["rev-parse", "--git-common-dir"], primary
    )
    if result.returncode or not result.stdout.strip():
        raise HarnessError("cannot resolve the repository's common Git directory")
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = primary / common
    return canonical_worktree_path(common)


def registered_worktree_toplevel(
    path: Path, command_runner: Any
) -> tuple[Path | None, str]:
    result = worktree_git_result(command_runner, ["rev-parse", "--show-toplevel"], path)
    if result.returncode or not result.stdout.strip():
        return (
            None,
            f"git rev-parse --show-toplevel failed with exit {result.returncode}",
        )
    top = Path(result.stdout.strip())
    if not top.is_absolute():
        top = path / top
    try:
        return canonical_worktree_path(top), ""
    except HarnessError as exc:
        return None, str(exc)


def linked_worktree_git_dir(
    path: Path, common_git_dir: Path, command_runner: Any
) -> tuple[Path | None, str]:
    result = worktree_git_result(
        command_runner, ["rev-parse", "--absolute-git-dir"], path
    )
    if result.returncode or not result.stdout.strip():
        return (
            None,
            f"git rev-parse --absolute-git-dir failed with exit {result.returncode}",
        )
    try:
        git_dir = canonical_worktree_path(Path(result.stdout.strip()))
        worktrees_admin = canonical_worktree_path(common_git_dir / "worktrees")
    except HarnessError as exc:
        return None, str(exc)
    if same_worktree_path(git_dir, common_git_dir) or not worktree_path_is_within(
        git_dir, worktrees_admin
    ):
        return None, "candidate does not have linked-worktree administrative metadata"
    return git_dir, ""


def worktree_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_worktree_claimant(claimant: str | None) -> str:
    if claimant is None:
        raise HarnessError("a cooperative lease claimant is required")
    normalized = claimant.strip()
    if (
        not normalized
        or len(normalized) > 200
        or not normalized.isprintable()
        or any(character in normalized for character in "\r\n\0")
    ):
        raise HarnessError("claimant must be 1-200 printable single-line characters")
    return normalized


def parse_worktree_lease_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def render_worktree_lease_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def worktree_lease_digest(record: dict[str, Any]) -> str:
    encoded = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_worktree_lease(path: Path) -> tuple[dict[str, Any] | None, str, bool]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "cooperative_lease_missing", True
    except (OSError, UnicodeError):
        return None, "cooperative_lease_probe_failed", False
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return None, "cooperative_lease_malformed", True
    if not isinstance(value, dict):
        return None, "cooperative_lease_malformed", True
    return value, "", True


def inspect_worktree_lease(
    path: Path,
    *,
    claimant: str | None,
    common_git_dir: Path,
    worktree: Path,
    now: datetime,
    minimum_remaining_seconds: float = WORKTREE_OWNERSHIP_MIN_APPLY_REMAINING_SECONDS,
) -> tuple[dict[str, Any], str, bool]:
    """Validate one cooperative ownership record without authenticating its claim."""

    info: dict[str, Any] = {
        "path": str(path),
        "status": "unknown",
        "claimant": None,
        "lease_id": None,
        "expires_at": None,
        "remaining_seconds": None,
        "digest": None,
    }
    record, reason, complete = load_worktree_lease(path)
    if record is None:
        info["status"] = reason
        return info, reason, complete

    expected_fields = {
        "schema_version",
        "lease_id",
        "claimant",
        "scope",
        "common_git_dir",
        "worktree",
        "created_at",
        "renewed_at",
        "expires_at",
    }
    if set(record) != expected_fields:
        info["status"] = "cooperative_lease_malformed"
        return info, "cooperative_lease_malformed", True
    if record.get("schema_version") != WORKTREE_OWNERSHIP_LEASE_SCHEMA_VERSION:
        info["status"] = "cooperative_lease_schema_mismatch"
        return info, "cooperative_lease_schema_mismatch", True
    try:
        uuid.UUID(str(record.get("lease_id")))
    except (ValueError, AttributeError, TypeError):
        info["status"] = "cooperative_lease_malformed"
        return info, "cooperative_lease_malformed", True
    record_claimant = record.get("claimant")
    try:
        normalized_claimant = validate_worktree_claimant(record_claimant)
    except HarnessError:
        info["status"] = "cooperative_lease_malformed"
        return info, "cooperative_lease_malformed", True
    if record.get("scope") != WORKTREE_OWNERSHIP_LEASE_SCOPE:
        info["status"] = "cooperative_lease_scope_mismatch"
        return info, "cooperative_lease_scope_mismatch", True
    if record.get("common_git_dir") != str(common_git_dir) or record.get(
        "worktree"
    ) != str(worktree):
        info["status"] = "cooperative_lease_identity_mismatch"
        return info, "cooperative_lease_identity_mismatch", True

    created = parse_worktree_lease_timestamp(record.get("created_at"))
    renewed = parse_worktree_lease_timestamp(record.get("renewed_at"))
    expires = parse_worktree_lease_timestamp(record.get("expires_at"))
    if (
        created is None
        or renewed is None
        or expires is None
        or not (created <= renewed < expires)
        or (expires - renewed).total_seconds() > WORKTREE_OWNERSHIP_MAX_SECONDS
    ):
        info["status"] = "cooperative_lease_malformed"
        return info, "cooperative_lease_malformed", True

    current = now.astimezone(timezone.utc)
    remaining = (expires - current).total_seconds()
    info.update(
        {
            "claimant": normalized_claimant,
            "lease_id": record["lease_id"],
            "expires_at": render_worktree_lease_timestamp(expires),
            "remaining_seconds": max(0.0, remaining),
            "digest": worktree_lease_digest(record),
            "record": record,
        }
    )
    if renewed > current:
        reason = "cooperative_lease_not_yet_valid"
    elif remaining <= 0:
        reason = "cooperative_lease_expired"
    elif claimant is None:
        reason = "cooperative_lease_claimant_not_supplied"
    elif normalized_claimant != claimant:
        reason = "cooperative_lease_owned_by_other"
    elif remaining < minimum_remaining_seconds:
        reason = "cooperative_lease_expires_too_soon"
    else:
        reason = ""
    info["status"] = reason or "active_owned"
    return info, reason, True


def worktree_lease_target(repo: Path, command_runner: Any) -> tuple[Path, Path, Path]:
    requested, primary, common_git_dir, _records = registered_worktree_context(
        repo, command_runner
    )
    if same_worktree_path(requested, primary):
        raise HarnessError("the primary checkout cannot hold a closeout lease")
    worktree_directory = canonical_worktree_path(primary / ".worktrees")
    if (
        not worktree_path_is_within(worktree_directory, primary)
        or same_worktree_path(worktree_directory, primary)
        or not worktree_path_is_within(requested, worktree_directory)
        or same_worktree_path(requested, worktree_directory)
    ):
        raise HarnessError(
            "worktree is outside the primary checkout's .worktrees directory"
        )
    top, top_error = registered_worktree_toplevel(requested, command_runner)
    if top_error or top is None or not same_worktree_path(top, requested):
        raise HarnessError(
            "Git work-tree configuration redirects away from the registered path"
        )
    git_dir, git_dir_error = linked_worktree_git_dir(
        requested, common_git_dir, command_runner
    )
    if git_dir is None:
        raise HarnessError(f"cannot resolve linked-worktree metadata: {git_dir_error}")
    return requested, common_git_dir, git_dir


def write_worktree_lease(path: Path, record: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def mutate_worktree_lease(
    repo: Path,
    *,
    action: str,
    claimant: str | None,
    ttl_seconds: float = WORKTREE_OWNERSHIP_DEFAULT_SECONDS,
    replace_stale: bool = False,
    command_runner: Any = worktree_git_runner,
    now: Any = worktree_utc_now,
) -> dict[str, Any]:
    """Create, renew, release, or inspect one cooperative ownership lease."""

    if action not in {"status", "acquire", "renew", "release"}:
        raise HarnessError(f"unsupported worktree lease action: {action}")
    if replace_stale and action != "acquire":
        raise HarnessError("--replace-stale is valid only with --action acquire")
    if action != "status":
        claimant = validate_worktree_claimant(claimant)
    elif claimant is not None:
        claimant = validate_worktree_claimant(claimant)
    if not (1.0 <= ttl_seconds <= WORKTREE_OWNERSHIP_MAX_SECONDS):
        raise HarnessError(
            f"lease TTL must be between 1 and {WORKTREE_OWNERSHIP_MAX_SECONDS:g} seconds"
        )

    worktree, common_git_dir, git_dir = worktree_lease_target(repo, command_runner)
    lease_path = git_dir / WORKTREE_OWNERSHIP_LEASE_FILENAME
    current_time = now().astimezone(timezone.utc)
    if action == "status":
        info, reason, complete = inspect_worktree_lease(
            lease_path,
            claimant=claimant,
            common_git_dir=common_git_dir,
            worktree=worktree,
            now=current_time,
            minimum_remaining_seconds=0.0,
        )
        status_without_claimant = (
            claimant is None and reason == "cooperative_lease_claimant_not_supplied"
        )
        if status_without_claimant:
            info["status"] = "active"
            reason = ""
        return {
            "action": action,
            "ok": complete and not reason,
            "reason": reason,
            "worktree": str(worktree),
            "common_git_dir": str(common_git_dir),
            "lease": info,
        }

    lock_directory = git_dir / WORKTREE_OWNERSHIP_LOCK_DIRECTORY
    try:
        lock_directory.mkdir()
    except FileExistsError as exc:
        raise HarnessError(
            "lease mutation lock already exists; inspect it before any manual recovery"
        ) from exc
    try:
        info, reason, complete = inspect_worktree_lease(
            lease_path,
            claimant=claimant,
            common_git_dir=common_git_dir,
            worktree=worktree,
            now=current_time,
            minimum_remaining_seconds=0.0,
        )
        if not complete:
            raise HarnessError("cannot safely read the existing cooperative lease")
        existing = info.get("record")

        if action == "acquire":
            if existing is not None and not (
                reason == "cooperative_lease_expired" and replace_stale
            ):
                raise HarnessError(
                    "lease already exists; only explicit --replace-stale may replace an expired lease"
                )
            if existing is None and reason != "cooperative_lease_missing":
                raise HarnessError(f"cannot replace unsafe lease state: {reason}")
            record = {
                "schema_version": WORKTREE_OWNERSHIP_LEASE_SCHEMA_VERSION,
                "lease_id": str(uuid.uuid4()),
                "claimant": claimant,
                "scope": WORKTREE_OWNERSHIP_LEASE_SCOPE,
                "common_git_dir": str(common_git_dir),
                "worktree": str(worktree),
                "created_at": render_worktree_lease_timestamp(current_time),
                "renewed_at": render_worktree_lease_timestamp(current_time),
                "expires_at": render_worktree_lease_timestamp(
                    current_time + timedelta(seconds=ttl_seconds)
                ),
            }
            write_worktree_lease(lease_path, record)
        elif action == "renew":
            if reason:
                raise HarnessError(f"lease renewal refused: {reason}")
            assert existing is not None
            record = existing.copy()
            record["renewed_at"] = render_worktree_lease_timestamp(current_time)
            record["expires_at"] = render_worktree_lease_timestamp(
                current_time + timedelta(seconds=ttl_seconds)
            )
            write_worktree_lease(lease_path, record)
        else:
            if existing is None or info.get("claimant") != claimant:
                raise HarnessError(f"lease release refused: {reason}")
            if reason not in {
                "",
                "cooperative_lease_expired",
                "cooperative_lease_expires_too_soon",
            }:
                raise HarnessError(f"lease release refused: {reason}")
            lease_path.unlink()
            return {
                "action": action,
                "ok": True,
                "reason": "",
                "worktree": str(worktree),
                "common_git_dir": str(common_git_dir),
                "lease": {"path": str(lease_path), "status": "released"},
            }
    finally:
        try:
            lock_directory.rmdir()
        except FileNotFoundError:
            pass

    verified, verified_reason, verified_complete = inspect_worktree_lease(
        lease_path,
        claimant=claimant,
        common_git_dir=common_git_dir,
        worktree=worktree,
        now=current_time,
        minimum_remaining_seconds=0.0,
    )
    return {
        "action": action,
        "ok": verified_complete and not verified_reason,
        "reason": verified_reason,
        "worktree": str(worktree),
        "common_git_dir": str(common_git_dir),
        "lease": verified,
    }


def worktree_lease_command(args: argparse.Namespace) -> int:
    result = mutate_worktree_lease(
        Path(args.repo),
        action=args.action,
        claimant=args.claimant,
        ttl_seconds=args.ttl_seconds,
        replace_stale=args.replace_stale,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        state = "ok" if result["ok"] else "keep"
        detail = result["reason"] or result["lease"]["status"]
        print(f"[{state}] {result['worktree']}: {detail}")
    return 0 if result["ok"] else 1


def configured_worktree_remotes(
    primary: Path, command_runner: Any
) -> tuple[list[str], str]:
    result = worktree_git_result(command_runner, ["remote"], primary)
    if result.returncode:
        return [], f"git remote failed with exit {result.returncode}"
    remotes = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not remotes:
        return [], "no configured remotes"
    return sorted(set(remotes)), ""


def refresh_worktree_remotes(
    primary: Path, remotes: list[str], command_runner: Any
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for remote in remotes:
        refspec = f"+refs/heads/*:refs/remotes/{remote}/*"
        result = worktree_git_result(
            command_runner,
            [
                "fetch",
                "--prune",
                "--no-tags",
                "--no-recurse-submodules",
                "--",
                remote,
                refspec,
            ],
            primary,
        )
        results.append(
            {
                "remote": remote,
                "ok": result.returncode == 0,
                "exit_code": result.returncode,
            }
        )
    return results


def remote_tracking_refs(
    primary: Path, remotes: list[str], command_runner: Any
) -> tuple[dict[str, str], str]:
    result = worktree_git_result(
        command_runner,
        ["for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes/"],
        primary,
    )
    if result.returncode:
        return {}, f"git for-each-ref failed with exit {result.returncode}"
    prefixes = tuple(f"refs/remotes/{remote}/" for remote in remotes)
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        try:
            ref, object_id = line.split(" ", 1)
        except ValueError:
            return {}, "git for-each-ref returned an invalid record"
        if not ref.startswith(prefixes) or ref.endswith("/HEAD"):
            continue
        refs[ref] = object_id.strip()
    if not refs:
        return {}, "fetch produced no remote-tracking refs"
    return refs, ""


def worktree_history_rewrite_evidence(
    primary: Path, common_git_dir: Path, command_runner: Any
) -> tuple[dict[str, Any], bool]:
    evidence: dict[str, Any] = {
        "ok": False,
        "grafts_file": str(common_git_dir / "info" / "grafts"),
        "grafts_present": False,
        "replace_refs": [],
        "error": "",
    }
    try:
        evidence["grafts_present"] = (common_git_dir / "info" / "grafts").exists()
    except OSError as exc:
        evidence["error"] = f"cannot inspect grafts metadata: {type(exc).__name__}"
        return evidence, False
    result = worktree_git_result(
        command_runner,
        ["for-each-ref", "--format=%(refname)", "refs/replace/"],
        primary,
    )
    if result.returncode:
        evidence["error"] = f"replace-ref probe failed with exit {result.returncode}"
        return evidence, False
    evidence["replace_refs"] = sorted(
        line.strip() for line in result.stdout.splitlines() if line.strip()
    )
    evidence["ok"] = not evidence["grafts_present"] and not evidence["replace_refs"]
    return evidence, True


def refs_containing_head(
    primary: Path,
    head: str,
    refs: dict[str, str],
    command_runner: Any,
) -> tuple[list[dict[str, str]], str]:
    result = worktree_git_result(
        command_runner,
        [
            "for-each-ref",
            "--format=%(refname)",
            f"--contains={head}",
            "refs/remotes/",
        ],
        primary,
    )
    if result.returncode:
        return [], f"reachability probe failed with exit {result.returncode}"
    containing = []
    for ref in result.stdout.splitlines():
        ref = ref.strip()
        if ref in refs:
            containing.append({"ref": ref, "oid": refs[ref]})
    return sorted(containing, key=lambda item: item["ref"]), ""


def worktree_local_refs(
    path: Path, command_runner: Any
) -> tuple[list[dict[str, str]], str]:
    result = worktree_git_result(
        command_runner,
        [
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            "refs/bisect/",
            "refs/worktree/",
            "refs/rewritten/",
        ],
        path,
    )
    if result.returncode:
        return [], f"worktree-local ref probe failed with exit {result.returncode}"
    refs: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        try:
            ref, object_id = line.split(" ", 1)
        except ValueError:
            return [], "worktree-local ref probe returned an invalid record"
        object_id = object_id.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40,64}", object_id):
            return [], "worktree-local ref probe returned an invalid object id"
        refs.append({"ref": ref, "oid": object_id})
    return sorted(refs, key=lambda item: item["ref"]), ""


def worktree_administrative_state(git_dir: Path) -> tuple[list[str], str]:
    """List linked-worktree metadata that plain removal would discard."""

    try:
        top_level = sorted(entry.name for entry in git_dir.iterdir())
    except OSError as exc:
        return [], f"cannot inspect worktree metadata: {type(exc).__name__}"
    state = [name for name in top_level if name not in WORKTREE_ADMIN_ALLOWED_TOP_LEVEL]
    for directory_name, allowed_names in (("logs", {"HEAD"}), ("refs", set())):
        directory = git_dir / directory_name
        try:
            directory_stat = directory.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            return [], (
                f"cannot inspect worktree {directory_name} metadata: "
                f"{type(exc).__name__}"
            )
        if not stat.S_ISDIR(directory_stat.st_mode):
            state.append(directory_name)
            continue
        try:
            children = sorted(entry.name for entry in directory.iterdir())
        except FileNotFoundError:
            # A concurrent metadata mutation is not safe evidence.
            return [], f"worktree {directory_name} metadata changed during inspection"
        except OSError as exc:
            return [], (
                f"cannot inspect worktree {directory_name} metadata: "
                f"{type(exc).__name__}"
            )
        state.extend(
            f"{directory_name}/{name}" for name in children if name not in allowed_names
        )
    return sorted(state), ""


def worktree_recovery_commits(path: Path, command_runner: Any) -> tuple[list[str], str]:
    reflog = worktree_git_result(
        command_runner,
        ["reflog", "show", "--format=%H", "--no-abbrev", "HEAD"],
        path,
    )
    if reflog.returncode:
        return [], f"HEAD reflog probe failed with exit {reflog.returncode}"
    commits = [line.strip().lower() for line in reflog.stdout.splitlines() if line]
    if any(not re.fullmatch(r"[0-9a-f]{40,64}", commit) for commit in commits):
        return [], "HEAD reflog probe returned an invalid object id"

    orig_head = worktree_git_result(
        command_runner,
        ["rev-parse", "--verify", "--quiet", "ORIG_HEAD^{commit}"],
        path,
    )
    if orig_head.returncode not in (0, 1):
        return [], f"ORIG_HEAD probe failed with exit {orig_head.returncode}"
    if orig_head.returncode == 0:
        object_id = orig_head.stdout.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40,64}", object_id):
            return [], "ORIG_HEAD probe returned an invalid object id"
        commits.append(object_id)
    return sorted(set(commits)), ""


def commits_without_local_retention(
    primary: Path, commits: list[str], command_runner: Any
) -> tuple[list[str], str]:
    unreachable: list[str] = []
    for offset in range(0, len(commits), 64):
        batch = commits[offset : offset + 64]
        result = worktree_git_result(
            command_runner,
            [
                "rev-list",
                "--no-walk",
                *batch,
                "--not",
                "--branches",
                "--tags",
            ],
            primary,
        )
        if result.returncode:
            return (
                [],
                f"recovery reachability probe failed with exit {result.returncode}",
            )
        for line in result.stdout.splitlines():
            object_id = line.strip().lower()
            if not re.fullmatch(r"[0-9a-f]{40,64}", object_id):
                return [], "recovery reachability probe returned an invalid object id"
            unreachable.append(object_id)
    return sorted(set(unreachable)), ""


def worktree_candidate_fingerprint(
    candidate: dict[str, Any], common_git_dir: Path
) -> str:
    state = {
        "path": candidate["path"],
        "path_key": candidate.get("path_key"),
        "common_git_dir": str(common_git_dir),
        "head": candidate["head"],
        "branch": candidate["branch"],
        "detached": candidate["detached"],
        "locked": candidate["locked"],
        "lock_reason": candidate["lock_reason"],
        "prunable": candidate["prunable"],
        "prunable_reason": candidate["prunable_reason"],
        "changes": candidate["changes"],
        "ignored": candidate["ignored"],
        "index_preservation_flags": candidate["index_preservation_flags"],
        "tracked_mode_changes": candidate["tracked_mode_changes"],
        "worktree_local_refs": candidate["worktree_local_refs"],
        "worktree_administrative_state": candidate["worktree_administrative_state"],
        "recovery_commits": candidate["recovery_commits"],
        "unretained_recovery_commits": candidate["unretained_recovery_commits"],
        "containing_remote_refs": candidate["containing_remote_refs"],
        "history_rewrite": candidate["history_rewrite"],
        "lease_digest": candidate["lease"].get("digest"),
        "lease_status": candidate["lease"].get("status"),
        "reasons": candidate["reasons"],
    }
    encoded = json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def inspect_worktree_candidate(
    record: dict[str, Any],
    *,
    primary: Path,
    requested: Path,
    process_cwd: Path,
    worktree_dir: Path,
    common_git_dir: Path,
    remote_evidence_ready: bool,
    remote_evidence_requested: bool,
    refs: dict[str, str],
    history_rewrite: dict[str, Any],
    history_rewrite_complete: bool,
    claimant: str | None,
    command_runner: Any,
    now: datetime,
) -> tuple[dict[str, Any], bool]:
    path = Path(record["path"])
    candidate: dict[str, Any] = {
        "path": str(path),
        "path_key": record.get("path_key"),
        "head": record["head"],
        "branch": record["branch"],
        "detached": record["detached"],
        "locked": record["locked"],
        "lock_reason": record["lock_reason"],
        "prunable": record["prunable"],
        "prunable_reason": record["prunable_reason"],
        "changes": [],
        "ignored": [],
        "index_preservation_flags": [],
        "tracked_mode_changes": [],
        "worktree_local_refs": [],
        "worktree_administrative_state": [],
        "recovery_commits": [],
        "unretained_recovery_commits": [],
        "containing_remote_refs": [],
        "history_rewrite": history_rewrite.copy(),
        "lease": {
            "path": None,
            "status": "not_inspected",
            "claimant": None,
            "lease_id": None,
            "expires_at": None,
            "remaining_seconds": None,
            "digest": None,
        },
        "reasons": [],
        "verdict": "keep",
        "fingerprint": "",
        "revalidation": "not_requested",
        "apply": "not_requested",
    }
    complete = True

    def keep(reason: str) -> None:
        if reason not in candidate["reasons"]:
            candidate["reasons"].append(reason)

    if record.get("path_key") is None:
        keep("path_unavailable")
        candidate["path_error"] = record.get("path_error", "")
        complete = False
    if record.get("path_key") is not None and same_worktree_path(path, primary):
        keep("primary_checkout")
    if record.get("path_key") is not None and same_worktree_path(path, requested):
        keep("requested_checkout")
    if record["bare"]:
        keep("bare_repository")
    if record["locked"]:
        keep("git_locked")
    if record["prunable"]:
        keep("prunable_metadata")
    if record["detached"]:
        keep("detached_head")

    shape_is_probeable = record.get("path_key") is not None and not record["bare"]
    contained = False
    if shape_is_probeable and not same_worktree_path(path, primary):
        if (
            not worktree_path_is_within(worktree_dir, primary)
            or same_worktree_path(worktree_dir, primary)
            or not worktree_path_is_within(path, worktree_dir)
            or same_worktree_path(path, worktree_dir)
        ):
            keep("outside_worktree_directory")
        else:
            contained = True
            if worktree_path_is_within(process_cwd, path):
                keep("process_cwd_occupied")

    top_matches = False
    if contained:
        measured_top, top_error = registered_worktree_toplevel(path, command_runner)
        if top_error or measured_top is None:
            keep("worktree_toplevel_probe_failed")
            candidate["worktree_toplevel_error"] = top_error
            complete = False
        elif not same_worktree_path(measured_top, path):
            keep("worktree_path_redirected")
            candidate["measured_toplevel"] = str(measured_top)
        else:
            top_matches = True

    if top_matches:
        head_result = worktree_git_result(command_runner, ["rev-parse", "HEAD"], path)
        if head_result.returncode or not head_result.stdout.strip():
            keep("head_probe_failed")
            complete = False
        else:
            measured_head = head_result.stdout.strip()
            if measured_head != record["head"]:
                keep("head_changed_during_audit")
            candidate["head"] = measured_head

    if top_matches:
        status_result = worktree_git_result(
            command_runner,
            [
                "status",
                "--porcelain=v1",
                "-z",
                "--ignored",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ],
            path,
        )
        if status_result.returncode:
            keep("status_probe_failed")
            complete = False
        else:
            entries = [entry for entry in status_result.stdout.split("\0") if entry]
            candidate["ignored"] = [
                entry.removeprefix("!! ")
                for entry in entries
                if entry.startswith("!! ")
            ]
            candidate["changes"] = [
                entry for entry in entries if not entry.startswith("!! ")
            ]
            if candidate["changes"]:
                keep("tracked_or_untracked_changes")
            if candidate["ignored"]:
                keep("ignored_files")
            index_result = worktree_git_result(
                command_runner, ["ls-files", "-v", "-z"], path
            )
            if index_result.returncode:
                keep("index_probe_failed")
                complete = False
            else:
                flagged = []
                for entry in index_result.stdout.split("\0"):
                    if len(entry) < 3 or entry[1] != " ":
                        continue
                    tag = entry[0]
                    if tag == "S" or tag.islower():
                        flagged.append(entry)
                candidate["index_preservation_flags"] = flagged
                if flagged:
                    keep("index_preservation_flags")

    if top_matches:
        mode_result = worktree_git_result(
            command_runner,
            [
                "-c",
                "core.fileMode=true",
                "diff-files",
                "--summary",
                "-z",
                "--ignore-submodules=none",
                "--",
            ],
            path,
        )
        if mode_result.returncode:
            keep("tracked_mode_probe_failed")
            complete = False
        else:
            candidate["tracked_mode_changes"] = [
                entry for entry in mode_result.stdout.split("\0") if entry
            ]
            if candidate["tracked_mode_changes"]:
                keep("tracked_mode_changes")

    git_dir: Path | None = None
    git_dir_error = ""
    if top_matches:
        git_dir, git_dir_error = linked_worktree_git_dir(
            path, common_git_dir, command_runner
        )
        if git_dir is None:
            keep("worktree_git_dir_probe_failed")
            candidate["worktree_git_dir_error"] = git_dir_error
            complete = False

    if top_matches:
        local_refs, local_refs_error = worktree_local_refs(path, command_runner)
        if local_refs_error:
            keep("worktree_local_ref_probe_failed")
            candidate["worktree_local_ref_error"] = local_refs_error
            complete = False
        else:
            candidate["worktree_local_refs"] = local_refs
            if local_refs:
                keep("worktree_local_refs")

    if git_dir is not None:
        administrative_state, administrative_error = worktree_administrative_state(
            git_dir
        )
        if administrative_error:
            keep("worktree_administrative_state_probe_failed")
            candidate["worktree_administrative_state_error"] = administrative_error
            complete = False
        else:
            candidate["worktree_administrative_state"] = administrative_state
            if administrative_state:
                keep("worktree_administrative_state")

    if top_matches:
        recovery_commits, recovery_error = worktree_recovery_commits(
            path, command_runner
        )
        if recovery_error:
            keep("worktree_recovery_probe_failed")
            candidate["worktree_recovery_error"] = recovery_error
            complete = False
        else:
            candidate["recovery_commits"] = recovery_commits
            unretained, retention_error = commits_without_local_retention(
                primary, recovery_commits, command_runner
            )
            if retention_error:
                keep("worktree_recovery_reachability_probe_failed")
                candidate["worktree_recovery_reachability_error"] = retention_error
                complete = False
            else:
                candidate["unretained_recovery_commits"] = unretained
                if unretained:
                    keep("unretained_recovery_commits")

    if top_matches:
        if not remote_evidence_ready:
            keep(
                "remote_refresh_failed"
                if remote_evidence_requested
                else "remote_evidence_not_refreshed"
            )
        elif not history_rewrite_complete:
            keep("history_rewrite_probe_failed")
            complete = False
        elif not history_rewrite["ok"]:
            keep("history_rewrite_metadata_present")
        else:
            containing, reachability_error = refs_containing_head(
                primary, candidate["head"], refs, command_runner
            )
            if reachability_error:
                keep("reachability_probe_failed")
                candidate["reachability_error"] = reachability_error
                complete = False
            elif not containing:
                keep("head_not_on_fetched_remote_ref")
            else:
                candidate["containing_remote_refs"] = containing

    if top_matches:
        if git_dir is None:
            keep("cooperative_lease_probe_failed")
            candidate["lease"]["status"] = "cooperative_lease_probe_failed"
            candidate["lease_error"] = git_dir_error
            complete = False
        else:
            lease_info, lease_reason, lease_complete = inspect_worktree_lease(
                git_dir / WORKTREE_OWNERSHIP_LEASE_FILENAME,
                claimant=claimant,
                common_git_dir=common_git_dir,
                worktree=path,
                now=now,
            )
            candidate["lease"] = lease_info
            if lease_reason:
                keep(lease_reason)
            complete = complete and lease_complete

    if not candidate["reasons"]:
        candidate["verdict"] = "remove"
    candidate["fingerprint"] = worktree_candidate_fingerprint(candidate, common_git_dir)
    return candidate, complete


def worktree_plan(
    repo: Path,
    *,
    refresh: bool,
    claimant: str | None = None,
    command_runner: Any = worktree_git_runner,
    process_cwd: Path | None = None,
    clock: Any = monotonic,
    now: Any = worktree_utc_now,
) -> dict[str, Any]:
    if claimant is not None:
        claimant = validate_worktree_claimant(claimant)
    requested, primary, common_git_dir, records = registered_worktree_context(
        repo, command_runner
    )
    worktree_dir = canonical_worktree_path(primary / ".worktrees", strict=False)
    current = canonical_worktree_path(process_cwd or Path.cwd())
    generated_monotonic = clock()
    generated_time = now().astimezone(timezone.utc)

    remotes, remote_error = configured_worktree_remotes(primary, command_runner)
    fetch_results: list[dict[str, Any]] = []
    refs: dict[str, str] = {}
    refresh_error = remote_error
    if refresh and not refresh_error:
        fetch_results = refresh_worktree_remotes(primary, remotes, command_runner)
        failed = [item for item in fetch_results if not item["ok"]]
        if failed:
            names = ", ".join(item["remote"] for item in failed)
            refresh_error = f"fetch failed for: {names}"
        else:
            refs, refresh_error = remote_tracking_refs(primary, remotes, command_runner)
    remote_evidence_ready = refresh and not refresh_error
    history_rewrite, history_rewrite_complete = worktree_history_rewrite_evidence(
        primary, common_git_dir, command_runner
    )

    candidates = []
    complete = not (refresh and refresh_error)
    for record in records:
        candidate, candidate_complete = inspect_worktree_candidate(
            record,
            primary=primary,
            requested=requested,
            process_cwd=current,
            worktree_dir=worktree_dir,
            common_git_dir=common_git_dir,
            remote_evidence_ready=remote_evidence_ready,
            remote_evidence_requested=refresh,
            refs=refs,
            history_rewrite=history_rewrite,
            history_rewrite_complete=history_rewrite_complete,
            claimant=claimant,
            command_runner=command_runner,
            now=generated_time,
        )
        candidates.append(candidate)
        complete = complete and candidate_complete

    return {
        "schema_version": WORKTREE_PLAN_SCHEMA_VERSION,
        "generated_at": render_worktree_lease_timestamp(generated_time),
        "fingerprint_lease_seconds": WORKTREE_FINGERPRINT_LEASE_SECONDS,
        "cooperative_lease": {
            "claimant": claimant,
            "scope": WORKTREE_OWNERSHIP_LEASE_SCOPE,
            "minimum_apply_remaining_seconds": (
                WORKTREE_OWNERSHIP_MIN_APPLY_REMAINING_SECONDS
            ),
            "noncooperating_processes_detected": False,
        },
        "repo": str(requested),
        "primary": str(primary),
        "common_git_dir": str(common_git_dir),
        "worktree_directory": str(worktree_dir),
        "refresh": {
            "requested": refresh,
            "ok": remote_evidence_ready,
            "remotes": remotes,
            "fetches": fetch_results,
            "error": refresh_error,
            "remote_refs": [
                {"ref": ref, "oid": oid} for ref, oid in sorted(refs.items())
            ],
        },
        "history_rewrite": history_rewrite,
        "apply_requested": False,
        "branch_deletion": "not_performed",
        "administrative_cleanup": "plain_remove_only_no_global_prune",
        "complete": complete,
        "worktrees": candidates,
        "summary": {},
        "_fingerprint_created_monotonic": generated_monotonic,
    }


def find_worktree_record(
    records: list[dict[str, Any]], candidate_path: Path
) -> dict[str, Any] | None:
    for record in records:
        if record.get("path_key") == worktree_path_key(candidate_path):
            return record
    return None


def apply_worktree_plan(
    plan: dict[str, Any],
    *,
    command_runner: Any = worktree_git_runner,
    clock: Any = monotonic,
) -> bool:
    """Apply one fresh plan; return false when any requested removal is refused."""

    plan["apply_requested"] = True
    if not plan["refresh"]["ok"]:
        plan["apply_error"] = "remote_refresh_failed"
        for candidate in plan["worktrees"]:
            candidate["apply"] = "kept"
        return False
    if not plan["complete"]:
        plan["apply_error"] = "audit_incomplete"
        for candidate in plan["worktrees"]:
            candidate["apply"] = "kept"
        return False
    claimant = plan.get("cooperative_lease", {}).get("claimant")
    if not claimant:
        plan["apply_error"] = "cooperative_lease_claimant_required"
        for candidate in plan["worktrees"]:
            candidate["apply"] = "kept"
        return False
    primary = Path(plan["primary"])
    requested = Path(plan["repo"])
    common_git_dir = Path(plan["common_git_dir"])
    worktree_dir = Path(plan["worktree_directory"])
    process_cwd = canonical_worktree_path(Path.cwd())
    remotes = list(plan["refresh"]["remotes"])
    fingerprint_started = plan.get("_fingerprint_created_monotonic")
    if not isinstance(fingerprint_started, (int, float)):
        plan["apply_error"] = "fingerprint_origin_missing"
        return False
    apply_ok = True

    for candidate in plan["worktrees"]:
        if candidate["verdict"] != "remove":
            candidate["apply"] = "kept"
            continue
        if clock() - fingerprint_started > WORKTREE_FINGERPRINT_LEASE_SECONDS:
            candidate["apply"] = "kept"
            candidate["apply_reason"] = "fingerprint_lease_expired"
            candidate["revalidation"] = "expired"
            apply_ok = False
            continue

        current_records = canonicalize_worktree_records(
            list_worktrees(primary, command_runner), relative_to=primary
        )
        current_record = find_worktree_record(current_records, Path(candidate["path"]))
        refs, refs_error = remote_tracking_refs(primary, remotes, command_runner)
        if current_record is None or refs_error:
            candidate["apply"] = "kept"
            candidate["apply_reason"] = (
                "worktree_disappeared" if current_record is None else "ref_probe_failed"
            )
            candidate["revalidation"] = "unavailable"
            apply_ok = False
            continue
        history_rewrite, history_complete = worktree_history_rewrite_evidence(
            primary, common_git_dir, command_runner
        )
        current, current_complete = inspect_worktree_candidate(
            current_record,
            primary=primary,
            requested=requested,
            process_cwd=process_cwd,
            worktree_dir=worktree_dir,
            common_git_dir=common_git_dir,
            remote_evidence_ready=True,
            remote_evidence_requested=True,
            refs=refs,
            history_rewrite=history_rewrite,
            history_rewrite_complete=history_complete,
            claimant=claimant,
            command_runner=command_runner,
            now=worktree_utc_now(),
        )
        if (
            not current_complete
            or current["verdict"] != "remove"
            or current["fingerprint"] != candidate["fingerprint"]
        ):
            candidate["apply"] = "kept"
            candidate["apply_reason"] = "state_changed_since_audit"
            candidate["revalidated_fingerprint"] = current["fingerprint"]
            candidate["revalidation"] = "changed"
            apply_ok = False
            continue

        final_lease_path = current["lease"].get("path")
        if not final_lease_path:
            candidate["apply"] = "kept"
            candidate["apply_reason"] = "cooperative_lease_revalidation_failed"
            candidate["revalidation"] = "changed"
            apply_ok = False
            continue
        final_lease_path = Path(final_lease_path)
        mutation_lock = final_lease_path.parent / WORKTREE_OWNERSHIP_LOCK_DIRECTORY
        try:
            mutation_lock.mkdir()
        except FileExistsError:
            candidate["apply"] = "kept"
            candidate["apply_reason"] = "cooperative_lease_mutation_in_progress"
            candidate["revalidation"] = "unavailable"
            apply_ok = False
            continue
        except OSError as exc:
            candidate["apply"] = "kept"
            candidate["apply_reason"] = "cooperative_lease_lock_failed"
            candidate["lease_lock_error"] = type(exc).__name__
            candidate["revalidation"] = "unavailable"
            apply_ok = False
            continue
        try:
            final_lease, final_lease_reason, final_lease_complete = (
                inspect_worktree_lease(
                    final_lease_path,
                    claimant=claimant,
                    common_git_dir=common_git_dir,
                    worktree=Path(current["path"]),
                    now=worktree_utc_now(),
                )
            )
            if (
                not final_lease_complete
                or final_lease_reason
                or final_lease.get("digest") != current["lease"].get("digest")
                or clock() - fingerprint_started > WORKTREE_FINGERPRINT_LEASE_SECONDS
            ):
                candidate["apply"] = "kept"
                candidate["apply_reason"] = "cooperative_lease_revalidation_failed"
                candidate["revalidation"] = "changed"
                apply_ok = False
                continue

            remove_result = worktree_git_result(
                command_runner,
                ["worktree", "remove", "--", current["path"]],
                primary,
            )
            candidate["remove_exit_code"] = remove_result.returncode
            candidate["revalidated_fingerprint"] = current["fingerprint"]
            candidate["revalidation"] = "matched"
            if remove_result.returncode:
                candidate["apply"] = "kept"
                candidate["apply_reason"] = "plain_remove_refused"
                apply_ok = False
            else:
                candidate["apply"] = "removed"
        finally:
            try:
                mutation_lock.rmdir()
            except FileNotFoundError:
                pass
    return apply_ok


def summarize_worktree_plan(plan: dict[str, Any]) -> None:
    candidates = plan["worktrees"]
    plan["summary"] = {
        "total": len(candidates),
        "would_remove": sum(item["verdict"] == "remove" for item in candidates),
        "kept": sum(item["verdict"] != "remove" for item in candidates),
        "removed": sum(item["apply"] == "removed" for item in candidates),
        "apply_refusals": sum(
            item["apply"] == "kept" and item["verdict"] == "remove"
            for item in candidates
        ),
    }


def render_worktree_plan(plan: dict[str, Any]) -> None:
    print(f"repo: {plan['repo']}")
    print(f"worktree directory: {plan['worktree_directory']}")
    claimant = plan["cooperative_lease"]["claimant"]
    if claimant:
        print(f"cooperative claimant: {claimant}")
    else:
        print("[read-only] no cooperative claimant was supplied")
    print(
        "[limit] non-cooperating external processes are not detected; "
        "their writes can still race plain removal"
    )
    refresh = plan["refresh"]
    if refresh["requested"]:
        state = "ok" if refresh["ok"] else "FAIL"
        detail = refresh["error"] or f"{len(refresh['remote_refs'])} refs refreshed"
        print(f"[{state}] remote evidence: {detail}")
    else:
        print("[read-only] remote evidence was not refreshed")
    for candidate in plan["worktrees"]:
        detail = ", ".join(candidate["reasons"]) or "safe after revalidation"
        print(f"[{candidate['verdict']}] {candidate['path']}: {detail}")
        if candidate["apply"] == "removed":
            print("  applied: removed with plain git worktree remove")
        elif candidate.get("apply_reason"):
            print(f"  applied: kept ({candidate['apply_reason']})")
    summary = plan["summary"]
    print(
        "summary: "
        f"{summary['would_remove']} removable, {summary['kept']} kept, "
        f"{summary['removed']} removed, {summary['apply_refusals']} apply refusals"
    )


def worktrees_command(
    args: argparse.Namespace,
    *,
    command_runner: Any = worktree_git_runner,
    clock: Any = monotonic,
) -> int:
    if args.apply and not args.refresh:
        raise HarnessError("--apply requires --refresh")
    claimant = getattr(args, "claimant", None)
    if args.apply and not claimant:
        raise HarnessError(
            "--apply requires --claimant with an active cooperative lease"
        )
    plan = worktree_plan(
        Path(args.repo),
        refresh=args.refresh,
        claimant=claimant,
        command_runner=command_runner,
        clock=clock,
    )
    apply_ok = True
    if args.apply:
        apply_ok = apply_worktree_plan(plan, command_runner=command_runner, clock=clock)
    summarize_worktree_plan(plan)
    plan.pop("_fingerprint_created_monotonic", None)
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        render_worktree_plan(plan)
    return 0 if plan["complete"] and apply_ok else 1


def codex_hook_source_status(
    requested_checkout: Path, authoritative_checkout: Path
) -> tuple[Path, bool, str]:
    """Return one active Codex layer's hook path and copy status."""
    authoritative_hooks = authoritative_checkout / ".codex" / "hooks.json"
    authoritative_bytes = read_optional_bytes(authoritative_hooks)
    if requested_checkout == authoritative_checkout:
        return (
            authoritative_hooks,
            True,
            f"normal checkout; Codex source: {authoritative_hooks}",
        )

    ignored_hooks = requested_checkout / ".codex" / "hooks.json"
    ignored_bytes = read_optional_bytes(ignored_hooks)
    source_prefix = (
        "linked worktree; Codex uses root checkout source: " f"{authoritative_hooks}"
    )
    if authoritative_bytes is None:
        if ignored_bytes is not None:
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
    if ignored_bytes is not None:
        if authoritative_bytes != ignored_bytes:
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


def read_optional_text(path: Path) -> str | None:
    """Read UTF-8 text, distinguishing an absent file from an unreadable one."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise HarnessError(f"cannot read {path}: {exc}") from exc


def read_optional_bytes(path: Path) -> bytes | None:
    """Read bytes, distinguishing an absent file from an unreadable one."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HarnessError(f"cannot read {path}: {exc}") from exc


def toml_config(config_path: Path) -> dict[str, Any] | None:
    """Return one TOML config document, or ``None`` when it is absent."""
    contents = read_optional_text(config_path)
    if contents is None:
        return None
    try:
        config = tomllib.loads(contents)
    except tomllib.TOMLDecodeError as exc:
        raise HarnessError(f"invalid Codex config {config_path}: {exc}") from exc
    except (RecursionError, ValueError) as exc:
        raise HarnessError(f"invalid Codex config {config_path}: {exc}") from exc
    validate_toml_integer_range(config, str(config_path))
    return config


def display_mcp_server_name(name: str) -> str:
    """Render a server name without allowing it to forge a diagnostic line."""
    return json.dumps(name, ensure_ascii=True)


def mcp_config_identity(config_path: Path) -> Path:
    """Use the filesystem's canonical spelling when comparing MCP sources."""
    return config_path.resolve()


def distinct_mcp_config_paths(config_paths: list[Path]) -> list[Path]:
    """Deduplicate config sources by filesystem identity, not path spelling."""
    paths: list[Path] = []
    identities: set[str] = set()
    for config_path in config_paths:
        resolved = mcp_config_identity(config_path)
        identity = str(resolved)
        if os.name == "nt":
            identity = identity.casefold()
        if identity not in identities:
            identities.add(identity)
            paths.append(resolved)
    return paths


def mcp_server_patches(
    config_path: Path,
) -> list[tuple[str, Path, dict[str, Any]]]:
    """Return validated MCP fields needed to model layered spawning state."""
    config_path = mcp_config_identity(config_path)
    config = toml_config(config_path)
    if config is None or "mcp_servers" not in config:
        return []
    servers = config["mcp_servers"]
    if not isinstance(servers, dict):
        raise HarnessError(f"mcp_servers in {config_path} must be a table")

    declarations: list[tuple[str, Path, dict[str, Any]]] = []
    for name, entry in servers.items():
        rendered_name = display_mcp_server_name(name)
        if not isinstance(entry, dict):
            raise HarnessError(
                f"mcp_servers.{rendered_name} in {config_path} must be a table"
            )
        patch: dict[str, Any] = {}
        if "enabled" in entry and not isinstance(entry["enabled"], bool):
            raise HarnessError(
                f"mcp_servers.{rendered_name}.enabled in {config_path} must be a boolean"
            )
        if "enabled" in entry:
            patch["enabled"] = entry["enabled"]
        if "command" in entry and "url" in entry:
            raise HarnessError(
                f"mcp_servers.{rendered_name} in {config_path} must not declare both "
                "command and url"
            )
        if "command" in entry and (
            not isinstance(entry["command"], str) or not entry["command"].strip()
        ):
            raise HarnessError(
                f"mcp_servers.{rendered_name}.command in {config_path} must be a "
                "non-empty string"
            )
        if "command" in entry:
            patch["command"] = entry["command"]
        if "url" in entry and (
            not isinstance(entry["url"], str) or not entry["url"].strip()
        ):
            raise HarnessError(
                f"mcp_servers.{rendered_name}.url in {config_path} must be a "
                "non-empty string"
            )
        if "url" in entry:
            patch["url"] = entry["url"]
        if "args" in entry and (
            not isinstance(entry["args"], list)
            or not all(isinstance(argument, str) for argument in entry["args"])
        ):
            raise HarnessError(
                f"mcp_servers.{rendered_name}.args in {config_path} must be an "
                "array of strings"
            )
        if "args" in entry:
            patch["args"] = tuple(entry["args"])
        declarations.append((name, config_path, patch))
    return declarations


def layered_mcp_server_states(config_paths: list[Path]) -> dict[str, dict[str, Any]]:
    """Merge inspectable MCP fields in Codex's base-to-project layer order."""
    states: dict[str, dict[str, Any]] = {}
    for config_path in distinct_mcp_config_paths(config_paths):
        for name, source, patch in mcp_server_patches(config_path):
            state = states.setdefault(
                name,
                {
                    "enabled": True,
                    "command": None,
                    "command_source": None,
                    "url": None,
                    "url_source": None,
                    "args": (),
                    "args_source": None,
                },
            )
            if "enabled" in patch:
                state["enabled"] = patch["enabled"]
            if "command" in patch:
                state["command"] = patch["command"]
                state["command_source"] = source
            if "url" in patch:
                state["url"] = patch["url"]
                state["url_source"] = source
            if "args" in patch:
                state["args"] = patch["args"]
                state["args_source"] = source
    for name, state in states.items():
        if state["command"] is not None and state["url"] is not None:
            raise HarnessError(
                f"effective mcp_servers.{display_mcp_server_name(name)} mixes "
                f"command from {state['command_source']} and url from "
                f"{state['url_source']}"
            )
    return states


def unbounded_docker_mcp_gateway(command: str, args: tuple[str, ...]) -> bool:
    """Recognize a Docker MCP gateway that can load the whole registry."""
    executable = re.split(r"[\\/]", command)[-1].casefold()
    if executable not in {"docker", "docker.exe", "docker.cmd", "docker.bat"}:
        return False
    gateway_run = any(
        args[index : index + 3] == ("mcp", "gateway", "run")
        for index in range(max(0, len(args) - 2))
    )
    if not gateway_run:
        return False
    return not any(
        argument in {"--servers", "--profile"}
        or argument.startswith("--servers=")
        or argument.startswith("--profile=")
        for argument in args
    )


def codex_mcp_topology_status(
    codex_home: Path, project_config_paths: list[Path]
) -> tuple[bool, str]:
    """Check the static user/project MCP process-spawning topology."""
    user_path = mcp_config_identity(codex_home / "config.toml")
    project_paths = distinct_mcp_config_paths(project_config_paths)
    user_states = layered_mcp_server_states([user_path])
    project_states = layered_mcp_server_states(project_paths)
    effective_states = layered_mcp_server_states([user_path, *project_paths])
    user_declarations = {
        name: state
        for name, state in user_states.items()
        if state["enabled"] and state["command"] is not None
    }
    project_declarations = {
        name: state
        for name, state in project_states.items()
        if state["enabled"] and state["command"] is not None
    }

    findings: list[str] = []
    for name in sorted(user_declarations.keys() & project_declarations.keys()):
        findings.append(
            f"active command-backed MCP server {display_mcp_server_name(name)} is "
            f"duplicated across user {user_declarations[name]['command_source']} "
            f"and project {project_declarations[name]['command_source']}"
        )
    for name, state in effective_states.items():
        if (
            state["enabled"]
            and state["command"] is not None
            and unbounded_docker_mcp_gateway(state["command"], state["args"])
        ):
            argument_source = state["args_source"] or state["command_source"]
            findings.append(
                f"active Docker MCP gateway {display_mcp_server_name(name)} has "
                f"command in {state['command_source']} and arguments in "
                f"{argument_source}; neither --servers nor --profile bound"
            )

    scope = (
        f"inspected base user config {user_path} and {len(project_paths)} active "
        "project config path(s); stored profiles, system/managed policy, CLI "
        "overrides, and runtime process state are outside this static check"
    )
    if findings:
        return False, f"{'; '.join(findings)}; {scope}"
    return (
        True,
        f"{len(user_declarations)} active user and {len(project_declarations)} "
        f"active project command-backed MCP declaration(s); no cross-scope "
        f"duplicate spawning name or unbounded Docker gateway; {scope}",
    )


def validate_toml_integer_range(value: Any, location: str) -> None:
    """Match Rust TOML's signed 64-bit integer representation."""
    pending = [(value, location)]
    while pending:
        current, current_location = pending.pop()
        if isinstance(current, bool):
            continue
        if isinstance(current, int):
            if not -(1 << 63) <= current <= I64_MAX:
                raise HarnessError(
                    f"invalid Codex config {current_location}: integer is outside "
                    "signed 64-bit range"
                )
            continue
        if isinstance(current, dict):
            pending.extend(
                (nested, f"{current_location}.{key}") for key, nested in current.items()
            )
            continue
        if isinstance(current, list):
            pending.extend(
                (nested, f"{current_location}[{index}]")
                for index, nested in enumerate(current)
            )


def inline_hooks_from_config(config_path: Path) -> Any | None:
    """Return a config layer's inline hooks table, if it declares one."""
    config = toml_config(config_path)
    if config is None:
        return None
    return config.get("hooks")


def windows_program_data_path() -> Path:
    """Resolve the Windows ProgramData known folder as Codex does."""
    fallback = Path("C:/ProgramData")

    class Guid(ctypes.Structure):
        _fields_ = (
            ("data1", ctypes.c_uint32),
            ("data2", ctypes.c_uint16),
            ("data3", ctypes.c_uint16),
            ("data4", ctypes.c_ubyte * 8),
        )

    try:
        folder_id = Guid.from_buffer_copy(
            uuid.UUID("62ab5d82-fdc1-4dc3-a9dd-070d1d495d97").bytes_le
        )
        path_pointer = ctypes.c_void_p()
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        get_known_folder_path = shell32.SHGetKnownFolderPath
        get_known_folder_path.argtypes = (
            ctypes.POINTER(Guid),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        get_known_folder_path.restype = ctypes.c_int32
        result = get_known_folder_path(
            ctypes.byref(folder_id), 0, None, ctypes.byref(path_pointer)
        )
        if result != 0 or path_pointer.value is None:
            return fallback
        try:
            return Path(ctypes.wstring_at(path_pointer.value))
        finally:
            free_memory = ole32.CoTaskMemFree
            free_memory.argtypes = (ctypes.c_void_p,)
            free_memory.restype = None
            free_memory(path_pointer)
    except (AttributeError, OSError, ValueError):
        return fallback


def codex_system_config_path() -> Path:
    """Return Codex's inspectable system config location for this platform."""
    if os.name == "nt":
        return windows_program_data_path() / "OpenAI" / "Codex" / "config.toml"
    return Path("/etc/codex/config.toml")


def codex_managed_config_path(codex_home: Path) -> Path:
    """Return Codex's inspectable legacy managed-config location."""
    if os.name == "nt":
        return codex_home / "managed_config.toml"
    return Path("/etc/codex/managed_config.toml")


def top_level_codex_config_values(config_path: Path, key: str) -> list[tuple[str, Any]]:
    """Return a config layer's top-level value for one key, when present."""
    config = toml_config(config_path)
    if config is None:
        return []
    return [(key, config[key])] if key in config else []


def inline_hook_documents_from_config(config_path: Path) -> list[tuple[str, str]]:
    """Return active stored inline-hook declarations in one config document."""
    declarations: list[tuple[str, str]] = []
    for location, hooks in top_level_codex_config_values(config_path, "hooks"):
        if not isinstance(hooks, dict):
            raise HarnessError(f"{location} in {config_path} must be a table")
        declarations.append((location, inline_hooks_json_document(hooks, config_path)))
    return declarations


def toml_json_default(value: Any) -> dict[str, str]:
    """Preserve ignored TOML-only scalar types without making known fields valid."""
    if isinstance(value, (datetime, date, time)):
        return {"__agent_harness_toml_scalar__": type(value).__name__}
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


def inline_hooks_json_document(hooks: dict[str, Any], config_path: Path) -> str:
    """Serialize a validated TOML hook table into the JSON adapter shape."""
    try:
        return json.dumps({"hooks": hooks}, default=toml_json_default)
    except (RecursionError, TypeError, ValueError) as exc:
        raise HarnessError(
            f"unsupported inline hooks value in {config_path}: {exc}"
        ) from exc


def project_root_markers_from_config(
    config_path: Path,
) -> list[tuple[str, list[str]]]:
    """Return active stored marker declarations with Codex-compatible shapes."""
    declarations: list[tuple[str, list[str]]] = []
    for location, markers in top_level_codex_config_values(
        config_path, "project_root_markers"
    ):
        if not isinstance(markers, list) or any(
            not isinstance(marker, str) for marker in markers
        ):
            raise HarnessError(
                f"{location} in {config_path} must be an array of strings"
            )
        declarations.append((location, markers))
    return declarations


def codex_profile_config_paths(codex_home: Path) -> list[Path]:
    """Enumerate stored profile-v2 configs without suppressing I/O errors."""
    try:
        entries = os.scandir(codex_home)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise HarnessError(
            f"cannot enumerate Codex profile configs in {codex_home}: {exc}"
        ) from exc
    suffix = ".config.toml"
    paths: list[Path] = []
    try:
        with entries:
            for entry in entries:
                candidate = codex_home / entry.name
                profile_name = entry.name[: -len(suffix)]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", profile_name):
                    continue
                if entry.name.endswith(suffix):
                    paths.append(candidate)
                    continue
                if not entry.name.casefold().endswith(suffix):
                    continue
                exact_suffix_alias = codex_home / f"{entry.name[:-len(suffix)]}{suffix}"
                try:
                    alias_stat = exact_suffix_alias.stat()
                except FileNotFoundError:
                    continue
                if os.path.samestat(alias_stat, candidate.stat()):
                    paths.append(candidate)
    except OSError as exc:
        raise HarnessError(
            f"cannot enumerate Codex profile configs in {codex_home}: {exc}"
        ) from exc
    return sorted(paths)


_CODEX_STRUCTURED_FEATURE_FIELDS = {
    "code_mode": {
        "enabled": "boolean",
        "excluded_tool_namespaces": "array of strings",
        "direct_only_tool_namespaces": "array of strings",
    },
    "multi_agent_v2": {
        "enabled": "boolean",
        "max_concurrent_threads_per_session": "usize",
        "min_wait_timeout_ms": "integer",
        "max_wait_timeout_ms": "integer",
        "default_wait_timeout_ms": "integer",
        "usage_hint_enabled": "boolean",
        "usage_hint_text": "string",
        "root_agent_usage_hint_text": "string",
        "subagent_usage_hint_text": "string",
        "multi_agent_mode_hint_text": "string",
        "tool_namespace": "string",
        "hide_spawn_agent_metadata": "boolean",
        "expose_spawn_agent_model_overrides": "boolean",
        "non_code_mode_only": "boolean",
    },
    "token_budget": {
        "enabled": "boolean",
        "reminder_threshold_tokens": "integer",
        "reminder_message_template": "string",
        "guidance_message": "string",
        "auto_compact_fallback_prompt": "string",
        "auto_compact_fallback_buffer_tokens": "integer",
    },
    "rollout_budget": {
        "enabled": "boolean",
        "limit_tokens": "integer",
        "reminder_at_remaining_tokens": "array of integers",
        "sampling_token_weight": "number",
        "prefill_token_weight": "number",
    },
    "current_time_reminder": {
        "enabled": "boolean",
        "reminder_interval_seconds": "u64",
        "clock_source": "current time source",
        "delivery_mode": "current time delivery mode",
        "sleep_tool": "boolean",
    },
    "apps_mcp_path_override": {
        "enabled": "boolean",
        "path": "string",
    },
    "network_proxy": {
        "enabled": "boolean",
        "proxy_url": "string",
        "enable_socks5": "boolean",
        "socks_url": "string",
        "enable_socks5_udp": "boolean",
        "allow_upstream_proxy": "boolean",
        "dangerously_allow_non_loopback_proxy": "boolean",
        "dangerously_allow_all_unix_sockets": "boolean",
        "mode": "network proxy mode",
        "domains": "network permission table",
        "unix_sockets": "network permission table",
        "allow_local_binding": "boolean",
    },
}


def codex_feature_field_matches(value: Any, expected: str) -> bool:
    """Match the Serde value shapes used by Codex's structured feature tables."""
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return type(value) is int
    if expected == "usize":
        return type(value) is int and 0 <= value <= USIZE_MAX
    if expected == "u64":
        return type(value) is int and 0 <= value <= U64_MAX
    if expected == "number":
        return type(value) in {int, float}
    if expected == "array of strings":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if expected == "array of integers":
        return isinstance(value, list) and all(type(item) is int for item in value)
    if expected == "current time source":
        return isinstance(value, str) and value in {"system", "external"}
    if expected == "current time delivery mode":
        return isinstance(value, str) and value in {
            "any_inference",
            "after_user_or_tool_output",
        }
    if expected == "network proxy mode":
        return isinstance(value, str) and value in {"limited", "full"}
    if expected == "network permission table":
        return isinstance(value, dict) and all(
            isinstance(key, str)
            and isinstance(permission, str)
            and permission in {"allow", "deny"}
            for key, permission in value.items()
        )
    raise AssertionError(f"unknown Codex feature field type: {expected}")


def validate_codex_feature_value(
    key: str, value: Any, config_path: Path, location: str
) -> None:
    """Validate FeaturesToml's bool-or-typed-table Serde union."""
    if isinstance(value, bool):
        return
    fields = _CODEX_STRUCTURED_FEATURE_FIELDS.get(key)
    if fields is None:
        raise HarnessError(
            f"features.{key} in {config_path}:{location} must be a boolean"
        )
    if not isinstance(value, dict):
        raise HarnessError(
            f"features.{key} in {config_path}:{location} must be a boolean or table"
        )
    unknown = sorted(set(value) - set(fields))
    if unknown:
        raise HarnessError(
            f"features.{key} in {config_path}:{location} has unsupported fields: "
            + ", ".join(unknown)
        )
    for field, field_value in value.items():
        expected = fields[field]
        if not codex_feature_field_matches(field_value, expected):
            raise HarnessError(
                f"features.{key}.{field} in {config_path}:{location} "
                f"must be {expected}"
            )


def hook_feature_declarations(
    config_path: Path,
    *,
    reject_legacy_profile: bool = False,
    project_local: bool = False,
) -> list[tuple[str, bool]]:
    """Return inspectable canonical and legacy-named hook feature toggles."""
    config = toml_config(config_path)
    if config is None:
        return []
    if reject_legacy_profile and "profile" in config:
        raise HarnessError(
            f"legacy profile selection in {config_path} is unsupported by Codex"
        )
    declarations: list[tuple[str, bool]] = []

    def inspect(container: dict[str, Any], location: str, *, active: bool) -> None:
        if "features" not in container:
            return
        features = container["features"]
        if not isinstance(features, dict):
            raise HarnessError(f"features in {config_path}:{location} must be a table")
        for key, value in features.items():
            # Codex sanitizes this user/system-only feature out of every
            # project-local layer before typed FeaturesToml deserialization.
            if project_local and key == "respect_system_proxy":
                continue
            validate_codex_feature_value(key, value, config_path, location)
        if active:
            key = "hooks" if "hooks" in features else "codex_hooks"
            if key in features:
                declarations.append(
                    (f"{config_path}:{location}.features.{key}", features[key])
                )

    inspect(config, "top-level", active=True)
    if reject_legacy_profile:
        if "profiles" in config and not isinstance(config["profiles"], dict):
            raise HarnessError(f"profiles in {config_path} must be a table")
        profiles = config.get("profiles", {})
        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                raise HarnessError(f"profiles.{name} in {config_path} must be a table")
            inspect(profile, f"profiles.{name}", active=False)
    return declarations


def requirements_hook_feature_declaration(
    requirements_path: Path,
) -> tuple[str, bool] | None:
    """Return the effective managed Codex hook feature requirement, if present."""
    requirements = toml_config(requirements_path)
    if requirements is None:
        return None
    aliases = [
        key for key in ("features", "feature_requirements") if key in requirements
    ]
    if len(aliases) > 1:
        raise HarnessError(
            f"{requirements_path} must not declare both features and feature_requirements"
        )
    if not aliases:
        return None
    section_name = aliases[0]
    features = requirements[section_name]
    if not isinstance(features, dict):
        raise HarnessError(f"{section_name} in {requirements_path} must be a table")
    for key, value in features.items():
        if not isinstance(value, bool):
            raise HarnessError(
                f"{section_name}.{key} in {requirements_path} must be a boolean"
            )

    # ManagedFeatures canonicalizes both names to CodexHooks. The flattened
    # BTreeMap visits the legacy name first, so a canonical declaration wins.
    key = "hooks" if "hooks" in features else "codex_hooks"
    if key not in features:
        return None
    return f"{requirements_path}:{section_name}.{key}", features[key]


def valid_user_hook_states(config_path: Path) -> list[tuple[str, bool | None]]:
    """Return valid user hook-state entries; Codex ignores malformed entries."""
    config = toml_config(config_path)
    if config is None:
        return []
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return []
    state = hooks.get("state")
    if not isinstance(state, dict):
        return []
    result: list[tuple[str, bool | None]] = []
    for key, entry in state.items():
        if not isinstance(entry, dict):
            continue
        enabled = entry.get("enabled")
        trusted_hash = entry.get("trusted_hash")
        if ("enabled" in entry and not isinstance(enabled, bool)) or (
            "trusted_hash" in entry and not isinstance(trusted_hash, str)
        ):
            continue
        normalized_key = key.strip()
        if normalized_key:
            result.append((normalized_key, enabled))
    return result


def codex_project_hook_activation_status(
    codex_home: Path,
    project_config_paths: list[Path],
    canonical_hook_keys: set[str],
) -> tuple[bool, str]:
    """Fail closed on inspectable settings that disable the project floor."""
    profile_paths = codex_profile_config_paths(codex_home)
    system_config = codex_system_config_path()
    requirements_path = system_config.with_name("requirements.toml")
    requirements = toml_config(requirements_path)
    blockers: list[str] = []
    if requirements is not None and "allow_managed_hooks_only" in requirements:
        managed_only = requirements["allow_managed_hooks_only"]
        if not isinstance(managed_only, bool):
            raise HarnessError(
                f"allow_managed_hooks_only in {requirements_path} must be a boolean"
            )
        if managed_only:
            blockers.append(f"{requirements_path}:allow_managed_hooks_only=true")
    required_hook_feature = requirements_hook_feature_declaration(requirements_path)
    hook_feature_pin: bool | None = None
    pin_location = ""
    if required_hook_feature is not None:
        pin_location, hook_feature_pin = required_hook_feature
        if not hook_feature_pin:
            blockers.append(f"{pin_location}=false")

    stored_feature_paths = [
        system_config,
        codex_home / "config.toml",
        *profile_paths,
        codex_managed_config_path(codex_home),
    ]
    # Every layer is still parsed and schema-checked, because a malformed
    # feature value fails the typed load no matter which layer wins.
    feature_disables: list[str] = []
    for config_path in dict.fromkeys(stored_feature_paths):
        feature_disables.extend(
            location
            for location, enabled in hook_feature_declarations(
                config_path, reject_legacy_profile=True
            )
            if not enabled
        )
    for config_path in dict.fromkeys(project_config_paths):
        feature_disables.extend(
            location
            for location, enabled in hook_feature_declarations(
                config_path, project_local=True
            )
            if not enabled
        )
    # A managed requirements pin of the hook feature TRUE and a lower-layer
    # disable contest each other, and which one Codex applies is not statically
    # provable from anything inspectable here: the shipped binary documents the
    # requirements schema but states no merge order for `[features]`, and the
    # one merge rule it does state out loud ("Codex merges these rules with
    # other config and uses the most restrictive result") is about prefix rules.
    # `doctor` certifies floors, so an unprovable conflict fails closed and
    # names both declarations rather than assuming the administrator wins.
    contested_disables = feature_disables if hook_feature_pin is True else []
    blockers.extend(feature_disables)

    user_paths = [codex_home / "config.toml", *profile_paths]
    for config_path in dict.fromkeys(user_paths):
        blockers.extend(
            f"{config_path}:hooks.state[{key!r}].enabled=false"
            for key, enabled in valid_user_hook_states(config_path)
            if key in canonical_hook_keys and enabled is False
        )

    boundary = (
        "CLI/session/managed-cloud feature, policy, and state overrides remain "
        "runtime-only; confirm enabled/trusted status in exact-CWD new-session /hooks"
    )
    if contested_disables:
        boundary = (
            f"{pin_location}=true contests {len(contested_disables)} "
            "hook-feature disable(s), but Codex's merge order for managed "
            "requirements against stored config features is UNPROVEN here, so "
            f"the conflict fails closed; {boundary}"
        )
    if blockers:
        return (
            False,
            f"inspectable activation blocker(s): {'; '.join(blockers)}; {boundary}",
        )
    return (
        True,
        f"no inspectable managed-only, feature-disable, or floor-state blocker; {boundary}",
    )


def codex_project_root_marker_status(codex_home: Path) -> tuple[bool, str]:
    """Fail closed when inspectable config can move Codex's project root.

    Codex determines its project root before loading project-local layers. The
    Git-root audit below is exact only for the default ``[\".git\"]`` marker
    topology, so any stored base, system, or profile-v2 override is an explicit
    static-verification boundary rather than a guessed layer walk.
    """
    config_paths = [
        codex_system_config_path(),
        codex_home / "config.toml",
        *codex_profile_config_paths(codex_home),
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


def inspectable_global_codex_floor_status(codex_home: Path) -> tuple[int, str]:
    """Count deny-floor copies in every statically inspectable global layer."""
    system_config = codex_system_config_path()
    requirements_path = system_config.with_name("requirements.toml")
    requirements_hook_feature_declaration(requirements_path)
    json_paths = [system_config.with_name("hooks.json"), codex_home / "hooks.json"]
    config_sources = [
        (requirements_path, "requirements"),
        (system_config, "config"),
        (codex_home / "config.toml", "config"),
        *((path, "config") for path in codex_profile_config_paths(codex_home)),
        (codex_managed_config_path(codex_home), "config"),
    ]
    sources: list[str] = []
    count = 0
    for hooks_path in dict.fromkeys(json_paths):
        hooks_text = read_optional_text(hooks_path)
        if hooks_text is None:
            continue
        groups = managed_codex_floor_groups(hooks_text)
        count += len(groups)
        if groups:
            sources.append(f"{hooks_path} ({len(groups)})")
    for config_path, source_kind in dict(config_sources).items():
        for location, document in inline_hook_documents_from_config(config_path):
            groups = managed_codex_floor_groups(document, source_kind=source_kind)
            count += len(groups)
            if groups:
                sources.append(f"{config_path}:{location} ({len(groups)})")

    source_detail = ", ".join(sources) if sources else "none"
    boundary = (
        "managed cloud/MDM/session/plugin hooks require /hooks in the exact "
        "new-session cwd"
    )
    return (
        count,
        f"{count} inspectable global floor group(s); sources: {source_detail}; "
        f"{boundary}",
    )


def inline_hooks_document(config_path: Path) -> str:
    """Convert inline TOML hooks to the hooks.json document shape."""
    hooks = inline_hooks_from_config(config_path)
    if hooks is None:
        return ""
    if not isinstance(hooks, dict):
        raise HarnessError(f"hooks in {config_path} must be a table")
    return inline_hooks_json_document(hooks, config_path)


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
    active_layers: list[Path] = []
    for directory in directories:
        dot_codex = directory / ".codex"
        try:
            mode = dot_codex.stat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise HarnessError(
                f"cannot inspect Codex layer {dot_codex}: {exc}"
            ) from exc
        if stat.S_ISDIR(mode):
            active_layers.append(directory)
    return active_layers


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


def tier_paths(repo: Path) -> list[Path]:
    """Every tier declaration this repo carries, highest precedence first.

    `.agent-harness/tier.json` is the runtime-neutral home and `.claude/` the
    legacy one a migrating repo may still carry. Precedence orders the fields
    that are not comparable (`human_todo`, `budgets`); it never decides the
    posture — see `merge_tier_declarations`.
    """
    return [
        repo / directory / "tier.json"
        for directory in (".agent-harness", ".claude")
        if (repo / directory / "tier.json").is_file()
    ]


def tier_path(repo: Path) -> Path | None:
    """The declaration `seed` must refuse to write over, if any exists."""
    paths = tier_paths(repo)
    return paths[0] if paths else None


def read_tier_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"invalid tier file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessError(f"tier file must contain an object: {path}")
    return data


# Weakest first: the strictest declaration binds, so a legacy `human-only`
# merge gate cannot be masked by a newer `free` one.
AUTHORITY_STRICTNESS = ("free", "gated", "human-only")


def merge_tier_declarations(declarations: list[dict[str, Any]]) -> dict[str, Any]:
    """The one posture co-located declarations bind to: the strictest.

    Law 9 and the dispatcher (`dispatch.load_tier`, SPECS §5) agree on the
    rules, and this mirrors them exactly rather than inventing a second
    semantics for the auditing tool:

    * the HIGHEST declared tier wins;
    * tightening flags are ORed, so a stale `.claude/tier.json` carrying
      `sensitive_data` keeps binding after the new file omits it;
    * `relaxed_work_loss_guards` is the one RELAXATION, so it applies only
      when EVERY declaration agrees — a single silent file must not hand a
      repo a looser git posture than it declared;
    * `authority.push`/`.merge` take the strictest value declared.

    Reading `.agent-harness/tier.json` with FALLBACK to the legacy file was
    first-found-wins, so a repo declaring T1 in the new file while a surviving
    T4 + sensitive_data legacy file sat beside it audited at the WEAKER posture
    the dispatcher would never grant it (issue #99).

    Fields that express no posture — `name`, `human_todo`, `budgets`,
    `last_reviewed` — are not comparable, so the highest-precedence
    declaration that CONTAINS the key supplies it (an explicit `null` is a
    declaration, not an omission). Each file is still validated on its own by
    `validate_tier`; this merge is about what binds, not about what is legal.
    """
    if not declarations:
        return {}
    merged: dict[str, Any] = {}
    for declaration in reversed(declarations):
        merged.update(declaration)
    tiers = [
        declaration["tier"]
        for declaration in declarations
        if declaration.get("tier") in TIER_NAMES
    ]
    if tiers:
        merged["tier"] = max(tiers)
    merged["flags"] = merge_tier_flags(declarations)
    authority = merge_tier_authority(declarations)
    if authority is not None:
        merged["authority"] = authority
    return merged


def merge_tier_flags(declarations: list[dict[str, Any]]) -> Any:
    """OR every tightening flag; require unanimity for the one relaxation."""
    flag_sets = [
        declaration.get("flags")
        for declaration in declarations
        if isinstance(declaration.get("flags"), dict)
    ]
    if not flag_sets:
        # Nothing mergeable: keep what the highest-precedence file declared so
        # `validate_tier` still reports the malformed value it reported before.
        return declarations[0].get("flags")
    flags: dict[str, Any] = {}
    for flag_set in flag_sets:
        for key, value in flag_set.items():
            if key == "relaxed_work_loss_guards":
                continue
            if isinstance(value, bool):
                flags[key] = bool(flags.get(key)) or value
            elif key not in flags:
                flags[key] = value
    flags["relaxed_work_loss_guards"] = all(
        bool(flag_set.get("relaxed_work_loss_guards")) for flag_set in flag_sets
    )
    return flags


def merge_tier_authority(declarations: list[dict[str, Any]]) -> Any:
    """The strictest push/merge dial any declaration sets, or None."""
    authorities = [
        declaration.get("authority")
        for declaration in declarations
        if isinstance(declaration.get("authority"), dict)
    ]
    if not authorities:
        return None
    merged = dict(authorities[-1])
    for authority in reversed(authorities):
        for key, value in authority.items():
            current = merged.get(key)
            if (
                value in AUTHORITY_STRICTNESS
                and current in AUTHORITY_STRICTNESS
                and AUTHORITY_STRICTNESS.index(value)
                <= AUTHORITY_STRICTNESS.index(current)
            ):
                continue
            merged[key] = value
    return merged


def tier_declarations(repo: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Read every declaration this repo carries, highest precedence first."""
    return [(path, read_tier_file(path)) for path in tier_paths(repo)]


def load_tier(repo: Path) -> tuple[list[Path], dict[str, Any]]:
    """(the declaration files, the strictest posture they bind to)."""
    declarations = tier_declarations(repo)
    return [path for path, _ in declarations], merge_tier_declarations(
        [data for _, data in declarations]
    )


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
    # The deny-floor ledger declares its own cap and rotation target in its
    # header (SPECS §3). Unregistered, an overflowing ledger was reported by
    # nothing at all.
    if (repo / "FLOOR_LIMITATIONS.md").is_file():
        checks.append(
            (
                repo / "FLOOR_LIMITATIONS.md",
                120,
                "rotate to archive/floor-limitations-<year>.md",
            )
        )
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


# --- reality checks: declarations measured against the world, not each other ---
#
# Every check below answers "is the declared thing actually true?" and reports
# one of three states. `MISMATCH` means two things that must agree do not, and
# is a hard failure. `UNPROVEN` means the check could not run (offline, no
# `gh`, an unresolvable host, an exhausted budget) and must never render as a
# pass. `advisory` is a real observation that is not by itself a defect.
# Subprocess use follows the deny floor's discipline (`dispatch.py`
# `command_output_before_deadline`): every resolver is read-only, bounded by a
# per-command timeout AND a shared aggregate deadline, and injectable so tests
# never spawn a process or touch the network. An offline run degrades to
# `UNPROVEN` and exits 0 rather than failing CI.
REALITY_BUDGET_SECONDS = 8.0
REALITY_COMMAND_TIMEOUT_SECONDS = 3.0
REALITY_OK = "ok"
REALITY_MISMATCH = "MISMATCH"
REALITY_UNPROVEN = "UNPROVEN"
REALITY_ADVISORY = "advisory"
PRIVACY_CLAIM_DOCS = ("AGENTS.md", "CLAUDE.md", "README.md")

# The phrasings a doc actually uses to claim privacy. The first version only
# matched "private" immediately followed by one of three singular nouns, which
# misses "this repository is private", "private repos" and "kept private" - the
# most natural spellings - so the advertised converse check almost never fired.
#
# EVERY alternative requires one of these nouns inside the match. A bare
# `(?:kept|keep|stays?|remains?)\s+private` fires on ordinary secrets-hygiene
# boilerplate - "Keep private keys out of version control", "Secrets remain
# private to the operator" - and then reports a two-word fragment as if the doc
# had made a claim about the REPOSITORY. Requiring the noun both removes that
# false positive and makes the quoted fragment show what is being kept private.
_PRIVACY_NOUNS = r"(?:repo|repository|remote)s?"
_PRIVACY_STATES = r"(?:is|are|was|were|stays?|stayed|remains?|remained|kept|keeps?)"
PRIVACY_CLAIM_PATTERN = re.compile(
    # "a private repo", "private GitHub repository"
    rf"private\s+(?:\w+\s+){{0,2}}{_PRIVACY_NOUNS}\b"
    # "this repository is private", "the repo stays private", "repos are kept private"
    rf"|{_PRIVACY_NOUNS}\b(?:\s+\w+){{0,3}}\s+{_PRIVACY_STATES}\s+private\b"
    # "keep the repo private"
    rf"|(?:keeps?|kept|stays?|remains?)\s+(?:\w+\s+){{0,2}}{_PRIVACY_NOUNS}\b"
    rf"(?:\s+\w+){{0,2}}\s+private\b",
    re.IGNORECASE,
)
# A remote nothing is published THROUGH a host: a `file://` URL, a drive path,
# or a relative/home/absolute local path. The leading `//` (or `\\`) authority
# is excluded: `//server/share/repo.git` is a UNC network share whose reach is
# exactly what a sensitive-data audit must not assert, and calling it
# "local-only" printed `ok` without measuring who can read it.
LOCAL_REMOTE_PATTERN = re.compile(r"^(?:file://|[a-zA-Z]:[\\/]|[.~]|/(?!/)|\\(?!\\))")
UNC_REMOTE_PATTERN = re.compile(r"^(?://|\\\\)[^/\\]")
# A `file://` URL hides a host in two different places, and the share test has
# to see both before `LOCAL_REMOTE_PATTERN`'s `file://` alternative claims the
# URL: `file://server/share/x` puts the host in the AUTHORITY, while
# `file:////server/share/x` has an empty authority and the UNC path in the path
# component. Stripping a fixed prefix caught only the second.
_FILE_URL = re.compile(r"(?i)^file://([^/]*)(/.*)?$")


def remote_names_a_network_share(url: str) -> bool:
    """Whether this remote names a HOST rather than a path on this machine."""
    candidate = url.strip()
    match = _FILE_URL.match(candidate)
    if match:
        authority = match.group(1)
        if authority and authority.lower() != "localhost":
            return True
        candidate = match.group(2) or ""
    return bool(UNC_REMOTE_PATTERN.match(candidate))


# The remote work is actually published to. A public remote under any other
# name (a fork's upstream, a mirror) is a topology note, not an exposure.
PUBLISHING_REMOTE = "origin"
# git's "dot repository": pushing to `.` targets THIS repository, never a
# remote (see git-config, branch.<name>.remote).
LOCAL_PUSH_REMOTE = "."
VENDORED_FLOOR_FILES = ("dispatch.py", "smoke_test.py")
# Both shapes a repo can carry its own floor bytes in. `.claude/hooks/` is the
# one `doctor` already recognizes as "a repo-local dispatcher copy rather than
# the shared home-anchored one"; probing only `hooks/` made the drift check a
# silent no-op for every repo that vendors the way this estate actually does.
VENDORED_FLOOR_DIRS = (PurePosixPath("hooks"), PurePosixPath(".claude/hooks"))


def bounded_command_output(
    argv: list[str],
    cwd: Path | None = None,
    timeout: float = REALITY_COMMAND_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """`bounded_command_result` for the callers that need no failure text."""
    resolved, stdout, _failure = bounded_command_result(argv, cwd, timeout)
    return resolved, stdout


def bounded_command_result(
    argv: list[str],
    cwd: Path | None = None,
    timeout: float = REALITY_COMMAND_TIMEOUT_SECONDS,
) -> tuple[bool, str, str]:
    """Run one read-only resolver under a hard timeout; never raise.

    Returns `(resolved, stdout, failure text)`. The third element is what a
    failed probe SAID — its stderr, or why it never started — so an UNPROVEN
    finding can name its own cause (a `gh` GraphQL quota refusal, an expired
    credential) instead of being mute. It is never a substitute for
    `resolved`: a resolver that answers leaves it empty.


    Decoding is explicit and tolerant. Under `text=True` alone, a resolver that
    emits bytes the platform locale cannot decode — a non-UTF-8 configured
    remote, a branch name in another encoding — raises `UnicodeDecodeError`
    while `subprocess.run` builds its result. Neither this handler nor `main()`
    catches that, so an audit died with a traceback where the contract says the
    check is simply UNPROVEN. `errors="replace"` keeps whatever is decodable
    and leaves the rest as replacement characters; `UnicodeError` is still
    caught, because a caller may pass its own runner.

    The timeout is a HARD bound on this function, not just on the direct child.
    `subprocess.run` kills only the process it started, so `git ls-remote`'s ssh
    helper — which inherits the captured pipes and carries its own much longer
    network timeout — could keep the drain waiting long past the deadline the
    aggregate budget is built on. The child is started in its own process group
    (POSIX) and the whole tree is killed on timeout (`taskkill /T` on Windows);
    the pipes are then closed without a second blocking read, so the bound
    holds even if a descendant survives.

    argv[0] is resolved against PATH before the spawn (`probe_spawn_argv`).
    These probes run with `cwd` set to the repository under inspection, and
    Windows would otherwise let that repository answer to the name `git`.
    """
    spawn_argv, unresolved = probe_spawn_argv(argv)
    if unresolved:
        return False, "", unresolved
    popen_kwargs: dict[str, Any] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            spawn_argv,
            cwd=str(cwd) if cwd is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            **popen_kwargs,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # The resolver never ran: an absent `gh` is a NAMED diagnosis here and
        # an indistinguishable empty answer without it.
        return False, "", f"{argv[0]} could not be started: {exc}"
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process_tree(proc)
        return False, "", f"{argv[0]} did not answer within {timeout:.1f}s"
    except (OSError, ValueError, UnicodeError) as exc:
        terminate_process_tree(proc)
        return False, "", f"{argv[0]} could not be read: {exc}"
    if proc.returncode == 0:
        return True, (stdout or "").strip(), ""
    return False, (stdout or "").strip(), (stderr or "").strip()


def terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Kill a timed-out resolver and every descendant, then stop reading it.

    Nothing here may block: this runs because a deadline was already missed.
    The pipes are closed rather than drained, so a descendant that survives
    cannot hold this process open — the file objects are released to the GC.
    """
    try:
        if os.name == "nt":
            # Resolved like every other spawn: this runs with the harness's own
            # cwd, which for `audit .` is the repository under inspection, and a
            # planted `taskkill.exe` would be handed a hostile process tree.
            # An unresolvable taskkill is not fatal — `proc.kill()` below still
            # reaches the direct child.
            killer, unresolved = probe_spawn_argv(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)]
            )
            if not unresolved:
                subprocess.run(
                    killer,
                    capture_output=True,
                    timeout=REALITY_COMMAND_TIMEOUT_SECONDS,
                    check=False,
                )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except (OSError, ValueError):
        pass
    for pipe in (proc.stdout, proc.stderr):
        try:
            if pipe is not None:
                pipe.close()
        except OSError:
            pass


# `git` is not by itself a local resolver: these subcommands contact the
# remote, so `--offline` has to refuse them by name rather than trust the
# binary. `remote --verbose` reads config and stays; `remote show/update`
# does not.
NETWORK_GIT_SUBCOMMANDS = frozenset(
    {"clone", "fetch", "pull", "push", "ls-remote", "submodule", "archive"}
)
NETWORK_GIT_REMOTE_ACTIONS = frozenset({"show", "update", "prune"})


def command_reaches_the_network(argv: list[str]) -> bool:
    """Whether this resolver would contact a host; `--offline` refuses these."""
    if argv[:1] != ["git"]:
        return True
    operands = [token for token in argv[1:] if not token.startswith("-")]
    if not operands:
        return False
    if operands[0] in NETWORK_GIT_SUBCOMMANDS:
        return True
    return (
        operands[0] == "remote"
        and len(operands) > 1
        and operands[1] in NETWORK_GIT_REMOTE_ACTIONS
    )


def offline_aware_command_runner(args: argparse.Namespace) -> Any:
    """The resolver an `--offline`-capable subcommand must use.

    One selector for every probe a subcommand makes: `doctor --repo --offline`
    shipped with the reality checks routed through it and the floor-reference
    probe still hard-wired to the network runner, so the "offline" run reached
    the remote anyway.
    """
    if getattr(args, "offline", False):
        return local_only_command_output
    return bounded_command_output


def local_only_command_output(
    argv: list[str],
    cwd: Path | None = None,
    timeout: float = REALITY_COMMAND_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """`audit --offline`: answer local resolvers, refuse every network one.

    A refused resolver returns "did not answer", which every caller already
    reports as UNPROVEN — the audit stays honest about what it did not
    measure instead of pretending an unmeasured remote is fine.
    """
    resolved, stdout, _failure = local_only_command_result(argv, cwd, timeout)
    return resolved, stdout


def local_only_command_result(
    argv: list[str],
    cwd: Path | None = None,
    timeout: float = REALITY_COMMAND_TIMEOUT_SECONDS,
) -> tuple[bool, str, str]:
    """`local_only_command_output`, keeping the reason it refused."""
    if command_reaches_the_network(argv):
        return False, "", f"--offline refused the network resolver `{argv[0]}`"
    return bounded_command_result(argv, cwd, timeout)


# The runners that accept a `timeout`, and so can be clamped to what is left of
# the aggregate budget. A test's fake runner is deliberately not one of them.
CLAMPABLE_COMMAND_RUNNERS = (
    bounded_command_output,
    local_only_command_output,
    bounded_command_result,
    local_only_command_result,
)
# The failure-text twin of each production runner. A probe that needs to NAME
# why it failed is routed through the twin; an injected fake runner has none
# and keeps its two-element contract.
COMMAND_RESULT_RUNNERS = {
    bounded_command_output: bounded_command_result,
    local_only_command_output: local_only_command_result,
}


def output_before_deadline(
    command_runner: Any,
    argv: list[str],
    cwd: Path | None,
    deadline: float | None,
) -> tuple[bool, str]:
    """`result_before_deadline` for callers that report no failure text."""
    resolved, output, _failure = result_before_deadline(
        command_runner, argv, cwd, deadline
    )
    return resolved, output


def result_before_deadline(
    command_runner: Any,
    argv: list[str],
    cwd: Path | None,
    deadline: float | None,
) -> tuple[bool, str, str]:
    """Run a resolver without overrunning the audit's aggregate budget.

    The clock is read ONCE, before the call: an exhausted budget starts no new
    process, and the per-command timeout is clamped to what is left, so the
    whole sweep is bounded by the budget plus at most one in-flight command.
    Unlike `dispatch.py`, a late answer is KEPT rather than discarded — a hook
    must not delay a tool call, but an audit has no latency contract, and
    throwing away a measurement that already proved a remote PUBLIC would turn
    the exact finding this exists to make into an UNPROVEN.

    Returns `(resolved, stdout, failure text)`. A runner that answers with the
    two-element contract — every injected fake — simply reports no failure
    text; the production runners are swapped for the twin that keeps it.
    """
    runner = COMMAND_RESULT_RUNNERS.get(command_runner, command_runner)
    if deadline is None:
        return normalized_command_result(runner(argv, cwd))
    remaining = deadline - monotonic()
    if remaining <= 0:
        return False, "", "the probe budget expired before this command ran"
    # Every production runner takes the clamp, not just the network one:
    # `--offline` still shells out to local git, and a `status`/`ls-files`/
    # `rev-list` on a network-mounted checkout can be slow enough to overrun
    # the advertised aggregate budget with its own 3s default. A test's fake
    # runner takes no timeout, so it is called with the plain signature.
    if runner in CLAMPABLE_COMMAND_RUNNERS:
        return normalized_command_result(
            runner(argv, cwd, timeout=min(REALITY_COMMAND_TIMEOUT_SECONDS, remaining))
        )
    return normalized_command_result(runner(argv, cwd))


def normalized_command_result(result: Any) -> tuple[bool, str, str]:
    """Accept either runner contract: `(resolved, stdout[, failure text])`."""
    values = tuple(result)
    if len(values) == 3:
        resolved, stdout, failure = values
    else:
        resolved, stdout = values
        failure = ""
    return bool(resolved), stdout, failure


def reality_finding(check: str, status: str, detail: str) -> dict[str, str]:
    return {"check": check, "status": status, "detail": detail}


# `git remote --verbose` preserves URL userinfo, so a remote configured as
# `https://ci-user:PAT@host/acme/repo.git` carries a live credential. Every
# finding this module renders reaches stdout, `--json` and the `doctor --repo`
# detail, so the token is stripped before it is stored, never at the printer.
_REMOTE_USERINFO = re.compile(r"^([a-z][a-z0-9+.-]*://)[^/@]+@", re.IGNORECASE)


def redact_remote_url(url: str) -> str:
    """Return the remote URL with any embedded credential replaced.

    Two places a credential rides in a remote URL, and both reach stdout,
    `--json` and the `doctor --repo` detail:

    * userinfo — `https://ci-user:PAT@host/acme/repo.git`. Only
      scheme-qualified userinfo is redacted: `git@github.com:owner/repo` is scp
      syntax whose `git` is a fixed account name, not a secret, and blanking it
      would make the finding harder to act on for no gain.
    * query/fragment — `https://gitlab.example/acme/repo.git?private_token=PAT`.
      Nothing downstream needs it (`github_repo_slug` already stops at `?`), so
      the whole tail is dropped rather than parsed for known parameter names,
      which would keep failing open on the next host's spelling.
    """
    redacted = _REMOTE_USERINFO.sub(r"\1***@", url.strip())
    parts = re.split(r"([?#])", redacted, maxsplit=1)
    if len(parts) == 1:
        return redacted
    return f"{parts[0]}{parts[1]}<redacted>"


# A probe's own output is not a URL this module composed: `git` echoes whole
# remotes on failure and `gh` echoes tokens from a misconfigured credential
# helper, so every known credential shape is masked before the text is stored
# in a finding. The last pattern is deliberately shape-blind — it catches the
# token format that has not been invented yet.
_PROBE_SECRET_PATTERNS = (
    re.compile(r"(?<=//)[^/@\s]+(?=@)"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{4,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{4,}"),
    re.compile(r"[A-Za-z0-9+/_]{24,}={0,2}"),
)
# Ordered: GitHub answers an exhausted quota with an HTTP 403, so the rate
# limit must be recognized before the authentication pattern claims it.
_PROBE_FAILURE_CAUSES = (
    (re.compile(r"rate[\s_-]?limit", re.IGNORECASE), "quota exhausted"),
    (
        re.compile(
            r"\b(401|403)\b|unauthorized|bad credentials|authentication"
            r"|gh auth login|not logged in",
            re.IGNORECASE,
        ),
        "authentication",
    ),
    (re.compile(r"\b404\b|not found", re.IGNORECASE), "not found"),
    (
        re.compile(
            r"could not resolve host|connection (refused|reset)|no such host"
            r"|network is unreachable|i/o timeout|tls handshake|did not answer",
            re.IGNORECASE,
        ),
        "network",
    ),
)


def redact_probe_text(text: str) -> str:
    """Mask every credential shape a probe's own output is known to carry."""
    for pattern in _PROBE_SECRET_PATTERNS:
        text = pattern.sub("***", text)
    return text


def classify_probe_failure(text: str) -> str:
    """Name a probe failure's cause when the text makes it recognizable."""
    for pattern, cause in _PROBE_FAILURE_CAUSES:
        if pattern.search(text):
            return cause
    return ""


def probe_failure_note(argv: list[str], failure: str, limit: int = 160) -> str:
    """One line naming what a probe was and what it said when it failed.

    An UNPROVEN visibility line used to report only that `gh` "returned <no
    output>", which is the same sentence for an exhausted GraphQL quota, an
    expired token and an absent binary (issue #106 / #90). Quoting the probe's
    own words names the cause; redaction runs BEFORE the text is stored,
    because every finding reaches stdout, `--json` and the `doctor` detail.
    """
    label = redact_probe_text(" ".join(argv))
    head = ""
    for line in failure.splitlines():
        if line.strip():
            head = redact_probe_text(line.strip())
            break
    if len(head) > limit:
        head = head[: limit - 3] + "..."
    if not head:
        return f"`{label}` did not answer"
    cause = classify_probe_failure(head)
    return f"`{label}` failed{f' ({cause})' if cause else ''}: {head}"


def github_repo_slug(remote: str) -> str:
    """Return owner/repo for a github.com remote, without any credentials.

    An `ssh://` URL may carry a port (`ssh://git@github.com:22/owner/repo.git`,
    which git resolves as `ssh -p 22 git@github.com` with path `/owner/repo`).
    Without `(?::\\d+)?` the port was captured as the owner, so `gh` was asked
    about `22/owner` and a genuinely public origin degraded to UNPROVEN instead
    of raising the mismatch. `(?::\\d+)?` is optional and backtracks, so the
    portless `ssh://git@github.com:owner/repo` spelling still parses.
    """
    patterns = (
        r"^(?:https?|git)://(?:[^/@]+@)?github\.com(?::\d+)?/([^/?#]+/[^/?#]+)",
        r"^ssh://(?:[^@/]+@)?github\.com(?::\d+)?[:/]([^/?#]+/[^/?#]+)",
        r"^(?:[^@/]+@)?github\.com:([^/?#]+/[^/?#]+)",
    )
    for pattern in patterns:
        match = re.match(pattern, remote.strip(), re.IGNORECASE)
        if match:
            return match.group(1).removesuffix(".git")
    return ""


def configured_push_remote(
    repo: Path, command_runner: Any, deadline: float | None
) -> tuple[str, bool]:
    """(remote `git push` targets, whether that selection was measured).

    `origin` is only git's LAST fallback. `branch.<name>.pushRemote`,
    `remote.pushDefault` and `branch.<name>.remote` each override it, in that
    order, so a repo with a private `origin` and
    `remote.pushDefault = public-mirror` publishes to the public one — while an
    origin-only rule downgraded that PUBLIC result to an exit-0 advisory.

    Every query is `git config`, which reads local files and stays available
    under `--offline`. `git config --get` also exits non-zero for an UNSET key,
    so a failed probe cannot be told from an absent one — which is fine while
    the budget holds and a lie once it does not. An exhausted budget therefore
    returns `False` for the second element rather than guessing `origin`: the
    caller reports the whole check UNPROVEN instead of downgrading a public
    push endpoint to an advisory it never measured.
    """

    def exhausted() -> bool:
        return deadline is not None and deadline - monotonic() <= 0

    def configured(key: str) -> str:
        resolved, value = output_before_deadline(
            command_runner, ["git", "config", "--get", key], repo, deadline
        )
        return value.strip() if resolved else ""

    if exhausted():
        return PUBLISHING_REMOTE, False
    resolved, branch = output_before_deadline(
        command_runner, ["git", "rev-parse", "--abbrev-ref", "HEAD"], repo, deadline
    )
    branch = branch.strip() if resolved else ""
    candidates = []
    if branch and branch != "HEAD":
        candidates.append(f"branch.{branch}.pushRemote")
    candidates.append("remote.pushDefault")
    if branch and branch != "HEAD":
        candidates.append(f"branch.{branch}.remote")
    for key in candidates:
        if exhausted():
            return PUBLISHING_REMOTE, False
        configured_name = configured(key)
        if configured_name:
            return configured_name, True
    return PUBLISHING_REMOTE, not exhausted()


def configured_remote_urls(
    repo: Path, command_runner: Any, deadline: float | None
) -> tuple[bool, list[tuple[str, str, str]]]:
    """Enumerate (name, url, direction) rows; False when git was silent.

    The NAME matters: publishing happens to `origin`, so a public `upstream`
    on a private fork is a normal topology rather than an exposure. So does the
    DIRECTION: `git remote --verbose` prints the fetch and push endpoints on
    separate rows, and `remote.<name>.pushurl` may differ from
    `remote.<name>.url`, so discarding the third field made a public fetch
    endpoint look like the place work is published.
    """
    resolved, output = output_before_deadline(
        command_runner, ["git", "remote", "--verbose"], repo, deadline
    )
    if not resolved:
        return False, []
    rows = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        direction = parts[2].strip("()").lower() if len(parts) > 2 else ""
        # A row with no direction is git's own default: the same endpoint is
        # both fetched from and pushed to.
        rows.append((parts[0], parts[1], direction if direction else "push"))
    return True, list(dict.fromkeys(rows))


def publishing_remote_endpoints(
    rows: list[tuple[str, str, str]],
    publishing_remote: str = PUBLISHING_REMOTE,
) -> list[tuple[str, str, bool, str]]:
    """Fold `git remote -v` rows into (name, url, publishes, note) entries.

    `publishes` is what decides MISMATCH vs advisory. It is true only for a URL
    work can actually be pushed to under the remote this repo publishes
    through:

    * a URL that is a PUSH endpoint — a public `url` behind a private
      `pushurl` is a fetch mirror, not a place anything is published;
    * of ``publishing_remote`` — which is `origin` only as git's LAST fallback;
      `configured_push_remote` resolves `branch.<name>.pushRemote` and
      `remote.pushDefault` first, because a repo with a private `origin` and
      `remote.pushDefault = public-mirror` publishes to the public one;
    * or of ANY remote when the resolved publishing remote is not configured at
      all. The origin-only rule presumed a private `origin` exists; with none,
      calling the one remote that carries the work "not the publishing remote"
      turned a real exposure into an exit-0 advisory.

    `note` is the clause that explains a non-publishing verdict, so the finding
    says which of the reasons applied.
    """
    by_name: dict[str, dict[str, list[str]]] = {}
    for name, url, direction in rows:
        endpoints = by_name.setdefault(name, {"fetch": [], "push": []})
        bucket = endpoints["push" if direction == "push" else "fetch"]
        if url not in bucket:
            bucket.append(url)
    # git's "dot repository": `remote.pushDefault = .` pushes into THIS
    # repository, so no configured remote is a publishing endpoint. Passing the
    # literal `.` through would match no remote and then trip the "no
    # publishing remote is configured, so treat them all as publishing" rule —
    # a hard MISMATCH for a public origin an ordinary push never reaches.
    pushes_locally = publishing_remote == LOCAL_PUSH_REMOTE
    has_publishing_remote = publishing_remote in by_name
    entries: list[tuple[str, str, bool, str]] = []
    for name, endpoints in by_name.items():
        # git prints both rows; a fetch-only listing means the same endpoint.
        push_urls = endpoints["push"] or endpoints["fetch"]
        publishes_here = not pushes_locally and (
            name == publishing_remote or not has_publishing_remote
        )
        for url in dict.fromkeys(endpoints["fetch"] + endpoints["push"]):
            if pushes_locally:
                note = (
                    f"git pushes to the local repository ({LOCAL_PUSH_REMOTE}), so "
                    f"nothing is published to {name}"
                )
            elif not publishes_here:
                note = (
                    f"{name} is not the publishing remote ({publishing_remote}), "
                    "so never push this repo there"
                )
            elif url not in push_urls:
                note = f"{name} only FETCHES from this URL; it pushes to " + ", ".join(
                    redact_remote_url(each) for each in push_urls
                )
            elif has_publishing_remote:
                note = (
                    ""
                    if publishing_remote == PUBLISHING_REMOTE
                    else f"git is configured to push to {publishing_remote}, "
                    f"not {PUBLISHING_REMOTE}"
                )
            else:
                note = (
                    f"no remote named {publishing_remote!r} is configured, so "
                    f"{name} is treated as a publishing remote"
                )
            entries.append((name, url, publishes_here and url in push_urls, note))
    # Spend the shared probe budget on the endpoints that can produce a
    # MISMATCH first. The caller walks this list under one aggregate deadline,
    # so with git's alphabetical remote order a handful of slow advisory
    # remotes ahead of `origin` could exhaust it and leave the one exposure
    # this check exists to catch reported as UNPROVEN — an exit-0 pass.
    return sorted(entries, key=lambda entry: not entry[2])


# The only three answers either transport may give. Anything else — a literal
# `null`, an error page, a spelling GitHub has not shipped yet — is not a
# verdict, and must fall through to the other lane rather than be believed.
KNOWN_VISIBILITIES = frozenset({"PUBLIC", "PRIVATE", "INTERNAL"})
_REST_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


def github_rest_repo_path(slug: str) -> str:
    """Map a repository slug onto the REST route's `owner/repo` pair.

    The result is interpolated into argv, so validation is an ALLOWLIST and
    every rejection returns "" — the REST lane is skipped and GraphQL answers.
    Exactly two segments, each of the characters GitHub allows in an owner or
    repository name and never all dots: `../x` must not become `repos/../x`,
    and `a&b/c` must never reach a command line at all. The host is pinned at
    the call site with `--hostname github.com`, not here.
    """
    path = slug.strip().strip("/")
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if path.lower().startswith(prefix):
            path = path[len(prefix) :]
            break
    segments = path.split("/")
    if len(segments) != 2:
        return ""
    for segment in segments:
        if not _REST_PATH_SEGMENT.fullmatch(segment) or not segment.strip("."):
            return ""
    return path


def github_visibility(
    slug: str, repo: Path, command_runner: Any, deadline: float | None
) -> tuple[str, str]:
    """(PUBLIC/PRIVATE/INTERNAL or "", the evidence or the failures).

    REST first. `gh repo view` is a GraphQL call, and an agent fleet exhausts
    the hourly GraphQL quota while the REST core quota is barely touched
    (measured 2026-07-27: GraphQL 0 remaining, REST 4925/5000, same answer in
    0.49s) — so every audit of a `sensitive_data` repo printed UNPROVEN for a
    remote that was verifiably private one REST call away (issue #106, the
    floor's #90). GraphQL stays as the fallback: it is the lane that works
    where `gh api` is unavailable or the REST shape changes.

    Both lanes pin the host. `gh` resolves a bare `OWNER/REPO` against `GH_HOST`
    or the default authenticated host, so on a machine pointed at a GitHub
    Enterprise instance the probe could answer PRIVATE about an entirely
    different repository that happens to share the slug — while the github.com
    remote this finding is about is public.

    When nothing answers, the second element carries what the probes SAID, so
    the UNPROVEN line names quota exhaustion instead of being mute.
    """
    diagnostics: list[str] = []
    lanes: list[list[str]] = []
    rest_path = github_rest_repo_path(slug)
    if rest_path:
        lanes.append(
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                f"repos/{rest_path}",
                "--jq",
                ".visibility",
            ]
        )
    else:
        diagnostics.append(
            f"the REST lane was skipped: {redact_probe_text(slug)!r} is not an "
            "owner/repo pair"
        )
    lanes.append(
        [
            "gh",
            "repo",
            "view",
            f"github.com/{slug}",
            "--json",
            "visibility",
            "--jq",
            ".visibility",
        ]
    )
    for argv in lanes:
        resolved, output, failure = result_before_deadline(
            command_runner, argv, repo, deadline
        )
        visibility = output.strip().upper()
        if resolved and visibility in KNOWN_VISIBILITIES:
            return visibility, f"`{' '.join(argv)}` -> {visibility}"
        if resolved:
            answer = redact_probe_text(visibility[:24]) or "<no output>"
            diagnostics.append(
                f"`{' '.join(argv)}` answered {answer!r}, which is not a visibility"
            )
        else:
            diagnostics.append(probe_failure_note(argv, failure))
    return "", "; ".join(diagnostics)


def privacy_claim_findings(repo: Path) -> list[dict[str, str]]:
    """Sibling docs asserting privacy while the overlay is absent: a split."""
    check = "documented privacy vs the sensitive_data overlay"
    claims: list[str] = []
    for name in PRIVACY_CLAIM_DOCS:
        path = repo / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        match = PRIVACY_CLAIM_PATTERN.search(text)
        if match:
            claims.append(f"{name} says {match.group(0)!r}")
    if not claims:
        return []
    return [
        reality_finding(
            check,
            REALITY_ADVISORY,
            f"{'; '.join(claims)}, but flags.sensitive_data is not declared true — "
            "the docs and the tier declaration disagree",
        )
    ]


def sensitive_data_findings(
    repo: Path,
    tier_data: dict[str, Any],
    *,
    command_runner: Any,
    deadline: float | None,
) -> list[dict[str, str]]:
    """Measure a declared `sensitive_data` overlay against remote visibility."""
    flags = tier_data.get("flags")
    declared = bool(flags.get("sensitive_data")) if isinstance(flags, dict) else False
    if not declared:
        return privacy_claim_findings(repo)
    check = "sensitive_data vs actual remote visibility"
    resolved, remotes = configured_remote_urls(repo, command_runner, deadline)
    if not resolved:
        return [
            reality_finding(
                check,
                REALITY_UNPROVEN,
                "`git remote --verbose` did not answer, so no remote visibility "
                "was measured",
            )
        ]
    if not remotes:
        return [
            reality_finding(
                check, REALITY_OK, "no remote is configured; nothing is published"
            )
        ]
    findings: list[dict[str, str]] = []
    publishing_remote, selection_proven = configured_push_remote(
        repo, command_runner, deadline
    )
    if not selection_proven:
        return [
            reality_finding(
                check,
                REALITY_UNPROVEN,
                "the probe budget expired before git's push-remote configuration "
                "could be read, so which remote publishes this repo is unmeasured; "
                "assuming `origin` here could downgrade a public push endpoint to "
                "an advisory",
            )
        ]
    for name, url, publishes, note in publishing_remote_endpoints(
        remotes, publishing_remote
    ):
        shown = redact_remote_url(url)
        if remote_names_a_network_share(url):
            findings.append(
                reality_finding(
                    check,
                    REALITY_UNPROVEN,
                    f"{name} {shown} is a network share; who can reach it is not "
                    "machine-checkable here",
                )
            )
            continue
        if LOCAL_REMOTE_PATTERN.match(url):
            findings.append(
                reality_finding(
                    check, REALITY_OK, f"{name} {shown} is a local-only remote"
                )
            )
            continue
        slug = github_repo_slug(url)
        if not slug:
            findings.append(
                reality_finding(
                    check,
                    REALITY_UNPROVEN,
                    f"{name} {shown} is not a github.com remote; its visibility is "
                    "not machine-checkable here",
                )
            )
            continue
        visibility, evidence = github_visibility(slug, repo, command_runner, deadline)
        if visibility == "PUBLIC":
            # A public endpoint work is actually PUSHED to is the exposure this
            # check exists to catch. Anything else — the upstream of a private
            # fork, a read-only mirror, a public fetch URL behind a private
            # pushurl — is a normal topology, and hard-failing it with no
            # allowlist and no escape hatch made the only remedy deleting the
            # remote.
            findings.append(
                reality_finding(
                    check,
                    REALITY_MISMATCH if publishes else REALITY_ADVISORY,
                    f"flags.sensitive_data is declared true but remote {name} "
                    f"{shown} resolves to the PUBLIC repository {slug} — evidence: "
                    f"{evidence}" + (f"; {note}" if note else ""),
                )
            )
        elif visibility in KNOWN_VISIBILITIES:
            findings.append(
                reality_finding(check, REALITY_OK, f"{name} {slug} is {visibility}")
            )
        else:
            findings.append(
                reality_finding(
                    check,
                    REALITY_UNPROVEN,
                    f"{name} {slug}: visibility is unmeasured (offline, "
                    f"unauthenticated, rate-limited, or gh is absent) — {evidence}",
                )
            )
    return findings


def human_todo_findings(
    repo: Path, tier: int, tier_data: dict[str, Any]
) -> list[dict[str, str]]:
    """Measure a declared human-action file against the filesystem."""
    check = "human_todo vs the file on disk"
    declared = tier_data.get("human_todo")
    if declared is None:
        if tier >= 2:
            return [
                reality_finding(
                    check,
                    REALITY_ADVISORY,
                    f"T{tier} declares no human_todo "
                    f"({'null' if 'human_todo' in tier_data else 'absent'}), so law "
                    "5 has no file to surface in summaries",
                )
            ]
        return []
    if not isinstance(declared, str) or not declared.strip():
        return [
            reality_finding(
                check,
                REALITY_MISMATCH,
                f"human_todo must be a repo-relative path or null, not {declared!r}",
            )
        ]
    relative = PurePosixPath(declared.replace("\\", "/"))
    # `PurePosixPath("C:/Users/...").is_absolute()` is False - no leading slash -
    # so a drive-absolute declaration slipped past the POSIX test and was then
    # JOINED to the repo path, where the drive silently won. Reject any value
    # that carries a Windows drive or root as well.
    windows_view = PureWindowsPath(declared)
    if (
        relative.is_absolute()
        or windows_view.is_absolute()
        or windows_view.drive
        or windows_view.root
        or ".." in relative.parts
        # A NUL cannot appear in any path on any supported platform, so it is a
        # malformed DECLARATION, not a filesystem that would not answer. Left
        # to the stat guard it surfaced as `ValueError` -> UNPROVEN -> exit 0.
        or "\x00" in declared
    ):
        return [
            reality_finding(
                check,
                REALITY_MISMATCH,
                f"human_todo {declared!r} is not a repo-relative path",
            )
        ]
    # `Path.is_file()` swallows the OS's refusal to answer, so a permissions
    # failure or an unavailable mount read as "absent" and produced a hard
    # MISMATCH claiming a file that may well exist does not. Same guarded stat
    # as the vendored floor probe: an access failure is UNPROVEN, not a defect.
    present, access_error = file_presence(repo / relative)
    if access_error:
        return [reality_finding(check, REALITY_UNPROVEN, access_error)]
    if present:
        return [reality_finding(check, REALITY_OK, f"{declared} exists")]
    return [
        reality_finding(
            check,
            REALITY_MISMATCH,
            f"human_todo declares {declared!r} but no such file exists in {repo}",
        )
    ]


def symlink_target(path: Path) -> str:
    """The link this path IS, or "" for an ordinary file or an unreadable link.

    Deliberately `lstat`-based: every other probe here follows links, which is
    right for reading content and wrong for deciding whether a repo vendors
    bytes of its own.
    """
    try:
        if not path.is_symlink():
            return ""
        return os.readlink(path)
    except (OSError, ValueError):
        return ""


def file_presence(path: Path) -> tuple[bool, str]:
    """(is a regular file, access error) for one path an audit asks about.

    `Path.is_file()` answers False for BOTH "absent" and "the OS refused to
    tell me" — a permissions failure or a transient filesystem error therefore
    read as absence (`[ok] no vendored floor copy`, or a hard `MISMATCH` for a
    declared `human_todo`), while a stricter Python/platform combination could
    instead abort the audit. Neither is one of the three states, so the access
    failure is preserved and reported as UNPROVEN by the caller.
    """
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return False, ""
    except NotADirectoryError:
        # A parent component is a file: the path cannot exist.
        return False, ""
    except (OSError, ValueError) as exc:
        return False, f"{path} could not be inspected ({exc}); existence is unproven"
    return stat.S_ISREG(mode), ""


def floor_version(path: Path) -> str:
    """The FLOOR_VERSION string a dispatcher copy declares, or ""."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    match = re.search(r'^FLOOR_VERSION\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def floor_identity(path: Path) -> tuple[str, str]:
    """(normalized sha256, FLOOR_VERSION) for a floor copy; ("", "") if absent."""
    if not path.is_file():
        return "", ""
    try:
        return normalized_text_sha256(path), floor_version(path)
    except (OSError, UnicodeDecodeError, UnicodeError):
        return "", ""


def describe_floor(label: str, digest: str, version: str) -> str:
    if not digest:
        return f"{label} absent/unreadable"
    return f"{label} {version or '<no FLOOR_VERSION>'} sha {digest[:12]}"


def harness_reference_status(
    harness_root: Path, command_runner: Any, deadline: float | None
) -> tuple[bool, str]:
    """Whether this harness checkout may serve as the canonical byte reference.

    The pin/compare primitives read the WORKING TREE, so a floor branch or a
    dirty tree would make unmerged bytes the reference. Refuse, and say so.
    """
    resolved, branch = output_before_deadline(
        command_runner,
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        harness_root,
        deadline,
    )
    if not resolved:
        return False, f"the branch of harness checkout {harness_root} is unresolvable"
    if branch.strip() != "main":
        return (
            False,
            f"harness checkout {harness_root} is on {branch.strip() or '<unknown>'!r}, "
            "not main, so its working tree is not the canonical reference",
        )
    resolved, dirty = output_before_deadline(
        command_runner,
        ["git", "status", "--porcelain", "--", "templates/hooks"],
        harness_root,
        deadline,
    )
    if not resolved:
        return (
            False,
            f"the working-tree state of harness checkout {harness_root} is "
            "unresolvable",
        )
    if dirty.strip():
        return (
            False,
            f"harness checkout {harness_root} has uncommitted templates/hooks "
            "changes, so its working tree is not the canonical reference",
        )
    # "Clean" is only as trustworthy as the index. `skip-worktree` (S) and
    # `assume-unchanged` (lowercase tag) both make `git status` omit a file's
    # local edits, so a modified template would report clean and then be hashed
    # from the working tree — the vendored copy matching that hidden edit would
    # read `ok` while published HEAD holds different canonical bytes.
    resolved, index_flags = output_before_deadline(
        command_runner,
        ["git", "ls-files", "-v", "--", "templates/hooks"],
        harness_root,
        deadline,
    )
    if not resolved:
        return (
            False,
            f"the index flags of harness checkout {harness_root} are unresolvable",
        )
    hidden = sorted(
        line.split(" ", 1)[1]
        for line in index_flags.splitlines()
        if line[:1] and (line[0].islower() or line[0] == "S") and " " in line
    )
    if hidden:
        return (
            False,
            f"harness checkout {harness_root} marks {', '.join(hidden)} "
            "skip-worktree/assume-unchanged, so `git status` cannot see local "
            "edits there and this working tree is not the canonical reference",
        )
    # Clean on a local `main` is not the same as agreeing with the published
    # one: unpushed commits to templates/hooks, or a main that is behind, would
    # otherwise be called canonical. This first query reads refs only, so it
    # answers the common case cheaply and with a diagnosis.
    resolved, divergence = output_before_deadline(
        command_runner,
        ["git", "rev-list", "--left-right", "--count", "origin/main...HEAD"],
        harness_root,
        deadline,
    )
    counts = divergence.split() if resolved else []
    if len(counts) == 2 and all(count.isdigit() for count in counts):
        behind, ahead = counts
        if behind != "0" or ahead != "0":
            return (
                False,
                f"harness checkout {harness_root} is {ahead} ahead of and "
                f"{behind} behind origin/main, so its working tree is not the "
                "canonical reference",
            )
    # `origin/main` is a LOCAL tracking ref. Unfetched, it can be arbitrarily
    # far behind the published branch, and `rev-list` then reports `0 0` for a
    # working tree that is stale — a vendored copy matching that obsolete
    # template would report `ok` while it has drifted from the published floor.
    # Prove currency against the remote, and when the remote cannot be asked
    # (offline, unreachable) say the reference is unproven rather than assume
    # it: `vendored_floor_findings` renders that as UNPROVEN, never as a pass.
    resolved_head, head = output_before_deadline(
        command_runner, ["git", "rev-parse", "HEAD"], harness_root, deadline
    )
    resolved_published, published = output_before_deadline(
        command_runner,
        ["git", "ls-remote", "origin", "refs/heads/main"],
        harness_root,
        deadline,
    )
    fields = published.split() if resolved_published else []
    published_tip = fields[0] if fields else ""
    if not resolved_head or not published_tip:
        return (
            False,
            f"harness checkout {harness_root} is clean on main, but the published "
            "main tip could not be read (offline, or origin is unreachable), so "
            "this working tree cannot be proven current",
        )
    if head.strip() != published_tip:
        return (
            False,
            f"harness checkout {harness_root} is clean on main at "
            f"{head.strip()[:12]}, but published main is at {published_tip[:12]} — "
            "the local origin/main is stale, so this working tree is not the "
            "canonical reference",
        )
    return (
        True,
        f"harness checkout {harness_root} is clean on main and level with "
        f"origin/main at the published tip {published_tip[:12]}",
    )


def vendored_floor_findings(
    repo: Path,
    harness_root: Path,
    claude_home: Path,
    *,
    command_runner: Any,
    deadline: float | None,
) -> list[dict[str, str]]:
    """Compare a repo's vendored floor bytes with template and deployed copies."""
    vendored: list[tuple[str, Path]] = []
    inaccessible: list[tuple[str, str]] = []
    for directory in VENDORED_FLOOR_DIRS:
        for name in VENDORED_FLOOR_FILES:
            label = f"{directory}/{name}"
            path = repo / directory / name
            # The link is inspected BEFORE anything follows it. `stat()` follows
            # links, so a `hooks/dispatch.py` symlinked to the harness template
            # hashed the TARGET and reported the repo as matching canonical
            # bytes — while the repo vendors none, and the link may resolve
            # elsewhere, or nowhere, on the next machine. A DANGLING link is
            # the same claim with the follow already failed: guarding this on
            # `present` let `[ok] no vendored floor copy` through for it.
            target = symlink_target(path)
            if target:
                present, access_error = False, (
                    f"{path} is a symlink to {target}; the bytes it resolves "
                    "to are this machine's, not this repo's vendored floor"
                )
            else:
                present, access_error = file_presence(path)
            if access_error:
                inaccessible.append((label, access_error))
            elif present:
                vendored.append((label, path))
    findings: list[dict[str, str]] = [
        # A path that cannot be traversed or stat'ed is neither "no vendored
        # copy" nor a compared one; the three-state contract calls it UNPROVEN.
        reality_finding(
            f"vendored {label} vs canonical bytes", REALITY_UNPROVEN, access_error
        )
        for label, access_error in inaccessible
    ]
    if not vendored:
        if findings:
            return findings
        # Say it. A leg that emits nothing at all cannot be told apart from a
        # leg that ran and found no drift.
        return [
            reality_finding(
                "vendored floor bytes vs canonical bytes",
                REALITY_OK,
                "no vendored floor copy under "
                + " or ".join(f"{directory}/" for directory in VENDORED_FLOOR_DIRS)
                + f" in {repo}; nothing to drift from the shared dispatcher",
            )
        ]
    reference_ok, reference_detail = harness_reference_status(
        harness_root, command_runner, deadline
    )
    for label, path in vendored:
        name = path.name
        check = f"vendored {label} vs canonical bytes"
        repo_digest, repo_version = floor_identity(path)
        template = harness_root / "templates" / "hooks" / name
        deployed = claude_home / "hooks" / name
        template_digest, template_version = floor_identity(template)
        deployed_digest, deployed_version = floor_identity(deployed)
        parts = [
            describe_floor("vendored", repo_digest, repo_version),
            describe_floor("canonical template", template_digest, template_version),
            describe_floor("deployed global", deployed_digest, deployed_version),
        ]
        notes: list[str] = []
        status = REALITY_OK
        if not repo_digest:
            status = REALITY_UNPROVEN
            notes.append(f"{path} could not be hashed")
        else:
            if reference_ok and template_digest:
                if template_digest != repo_digest:
                    status = REALITY_MISMATCH
                    notes.append("vendored bytes differ from the canonical template")
            else:
                status = REALITY_UNPROVEN
                notes.append(
                    "not compared with the canonical template: "
                    + (reference_detail if not reference_ok else f"{template} absent")
                )
            # The deployed global copy is a fact about the AUDITING MACHINE,
            # not about this repo. Promoting that difference to MISMATCH made
            # `audit` non-hermetic: an operator who had not run
            # `sync-global --apply` since the last FLOOR_VERSION bump failed a
            # repo gate from their home directory, while the same repo passed
            # on a CI runner with no `~/.claude` at all. `doctor` owns machine
            # state (`shared dispatcher`, `floor version`); `audit` records it.
            if not deployed_digest:
                notes.append(
                    f"no deployed global copy at {deployed} on this machine, so "
                    "the deployed comparison was skipped"
                )
            elif deployed_digest != repo_digest:
                if status == REALITY_OK:
                    status = REALITY_ADVISORY
                notes.append(
                    "vendored bytes differ from the deployed global copy on this "
                    "machine — a machine-state observation, not a repo defect; "
                    "reconcile with `harness.py doctor` and `sync-global --apply`"
                )
        detail = "; ".join(parts)
        if notes:
            detail = f"{detail} — {'; '.join(notes)}"
        findings.append(reality_finding(check, status, detail))
    return findings


def reality_findings(
    repo: Path,
    tier: int,
    tier_data: dict[str, Any],
    *,
    harness_root: Path | None = None,
    claude_home: Path | None = None,
    command_runner: Any = bounded_command_output,
    deadline: float | None = None,
) -> list[dict[str, str]]:
    """Every declaration this repo makes that is cheaply checkable for real."""
    if harness_root is None:
        harness_root = Path(__file__).resolve().parent
    if claude_home is None:
        claude_home = Path.home() / ".claude"
    if deadline is None:
        deadline = monotonic() + REALITY_BUDGET_SECONDS
    findings = sensitive_data_findings(
        repo, tier_data, command_runner=command_runner, deadline=deadline
    )
    findings.extend(
        vendored_floor_findings(
            repo,
            harness_root,
            claude_home,
            command_runner=command_runner,
            deadline=deadline,
        )
    )
    findings.extend(human_todo_findings(repo, tier, tier_data))
    return findings


def audit_repo(
    path: Path,
    *,
    harness_root: Path | None = None,
    claude_home: Path | None = None,
    command_runner: Any = bounded_command_output,
    deadline: float | None = None,
) -> dict[str, Any]:
    repo = git_root(path)
    declarations = tier_declarations(repo)
    tier_data = merge_tier_declarations([data for _, data in declarations])
    issues: list[str] = []
    if not declarations:
        issues.append(
            "missing .agent-harness/tier.json (legacy .claude/tier.json also accepted)"
        )
        tier = 1
    else:
        # Validation is PER FILE: the merged posture is deliberately allowed to
        # combine a tier from one declaration with a name from another, so
        # validating it would invent contradictions the repo never declared.
        # The file is named only when there is more than one to blame.
        for config_path, data in declarations:
            label = (
                f"{config_path.relative_to(repo).as_posix()}: "
                if len(declarations) > 1
                else ""
            )
            issues.extend(f"{label}{issue}" for issue in validate_tier(data))
        tier = tier_data.get("tier") if tier_data.get("tier") in TIER_NAMES else 1
    if not (repo / "AGENTS.md").is_file():
        issues.append("missing root AGENTS.md")
    issues.extend(budget_issues(repo, tier))
    issues.extend(stale_path_issues(repo))
    findings = reality_findings(
        repo,
        tier,
        tier_data,
        harness_root=harness_root,
        claude_home=claude_home,
        command_runner=command_runner,
        deadline=deadline,
    )
    mismatches = [f for f in findings if f["status"] == REALITY_MISMATCH]
    unproven = [f for f in findings if f["status"] == REALITY_UNPROVEN]
    status = run(["git", "status", "--short", "--branch"], repo)
    return {
        "repo": str(repo),
        "tier_file": str(declarations[0][0]) if declarations else None,
        # Every declaration that bound this posture, not just the first found:
        # a consumer that sees one path cannot tell a single-file repo from one
        # whose legacy file supplied the tier.
        "tier_files": [str(config_path) for config_path, _ in declarations],
        "tier": tier,
        "git": status.stdout.strip(),
        "issues": issues,
        "reality": findings,
        # `ok` is the exit code, not a claim that everything was measured:
        # `unproven` is what a consumer needs to tell a clean run from an
        # unmeasured one.
        "unproven": len(unproven),
        "ok": not issues and not mismatches,
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


def tree_digest(root: Path) -> str | None:
    """Digest an ordinary tree, reject unsafe entries, or return None if absent."""
    digest = hashlib.sha256()
    if path_is_alias(root):
        raise HarnessError(f"unsafe skill tree alias: {root}")
    try:
        if not stat.S_ISDIR(root.lstat().st_mode):
            raise HarnessError(f"skill tree root must be an ordinary directory: {root}")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HarnessError(f"cannot inspect skill tree {root}: {exc}") from exc

    entries: list[tuple[bytes, bytes, Path]] = [(b"", b"D", root)]
    pending = [root]
    while pending:
        directory = pending.pop()
        if path_is_alias(directory):
            raise HarnessError(f"unsafe skill tree alias: {directory}")
        try:
            if not stat.S_ISDIR(directory.lstat().st_mode):
                raise HarnessError(f"skill tree changed during inspection: {directory}")
            children = list(directory.iterdir())
        except FileNotFoundError as exc:
            raise HarnessError(
                f"skill tree changed during inspection: {directory}"
            ) from exc
        except OSError as exc:
            raise HarnessError(f"cannot inspect skill tree {directory}: {exc}") from exc
        for path in children:
            if path_is_alias(path):
                raise HarnessError(f"unsafe skill tree alias: {path}")
            try:
                mode = path.lstat().st_mode
            except FileNotFoundError as exc:
                raise HarnessError(
                    f"skill tree changed during inspection: {path}"
                ) from exc
            except OSError as exc:
                raise HarnessError(f"cannot inspect skill tree {path}: {exc}") from exc
            relative = path.relative_to(root).as_posix().encode("utf-8")
            if stat.S_ISDIR(mode):
                entries.append((relative, b"D", path))
                pending.append(path)
            elif stat.S_ISREG(mode):
                entries.append((relative, b"F", path))
            else:
                raise HarnessError(f"unsupported skill tree entry: {path}")

    for relative, kind, entry_path in sorted(entries, key=lambda entry: entry[0]):
        payload = b""
        if path_is_alias(entry_path):
            raise HarnessError(f"unsafe skill tree alias: {entry_path}")
        try:
            entry_mode = entry_path.lstat().st_mode
            expected_kind = (
                stat.S_ISREG(entry_mode) if kind == b"F" else stat.S_ISDIR(entry_mode)
            )
            if not expected_kind:
                raise HarnessError(
                    f"skill tree changed during inspection: {entry_path}"
                )
            # A file or directory whose bytes/children match but whose executable
            # tuple has drifted is NOT the same tree: a script may no longer run,
            # or a directory may no longer be searchable. same_tree would otherwise
            # make `sync-global --apply` skip the copy that restores access.
            # The remaining mode bits are umask/filesystem noise, and Windows
            # reports no meaningful POSIX executable bits.
            executable = bytes(
                int(bool(entry_mode & bit))
                for bit in (stat.S_IXUSR, stat.S_IXGRP, stat.S_IXOTH)
            )
            if kind == b"F":
                payload = entry_path.read_bytes()
        except FileNotFoundError as exc:
            raise HarnessError(
                f"skill tree changed during inspection: {entry_path}"
            ) from exc
        except OSError as exc:
            raise HarnessError(
                f"cannot inspect skill tree {entry_path}: {exc}"
            ) from exc
        digest.update(kind)
        digest.update(executable)
        digest.update(len(relative).to_bytes(8, byteorder="big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, byteorder="big"))
        digest.update(payload)
    return digest.hexdigest()


def same_tree(left: Path, right: Path) -> bool:
    left_digest = tree_digest(left)
    if left_digest is None:
        raise HarnessError(f"source skill tree is missing: {left}")
    right_digest = tree_digest(right)
    return right_digest is not None and left_digest == right_digest


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


class JsonObjectPairs(list[tuple[str, Any]]):
    """Lossless JSON object pairs used for schema-aware duplicate checks."""


class JsonIntegerToken:
    """Preserve an ignored integer lexeme beyond Python's conversion limit."""

    def __init__(self, raw: str) -> None:
        self.raw = raw


def validate_serde_string(value: str, location: str) -> None:
    if any("\ud800" <= character <= "\udfff" for character in value):
        raise HarnessError(
            f"invalid existing hooks.json: {location} contains a lone surrogate"
        )


def validate_tagged_handler_content(value: Any, depth: int = 0) -> None:
    """Match serde's buffered Content validation for internally tagged handlers."""
    if isinstance(value, str):
        validate_serde_string(value, "handler content")
        return
    if isinstance(value, JsonIntegerToken):
        if len(value.raw) <= 21:
            parsed = int(value.raw)
            if -(1 << 63) <= parsed <= U64_MAX:
                return
        if not math.isfinite(float(value.raw)):
            raise HarnessError(
                "invalid existing hooks.json: handler integer is out of range"
            )
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise HarnessError(
            "invalid existing hooks.json: handler number is out of range"
        )
    if isinstance(value, JsonObjectPairs):
        if depth >= SERDE_JSON_HANDLER_CONTENT_MAX_CONTAINERS:
            raise HarnessError(
                "invalid existing hooks.json: handler content nesting is too deep"
            )
        for key, nested in value:
            validate_tagged_handler_content(key, depth + 1)
            validate_tagged_handler_content(nested, depth + 1)
        return
    if isinstance(value, list):
        if depth >= SERDE_JSON_HANDLER_CONTENT_MAX_CONTAINERS:
            raise HarnessError(
                "invalid existing hooks.json: handler content nesting is too deep"
            )
        for nested in value:
            validate_tagged_handler_content(nested, depth + 1)


def json_object_fields(
    value: JsonObjectPairs,
    known_fields: set[str],
    *,
    location: str,
    aliases: dict[str, str] | None = None,
    deny_unknown: bool = False,
) -> dict[str, Any]:
    """Collect schema fields while matching serde's ignored-unknown behavior."""
    fields: dict[str, Any] = {}
    aliases = aliases or {}
    for key, nested in value:
        validate_serde_string(key, f"{location} key")
        canonical = aliases.get(key, key)
        if canonical not in known_fields:
            if deny_unknown:
                raise HarnessError(
                    f"existing hooks.json contains unknown {location} field {key!r}"
                )
            continue
        if canonical in fields:
            raise HarnessError(
                f"invalid existing hooks.json: duplicate {location} field {key!r}"
            )
        fields[canonical] = nested
    return fields


def validate_raw_json_hook_schema(value: Any) -> None:
    """Reject duplicate known fields before JSON objects collapse to dictionaries."""
    if not isinstance(value, JsonObjectPairs):
        return
    root = json_object_fields(
        value,
        {"description", "hooks"},
        location="top-level",
        deny_unknown=True,
    )
    raw_hooks = root.get("hooks", JsonObjectPairs())
    if not isinstance(raw_hooks, JsonObjectPairs):
        return
    events = json_object_fields(
        raw_hooks,
        set(CODEX_HOOK_EVENT_NAMES),
        location="hook event",
    )
    for event_name, raw_groups in events.items():
        if not isinstance(raw_groups, list):
            continue
        for raw_group in raw_groups:
            if not isinstance(raw_group, JsonObjectPairs):
                continue
            group = json_object_fields(
                raw_group,
                {"matcher", "hooks"},
                location=f"hooks.{event_name} group",
            )
            raw_handlers = group.get("hooks", [])
            if not isinstance(raw_handlers, list):
                continue
            for raw_handler in raw_handlers:
                if not isinstance(raw_handler, JsonObjectPairs):
                    continue
                for key, raw_value in raw_handler:
                    if key != "type":
                        validate_tagged_handler_content(raw_value)
                tag = json_object_fields(
                    raw_handler,
                    {"type"},
                    location=f"hooks.{event_name} handler",
                ).get("type")
                if tag != "command":
                    continue
                json_object_fields(
                    raw_handler,
                    {
                        "type",
                        "command",
                        "commandWindows",
                        "timeout",
                        "async",
                        "statusMessage",
                        "additionalContextLimit",
                    },
                    aliases={"command_windows": "commandWindows"},
                    location=f"hooks.{event_name} command handler",
                )


def json_pairs_to_value(value: Any) -> Any:
    """Collapse lossless object pairs after schema-aware duplicate validation."""

    def leaf(current: Any) -> Any:
        if isinstance(current, JsonIntegerToken):
            if current.raw == "-0":
                return current
            if len(current.raw) <= 100:
                return int(current.raw)
        return current

    def container(current: Any) -> dict[str, Any] | list[Any] | None:
        if isinstance(current, JsonObjectPairs):
            return {}
        if isinstance(current, list):
            return []
        return None

    result = container(value)
    if result is None:
        return leaf(value)
    pending: list[tuple[Any, dict[str, Any] | list[Any]]] = [(value, result)]
    while pending:
        raw_container, converted = pending.pop()
        if isinstance(raw_container, JsonObjectPairs):
            if not isinstance(converted, dict):
                raise AssertionError("object conversion target must be a dictionary")
            for key, nested in raw_container:
                nested_container = container(nested)
                converted[key] = (
                    nested_container if nested_container is not None else leaf(nested)
                )
                if nested_container is not None:
                    pending.append((nested, nested_container))
            continue
        if not isinstance(converted, list):
            raise AssertionError("array conversion target must be a list")
        for nested in raw_container:
            nested_container = container(nested)
            converted.append(
                nested_container if nested_container is not None else leaf(nested)
            )
            if nested_container is not None:
                pending.append((nested, nested_container))
    return result


def reject_json_constant(value: str) -> None:
    """Reject Python's non-standard NaN and Infinity JSON extensions."""
    raise HarnessError(f"invalid existing hooks.json: invalid constant {value!r}")


def validate_optional_unsigned(
    handler: dict[str, Any], field: str, maximum: int
) -> None:
    if field not in handler or handler[field] is None:
        return
    value = handler[field]
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= maximum
    ):
        raise HarnessError(
            f"existing command hook handler {field} must be null or an unsigned integer"
        )


def validate_hook_handler(
    handler: Any, event_name: str, *, unsigned_maximum: int
) -> None:
    """Validate one handler against Codex's tagged HookHandlerConfig schema."""
    if not isinstance(handler, dict):
        raise HarnessError(f"existing hooks.{event_name} handlers must be objects")
    handler_type = handler.get("type")
    if not isinstance(handler_type, str):
        raise HarnessError(f"existing hooks.{event_name} handler type must be a string")
    validate_serde_string(handler_type, f"hooks.{event_name} handler type")
    if handler_type not in {"command", "prompt", "agent"}:
        raise HarnessError(
            f"existing hooks.{event_name} handler has unknown type {handler_type!r}"
        )
    if handler_type != "command":
        return

    command = handler.get("command")
    if not isinstance(command, str):
        raise HarnessError(
            f"existing hooks.{event_name} command handler must contain a string command"
        )
    validate_serde_string(command, f"hooks.{event_name} command")
    if "commandWindows" in handler and "command_windows" in handler:
        raise HarnessError(
            "existing command hook handler must not declare both commandWindows "
            "and command_windows"
        )
    for field in ("commandWindows", "command_windows"):
        if (
            field in handler
            and handler[field] is not None
            and not isinstance(handler[field], str)
        ):
            raise HarnessError(
                f"existing command hook handler {field} must be null or a string"
            )
        if isinstance(handler.get(field), str):
            validate_serde_string(handler[field], f"command handler {field}")
    validate_optional_unsigned(handler, "timeout", min(U64_MAX, unsigned_maximum))
    if "async" in handler and not isinstance(handler["async"], bool):
        raise HarnessError("existing command hook handler async must be a boolean")
    if (
        "statusMessage" in handler
        and handler["statusMessage"] is not None
        and not isinstance(handler["statusMessage"], str)
    ):
        raise HarnessError(
            "existing command hook handler statusMessage must be null or a string"
        )
    if isinstance(handler.get("statusMessage"), str):
        validate_serde_string(handler["statusMessage"], "command handler statusMessage")
    validate_optional_unsigned(
        handler, "additionalContextLimit", min(USIZE_MAX, unsigned_maximum)
    )


def validate_hook_events(
    hooks: Any, *, unsigned_maximum: int = U64_MAX
) -> dict[str, Any]:
    """Validate every known event because one malformed sibling drops the layer."""
    if not isinstance(hooks, dict):
        raise HarnessError("existing hooks.json has a non-object hooks field")
    for event_name in CODEX_HOOK_EVENT_NAMES:
        if event_name not in hooks:
            continue
        groups = hooks[event_name]
        if not isinstance(groups, list):
            raise HarnessError(f"existing hooks.{event_name} must be an array")
        for group in groups:
            if not isinstance(group, dict):
                raise HarnessError(
                    f"existing hooks.{event_name} entries must be objects"
                )
            if (
                "matcher" in group
                and group["matcher"] is not None
                and not isinstance(group["matcher"], str)
            ):
                raise HarnessError(
                    f"existing hooks.{event_name} group matcher must be null or a string"
                )
            if isinstance(group.get("matcher"), str):
                validate_serde_string(
                    group["matcher"], f"hooks.{event_name} group matcher"
                )
            handlers = group.get("hooks", [])
            if not isinstance(handlers, list):
                raise HarnessError(
                    f"existing hooks.{event_name} group hooks must be an array"
                )
            for handler in handlers:
                validate_hook_handler(
                    handler, event_name, unsigned_maximum=unsigned_maximum
                )
    return hooks


def validate_config_hook_state(hooks: dict[str, Any]) -> None:
    """Validate HooksToml state fields that typed ConfigToml loading requires."""
    state = hooks.get("state", {})
    if not isinstance(state, dict):
        raise HarnessError("existing inline hooks.state must be a table")
    for name, entry in state.items():
        if not isinstance(entry, dict):
            raise HarnessError(f"existing inline hooks.state.{name} must be a table")
        if "enabled" in entry and not isinstance(entry["enabled"], bool):
            raise HarnessError(
                f"existing inline hooks.state.{name}.enabled must be a boolean"
            )
        if "trusted_hash" in entry and not isinstance(entry["trusted_hash"], str):
            raise HarnessError(
                f"existing inline hooks.state.{name}.trusted_hash must be a string"
            )


# Codex reads `managed_dir` on POSIX hosts and `windows_managed_dir` on
# Windows, and each field carries its own path flavour. Validating a field
# under the other flavour false-greens a value Codex will reject as relative.
_REQUIREMENTS_HOOK_PATH_FIELDS: tuple[tuple[str, type[PurePath], str, str], ...] = (
    ("managed_dir", PurePosixPath, "POSIX", "posix"),
    ("windows_managed_dir", PureWindowsPath, "Windows", "nt"),
)


def requirements_hook_field_is_active_here(field: str) -> bool:
    """Return whether THIS host is the one that consumes this managed field.

    Existence is only asserted for the field the running platform actually
    reads — the other field describes a different machine's filesystem, so
    probing it would produce a portability-dependent verdict rather than a
    check.
    """
    for name, _flavour, _label, os_name in _REQUIREMENTS_HOOK_PATH_FIELDS:
        if name == field:
            return os.name == os_name
    return False


# `\\?\C:\dir` and `\\.\C:\dir` are the extended-length/device spellings of a
# LOCAL drive: they carry a `\\`-prefixed drive but never leave the machine.
# `\\?\UNC\server\share` is the device spelling of a real network share.
_WINDOWS_LOCAL_DEVICE_DRIVE = re.compile(r"(?i)^[\\/]{2}[?.][\\/](?!unc[\\/])")


def requirements_hook_path_is_locally_probeable(value: str) -> bool:
    """Return whether existence can be probed without reaching a network host.

    A UNC value (`\\\\server\\share\\...`, or its `//server/share` spelling)
    turns `is_dir()` into an SMB round trip: off-VPN or with the host down it
    blocks on name resolution for tens of seconds and then answers about
    reachability rather than about the directory. Existence therefore stays
    UNPROVEN for those paths; absoluteness is still asserted. POSIX network
    mounts are indistinguishable from local paths, so this narrowing can only
    recognize the UNC spelling.

    Only a genuine server/share is exempted: the `\\\\?\\C:\\...` and
    `\\\\.\\C:\\...` device spellings address a local drive and are still
    probed, so `doctor` cannot certify a missing directory written that way.

    This answers about WINDOWS path semantics, so callers must apply it only to
    a value in the Windows flavour. On POSIX `//missing/share` is an ordinary
    absolute path, not a share, and reparsing it here would skip the probe and
    let `doctor` certify a directory Codex cannot load.
    """
    drive = PureWindowsPath(value).drive
    if not drive.startswith(("\\\\", "//")):
        return True
    return bool(_WINDOWS_LOCAL_DEVICE_DRIVE.match(drive))


def validate_requirements_hook_paths(hooks: dict[str, Any]) -> None:
    """Validate ManagedHooksRequirementsToml's optional path fields.

    Codex documents both fields as absolute paths and refuses to load managed
    hooks from a relative or missing directory, so a `str` type check alone
    false-greens a managed hook source Codex would reject. Fail closed instead.
    """
    for field, flavour, flavour_label, _os_name in _REQUIREMENTS_HOOK_PATH_FIELDS:
        if field not in hooks:
            continue
        value = hooks[field]
        if not isinstance(value, str):
            raise HarnessError(
                f"existing requirements hooks.{field} must be a path string"
            )
        if not flavour(value).is_absolute():
            raise HarnessError(
                f"existing requirements hooks.{field} must be an absolute path "
                f"in {flavour_label} form: {value!r}"
            )
        if not requirements_hook_field_is_active_here(field):
            continue
        if (
            flavour is PureWindowsPath
            and not requirements_hook_path_is_locally_probeable(value)
        ):
            continue
        try:
            resolvable = Path(value).is_dir()
        except OSError as exc:
            raise HarnessError(
                f"cannot inspect requirements hooks.{field} {value!r}: {exc}"
            ) from exc
        if not resolvable:
            raise HarnessError(
                f"existing requirements hooks.{field} is not an existing directory: "
                f"{value!r}"
            )


def parse_hooks_document(
    current: str, *, source_kind: str = "json"
) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    """Parse and validate a complete Codex JSON or synthetic TOML hook layer."""
    if source_kind not in {"json", "config", "requirements"}:
        raise HarnessError(f"unsupported hook source kind: {source_kind}")
    json_source = source_kind == "json"
    try:
        raw_data = json.loads(
            current,
            object_pairs_hook=JsonObjectPairs if json_source else None,
            parse_constant=reject_json_constant if json_source else None,
            parse_int=JsonIntegerToken if json_source else int,
        )
    except json.JSONDecodeError as exc:
        raise HarnessError(f"invalid existing hooks.json: {exc}") from exc
    except (RecursionError, ValueError) as exc:
        raise HarnessError(f"invalid existing hooks.json: {exc}") from exc
    if json_source:
        try:
            validate_raw_json_hook_schema(raw_data)
            current_data = json_pairs_to_value(raw_data)
        except RecursionError as exc:
            raise HarnessError(f"invalid existing hooks.json: {exc}") from exc
    else:
        current_data = raw_data
    if not isinstance(current_data, dict):
        raise HarnessError("existing hooks.json must contain an object")
    if json_source:
        if (
            "description" in current_data
            and current_data["description"] is not None
            and not isinstance(current_data["description"], str)
        ):
            raise HarnessError(
                "existing hooks.json description must be null or a string"
            )
        if isinstance(current_data.get("description"), str):
            validate_serde_string(current_data["description"], "description")
    hooks = validate_hook_events(
        current_data.get("hooks", {}),
        unsigned_maximum=U64_MAX if json_source else I64_MAX,
    )
    if source_kind == "config":
        validate_config_hook_state(hooks)
    elif source_kind == "requirements":
        validate_requirements_hook_paths(hooks)
    groups = hooks.get("PreToolUse", [])
    return current_data, hooks, groups


def windows_hook_command(handler: dict[str, Any]) -> str:
    """Return Codex's canonical or aliased Windows command value."""
    if "commandWindows" in handler and "command_windows" in handler:
        raise HarnessError(
            "hook handler must not declare both commandWindows and command_windows"
        )
    return handler.get("commandWindows", handler.get("command_windows")) or ""


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
    if handler.get("type") != "command":
        return False
    for command in (handler.get("command", ""), windows_hook_command(handler)):
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
    if handler.get("type") != "command":
        return False
    return any(
        command
        and (
            command_points_to_dispatcher(command)
            or "invoke_deny_floor" in command.lower()
        )
        for command in (
            strip_shell_comments(handler.get("command", "")),
            strip_shell_comments(
                decode_windows_hook_command(windows_hook_command(handler))
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


def managed_codex_floor_groups(current: str, *, source_kind: str = "json") -> list[Any]:
    """Find every direct global Codex floor, including unowned custom copies."""
    _current_data, _hooks, existing_groups = parse_hooks_document(
        current, source_kind=source_kind
    )

    def is_managed(group: Any) -> bool:
        for handler in group.get("hooks", []):
            if is_global_floor_handler(handler):
                return True
        return False

    return [group for group in existing_groups if is_managed(group)]


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
    # Certify only the exact terminal two-token form. Even otherwise familiar
    # PowerShell options can alter stdout, termination, or parser precedence;
    # a conservative hook proof must not infer across those behaviors.
    if (
        len(tokens) != 2
        or not _is_encoded_switch(tokens[0])
        or ":" in tokens[0].lstrip("-/")
    ):
        return ""
    payload = tokens[1]
    # The payload must be a bare base64 string AND appear VERBATIM in the raw
    # argv: if shlex stripped a backslash/quote (`SQ\Bu` -> `SQBu`), the bytes
    # we decode differ from what PowerShell receives.
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", payload) or payload not in rest:
        return ""
    return payload


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
# These shapes are anchored to HOME or a system variable, so they resolve the
# same wherever Codex starts the session.
_CWD_INDEPENDENT_FLOOR_VALUE_SOURCES = (
    # dispatcher: HOME-anchored only (var+separator, `+`-concat, Join-Path)
    rf"['\"]?{_HOME_VAR}/{_FLOOR_DISPATCH}['\"]?",
    rf"{_HOME_VAR}\+'/{_FLOOR_DISPATCH}'",
    rf"join-path {_HOME_VAR} '{_FLOOR_DISPATCH}'",
    # interpreter (py.exe): SYSTEM-variable anchored, never relative
    rf"['\"]?{_SYSTEM_VAR}/py\.exe['\"]?",
    rf"{_SYSTEM_VAR}\+'/py\.exe'",
    rf"join-path {_SYSTEM_VAR} 'py\.exe'",
)
# wrapper, HOME-anchored: `~/work/repo/invoke_deny_floor.sh` resolves to the
# same file from every session cwd, so it belongs with the cwd-independent
# shapes even though it names the project's own wrapper script.
#
# Unlike the dispatcher shapes above, this one is built PER PLATFORM and
# refuses single quotes, because "cwd-independent" is only true if the anchor
# actually expands where the command runs:
#   * `$env:USERPROFILE` is PowerShell-only. A POSIX shell expands `$env` to
#     nothing and runs `:USERPROFILE/...`, so the floor never starts.
#   * single quotes suppress expansion in BOTH sh and PowerShell, so
#     `w='$HOME/…/invoke_deny_floor.sh'` invokes a literal `$HOME` directory.
#   * `~` is expanded by the shell only when it is unquoted; inside double
#     quotes sh keeps it literal.
#   * POSIX variable names are CASE-SENSITIVE, so `$home` is a different (and
#     normally empty) variable. The recognizer lowercases before matching, so
#     the original spelling is re-checked separately for the POSIX side;
#     PowerShell really is case-insensitive and keeps the loose match.
_POSIX_HOME_ENV_VAR = r"\$\{?home\}?"
_WINDOWS_HOME_ENV_VAR = rf"(?:{_POSIX_HOME_ENV_VAR}|\$\{{?env:userprofile\}}?)"
_WRAPPER_TAIL = rf"/(?:[\w.-]+/)*{_FLOOR_WRAPPER}"
# Applied to the ORIGINAL-CASE text, never the lowercased normalization.
_POSIX_HOME_ANCHOR_EXACT = re.compile(r"^(?:~|\$\{?HOME\}?)/")


def posix_home_anchor_case_is_exact(text: str) -> bool:
    """Whether a POSIX HOME anchor is spelled the way sh will expand it."""
    return bool(_POSIX_HOME_ANCHOR_EXACT.match(text.strip("'\"").replace("\\", "/")))


def _home_anchored_wrapper_source(windows: bool) -> str:
    home_var = _WINDOWS_HOME_ENV_VAR if windows else _POSIX_HOME_ENV_VAR
    return rf'(?:~{_WRAPPER_TAIL}|"?{home_var}{_WRAPPER_TAIL}"?)'


_HOME_ANCHORED_WRAPPER_VALUE_PATTERNS = {
    windows: re.compile(_home_anchored_wrapper_source(windows))
    for windows in (False, True)
}
# wrapper, relative: a repo-relative path whose final component is the wrapper
# script (the project's own adapter, trusted via a /hooks review). Being
# relative, it only resolves when Codex's session cwd is the hook source root,
# which is why it is the one shape `reject_relative_wrapper` drops.
_WRAPPER_FLOOR_VALUE_SOURCE = (
    rf"['\"]?(?:{_FLOOR_VAR}/)?(?:[\w.-]+/)*{_FLOOR_WRAPPER}['\"]?"
)

_CWD_INDEPENDENT_FLOOR_VALUE_PATTERNS = tuple(
    re.compile(pattern) for pattern in _CWD_INDEPENDENT_FLOOR_VALUE_SOURCES
)
_FLOOR_VALUE_PATTERNS = _CWD_INDEPENDENT_FLOOR_VALUE_PATTERNS + (
    re.compile(_WRAPPER_FLOOR_VALUE_SOURCE),
)


def value_binds_anchored_floor_path(
    value: str, *, reject_relative_wrapper: bool = False, windows: bool = False
) -> bool:
    """Return whether an assignment value resolves to a genuine floor path.

    Uses a strict whitelist of the exact known-good value shapes rather than
    char-level boundary heuristics. Any value that does not fully match one of
    the accepted dispatcher/interpreter/wrapper forms is rejected, so a floor
    variable's runtime value can never diverge from the pinned floor via a
    rebind, a glued prefix (``x.claude/...`` / ``evil'.claude/...'``), or
    concatenation past the marker.

    ``reject_relative_wrapper`` additionally drops the RELATIVE wrapper shape,
    which is only meaningful when the session cwd is the hook source root. A
    HOME-anchored wrapper path survives, because it names the same file from
    every cwd — but only under an anchor ``windows`` says this command's shell
    actually expands, and never single-quoted.
    """
    normalized = value.lower().replace("\\", "/")
    patterns = (
        _CWD_INDEPENDENT_FLOOR_VALUE_PATTERNS
        if reject_relative_wrapper
        else _FLOOR_VALUE_PATTERNS
    )
    if any(pattern.fullmatch(normalized) for pattern in patterns):
        return True
    if not _HOME_ANCHORED_WRAPPER_VALUE_PATTERNS[windows].fullmatch(normalized):
        return False
    return windows or posix_home_anchor_case_is_exact(value)


def is_inert_floor_setup_segment(
    segment: str,
    allowed_variables: set[str],
    *,
    windows: bool,
    reject_relative_wrapper: bool = False,
) -> bool:
    assignment = inert_floor_assignment(segment, windows=windows)
    if assignment is None:
        return False
    name, value = assignment
    if name in allowed_variables:
        # A floor variable may only be (re)bound to the anchored floor path; any
        # other value — an attacker rebind or concatenation past the marker —
        # is rejected so the executed path cannot diverge from the pinned one.
        return value_binds_anchored_floor_path(
            value,
            reject_relative_wrapper=reject_relative_wrapper,
            windows=windows,
        )
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
    tokens: list[str],
    dispatcher_variables: set[str],
    *,
    allow_py_selector: bool,
) -> bool:
    """Require the dispatcher as Python's script under a strict option prefix."""
    index = 1
    if allow_py_selector and index < len(tokens) and tokens[index] == "-3":
        index += 1
    if index < len(tokens) and tokens[index] == "--":
        index += 1
    return index < len(tokens) and token_is_dispatcher(
        tokens[index], dispatcher_variables
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
        stripped_head = head.strip("'\"")
        allow_py_selector = bool(
            re.fullmatch(r"(?i)py(?:\.exe)?", stripped_head)
            or token_references_variable(head, interpreter_variables)
        )
        return python_script_operand_is_dispatcher(
            tokens,
            dispatcher_variables,
            allow_py_selector=allow_py_selector,
        )
    return False


_WRAPPER_PATH_TOKEN = re.compile(
    rf"^(?:{_PATH_COMPONENT}/)*invoke_deny_floor\.(?:sh|ps1|cmd|bat)$"
)
# The subset of wrapper path tokens that name the same file from every session
# cwd. Intermediate components are restricted to literal words so a smuggled
# `$pwd`/`$cwd` expansion cannot ride in behind the home anchor, and the anchor
# itself must be one this command's shell expands (see the value patterns).
_HOME_ANCHORED_WRAPPER_TOKENS = {
    windows: re.compile(
        rf"^(?:~|{_WINDOWS_HOME_ENV_VAR if windows else _POSIX_HOME_ENV_VAR})"
        rf"{_WRAPPER_TAIL}$"
    )
    for windows in (False, True)
}


def token_is_wrapper(
    token: str,
    wrapper_variables: set[str],
    *,
    reject_relative: bool = False,
    windows: bool = False,
    anchor_is_literal: bool = False,
    double_quoted: bool = False,
) -> bool:
    stripped = token.strip("'\"").lower().replace("\\", "/")
    # The WHOLE token must be a clean path whose final component is the wrapper
    # script, so neither `invoke_deny_floor.sh.evil` nor an assignment word
    # (`x=.../invoke_deny_floor.sh`) can pass.
    if _WRAPPER_PATH_TOKEN.fullmatch(stripped):
        # Under ``reject_relative`` only the HOME-anchored spelling survives:
        # every other recognized literal form resolves against the session cwd.
        # A quoted or escaped anchor is not an anchor — the shell passes
        # `$HOME`/`~` through literally — so it fails closed with the
        # relative shapes.
        if not reject_relative:
            return True
        if anchor_is_literal:
            return False
        if not _HOME_ANCHORED_WRAPPER_TOKENS[windows].fullmatch(stripped):
            return False
        if windows:
            return True
        if not posix_home_anchor_case_is_exact(token):
            return False
        # An UNQUOTED `$HOME` expansion is subject to field splitting, so a
        # home directory containing whitespace hands `sh` several operands and
        # the wrapper never starts. `"$HOME/…"` is one word; tilde expansion
        # results are exempt from field splitting, so bare `~/…` is safe.
        return double_quoted or stripped.startswith("~")
    # A variable-bound wrapper is admitted here on name alone; the anchoring of
    # the value is enforced separately, because `platform_project_floor_command`
    # requires every setup segment to pass `is_inert_floor_setup_segment` under
    # the same ``reject_relative_wrapper`` flag.
    return token_references_variable(token, wrapper_variables)


def shell_script_operand_is_wrapper(
    tokens: list[str],
    wrapper_variables: set[str],
    *,
    reject_relative: bool = False,
    windows: bool = False,
    anchor_is_literal: Any = None,
    double_quoted: Any = None,
) -> bool:
    """Require the wrapper as sh/bash's script under a strict option prefix."""
    index = 1
    if index < len(tokens) and tokens[index] == "--":
        index += 1
    return index < len(tokens) and token_is_wrapper(
        tokens[index],
        wrapper_variables,
        reject_relative=reject_relative,
        windows=windows,
        anchor_is_literal=bool(anchor_is_literal and anchor_is_literal(tokens[index])),
        double_quoted=bool(double_quoted and double_quoted(tokens[index])),
    )


def powershell_file_operand_is_wrapper(
    tokens: list[str],
    wrapper_variables: set[str],
    *,
    reject_relative: bool = False,
    windows: bool = False,
    anchor_is_literal: Any = None,
    double_quoted: Any = None,
) -> bool:
    """Require the wrapper as PowerShell's immediate -File operand."""
    if len(tokens) < 2 or not tokens[1].startswith(("-", "/")):
        return False
    option = tokens[1].lstrip("-/").lower()
    if ":" in option or not option or not "file".startswith(option):
        return False
    if len(tokens) < 3:
        return False
    return token_is_wrapper(
        tokens[2],
        wrapper_variables,
        reject_relative=reject_relative,
        windows=windows,
        anchor_is_literal=bool(anchor_is_literal and anchor_is_literal(tokens[2])),
        double_quoted=bool(double_quoted and double_quoted(tokens[2])),
    )


def segment_invokes_wrapper(
    segment: str,
    wrapper_variables: set[str],
    *,
    reject_relative: bool = False,
    windows: bool = False,
) -> bool:
    """Recognize conservative project-wrapper execution shapes.

    The wrapper must be the EXECUTED script operand — a `-c` command string or a
    trailing argument that merely mentions the wrapper path does not qualify.

    ``reject_relative`` fails closed on a session-cwd-relative wrapper path.
    Codex runs hook commands from the session cwd, so when that directory is not
    the hook source root the relative path resolves somewhere else entirely. A
    HOME-anchored wrapper (`~/work/repo/invoke_deny_floor.sh`) names the same
    file from every cwd and is still certified there — but only under an anchor
    ``windows`` says this shell expands, and never single-quoted.
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

    def anchor_is_literal(token: str) -> bool:
        """Whether the shell passes this token's anchor through UNEXPANDED.

        `shlex` has already removed quotes and escapes, so the token alone
        cannot tell `$HOME/x` from `'$HOME/x'`, `\\$HOME/x` or `"~/x"` — all of
        which the shell hands over literally, leaving a session-cwd-relative
        path. The raw segment is consulted for the character that introduced
        the token:

        * a backslash escapes either anchor kind;
        * `~` expands only when wholly unquoted (sh keeps `"~/x"` literal);
        * a variable expands inside double quotes but not single ones.

        A token that is not present verbatim in the raw segment lost an escape
        or quote INSIDE itself, which is unrecognizable, so it fails closed.
        """
        index = stripped.find(token)
        if index < 0:
            return True
        preceding = stripped[index - 1] if index else ""
        if preceding == "\\":
            return True
        if token.startswith("~"):
            return preceding in {"'", '"'}
        return preceding == "'"

    def double_quoted(token: str) -> bool:
        """Whether the token was written as one double-quoted shell word.

        An unquoted `$HOME` expansion is subject to field splitting, so a home
        directory containing whitespace turns one operand into several and the
        wrapper never starts.
        """
        index = stripped.find(token)
        return index > 0 and stripped[index - 1] == '"'

    head = tokens[0]
    # Direct execution: the wrapper (or a variable bound to it) is the head.
    if token_is_wrapper(
        head,
        wrapper_variables,
        reject_relative=reject_relative,
        windows=windows,
        anchor_is_literal=anchor_is_literal(head),
        double_quoted=double_quoted(head),
    ):
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
        return shell_script_operand_is_wrapper(
            tokens,
            wrapper_variables,
            reject_relative=reject_relative,
            windows=windows,
            anchor_is_literal=anchor_is_literal,
            double_quoted=double_quoted,
        )
    if head_base in {"powershell", "pwsh"}:
        return powershell_file_operand_is_wrapper(
            tokens,
            wrapper_variables,
            reject_relative=reject_relative,
            windows=windows,
            anchor_is_literal=anchor_is_literal,
            double_quoted=double_quoted,
        )
    return False


def command_binds_pin(command: str, expected_pin: str | None) -> bool:
    """Return whether the command declares this audit marker.

    AUDIT-ONLY (issue #18). The `expected=<sha256>` value is a declaration
    inside the Codex hook definition, not a runtime integrity control: nothing
    exports it to the dispatcher, and `dispatch.py` takes no expected-hash
    argument. It proves only that the trusted hook DEFINITION was written
    against these dispatcher bytes, which is why a dispatcher change obliges an
    estate-wide marker refresh plus a fresh-session `/hooks` re-trust. Runtime
    byte integrity is separate evidence and is deliberately not claimed here.
    """
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
    command: str,
    expected_pin: str | None,
    *,
    windows: bool = False,
    reject_relative_wrapper: bool = False,
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
            or segment_invokes_wrapper(
                segment,
                wrapper_variables,
                reject_relative=reject_relative_wrapper,
                windows=windows,
            )
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
        is_inert_floor_setup_segment(
            segment,
            allowed_variables,
            windows=windows,
            reject_relative_wrapper=reject_relative_wrapper,
        )
        for segment in setup_segments
    ):
        return False
    return expected_pin is None or any(
        command_binds_pin(segment, expected_pin) for segment in setup_segments
    )


def repo_codex_floor_candidates(
    current: str, *, source_kind: str = "json"
) -> list[Any]:
    """Return one entry per handler that could create a project floor dispatch."""
    _current_data, _hooks, groups = parse_hooks_document(
        current, source_kind=source_kind
    )
    result = []
    for group in groups:
        for handler in group.get("hooks", []):
            if handler.get("type") != "command":
                continue
            commands = (
                strip_shell_comments(handler.get("command", "")),
                strip_shell_comments(
                    decode_windows_hook_command(windows_hook_command(handler))
                ),
            )
            if any(
                ".claude/hooks/dispatch.py" in command.lower().replace("\\", "/")
                or "invoke_deny_floor" in command.lower()
                for command in commands
            ):
                result.append(group)
    return result


# Any `name=<64 hex>` assignment, i.e. the audit marker an adapter declares.
# Deliberately looser than `command_binds_pin`, so a marker that is present but
# STALE reads as a stale marker instead of as no marker at all.
_AUDIT_MARKER = re.compile(
    r"(?i)(?:^|[\s{(;&|])\$?[a-z_][a-z0-9_]*\s*=\s*[\"']?([0-9a-f]{64})[\"']?"
    r"(?=$|[\s;}})])"
)


# A command names the SHARED dispatcher when the `.claude/hooks/dispatch.py`
# suffix is anchored to a home variable. Both spellings the floor recognizer
# accepts must be recognized here too, or the inventory reports a repo-local
# copy for an adapter the recognizer just certified: the adjacent forms
# (`$HOME/...`, `$env:USERPROFILE+'/...'`) and PowerShell's whitespace-separated
# `Join-Path $env:USERPROFILE '.claude/hooks/dispatch.py'`.
_SHARED_DISPATCHER_REFERENCE = re.compile(
    rf"{_HOME_VAR}[^\s;]*{_FLOOR_DISPATCH}"
    rf"|join-path\s+{_HOME_VAR}\s+['\"]?[^\s;'\"]*{_FLOOR_DISPATCH}"
)


def codex_adapter_command_notes(
    command: str, label: str, expected_pin: str
) -> tuple[list[str], list[str]]:
    """Describe one platform command's deviations from the adapter contract.

    Returns (gaps, inventory). A gap is a deviation nothing else can supply; an
    inventory note records a legitimate but non-default choice — a vendored
    dispatcher or a repo wrapper that carries the flags out of static view.
    """
    if not command.strip():
        # An undeclared platform command has no flags, no marker and no
        # dispatcher by definition. Reporting each of those absences as its own
        # violation sent readers hunting for a malformed command instead of a
        # missing one.
        return [f"{label} declares no command for this platform"], []
    inspected = strip_shell_comments(command)
    normalized = inspected.lower().replace("\\", "/")
    delegates_to_wrapper = "invoke_deny_floor" in normalized
    gaps: list[str] = []
    inventory: list[str] = []
    for flag, value in (("event", "pre"), ("runtime", "codex")):
        if command_has_flag_value(inspected, flag, value):
            continue
        if delegates_to_wrapper:
            inventory.append(
                f"{label} leaves --{flag} {value} to a repo wrapper; follow the "
                "launcher to confirm it"
            )
        else:
            gaps.append(f"{label} never passes --{flag} {value}")
    markers = {match.group(1).lower() for match in _AUDIT_MARKER.finditer(inspected)}
    if not markers:
        gaps.append(f"{label} declares no expected=<sha256> audit marker")
    elif expected_pin not in markers:
        gaps.append(
            f"{label} declares a stale audit marker "
            f"{sorted(markers)[0][:12]}... (installed dispatcher "
            f"{expected_pin[:12]}...)"
        )
    if not _SHARED_DISPATCHER_REFERENCE.search(normalized):
        if ".claude/hooks/dispatch.py" in normalized:
            inventory.append(
                f"{label} names a repo-local dispatcher copy rather than the "
                "shared home-anchored one"
            )
        elif delegates_to_wrapper:
            inventory.append(
                f"{label} reaches a dispatcher only through a repo wrapper"
            )
        else:
            inventory.append(f"{label} names no shared dispatcher")
    return gaps, inventory


def codex_adapter_contract_notes(
    current: str, source_label: str, expected_pin: str, *, source_kind: str = "json"
) -> tuple[list[str], list[str], int]:
    """Inventory every candidate adapter handler in one hook source.

    `doctor` already fails a repo whose canonical adapter is unpinned or stale,
    but it reported only a count, which cannot distinguish "no marker" from
    "stale marker" from "no --runtime codex". Estate audits need the reason.

    Returns (gaps, inventory, inspected_handlers). The count exists so a caller
    can tell "checked and clean" apart from "there was nothing to check".
    """
    _current_data, _hooks, groups = parse_hooks_document(
        current, source_kind=source_kind
    )
    gaps: list[str] = []
    inventory: list[str] = []
    inspected_handlers = 0
    for group_index, group in enumerate(groups):
        for handler_index, handler in enumerate(group.get("hooks", [])):
            if handler.get("type") != "command":
                continue
            commands = {
                "command": handler.get("command", ""),
                "commandWindows": decode_windows_hook_command(
                    windows_hook_command(handler)
                ),
            }
            # Candidacy must agree with `repo_codex_floor_candidates`, which
            # decides on comment-stripped text. A commented-out mention of the
            # dispatcher is not an adapter handler; treating it as one reported
            # contract gaps against a handler every floor check ignores, which
            # turned an unrelated commented command into a false red.
            if not any(
                ".claude/hooks/dispatch.py" in stripped.lower().replace("\\", "/")
                or "invoke_deny_floor" in stripped.lower()
                for stripped in (
                    strip_shell_comments(text) for text in commands.values()
                )
            ):
                continue
            inspected_handlers += 1
            for field, text in commands.items():
                label = (
                    f"{source_label}:pre_tool_use:{group_index}:{handler_index}"
                    f".{field}"
                )
                command_gaps, command_inventory = codex_adapter_command_notes(
                    text, label, expected_pin
                )
                gaps.extend(command_gaps)
                inventory.extend(command_inventory)
    return gaps, inventory, inspected_handlers


def handler_gates_synchronously(handler: dict[str, Any]) -> bool:
    """Reject handler shapes Codex would not run as a blocking PreToolUse gate.

    Codex skips async PreToolUse handlers. Schema validation already rejects
    invalid timeouts; missing, null, and zero normalize to blocking timeouts.
    Unknown compatibility-looking fields are ignored by Codex and by this gate.
    """
    return handler.get("async") is not True


def repo_codex_floor_entries(
    current: str,
    expected_pin: str | None = None,
    *,
    source_kind: str = "json",
    reject_relative_wrapper: bool = False,
) -> list[tuple[int, int, Any]]:
    """Return positions and groups for platform-complete project floor handlers."""
    _current_data, _hooks, groups = parse_hooks_document(
        current, source_kind=source_kind
    )

    result = []
    for group_index, group in enumerate(groups):
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
        windows_command = decode_windows_hook_command(windows_hook_command(handler))
        if platform_project_floor_command(
            command,
            expected_pin,
            reject_relative_wrapper=reject_relative_wrapper,
        ) and platform_project_floor_command(
            windows_command,
            expected_pin,
            windows=True,
            reject_relative_wrapper=reject_relative_wrapper,
        ):
            result.append((group_index, 0, group))
    return result


def repo_codex_floor_groups(
    current: str,
    expected_pin: str | None = None,
    *,
    source_kind: str = "json",
    reject_relative_wrapper: bool = False,
) -> list[Any]:
    """Return one group entry per platform-complete project floor handler."""
    return [
        group
        for _group_index, _handler_index, group in repo_codex_floor_entries(
            current,
            expected_pin,
            source_kind=source_kind,
            reject_relative_wrapper=reject_relative_wrapper,
        )
    ]


def normalized_text_sha256(path: Path) -> str:
    """Hash a file's LF-normalized text; the value adapters declare as a marker.

    Line endings are normalized so the same checkout hashes identically on
    Windows and POSIX. See `command_binds_pin` for what the declared value does
    and does not prove.
    """
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
    try:
        return json.dumps(current_data, indent=2, allow_nan=False) + "\n"
    except (RecursionError, TypeError, ValueError) as exc:
        raise HarnessError(
            "refusing to rewrite hooks.json with an ignored value that cannot be "
            "serialized"
        ) from exc


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
    skill_states = [
        (source, target, same_tree(source, target)) for source, target in skill_actions
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
    remaining_global_floors = managed_codex_floor_groups(hook_text) if hook_text else []
    if remaining_global_floors:
        raise HarnessError(
            "refusing global sync: an unowned or ambiguous Codex floor remains in "
            f"{codex_home / 'hooks.json'}"
        )
    print(
        f"{'=' if current_hooks == hook_text else '->'} {codex_home / 'hooks.json'}"
        " (no global Codex deny floor)"
    )
    for _source, target, equal in skill_states:
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
    for source, target, equal in skill_states:
        if equal:
            continue
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
    try:
        global_floor_count, global_floor_detail = inspectable_global_codex_floor_status(
            codex_home
        )
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
            (
                "no inspectable global Codex floor",
                global_floor_count == 0,
                global_floor_detail,
            ),
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
    # `harness_reference_status` reaches the remote for the published main tip,
    # so this probe answers to `--offline` exactly like the repo reality checks
    # below; otherwise a supposedly offline run still waits out `git ls-remote`.
    # ONE budget for every probe this command makes. The floor-version check
    # and the `--repo` reality checks both call `harness_reference_status`, so
    # a separate deadline each let an unreachable harness origin be waited out
    # twice — and let the two legs report different reference states.
    probe_deadline = monotonic() + REALITY_BUDGET_SECONDS
    reference_ok, reference_detail = harness_reference_status(
        harness_root, offline_aware_command_runner(args), probe_deadline
    )
    template_version = floor_version(
        harness_root / "templates" / "hooks" / "dispatch.py"
    )
    deployed_version = floor_version(claude_home / "hooks" / "dispatch.py")
    # When the working-tree template is not the canonical reference, this
    # comparison cannot certify anything: reporting it as a pass would call
    # unmerged branch bytes the canonical floor. It is UNPROVEN, and UNPROVEN
    # never renders as `[ok]`.
    checks.append(
        (
            "floor version",
            (
                (bool(template_version) and template_version == deployed_version)
                if reference_ok
                else REALITY_UNPROVEN
            ),
            f"canonical template {template_version or '<unreadable>'}; deployed "
            f"global {deployed_version or '<unreadable>'}; reference integrity: "
            f"{reference_detail}"
            + (
                ""
                if reference_ok
                else " — nothing here was compared against canonical bytes"
            ),
        )
    )
    if args.repo:
        mcp_ok = False
        mcp_detail = "project config sources were not resolved"
        try:
            marker_ok, marker_detail = codex_project_root_marker_status(codex_home)
        except (HarnessError, OSError, UnicodeError) as exc:
            marker_ok = False
            marker_detail = str(exc)
        checks.append(("Codex project root markers", marker_ok, marker_detail))
        activation_ok = False
        activation_detail = "project hook sources were not resolved"
        try:
            requested_logical_path = codex_existing_cwd(Path(args.repo))
            requested_path = Path(args.repo).resolve()
            requested_logical_checkout = lexical_git_root(requested_logical_path)
            if requested_logical_checkout is None:
                raise HarnessError(
                    "requested logical path has no .git project-root marker: "
                    f"{requested_logical_path}"
                )
            requested_checkout, authoritative_checkout = root_checkout(requested_path)
            if requested_logical_checkout.resolve() != requested_checkout:
                raise HarnessError(
                    "logical Codex project root disagrees with resolved Git checkout: "
                    f"{requested_logical_checkout} -> "
                    f"{requested_logical_checkout.resolve()}; Git -> "
                    f"{requested_checkout}"
                )
            logical_relative_path = requested_logical_path.relative_to(
                requested_logical_checkout
            )
            resolved_relative_path = requested_path.relative_to(requested_checkout)
            if logical_relative_path != resolved_relative_path:
                raise HarnessError(
                    "logical Codex cwd has a different project-layer ancestry than "
                    "the resolved Git cwd: "
                    f"{logical_relative_path} != {resolved_relative_path}"
                )
            project_config_paths = [
                layer / ".codex" / "config.toml"
                for layer in codex_project_layer_dirs(
                    requested_path, requested_checkout
                )
            ]
            if marker_ok:
                try:
                    mcp_ok, mcp_detail = codex_mcp_topology_status(
                        codex_home, project_config_paths
                    )
                except (HarnessError, OSError, UnicodeError) as exc:
                    mcp_ok = False
                    mcp_detail = str(exc)
            else:
                mcp_detail = (
                    "static project MCP layer walk is unavailable because the Codex "
                    f"project-root marker check failed: {marker_detail}"
                )
            repo_hook_paths, source_ok, source_detail = codex_hook_sources_status(
                requested_path, requested_checkout, authoritative_checkout
            )
            json_hook_documents = [
                (hooks, text)
                for hooks in repo_hook_paths
                if (text := read_optional_text(hooks)) is not None
            ]
            inline_hook_documents = [
                (hooks, document)
                for hooks in repo_hook_paths
                if (document := inline_hooks_document(hooks.with_name("config.toml")))
            ]

            # Codex runs a hook command from the SESSION cwd, not from the
            # directory that owns the hook source. Wherever those differ — a
            # `--repo <subdir>` audit, or a linked worktree sourcing hooks from
            # the root checkout — a repo-relative wrapper path resolves
            # somewhere other than the hook source root, so it cannot be
            # certified.
            def wrapper_is_cwd_relative_here(hooks: Path) -> bool:
                return hooks.parent.parent.resolve() != requested_path

            repo_hook_sources = [
                (hooks, text, "json") for hooks, text in json_hook_documents
            ] + [(hooks, text, "config") for hooks, text in inline_hook_documents]
            project_floor_count = sum(
                len(
                    repo_codex_floor_groups(
                        text,
                        source_kind=source_kind,
                        reject_relative_wrapper=wrapper_is_cwd_relative_here(hooks),
                    )
                )
                for hooks, text, source_kind in repo_hook_sources
            )
            candidate_floor_count = sum(
                len(repo_codex_floor_candidates(text, source_kind=source_kind))
                for _hooks, text, source_kind in repo_hook_sources
            )
            # Binding a repo-relative wrapper is a property of the adapter TEXT,
            # not of this audit's cwd. Detect it for every source so the
            # dependency is reported even from the one cwd where it happens to
            # resolve; only the cwd that actually breaks it fails the floor.
            cwd_relative_wrapper_sources = [
                (hooks, source_kind, lenient - strict)
                for hooks, text, source_kind in repo_hook_sources
                if (
                    lenient := len(
                        repo_codex_floor_groups(text, source_kind=source_kind)
                    )
                )
                != (
                    strict := len(
                        repo_codex_floor_groups(
                            text,
                            source_kind=source_kind,
                            reject_relative_wrapper=True,
                        )
                    )
                )
            ]
            unresolvable_wrapper_sources = [
                f"{hooks} ({source_kind}): "
                f"{count} handler(s) bind a session-cwd-relative wrapper path"
                for hooks, source_kind, count in cwd_relative_wrapper_sources
                if wrapper_is_cwd_relative_here(hooks)
            ]
            cwd_dependent_wrapper_notes = [
                f"{hooks} ({source_kind}): {count} handler(s) bind a "
                "session-cwd-relative wrapper path, so this adapter certifies "
                f"only for sessions started in {hooks.parent.parent}"
                for hooks, source_kind, count in cwd_relative_wrapper_sources
                if not wrapper_is_cwd_relative_here(hooks)
            ]
            expected_pin = normalized_text_sha256(
                harness_root / "templates" / "hooks" / "dispatch.py"
            )
            current_floor_count = sum(
                len(
                    repo_codex_floor_groups(
                        text,
                        expected_pin,
                        source_kind=source_kind,
                        reject_relative_wrapper=wrapper_is_cwd_relative_here(hooks),
                    )
                )
                for hooks, text, source_kind in repo_hook_sources
            )
            adapter_gaps: list[str] = []
            adapter_inventory: list[str] = []
            adapter_handler_count = 0
            for hooks, text, source_kind in repo_hook_sources:
                (
                    source_gaps,
                    source_inventory,
                    source_handlers,
                ) = codex_adapter_contract_notes(
                    text, str(hooks), expected_pin, source_kind=source_kind
                )
                adapter_gaps.extend(source_gaps)
                adapter_inventory.extend(source_inventory)
                adapter_handler_count += source_handlers
            adapter_inventory.extend(cwd_dependent_wrapper_notes)
            adapter_ok = not adapter_gaps
            # With no adapter handler anywhere there is nothing to certify, and
            # claiming a current marker would assert a fact about a file that
            # declares none. Say which of the two clean states this is.
            adapter_detail = "; ".join(
                [f"contract gap: {gap}" for gap in adapter_gaps]
                + [f"note: {note}" for note in adapter_inventory]
            ) or (
                f"{adapter_handler_count} adapter handler(s) across "
                f"{len(repo_hook_sources)} inspected hook source(s) declare a "
                "current audit marker and pass --event pre --runtime codex"
                if adapter_handler_count
                else f"{len(repo_hook_sources)} inspected hook source(s) declare no "
                "handler that reaches the shared floor: nothing to check here, and "
                "the project floor check owns that verdict"
            )
            canonical_hooks = authoritative_checkout / ".codex" / "hooks.json"
            canonical_root_floor_entries = [
                entry
                for hooks, hooks_text in json_hook_documents
                if hooks == canonical_hooks
                for entry in repo_codex_floor_entries(
                    hooks_text,
                    expected_pin,
                    reject_relative_wrapper=wrapper_is_cwd_relative_here(hooks),
                )
            ]
            canonical_root_floor_count = len(canonical_root_floor_entries)
            # Hook IDs use Codex's lexical source path. Preserve an explicit
            # symlink/junction -C path for normal checkouts; linked worktrees
            # source hooks from the authoritative root checkout instead.
            canonical_state_hooks = (
                requested_logical_checkout / ".codex" / "hooks.json"
                if requested_checkout == authoritative_checkout
                else canonical_hooks
            )
            canonical_hook_keys = {
                f"{canonical_state_hooks}:pre_tool_use:{group_index}:{handler_index}"
                for group_index, handler_index, _group in canonical_root_floor_entries
            }
            try:
                activation_ok, activation_detail = codex_project_hook_activation_status(
                    codex_home, project_config_paths, canonical_hook_keys
                )
            except (HarnessError, OSError, UnicodeError) as exc:
                activation_ok = False
                activation_detail = str(exc)
            wrapper_detail = (
                "session cwd "
                f"{requested_path} is not the hook source root, so "
                f"{'; '.join(unresolvable_wrapper_sources)}"
                " that Codex would resolve under the session cwd instead; "
                if unresolvable_wrapper_sources
                else ""
            )
            project_detail = (
                f"{project_floor_count} project floor handler(s); "
                f"{candidate_floor_count} candidate handler(s); "
                f"{current_floor_count} current audit-marker handler(s); "
                f"{canonical_root_floor_count} canonical root hooks.json handler(s); "
                f"{wrapper_detail}"
                f"{source_detail}; the expected=<sha256> value is an audit-only "
                "marker, never verified at runtime; trust is checked manually "
                "in /hooks"
            )
        except (HarnessError, OSError, UnicodeError) as exc:
            project_floor_count = -1
            candidate_floor_count = -1
            current_floor_count = -1
            canonical_root_floor_count = -1
            source_ok = False
            source_detail = str(exc)
            project_detail = str(exc)
            adapter_ok = False
            adapter_detail = str(exc)
        checks.append(("Codex hook source", source_ok, source_detail))
        checks.append(("Codex adapter contract", adapter_ok, adapter_detail))
        checks.append(("Codex MCP topology", mcp_ok, mcp_detail))
        checks.append(
            ("Codex project hook activation", activation_ok, activation_detail)
        )
        checks.append(
            (
                "project Codex floor",
                marker_ok
                and source_ok
                and activation_ok
                and candidate_floor_count == 1
                and project_floor_count == 1
                and current_floor_count == 1
                and canonical_root_floor_count == 1,
                project_detail,
            )
        )
        try:
            reality_repo = git_root(Path(args.repo))
            _reality_configs, reality_tier_data = load_tier(reality_repo)
            reality_tier = (
                reality_tier_data.get("tier")
                if reality_tier_data.get("tier") in TIER_NAMES
                else 1
            )
            findings = reality_findings(
                reality_repo,
                reality_tier,
                reality_tier_data,
                harness_root=harness_root,
                claude_home=claude_home,
                # `doctor --repo` runs the same reality checks as `audit`, so
                # it needs the same escape hatch: without it an operator off
                # network waits out the whole probe budget on `gh` and remote
                # ref lookups before every one of them degrades to UNPROVEN.
                command_runner=offline_aware_command_runner(args),
                deadline=probe_deadline,
            )
            statuses = {finding["status"] for finding in findings}
            reality_ok: bool | str = True
            if REALITY_MISMATCH in statuses:
                reality_ok = False
            elif REALITY_UNPROVEN in statuses:
                reality_ok = REALITY_UNPROVEN
            reality_detail = (
                "; ".join(
                    f"[{finding['status']}] {finding['check']}: {finding['detail']}"
                    for finding in findings
                )
                or "this repo declares nothing that is checkable against reality"
            )
        except (HarnessError, OSError, UnicodeError) as exc:
            reality_ok = False
            reality_detail = str(exc)
        checks.append(("declared vs real", reality_ok, reality_detail))
    # Three states, one renderer: a check that could not run prints as
    # UNPROVEN, never as `[ok]`. It is not a failure either — an unprovable
    # canonical reference is a property of where the operator is standing, not
    # a defect in the floor being audited.
    for label, ok, detail in checks:
        if ok == REALITY_UNPROVEN:
            state = REALITY_UNPROVEN
        else:
            state = "ok" if ok else "FAIL"
        print(f"[{state}] {label}: {detail}")
    return 0 if all(ok == REALITY_UNPROVEN or ok for _, ok, _ in checks) else 1


def audit_command(
    args: argparse.Namespace,
    *,
    harness_root: Path | None = None,
    claude_home: Path | None = None,
    command_runner: Any | None = None,
) -> int:
    """Render one audit. The seams exist so a test never runs the real world.

    `audit_repo` already takes the harness checkout, the deployed `~/.claude`
    copy and the resolver as arguments; without the same seams here, any test
    that exercises the RENDERING falls back to the real harness checkout, the
    real home directory and a real `git`/`gh` — which is exactly the
    auditing-machine dependence these checks exist to remove.
    """
    if command_runner is None:
        command_runner = offline_aware_command_runner(args)
    result = audit_repo(
        Path(args.path),
        harness_root=harness_root,
        claude_home=claude_home,
        command_runner=command_runner,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"repo: {result['repo']}")
        sources = ", ".join(result["tier_files"]) or "missing"
        if len(result["tier_files"]) > 1:
            sources += "; strictest binds"
        print(f"tier: T{result['tier']} ({sources})")
        print(result["git"])
        for issue in result["issues"]:
            print(f"[FAIL] {issue}")
        for finding in result["reality"]:
            print(f"[{finding['status']}] {finding['check']}: {finding['detail']}")
        if result["ok"]:
            # An unproven check is neither a pass nor a failure, so the summary
            # line has to say how much of this run was actually measured.
            unproven = result["unproven"]
            print(
                "[ok] harness audit"
                + (
                    f" — {unproven} check(s) UNPROVEN and therefore not passed"
                    if unproven
                    else ""
                )
            )
    return 0 if result["ok"] else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit", help="validate a repository harness")
    audit.add_argument("path", nargs="?", default=".")
    audit.add_argument("--json", action="store_true")
    audit.add_argument(
        "--offline",
        action="store_true",
        help="run no network resolver; unmeasured checks report UNPROVEN",
    )
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
    check.add_argument(
        "--offline",
        action="store_true",
        help="run no network resolver in the --repo reality checks; "
        "unmeasured checks report UNPROVEN",
    )
    check.set_defaults(func=doctor)

    worktrees = sub.add_parser(
        "worktrees", help="audit or plainly remove proven-safe linked worktrees"
    )
    worktrees.add_argument(
        "--repo", default=".", help="repository or linked worktree to inspect"
    )
    worktrees.add_argument(
        "--refresh",
        action="store_true",
        help="fetch every configured remote before evaluating reachability",
    )
    worktrees.add_argument(
        "--apply",
        action="store_true",
        help="remove revalidated safe candidates; requires --refresh and --claimant",
    )
    worktrees.add_argument(
        "--claimant",
        help="self-declared identity that must own each active cooperative lease",
    )
    worktrees.add_argument("--json", action="store_true")
    worktrees.set_defaults(func=worktrees_command)

    lease = sub.add_parser(
        "worktree-lease", help="manage a cooperative linked-worktree ownership lease"
    )
    lease.add_argument(
        "--repo", default=".", help="the exact linked worktree that owns the lease"
    )
    lease.add_argument(
        "--action", choices=("status", "acquire", "renew", "release"), required=True
    )
    lease.add_argument("--claimant", help="stable identity of the cooperating owner")
    lease.add_argument(
        "--ttl-seconds",
        type=float,
        default=WORKTREE_OWNERSHIP_DEFAULT_SECONDS,
    )
    lease.add_argument(
        "--replace-stale",
        action="store_true",
        help="allow acquire to replace only a structurally valid expired lease",
    )
    lease.add_argument("--json", action="store_true")
    lease.set_defaults(func=worktree_lease_command)
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
