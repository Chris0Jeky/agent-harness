"""Corrupt --from-corpus cache must fail as a harness error (exit 3)."""

import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAY_PATH = ROOT / "scripts" / "replay_corpus.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


replay = load_module("replay_corpus_corrupt_cache_under_test", REPLAY_PATH)


class CorruptCacheTests(unittest.TestCase):
    def test_corrupt_row_raises_harness_error(self):
        path = self._cache_path()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps({replay.CORPUS_CACHE_META_KEY: {"integrity": {}}}) + "\n"
            )
            handle.write("{not json\n")
        with self.assertRaises(replay.ReplayHarnessError):
            replay.load_corpus(path)

    def test_main_returns_tool_failure_without_traceback(self):
        path = self._cache_path()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps({replay.CORPUS_CACHE_META_KEY: {"integrity": {}}}) + "\n"
            )
            handle.write("{not json\n")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = replay.main(["--from-corpus", str(path), "--quiet"])
        self.assertEqual(code, replay.EXIT_TOOL_FAILURE)
        self.assertNotIn("Traceback", stderr.getvalue())

    def _cache_path(self):
        tmp = Path(self._tmpdir().name) / "corpus.jsonl"
        return tmp

    def test_bad_counts_and_ledger_do_not_echo_cache_contents(self):
        command = "echo synthetic-private-command"
        private_value = "synthetic-private-count"
        rows = [
            {"command": command, "claude": private_value},
            {replay.CORPUS_CACHE_META_KEY: {"integrity": {"rows": private_value}}},
        ]
        for row in rows:
            with self.subTest(row=row):
                path = self._cache_path()
                path.write_text(json.dumps(row) + "\n", encoding="utf-8")
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                    stderr
                ):
                    code = replay.main(["--from-corpus", str(path), "--quiet"])
                self.assertEqual(code, replay.EXIT_TOOL_FAILURE)
                output = stdout.getvalue() + stderr.getvalue()
                self.assertNotIn(command, output)
                self.assertNotIn(private_value, output)
                self.assertNotIn("Traceback", output)

    def _tmpdir(self):
        if not hasattr(self, "_tmp"):
            import tempfile

            self._tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self._tmp.cleanup)
        return self._tmp


if __name__ == "__main__":
    unittest.main()
