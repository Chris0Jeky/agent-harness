#!/usr/bin/env python3
"""Run one existing CI Python check with the shared curated file inventory."""

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = "scripts/python_check_files.json"
COMMANDS = {
    "ruff": ("-m", "ruff", "check"),
    "black": ("-m", "black", "--check", "--diff", "replay_v0"),
    "compile": ("-m", "py_compile"),
}


def load_files(root):
    """Read the single ordered inventory; missing or malformed input refuses."""
    files = json.loads((root / INVENTORY).read_text("utf-8"))
    if not isinstance(files, list) or not files:
        raise ValueError("Python check inventory must be a nonempty list")
    seen = set()
    for name in files:
        if (
            not isinstance(name, str)
            or not name
            or name.startswith("-")
            or "\\" in name
            or ":" in name
            or PurePosixPath(name).is_absolute()
            or any(part in ("", ".", "..") for part in name.split("/"))
            or not name.endswith(".py")
        ):
            raise ValueError(f"invalid Python check path: {name!r}")
        if name in seen:
            raise ValueError(f"duplicate Python check path: {name}")
        if not (root / name).is_file():
            raise ValueError(f"Python check file is missing: {name}")
        seen.add(name)
    return files


def main(argv=None, *, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=COMMANDS)
    args = parser.parse_args(argv)
    root = Path(root)
    try:
        files = load_files(root)
        # Keep Black's pre-existing whole-replay scan in addition to the list.
        return subprocess.run(
            [sys.executable, *COMMANDS[args.tool], *files],
            cwd=root,
            check=False,
        ).returncode
    except (OSError, ValueError) as exc:
        print(f"python checks: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
