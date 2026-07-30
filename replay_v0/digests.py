"""Exact-byte and canonical semantic digests for replay v0."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
from typing import Any


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 hex digest of exact bytes."""

    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Hash a file's exact bytes without newline or encoding normalization."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def executable_bits(path: str | Path) -> str:
    """Return the owner/group/other execute tuple that affects traversal or launch."""

    mode = Path(path).stat().st_mode
    return "".join(
        "1" if mode & bit else "0" for bit in (stat.S_IXUSR, stat.S_IXGRP, stat.S_IXOTH)
    )


def sha256_tree(path: str | Path) -> str:
    """Hash tree names, regular-file bytes, and executable-bit tuples."""

    root = Path(path)
    if not root.is_dir() or root.is_symlink():
        raise OSError("tree digest root must be a readable directory")

    entries: list[dict[str, str]] = [
        {
            "executable_bits": executable_bits(root),
            "kind": "directory",
            "path": "",
        }
    ]
    for entry in root.rglob("*"):
        relative_path = entry.relative_to(root).as_posix()
        if entry.is_symlink():
            if not entry.is_file():
                raise OSError(
                    "tree digest does not support directory or broken symlinks"
                )
            entries.append(
                {
                    "executable_bits": executable_bits(entry),
                    "kind": "file",
                    "path": relative_path,
                    "sha256": sha256_file(entry),
                }
            )
        elif entry.is_dir():
            entries.append(
                {
                    "executable_bits": executable_bits(entry),
                    "kind": "directory",
                    "path": relative_path,
                }
            )
        elif entry.is_file():
            entries.append(
                {
                    "executable_bits": executable_bits(entry),
                    "kind": "file",
                    "path": relative_path,
                    "sha256": sha256_file(entry),
                }
            )
        else:
            raise OSError("tree digest supports only directories and regular files")
    entries.sort(key=lambda item: item["path"])
    return sha256_bytes(canonical_json_bytes(entries))


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JSON value deterministically for semantic identity derivation."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
