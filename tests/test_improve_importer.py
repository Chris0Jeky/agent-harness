"""Deeply nested transcript lines are skipped, not fatal (importer review).

Covers `replay_v0.importer._iter_jsonl` through `claude_commands`: a line that
nests past the interpreter recursion limit is malformed input, so it is
counted as unparsed like any other bad line and the valid records around it
are still extracted.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from replay_v0.importer import claude_commands


def write_nested_line_then_record(path: Path) -> None:
    """One undecodable deeply nested line followed by one valid record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": "2026-02-03T04:05:06.789Z",
        "cwd": "/fictional/app",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "git status"},
                }
            ]
        },
    }
    with path.open("w", encoding="utf-8") as handle:
        handle.write("[" * 50000 + "\n")
        handle.write(json.dumps(record) + "\n")


class DeeplyNestedLineTests(unittest.TestCase):
    def test_deeply_nested_line_is_counted_unparsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "claude"
            write_nested_line_then_record(root / "s.jsonl")
            stats: Counter[str] = Counter()
            found = list(claude_commands(root, stats))
        self.assertEqual(
            found, [("git status", "2026-02-03T04:05:06Z", "/fictional/app")]
        )
        self.assertEqual(stats["unparsed-lines"], 1)
