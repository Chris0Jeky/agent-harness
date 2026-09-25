"""Compare recovered input bytes with the historical BH1 receipt, offline.

A matching digest is not benchmark-claim verification or upstream authentication.
This command never changes acceptance from blocked and never executes a generator.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
import stat

EXPECTED_SHA256 = {
    "benchmark.json": "d58f9add7926f471b694cb4809cb12559ab9d2a1af88cb5efe096b0e875766fb",
    "KEY_RUNS.json": "9f1375733e52c93b0f11a235df117dc5e19a833e57ab3b55b3f86ccc18b61418",
}


def verify(root: Path, expected: Mapping[str, str] | None = None) -> dict:
    """Check fixed input names; injected expectations are for synthetic controls."""
    expected = EXPECTED_SHA256 if expected is None else expected
    if not expected or any(
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        for name, digest in expected.items()
    ):
        raise ValueError("expected nonempty basename/lowercase-SHA256 pairs")
    files = []
    for name, expected_digest in expected.items():
        row = {
            "name": name,
            "expected_sha256": expected_digest,
            "observed_sha256": None,
            "bytes_read": 0,
            "status": "missing",
        }
        try:
            path = root / name
            if not stat.S_ISREG(path.lstat().st_mode):
                row["status"] = "not_regular_file"
            else:
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        row["bytes_read"] += len(chunk)
                row["observed_sha256"] = digest.hexdigest()
                row["status"] = (
                    "match" if digest.hexdigest() == expected_digest else "mismatch"
                )
        except FileNotFoundError:
            row["status"] = "missing"
        except (OSError, ValueError) as exc:
            # Do not disclose file contents or caller-local paths in diagnostics.
            row["status"] = f"unreadable:{type(exc).__name__}"
        files.append(row)
    return {
        "schema_version": "bh-frozen-input-check.v1",
        "basis": "Historical receipt, not independently authenticated upstream data",
        "matches_receipt": all(row["status"] == "match" for row in files),
        "benchmark_claims_verified": False,
        "generator_verified": False,
        "acceptance": "blocked",
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    args = parser.parse_args(argv)
    result = verify(args.inputs)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["matches_receipt"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
