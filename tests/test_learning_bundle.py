"""Bundle identity, consumer verification and frozen synthetic compatibility cases."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "learning_bundle", ROOT / "scripts" / "learning_bundle.py"
)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)
lc = bundle.contracts
COMPAT = ROOT / "schemas" / "learning" / "compat"


class BundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tree = Path(temporary.name)
        for relative in (*bundle.BUNDLE_FILES, bundle.MANIFEST_PATH):
            target = self.tree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        shutil.copyfile(
            ROOT / "scripts" / "learning_bundle.py",
            self.tree / "scripts" / "learning_bundle.py",
        )

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.tree / "scripts" / "learning_bundle.py"), *args],
            cwd=self.tree,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def document(self):
        return json.loads((self.tree / bundle.MANIFEST_PATH).read_text("utf-8"))

    def test_committed_manifest_matches_current_files(self):
        committed = json.loads((ROOT / bundle.MANIFEST_PATH).read_text("utf-8"))
        self.assertEqual(bundle.manifest(ROOT), committed)
        self.assertEqual(self.cli("check").returncode, 0)

    def test_bundle_membership_and_digest_rule(self):
        paths = sorted(
            ["scripts/learning_contracts.py"]
            + [
                f"schemas/learning/{path.name}"
                for path in (ROOT / "schemas" / "learning").glob("*.json")
                if path.suffix == ".json" and path.name != "BUNDLE.json"
            ]
        )
        self.assertEqual(list(bundle.BUNDLE_FILES), paths)
        document = bundle.manifest(ROOT)
        self.assertEqual([item["path"] for item in document["files"]], paths)
        self.assertEqual(document["record_schemas"], sorted(lc.RECORD_SCHEMAS))
        payload = "".join(
            item["path"] + "\t" + item["sha256"] + "\n" for item in document["files"]
        )
        self.assertEqual(
            document["digest"], hashlib.sha256(payload.encode("utf-8")).hexdigest()
        )
        result = self.cli("digest")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), document["digest"])

    def test_crlf_and_lf_have_the_same_file_digest(self):
        lf, crlf = self.tree / "lf.txt", self.tree / "crlf.txt"
        lf.write_bytes(b"synthetic\nbytes\n")
        crlf.write_bytes(b"synthetic\r\nbytes\r\n")
        self.assertEqual(bundle.file_digest(lf), bundle.file_digest(crlf))
        self.assertEqual(
            bundle.file_digest(lf), hashlib.sha256(b"synthetic\nbytes\n").hexdigest()
        )

    def test_check_reports_changed_added_and_removed_paths(self):
        changed = "schemas/learning/lifecycle.json"
        added = "schemas/learning/synthetic-extra.json"
        removed = "schemas/learning/objectives.json"
        for kind, relative in (
            ("changed", changed),
            ("added", added),
            ("removed", removed),
        ):
            with self.subTest(kind=kind):
                target = self.tree / relative
                original = target.read_bytes() if target.exists() else None
                if kind == "removed":
                    target.unlink()
                else:
                    target.write_bytes((original or b"{}") + b"\n ")
                result = self.cli("check")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(json.loads(result.stderr), [relative])
                if original is None:
                    target.unlink()
                else:
                    target.write_bytes(original)
        # Report all three together, in repository-relative lexical order.
        with (self.tree / changed).open("ab") as stream:
            stream.write(b" ")
        (self.tree / added).write_bytes(b"{}\n")
        (self.tree / removed).unlink()
        result = self.cli("check")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stderr), sorted([changed, added, removed]))

    def test_build_preserves_version_and_bump_increments_it(self):
        target = self.tree / bundle.MANIFEST_PATH
        target.unlink()
        self.assertEqual(bundle.manifest(self.tree)["version"], 1)
        result = self.cli("build")
        self.assertEqual(result.returncode, 0, result.stderr)
        original = self.document()
        self.assertEqual(original["version"], 1)
        self.assertEqual(self.cli("build", "--bump").returncode, 0)
        bumped = self.document()
        self.assertEqual(bumped["version"], 2)
        self.assertEqual(bumped["digest"], original["digest"])
        self.assertEqual(self.cli("build").returncode, 0)
        self.assertEqual(self.document(), bumped)
        self.assertEqual(
            target.read_bytes(), (json.dumps(bumped, indent=2) + "\n").encode("utf-8")
        )
        self.assertEqual(self.cli("check").returncode, 0)

    def consumer(self):
        consumer = self.tree / "consumer"
        for relative in bundle.BUNDLE_FILES:
            mapped = (
                "tools/learning_contracts.py"
                if relative == "scripts/learning_contracts.py"
                else relative
            )
            target = consumer / mapped
            target.parent.mkdir(parents=True, exist_ok=True)
            # A consumer on Windows can have CRLF while upstream has LF.
            target.write_bytes(
                (ROOT / relative)
                .read_bytes()
                .replace(b"\r\n", b"\n")
                .replace(b"\n", b"\r\n")
            )
        return consumer

    def test_verify_maps_an_exact_copy_then_reports_one_byte_drift(self):
        consumer = self.consumer()
        args = (
            "verify",
            "--vendored",
            str(consumer),
            "--map",
            "scripts/learning_contracts.py=tools/learning_contracts.py",
        )
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"digest": self.document()["digest"], "matches": True, "drift": []},
        )
        with (consumer / "tools" / "learning_contracts.py").open("ab") as stream:
            stream.write(b" ")
        result = self.cli(*args)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "digest": self.document()["digest"],
                "matches": False,
                "drift": ["scripts/learning_contracts.py"],
            },
        )
        missing = "schemas/learning/common.schema.json"
        (consumer / missing).unlink()
        result = self.cli(*args)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["drift"],
            sorted([missing, "scripts/learning_contracts.py"]),
        )

    def test_verify_without_mapping_and_repeated_maps(self):
        result = self.cli("verify", "--vendored", str(self.tree))
        self.assertEqual(result.returncode, 0, result.stderr)
        consumer = self.consumer()
        source = consumer / "schemas/learning/lifecycle.json"
        target = consumer / "tools/lifecycle.json"
        source.rename(target)
        result = self.cli(
            "verify",
            "--vendored",
            str(consumer),
            "--map",
            "scripts/learning_contracts.py=tools/learning_contracts.py",
            "--map",
            "schemas/learning/lifecycle.json=tools/lifecycle.json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_refusals_have_exit_two_and_json_errors(self):
        consumer = self.consumer()
        for args in (
            (),
            ("unknown",),
            ("build", "--unknown"),
            ("verify",),
            ("verify", "--vendored", str(self.tree / "missing")),
            ("verify", "--vendored", str(consumer), "--map", "not-a-map"),
            ("verify", "--vendored", str(consumer), "--map", "unknown=x"),
            (
                "verify",
                "--vendored",
                str(consumer),
                "--map",
                "scripts/learning_contracts.py=../outside.py",
            ),
            (
                "verify",
                "--vendored",
                str(consumer),
                "--map",
                "scripts/learning_contracts.py=C:/outside.py",
            ),
        ):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIsInstance(json.loads(result.stderr)["error"], str)
        target = self.tree / bundle.MANIFEST_PATH
        for raw in ("{", "[]", '{"schema":"unknown"}'):
            with self.subTest(manifest=raw):
                target.write_text(raw, encoding="utf-8")
                result = self.cli("check")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("error", json.loads(result.stderr))
        target.unlink()
        result = self.cli("digest")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("error", json.loads(result.stderr))


class CompatibilityTests(unittest.TestCase):
    def test_every_accept_record_validates_and_every_schema_is_covered(self):
        seen = set()
        for path in sorted((COMPAT / "accept").glob("*.jsonl")):
            records = lc.read_records(path)
            self.assertTrue(records, path.name)
            for record in records:
                with self.subTest(file=path.name, schema=record["schema"]):
                    self.assertEqual(lc.validate_record(record), [])
                    self.assertEqual(path.stem, record["schema"].replace("/", "-"))
                    seen.add(record["schema"])
        self.assertEqual(seen, set(lc.RECORD_SCHEMAS))

    def test_every_reject_record_fails_for_its_expected_reason(self):
        paths = sorted((COMPAT / "reject").glob("*.json"))
        self.assertGreaterEqual(len(paths), 8)
        for path in paths:
            with self.subTest(file=path.name):
                record = lc.read_records(path)[0]
                expected = record.pop("_expect")
                self.assertIsInstance(expected, str)
                self.assertTrue(expected)
                errors = lc.validate_record(record)
                self.assertTrue(errors, path.name)
                self.assertTrue(any(expected in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
