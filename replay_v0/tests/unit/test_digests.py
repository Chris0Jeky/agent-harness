from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from replay_v0.digests import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    sha256_tree,
)


class DigestTests(unittest.TestCase):
    def test_file_digest_covers_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory) / "events.jsonl"
            path.write_bytes(b'{"event_id":"one"}\n')
            lf_digest = sha256_file(path)
            path.write_bytes(b'{"event_id":"one"}\r\n')
            crlf_digest = sha256_file(path)
        self.assertNotEqual(lf_digest, crlf_digest)
        self.assertEqual(hashlib.sha256(b'{"event_id":"one"}\n').hexdigest(), lf_digest)

    def test_canonical_json_digest_ignores_mapping_insertion_order(self) -> None:
        left = canonical_json_bytes({"b": 2, "a": [1, "two"]})
        right = canonical_json_bytes({"a": [1, "two"], "b": 2})
        self.assertEqual(left, right)
        self.assertEqual(sha256_bytes(left), sha256_bytes(right))

    def test_tree_digest_binds_relative_names_and_exact_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as first_raw_directory:
            with tempfile.TemporaryDirectory() as second_raw_directory:
                first = Path(first_raw_directory)
                second = Path(second_raw_directory)
                for root in (first, second):
                    (root / "empty").mkdir()
                    (root / "policy.py").write_bytes(b"import rules\n")
                    (root / "rules.py").write_bytes(b'EFFECT = "deny"\n')

                original = sha256_tree(first)
                self.assertEqual(original, sha256_tree(second))
                (first / "rules.py").write_bytes(b'EFFECT = "allow"\n')
                self.assertNotEqual(original, sha256_tree(first))


if __name__ == "__main__":
    unittest.main()
