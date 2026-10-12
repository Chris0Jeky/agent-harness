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
FIXTURE_PATH = "schemas/learning/compat/FIXTURES.json"
FIXTURE_SCHEMA = "learning-compat-fixtures/v1"
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


def manifest(root, *, version=None):
    """Describe current bundle bytes, preserving the recorded version if present."""
    root = Path(root)
    if version is None:
        version = (
            _read_manifest(root)["version"] if (root / MANIFEST_PATH).exists() else 1
        )
    if type(version) is not int or version < 1:
        raise BundleError("bundle version must be a positive integer")
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


def _verify(document, vendored, mappings, *, strict=False):
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
    result = {"digest": document["digest"], "matches": not drift, "drift": drift}
    if strict:
        # Include explicitly mapped schema directories, not unrelated consumer trees.
        parents = {"schemas/learning"} | {
            str(PurePosixPath(renamed.get(path, path)).parent)
            for path in paths
            if path.startswith("schemas/learning/")
        }
        extra = []
        for parent in sorted(parents):
            directory = vendored / parent
            if not directory.resolve().is_relative_to(vendored):
                raise BundleError(f"vendored schema directory escapes: {parent}")
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                relative = entry.relative_to(vendored).as_posix()
                if (
                    entry.suffix == ".json"
                    and relative != MANIFEST_PATH
                    and relative not in targets
                ):
                    extra.append(relative)
        result["extra"] = sorted(set(extra))
        result["matches"] = not drift and not extra
    return result


def fixture_manifest(root, version):
    """Pin compat bytes separately; consumers need not vendor the fixture corpus."""
    root = Path(root)
    directory = root / "schemas/learning/compat"
    if directory.is_symlink() or not directory.is_dir():
        raise BundleError(
            "compatibility fixture directory must be an ordinary directory"
        )
    files = []
    for path in sorted(
        directory.rglob("*"), key=lambda path: path.relative_to(root).as_posix()
    ):
        relative = path.relative_to(root).as_posix()
        if relative == FIXTURE_PATH:
            continue
        if path.is_symlink():
            raise BundleError(
                f"compatibility fixture aliases are unsupported: {relative}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise BundleError(
                f"compatibility fixture is not an ordinary file: {relative}"
            )
        files.append({"path": relative, "sha256": file_digest(path)})
    if not files:
        raise BundleError("compatibility fixtures must be nonempty")
    return {
        "schema": FIXTURE_SCHEMA,
        "version": version,
        "files": files,
        "digest": _digest(files),
    }


def _read_fixture_lock(root):
    document = contracts.loads((root / FIXTURE_PATH).read_text("utf-8"))
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "version", "files", "digest"}
        or document["schema"] != FIXTURE_SCHEMA
        or type(document["version"]) is not int
        or document["version"] < 1
        or not isinstance(document["files"], list)
        or not document["files"]
    ):
        raise BundleError("invalid compatibility fixture lock")
    paths = []
    for item in document["files"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not isinstance(item["path"], str)
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise BundleError("invalid compatibility fixture entry")
        relative = _relpath(item["path"])
        if (
            not relative.startswith("schemas/learning/compat/")
            or relative == FIXTURE_PATH
        ):
            raise BundleError(f"path outside compatibility fixtures: {relative}")
        paths.append(relative)
    if paths != sorted(set(paths)) or document["digest"] != _digest(document["files"]):
        raise BundleError("invalid compatibility fixture order or digest")
    return document


def build_manifest(root, *, bump=False, version=None):
    """Refresh both pins; changed or unpinned fixtures require a version advance."""
    root = Path(root)
    previous = None
    if (root / MANIFEST_PATH).exists():
        try:
            previous = _read_manifest(root)
        except (OSError, ValueError, contracts.ContractError):
            if version is None:
                raise
    locked = None
    if (root / FIXTURE_PATH).exists():
        try:
            locked = _read_fixture_lock(root)
        except (OSError, ValueError, contracts.ContractError):
            if not bump and version is None:
                raise
    prior_version = max(
        previous["version"] if previous else 0,
        locked["version"] if locked else 0,
    )
    if previous is None and (root / FIXTURE_PATH).exists() and version is None:
        raise BundleError("missing bundle manifest; recover with build --version N")
    selected = version
    if selected is None:
        selected = (previous["version"] if previous else 1) + int(bump)
    if type(selected) is not int or selected < 1 or selected < prior_version:
        raise BundleError("bundle version must be positive and must not decrease")
    document = manifest(root, version=selected)
    fixtures = fixture_manifest(root, selected)
    changed = locked is None or locked["digest"] != fixtures["digest"]
    if changed and prior_version and selected <= prior_version:
        raise BundleError(
            "compatibility fixtures changed or unpinned; build --bump required"
        )
    # A failed second write leaves a detectable version mismatch, never a green check.
    for relative, value in ((FIXTURE_PATH, fixtures), (MANIFEST_PATH, document)):
        (root / relative).write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n"
        )


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BundleError(message)


def main(argv=None):
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    version = build.add_mutually_exclusive_group()
    version.add_argument("--bump", action="store_true")
    version.add_argument("--version", type=int)
    commands.add_parser("check")
    verify = commands.add_parser("verify")
    verify.add_argument("--vendored", required=True)
    verify.add_argument("--map", action="append", default=[])
    verify.add_argument("--strict", action="store_true")
    commands.add_parser("digest")
    try:
        args = parser.parse_args(argv)
        if args.command == "build":
            build_manifest(ROOT, bump=args.bump, version=args.version)
            return 0
        document = _read_manifest(ROOT)
        if args.command == "digest":
            print(document["digest"])
            return 0
        if args.command == "verify":
            result = _verify(document, args.vendored, args.map, strict=args.strict)
            print(json.dumps(result))
            return 0 if result["matches"] else 1
        current = manifest(ROOT)
        locked = _read_fixture_lock(ROOT)
        fixtures = fixture_manifest(ROOT, document["version"])
        drift = _drift(document, current) + _drift(locked, fixtures)
        if document != current and not _drift(document, current):
            drift.append(MANIFEST_PATH)
        if locked != fixtures and not _drift(locked, fixtures):
            drift.append(FIXTURE_PATH)
        if not drift:
            return 0
        print(json.dumps(sorted(set(drift))), file=sys.stderr)
        return 1
    except (OSError, ValueError, contracts.ContractError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
