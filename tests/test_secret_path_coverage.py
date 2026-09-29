"""The secret-file matcher's coverage, as data (issue #244).

`is_secret_path` is a regex plus a glob probe set, and `token_is_secret_filename`
is its stricter basename twin. Three review rounds found
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

# (path, is_secret_path, token_is_secret_filename, why the row is here)
# is_secret_path guards command operands; the stricter token_is_secret_filename
# matches a secret FILE basename for git ref and checkout operands, where a loose
# substring would flag a branch such as fix/credential-x.
COVERAGE = (
    # `.env` family: anchored to a path boundary; the suffix alphabet is [\w.].
    (".env", True, True, ".env itself"),
    (".ENV", True, True, "case-insensitive"),
    (".envrc", True, False, "direnv file"),
    (".env.production", True, True, ".env.<suffix>"),
    ("src/.env.local", True, True, "under a directory"),
    (".env.foo-bar", False, False, "a hyphen ends the [\\w.] suffix, so no match"),
    ("prod.env", False, False, "the extension spelling is not the name"),
    # `credential` anywhere in the path.
    ("credentials.json", True, True, "credential substring"),
    ("aws/credentials", True, False, "no extension needed"),
    ("deploy/Credentials.yml", True, True, "case-insensitive"),
    # `secret.` / `secrets.`: unanchored, so any position, but the dot is required.
    ("secret.txt", True, True, "prefix"),
    ("secrets.json", True, True, "plural"),
    ("config/secret.yaml", True, True, "under a directory"),
    ("SECRET.TXT", True, True, "case-insensitive"),
    ("my-secret.txt", True, False, "unanchored: not a prefix test"),
    ("app-secrets.json", True, False, "unanchored plural"),
    ("notsecret.txt", True, False, "unanchored even inside a word"),
    ("my.secret", False, False, "no dot after secret: not the *secret* glob"),
    # SSH key names: a prefix match with no trailing boundary.
    ("id_rsa", True, True, "key name"),
    ("id_ed25519", True, True, "key name"),
    ("id_ecdsa.pub", True, True, "public half matches too"),
    ("id_rsax", True, False, "no trailing boundary: a prefix match"),
    # Exactly one extension.
    ("prod.pem", True, True, "*.pem"),
    ("key.pem", True, True, "*.pem"),
    ("prod.key", False, False, "extension not covered (#130)"),
    ("prod.p12", False, False, "extension not covered (#130)"),
    ("prod.pfx", False, False, "extension not covered (#130)"),
    ("prod.crt", False, False, "extension not covered (#130)"),
    ("prod.netrc", False, False, "extension not covered (#130)"),
    ("notes.txt", False, False, "ordinary file"),
)


class SecretPathCoverageTests(unittest.TestCase):
    def test_the_coverage_table_matches_the_matcher(self) -> None:
        for path, matched, _strict, why in COVERAGE:
            with self.subTest(path=path, why=why):
                self.assertIs(dispatch.is_secret_path(path), matched)

    def test_the_strict_filename_column_matches_its_predicate(self) -> None:
        for path, _matched, strict, why in COVERAGE:
            with self.subTest(path=path, why=why):
                self.assertIs(dispatch.token_is_secret_filename(path), strict)

    def test_backslash_paths_read_like_forward_slashes(self) -> None:
        for path, matched, _strict, why in COVERAGE:
            if "/" not in path:
                continue
            windows = path.replace("/", "\\")
            with self.subTest(path=windows, why=why):
                self.assertIs(dispatch.is_secret_path(windows), matched)


if __name__ == "__main__":
    unittest.main()
