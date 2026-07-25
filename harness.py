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
import stat
import subprocess
import sys
import tomllib
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

DEFAULT_CODEX_PROJECT_ROOT_MARKERS = [".git"]

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
    if required_hook_feature is not None:
        location, enabled = required_hook_feature
        if not enabled:
            blockers.append(f"{location}=false")

    stored_feature_paths = [
        system_config,
        codex_home / "config.toml",
        *profile_paths,
        codex_managed_config_path(codex_home),
    ]
    for config_path in dict.fromkeys(stored_feature_paths):
        blockers.extend(
            location
            for location, enabled in hook_feature_declarations(
                config_path, reject_legacy_profile=True
            )
            if not enabled
        )
    for config_path in dict.fromkeys(project_config_paths):
        blockers.extend(
            location
            for location, enabled in hook_feature_declarations(
                config_path, project_local=True
            )
            if not enabled
        )

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

    entries: list[tuple[bytes, bytes, Path | None]] = []
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
                entries.append((relative, b"D", None))
                pending.append(path)
            elif stat.S_ISREG(mode):
                entries.append((relative, b"F", path))
            else:
                raise HarnessError(f"unsupported skill tree entry: {path}")

    for relative, kind, file_path in sorted(entries, key=lambda entry: entry[0]):
        payload = b""
        executable = b"-"
        if file_path is not None:
            if path_is_alias(file_path):
                raise HarnessError(f"unsafe skill tree alias: {file_path}")
            try:
                entry_mode = file_path.lstat().st_mode
                if not stat.S_ISREG(entry_mode):
                    raise HarnessError(
                        f"skill tree changed during inspection: {file_path}"
                    )
                # A helper script whose bytes match but whose executable bit has
                # drifted (source 0755, installed 0644) is NOT the same tree: the
                # installed skill cannot run it, and same_tree would otherwise make
                # `sync-global --apply` skip the copy that would restore the mode.
                # Only the executable bit is digested — the rest of the mode is
                # umask/filesystem noise and Windows reports no meaningful bits.
                if entry_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                    executable = b"X"
                payload = file_path.read_bytes()
            except FileNotFoundError as exc:
                raise HarnessError(
                    f"skill tree changed during inspection: {file_path}"
                ) from exc
            except OSError as exc:
                raise HarnessError(
                    f"cannot inspect skill tree {file_path}: {exc}"
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


def requirements_hook_path_resolves_here(value: str) -> bool:
    """Return whether the running platform can resolve this managed hook path.

    The two fields carry different path flavours, and which one Codex consumes
    depends on the host. Absoluteness is therefore accepted under either
    flavour, but existence is only asserted for a value that is unambiguously
    absolute under THIS platform's rules — a Windows path audited on Linux (or
    a POSIX path audited on Windows) is a different machine's fact, so probing
    it would produce a portability-dependent verdict rather than a check.
    """
    if os.name == "nt":
        return PureWindowsPath(value).is_absolute()
    return PurePosixPath(value).is_absolute()


def validate_requirements_hook_paths(hooks: dict[str, Any]) -> None:
    """Validate ManagedHooksRequirementsToml's optional path fields.

    Codex documents both fields as absolute paths and refuses to load managed
    hooks from a relative or missing directory, so a `str` type check alone
    false-greens a managed hook source Codex would reject. Fail closed instead.
    """
    for field in ("managed_dir", "windows_managed_dir"):
        if field not in hooks:
            continue
        value = hooks[field]
        if not isinstance(value, str):
            raise HarnessError(
                f"existing requirements hooks.{field} must be a path string"
            )
        if not (
            PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()
        ):
            raise HarnessError(
                f"existing requirements hooks.{field} must be an absolute path: "
                f"{value!r}"
            )
        if not requirements_hook_path_resolves_here(value):
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
    """Require the wrapper as sh/bash's script under a strict option prefix."""
    index = 1
    if index < len(tokens) and tokens[index] == "--":
        index += 1
    return index < len(tokens) and token_is_wrapper(tokens[index], wrapper_variables)


def powershell_file_operand_is_wrapper(
    tokens: list[str], wrapper_variables: set[str]
) -> bool:
    """Require the wrapper as PowerShell's immediate -File operand."""
    if len(tokens) < 2 or not tokens[1].startswith(("-", "/")):
        return False
    option = tokens[1].lstrip("-/").lower()
    if ":" in option or not option or not "file".startswith(option):
        return False
    if len(tokens) < 3:
        return False
    return token_is_wrapper(tokens[2], wrapper_variables)


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
    if head_base in {"powershell", "pwsh"}:
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
            command, expected_pin
        ) and platform_project_floor_command(
            windows_command, expected_pin, windows=True
        ):
            result.append((group_index, 0, group))
    return result


def repo_codex_floor_groups(
    current: str,
    expected_pin: str | None = None,
    *,
    source_kind: str = "json",
) -> list[Any]:
    """Return one group entry per platform-complete project floor handler."""
    return [
        group
        for _group_index, _handler_index, group in repo_codex_floor_entries(
            current, expected_pin, source_kind=source_kind
        )
    ]


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
    if args.repo:
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
            repo_hook_paths, source_ok, source_detail = codex_hook_sources_status(
                requested_path, requested_checkout, authoritative_checkout
            )
            json_hook_documents = [
                (hooks, text)
                for hooks in repo_hook_paths
                if (text := read_optional_text(hooks)) is not None
            ]
            json_hook_texts = [text for _hooks, text in json_hook_documents]
            inline_hook_texts = [
                document
                for hooks in repo_hook_paths
                if (document := inline_hooks_document(hooks.with_name("config.toml")))
            ]
            repo_hook_sources = [(text, "json") for text in json_hook_texts] + [
                (text, "config") for text in inline_hook_texts
            ]
            project_floor_count = sum(
                len(repo_codex_floor_groups(text, source_kind=source_kind))
                for text, source_kind in repo_hook_sources
            )
            candidate_floor_count = sum(
                len(repo_codex_floor_candidates(text, source_kind=source_kind))
                for text, source_kind in repo_hook_sources
            )
            expected_pin = normalized_text_sha256(
                harness_root / "templates" / "hooks" / "dispatch.py"
            )
            current_floor_count = sum(
                len(
                    repo_codex_floor_groups(text, expected_pin, source_kind=source_kind)
                )
                for text, source_kind in repo_hook_sources
            )
            canonical_hooks = authoritative_checkout / ".codex" / "hooks.json"
            canonical_root_floor_entries = [
                entry
                for hooks, hooks_text in json_hook_documents
                if hooks == canonical_hooks
                for entry in repo_codex_floor_entries(hooks_text, expected_pin)
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
