"""The secret-file matcher's coverage, as data (issue #244).

`is_secret_path` is a regex plus a glob probe set. Three review rounds found
three precision defects in the prose that described it, so the prose now points
here: this table is the authoritative statement of what the floor treats as a
secret-looking path. Every verdict was measured against the frozen matcher, not
inferred from its source. A matcher change fails this test instead of silently
making FLOOR_LIMITATIONS.md and SPECS.md wrong.
"""

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"

_spec = importlib.util.spec_from_file_location("dispatch_secret_paths", DISPATCH_PATH)
dispatch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dispatch)

# (path, matched, why the row is here)
COVERAGE = (
    # `.env` family: anchored to a path boundary; the suffix alphabet is [\w.].
    (".env", True, ".env itself"),
    (".ENV", True, "case-insensitive"),
    (".envrc", True, "direnv file"),
    (".env.production", True, ".env.<suffix>"),
    ("src/.env.local", True, "under a directory"),
    (".env.foo-bar", False, "a hyphen ends the [\\w.] suffix, so no match"),
    ("prod.env", False, "the extension spelling is not the name"),
    # `credential` anywhere in the path.
    ("credentials.json", True, "credential substring"),
    ("aws/credentials", True, "no extension needed"),
    ("deploy/Credentials.yml", True, "case-insensitive"),
    # `secret.` / `secrets.`: unanchored, so any position, but the dot is required.
    ("secret.txt", True, "prefix"),
    ("secrets.json", True, "plural"),
    ("config/secret.yaml", True, "under a directory"),
    ("SECRET.TXT", True, "case-insensitive"),
    ("my-secret.txt", True, "unanchored: not a prefix test"),
    ("app-secrets.json", True, "unanchored plural"),
    ("notsecret.txt", True, "unanchored even inside a word"),
    ("my.secret", False, "no dot after secret: not the *secret* glob"),
    # SSH key names: a prefix match with no trailing boundary.
    ("id_rsa", True, "key name"),
    ("id_ed25519", True, "key name"),
    ("id_ecdsa.pub", True, "public half matches too"),
    ("id_rsax", True, "no trailing boundary: a prefix match"),
    # Exactly one extension.
    ("prod.pem", True, "*.pem"),
    ("key.pem", True, "*.pem"),
    ("prod.key", False, "extension not covered (#130)"),
    ("prod.p12", False, "extension not covered (#130)"),
    ("prod.pfx", False, "extension not covered (#130)"),
    ("prod.crt", False, "extension not covered (#130)"),
    ("prod.netrc", False, "extension not covered (#130)"),
    ("notes.txt", False, "ordinary file"),
)


class SecretPathCoverageTests(unittest.TestCase):
    def test_the_coverage_table_matches_the_matcher(self) -> None:
        for path, matched, why in COVERAGE:
            with self.subTest(path=path, why=why):
                self.assertIs(dispatch.is_secret_path(path), matched)

    def test_backslash_paths_read_like_forward_slashes(self) -> None:
        for path, matched, why in COVERAGE:
            if "/" not in path:
                continue
            windows = path.replace("/", "\\")
            with self.subTest(path=windows, why=why):
                self.assertIs(dispatch.is_secret_path(windows), matched)


if __name__ == "__main__":
    unittest.main()
