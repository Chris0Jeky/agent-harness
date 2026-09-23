"""Bounded JSON and value primitives for offline, non-authoritative UX receipts."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any

MAX_JSON_BYTES = 256 * 1024
MAX_DEPTH = 32
MAX_NODES = 20000


class ContractError(ValueError):
    """Content-free diagnostic: never include source text or filesystem paths."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def object_keys(value: Any, keys: set[str]) -> None:
    require(type(value) is dict and set(value) == keys, "object_fields")


def text(value: Any, maximum: int = 2000) -> None:
    require(type(value) is str and bool(value.strip()) and len(value) <= maximum, "text")


def integer(value: Any, minimum: int, maximum: int) -> None:
    require(type(value) is int and minimum <= value <= maximum, "integer")


def array(value: Any, minimum: int, maximum: int) -> None:
    require(type(value) is list and minimum <= len(value) <= maximum, "array")


def strings(value: Any, minimum: int = 1, maximum: int = 30) -> None:
    array(value, minimum, maximum)
    for item in value:
        text(item)
    require(len(set(value)) == len(value), "duplicate_value")


def validate_tree(value: Any) -> None:
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        require(depth <= MAX_DEPTH and nodes <= MAX_NODES, "json_complexity")
        if type(item) is dict:
            require(all(type(key) is str for key in item), "json_key")
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            try:
                require(len(item.encode("utf-8")) <= MAX_JSON_BYTES, "json_string_size")
            except UnicodeError as exc:
                raise ContractError("json_unicode") from exc
        elif type(item) is float:
            require(math.isfinite(item), "json_nonfinite")
        elif type(item) is int:
            require(abs(item) <= 2**63 - 1, "json_integer_size")
        else:
            require(item is None or type(item) is bool, "json_type")


def canonical(value: Any) -> bytes:
    validate_tree(value)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    require(len(raw) <= MAX_JSON_BYTES, "json_size")
    return raw


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def regular(info: os.stat_result) -> bool:
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not (getattr(info, "st_file_attributes", 0) & 0x400))


def read_regular(path: Path, limit: int) -> bytes:
    """Reject static aliases/special files; not a concurrent-writer sandbox."""
    try:
        before = path.lstat()
        require(regular(before) and before.st_size <= limit, "file_type_or_size")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            require(regular(opened) and os.path.samestat(before, opened), "file_changed")
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        require(len(raw) <= limit, "file_size")
        require((opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "file_changed")
        return raw
    except OSError as exc:
        raise ContractError("file_unavailable") from exc


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        require(key not in result, "json_duplicate_key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ContractError("json_nonfinite")


def load_json(path: Path) -> Any:
    raw = read_regular(path, MAX_JSON_BYTES)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except ContractError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError("json_invalid") from exc
    canonical(value)
    return value
