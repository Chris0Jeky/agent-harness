"""Advisory probe for two explicitly mapped agent-harness documentation claims.

This is not a policy resolver or an estate-wide Markdown parser. A produced report
always exits zero, even for candidates or unknowns. No merge verdict is emitted.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

MAX_BYTES = 1024 * 1024
CLAUSE = re.compile(
    r"^This repo is tier [0-4] \([^\n)]+\) per `\.agent-harness/tier\.json`: "
    r"push ([a-z-]+), merge ([a-z-]+)\.$"
)
VALUES = {"free", "gated", "human-only"}


def _read(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("not a regular nonsymlink input")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("input exceeds size bound")
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _clauses(text):
    matches = []
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        # Ignore conventional fenced examples. Ambiguous/unmapped text is unknown;
        # this is deliberately not a complete CommonMark parser.
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            token, tail = marker.groups()
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not tail.strip():
                fence = None
            continue
        if fence is None:
            match = CLAUSE.fullmatch(line)
            if match:
                matches.append((number, match.groups()))
    return matches


def measure(root: Path) -> dict:
    """Read only the declared tier file and one exact mapped root-doc clause.

    Digests identify the bytes examined. They do not bind a checkout revision,
    authenticate a source, or authorize using this report as a merge decision.
    """
    inputs = {".agent-harness/tier.json": None, "CLAUDE.md": None}
    loaded = {}
    for name in inputs:
        try:
            loaded[name], inputs[name] = _read(root / name)
        except (OSError, ValueError):
            pass
    reason = None
    declared = {}
    documented = {}
    line = None
    if len(loaded) != len(inputs):
        reason = "unavailable_input"
    else:
        try:
            data = json.loads(
                loaded[".agent-harness/tier.json"], object_pairs_hook=_unique
            )
            if not isinstance(data, dict) or not isinstance(
                data.get("authority"), dict
            ):
                raise ValueError("invalid contract")
            declared = data["authority"]
            clauses = _clauses(loaded["CLAUDE.md"])
            if len(clauses) != 1:
                reason = "ambiguous_or_unmapped_clause"
            else:
                line, values = clauses[0]
                documented = dict(zip(("push", "merge"), values))
        except (ValueError, RecursionError):
            reason = "invalid_contract"
    rows = []
    for key in ("push", "merge"):
        source = declared.get(key)
        target = documented.get(key)
        known = (
            reason is None
            and isinstance(source, str)
            and source in VALUES
            and isinstance(target, str)
            and target in VALUES
        )
        state = (
            "unknown" if not known else ("match" if source == target else "candidate")
        )
        rows.append(
            {
                "contract": f"authority.{key}",
                "status": state,
                "declared": source if known else None,
                "documented": target if known else None,
                "finding_key": (
                    f"authority-doc-v1:{key}:{source}:{target}"
                    if state == "candidate"
                    else None
                ),
            }
        )
    unknown = sum(row["status"] == "unknown" for row in rows)
    return {
        "detector": "authority-doc-v1",
        "authority": "advisory",
        "merge_verdict": None,
        "revision_verified": False,
        "inputs": inputs,
        "line": line,
        "reason": reason,
        "counts": {
            "requested": 2,
            "inspected": 2 - unknown,
            "candidate": sum(row["status"] == "candidate" for row in rows),
            "unknown": unknown,
        },
        "observations": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(measure(args.repo), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
