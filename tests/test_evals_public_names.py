"""The public evals docs name private repositories and products by role only."""

from __future__ import annotations

from pathlib import Path
import re
import unittest

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "docs" / "evals"
# Assembled from fragments so this file does not match itself.
PRIVATE_WORDS = [
    "task" + "deck",
    "agent" + "-hq",
    "mu" + "se",
    "her" + "mes",
    "claude" + "-config",
    "estate" + "-console",
]
PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    + "|".join(map(re.escape, PRIVATE_WORDS))
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# The control-plane abbreviation is only private when it stands alone as a word.
ABBREVIATION = re.compile(r"\b" + "H" + "Q" + r"\b", re.IGNORECASE)


class EvalsPublicNamesTests(unittest.TestCase):
    def test_evals_docs_exist(self) -> None:
        self.assertTrue(sorted(EVALS.rglob("*.md")))

    def test_no_private_names_in_evals_docs(self) -> None:
        for path in sorted(p for p in EVALS.rglob("*") if p.is_file()):
            rel = path.relative_to(REPO).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            with self.subTest(path=rel):
                self.assertIsNone(PATTERN.search(text), rel)
                self.assertIsNone(ABBREVIATION.search(text), rel)
                self.assertIsNone(PATTERN.search(path.name), rel)


if __name__ == "__main__":
    unittest.main()
