#!/usr/bin/env python3
"""Build and verify the portable learning-contract bundle (SPECS section 15)."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = "schemas/learning/BUNDLE.json"
BUNDLE_SCHEMA = "learning-contract-bundle/v1"
_SPEC = importlib.util.spec_from_file_location(
    "learning_contracts", ROOT / "scripts" / "learning_contracts.py"
)
contracts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(contracts)


class BundleError(ValueError):
    """An unusable manifest or command, rather than contract drift (exit 2)."""


def _bundle_files(root):
    return sorted(
        ["scripts/learning_contracts.py"]
        + [
            path.relative_to(root).as_posix()
            for path in (root / "schemas" / "learning").glob("*.json")
            if path.is_file() and path.suffix == ".json" and path.name != "BUNDLE.json"
        ]
    )


BUNDLE_FILES = tuple(_bundle_files(ROOT))


def file_digest(path):
    """SHA-256 of bytes with CRLF normalised to LF, without decoding text."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _digest(files):
    payload = "".join(f"{item['path']}\t{item['sha256']}\n" for item in files)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relpath(value):
    if (
        not value
        or "\\" in value
        or ":" in value
        or PurePosixPath(value).is_absolute()
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise BundleError(f"not a repository-relative POSIX path: {value!r}")
    return value


def _read_manifest(root):
    document = contracts.loads((root / MANIFEST_PATH).read_text("utf-8"))
    if not isinstance(document, dict) or set(document) != {
        "schema",
        "version",
        "files",
        "record_schemas",
        "digest",
    }:
        raise BundleError("invalid bundle manifest fields")
    if document["schema"] != BUNDLE_SCHEMA:
        raise BundleError("unsupported bundle manifest schema")
    if type(document["version"]) is not int or document["version"] < 1:
        raise BundleError("bundle version must be a positive integer")
    files = document["files"]
    if not isinstance(files, list) or not files:
        raise BundleError("bundle files must be a nonempty list")
    paths = []
    for item in files:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not isinstance(item["path"], str)
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise BundleError("invalid bundle file entry")
        path = _relpath(item["path"])
        parts = PurePosixPath(path).parts
        if path != "scripts/learning_contracts.py" and not (
            len(parts) == 3
            and parts[:2] == ("schemas", "learning")
            and parts[2].endswith(".json")
            and path != MANIFEST_PATH
        ):
            raise BundleError(f"path outside the contract bundle: {path}")
        paths.append(path)
    if paths != sorted(set(paths)) or "scripts/learning_contracts.py" not in paths:
        raise BundleError(
            "bundle paths must be sorted, unique and include the validator"
        )
    names = document["record_schemas"]
    if (
        not isinstance(names, list)
        or not names
        or not all(isinstance(name, str) for name in names)
        or names != sorted(set(names))
    ):
        raise BundleError("record_schemas must be a sorted unique list of strings")
    if document["digest"] != _digest(files):
        raise BundleError("manifest digest does not match its file entries")
    return document


def manifest(root):
    """Describe current bundle bytes, preserving the recorded version if present."""
    root = Path(root)
    version = _read_manifest(root)["version"] if (root / MANIFEST_PATH).exists() else 1
    files = [
        {"path": path, "sha256": file_digest(root / path)}
        for path in _bundle_files(root)
    ]
    return {
        "schema": BUNDLE_SCHEMA,
        "version": version,
        "files": files,
        "record_schemas": sorted(contracts.RECORD_SCHEMAS),
        "digest": _digest(files),
    }


def _drift(expected, actual):
    old = {item["path"]: item["sha256"] for item in expected["files"]}
    new = {item["path"]: item["sha256"] for item in actual["files"]}
    return sorted(
        path for path in old.keys() | new.keys() if old.get(path) != new.get(path)
    )


def _verify(document, vendored, mappings):
    vendored = Path(vendored).resolve()
    if not vendored.is_dir():
        raise BundleError(f"vendored directory does not exist: {vendored}")
    paths = {item["path"] for item in document["files"]}
    renamed = {}
    for mapping in mappings:
        source, separator, target = mapping.partition("=")
        if not separator or source not in paths or source in renamed:
            raise BundleError(f"invalid or duplicate mapping: {mapping!r}")
        renamed[source] = _relpath(target)
    targets = [renamed.get(path, path) for path in paths]
    if len(set(targets)) != len(targets):
        raise BundleError("mapped bundle paths must have distinct destinations")
    drift = []
    for item in document["files"]:
        path = item["path"]
        target = (vendored / renamed.get(path, path)).resolve()
        if not target.is_relative_to(vendored):
            raise BundleError(f"vendored path escapes directory: {path}")
        if not target.is_file() or file_digest(target) != item["sha256"]:
            drift.append(path)
    return {"digest": document["digest"], "matches": not drift, "drift": drift}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BundleError(message)


def main(argv=None):
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--bump", action="store_true")
    commands.add_parser("check")
    verify = commands.add_parser("verify")
    verify.add_argument("--vendored", required=True)
    verify.add_argument("--map", action="append", default=[])
    commands.add_parser("digest")
    try:
        args = parser.parse_args(argv)
        if args.command == "build":
            document = manifest(ROOT)
            if args.bump:
                document["version"] += 1
            (ROOT / MANIFEST_PATH).write_text(
                json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
            return 0
        document = _read_manifest(ROOT)
        if args.command == "digest":
            print(document["digest"])
            return 0
        if args.command == "verify":
            result = _verify(document, args.vendored, args.map)
            print(json.dumps(result))
            return 0 if result["matches"] else 1
        current = manifest(ROOT)
        if document == current:
            return 0
        drift = _drift(document, current)
        print(json.dumps(drift or [MANIFEST_PATH]), file=sys.stderr)
        return 1
    except (OSError, ValueError, contracts.ContractError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
