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

from replay_v0.importer import Scrubber, claude_commands


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


class NonObjectLineTests(unittest.TestCase):
    def test_valid_json_non_object_lines_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "claude"
            root.mkdir()
            (root / "s.jsonl").write_text("[]\n42\n\"hi\"\n", encoding="utf-8")
            stats: Counter[str] = Counter()
            self.assertEqual(list(claude_commands(root, stats)), [])
        self.assertEqual(stats["non-object-lines"], 3)
        self.assertEqual(stats["unparsed-lines"], 0)


class BareIpv6LiteralTests(unittest.TestCase):
    def setUp(self):
        self.scrubber = Scrubber([])

    def test_global_ipv6_literals_are_redacted(self):
        for command, secret in (
            ("ping6 2001:db8::1", "2001:db8::1"),
            ("ping 2001:db8:85a3::8a2e:370:7334", "8a2e:370:7334"),
            ("traceroute fd00::abcd", "fd00::abcd"),
            ("dig fe80::1%eth0", "fe80::1"),
        ):
            with self.subTest(command=command):
                text = self.scrubber.scrub(command)
                self.assertNotIn(secret, text)
                self.assertIn("<ip>", text)

    def test_loopback_and_non_addresses_are_unchanged(self):
        for command in (
            "ping6 ::1",
            "ping 127.0.0.1",
            "host std::vector",
            "ping 12:34:56",
            "dig example::",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.scrubber.scrub(command), command)
