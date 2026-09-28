"""Build the charter-v0.2 replay corpus: charter-v0.1 plus cases from the floor's smoke matrix.

The 50 hand-labelled charter-v0.1 cases are kept unchanged and first. The rest
are drawn deterministically from `templates/hooks/smoke_test.py` CASES at tier 1
with no overlay flags, stratified by command head and expected decision. Their
case class is the frozen floor's charter expectation (`deny` -> dangerous,
`allow` -> benign), not an independent judgement, and each rationale says so.

    python scripts/build_charter_corpus.py [--check]
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "replay_v0" / "corpora" / "charter"
TARGET = ROOT / "replay_v0" / "corpora" / "charter-v0.2"
SMOKE = ROOT / "templates" / "hooks" / "smoke_test.py"
PER_BUCKET = 2
MAX_LENGTH = 200
CWD = "sandbox/replay-demo"
# Commands that could carry machine, identity or credential material are left out.
EXCLUDE = re.compile(
    r"(?i)users[\\/]|/home/|[\r\n\x00]|[0-9a-f]{32}|gh[pousr]_|github_pat|"
    r"\bsk-|AKIA|BEGIN [A-Z ]*PRIVATE|@[a-z0-9-]+\.[a-z]{2,}|"
    + "|".join(["mu" + "se", "her" + "mes", "claude" + "-config", "chris" + "0jeky"])
)
_SLUG = re.compile(r"[^a-z0-9]+")


def load_cases() -> list[tuple[str, int, dict, str]]:
    spec = importlib.util.spec_from_file_location("smoke_matrix", SMOKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.CASES)


def head_slug(command: str) -> str:
    words = command.split()
    head = words[0] if words else "empty"
    head = head.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return _SLUG.sub("-", head).strip("-")[:20] or "other"


def selected(cases: list[tuple[str, int, dict, str]]) -> list[tuple[str, str, str]]:
    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    seen: set[str] = set()
    for command, tier, flags, expected in cases:
        if tier != 1 or flags or expected not in ("allow", "deny"):
            continue
        if len(command) > MAX_LENGTH or EXCLUDE.search(command) or command in seen:
            continue
        seen.add(command)
        buckets[(head_slug(command), expected)].append(command)
    picked: list[tuple[str, str, str]] = []
    for (head, expected), commands in sorted(buckets.items()):
        ranked = sorted(
            commands, key=lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
        )
        picked.extend((head, expected, command) for command in ranked[:PER_BUCKET])
    return picked


def jsonl(records: list[dict]) -> bytes:
    lines = [json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in records]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build() -> dict[str, bytes]:
    events = [
        json.loads(line)
        for line in (SOURCE / "events.jsonl").read_text("utf-8").splitlines()
    ]
    cases = [
        json.loads(line)
        for line in (SOURCE / "cases.jsonl").read_text("utf-8").splitlines()
    ]
    counters: dict[str, int] = defaultdict(int)
    for index, (head, expected, command) in enumerate(selected(load_cases())):
        klass = "dangerous" if expected == "deny" else "benign"
        counters[(head, klass)] += 1
        event_id = f"floor-{klass[:3]}-{head}-{counters[(head, klass)]:02d}"
        minute, second = divmod(index, 60)
        events.append(
            {
                "schema_version": "command-event.v1",
                "event_id": event_id,
                "timestamp": f"2026-09-29T{10 + minute // 60:02d}:"
                f"{minute % 60:02d}:{second:02d}Z",
                "command": command,
                "cwd": CWD,
                "source": "synthetic",
            }
        )
        cases.append(
            {
                "schema_version": "charter-case.v1",
                "event_id": event_id,
                "case_class": klass,
                "case_family": f"floor-{head}",
                "rationale": (
                    "From the floor smoke matrix at tier 1: the frozen floor's "
                    f"charter expects {expected}."
                ),
                "provenance": "synthetic",
            }
        )
    files = {"events.jsonl": jsonl(events), "cases.jsonl": jsonl(cases)}
    manifest = {
        "schema_version": "corpus-manifest.v1",
        "corpus_id": "charter-v0.2",
        "event_count": len(events),
        "files": [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        ],
    }
    files["corpus-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode(
        "utf-8"
    )
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if out of date")
    args = parser.parse_args(argv)
    files = build()
    if args.check:
        stale = [
            name
            for name, data in files.items()
            if not (TARGET / name).is_file() or (TARGET / name).read_bytes() != data
        ]
        if stale:
            print("out of date: " + ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (TARGET / name).write_bytes(data)
    print(json.loads(files["corpus-manifest.json"])["event_count"], "events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
