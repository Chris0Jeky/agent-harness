import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "templates" / "hooks" / "dispatch.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "curl_8_21_0_option_arity.json"


def load_dispatch_module():
    spec = importlib.util.spec_from_file_location("arity_dispatch", DISPATCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load dispatcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CurlOptionArityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dispatch = load_dispatch_module()
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_long_value_options_match_pinned_curl_table(self) -> None:
        self.assertEqual(
            set(self.fixture["long_options_with_value"]),
            set(self.dispatch._CURL_LONG_OPTIONS_WITH_VALUE),
        )

    def test_short_value_options_match_pinned_curl_table(self) -> None:
        self.assertEqual(
            set(self.fixture["short_options_with_value"]),
            set(self.dispatch._CURL_SHORT_OPTIONS_WITH_VALUE),
        )


if __name__ == "__main__":
    unittest.main()
