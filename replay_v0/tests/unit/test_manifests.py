from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from replay_v0.digests import sha256_bytes
from replay_v0.manifests import (
    ManifestError,
    build_corpus_manifest,
    build_run_manifest,
    load_corpus_manifest,
    manifest_json_bytes,
    validate_corpus_manifest,
    validate_run_manifest,
)

BASELINE = {
    "kind": "recorded",
    "id": "floor-v1-final",
    "sha256": "1" * 64,
}
CANDIDATE = {
    "kind": "process",
    "id": "candidate-policy",
    "sha256": "2" * 64,
}
CORPUS = {
    "id": "charter-v0.1",
    "manifest_sha256": "3" * 64,
    "event_count": 50,
}
FAIL_ON = ["newly-allowed", "newly-indeterminate"]


class CorpusManifestTests(unittest.TestCase):
    def test_corpus_event_count_must_be_positive(self) -> None:
        manifest = {
            "schema_version": "corpus-manifest.v1",
            "corpus_id": "empty-v0",
            "event_count": 0,
            "files": [{"path": "events.jsonl", "sha256": "a" * 64}],
        }
        with self.assertRaisesRegex(ManifestError, "expected a positive integer"):
            validate_corpus_manifest(manifest)

        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            (directory / "events.jsonl").write_bytes(b"")
            with self.assertRaisesRegex(
                ManifestError, "expected a positive integer"
            ):
                build_corpus_manifest(
                    corpus_id="empty-v0",
                    event_count=0,
                    base_directory=directory,
                    files=["events.jsonl"],
                )

    def test_build_and_load_validate_every_exact_file_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            (directory / "events.jsonl").write_bytes(b'{"event_id":"one"}\n')
            (directory / "cases.jsonl").write_bytes(b'{"event_id":"one"}\n')
            manifest = build_corpus_manifest(
                corpus_id="charter-v0.1",
                event_count=1,
                base_directory=directory,
                files=["events.jsonl", "cases.jsonl"],
            )
            manifest_bytes = manifest_json_bytes(manifest)
            manifest_path = directory / "corpus-manifest.json"
            manifest_path.write_bytes(manifest_bytes)

            loaded = load_corpus_manifest(manifest_path)
            self.assertEqual(manifest, loaded.value)
            self.assertEqual(sha256_bytes(manifest_bytes), loaded.manifest_sha256)

            (directory / "events.jsonl").write_bytes(b'{"event_id":"changed"}\n')
            with self.assertRaisesRegex(ManifestError, "does not match"):
                load_corpus_manifest(manifest_path)

    def test_manifest_digest_covers_exact_manifest_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            (directory / "events.jsonl").write_bytes(b"{}\n")
            manifest = build_corpus_manifest(
                corpus_id="tiny-v0",
                event_count=1,
                base_directory=directory,
                files=["events.jsonl"],
            )
            compact = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
            pretty = manifest_json_bytes(manifest)
            manifest_path = directory / "corpus-manifest.json"
            manifest_path.write_bytes(compact)
            compact_loaded = load_corpus_manifest(manifest_path)
            manifest_path.write_bytes(pretty)
            pretty_loaded = load_corpus_manifest(manifest_path)
        self.assertEqual(compact_loaded.value, pretty_loaded.value)
        self.assertNotEqual(
            compact_loaded.manifest_sha256, pretty_loaded.manifest_sha256
        )

    def test_absolute_parent_duplicate_and_windows_paths_are_rejected(self) -> None:
        base = {
            "schema_version": "corpus-manifest.v1",
            "corpus_id": "charter-v0.1",
            "event_count": 1,
            "files": [{"path": "events.jsonl", "sha256": "a" * 64}],
        }
        for invalid_path in (
            "/private/events.jsonl",
            "../events.jsonl",
            "C:\\events.jsonl",
            ".",
        ):
            value = copy.deepcopy(base)
            value["files"][0]["path"] = invalid_path
            with self.subTest(path=invalid_path):
                with self.assertRaises(ManifestError):
                    validate_corpus_manifest(value)

        duplicate = copy.deepcopy(base)
        duplicate["files"].append(dict(duplicate["files"][0]))
        with self.assertRaisesRegex(ManifestError, "duplicate path"):
            validate_corpus_manifest(duplicate)


class RunManifestTests(unittest.TestCase):
    def build(self, generated_at: str = "2026-07-30T12:00:00Z"):
        return build_run_manifest(
            generated_at=generated_at,
            baseline=BASELINE,
            candidate=CANDIDATE,
            corpus=CORPUS,
            fail_on=FAIL_ON,
        )

    def test_run_id_is_stable_and_excludes_generated_at(self) -> None:
        first = self.build("2026-07-30T12:00:00Z")
        second = self.build("2030-01-01T00:00:00Z")
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertNotEqual(first["generated_at"], second["generated_at"])

    def test_run_manifest_corpus_event_count_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ManifestError, "expected a positive integer"):
            build_run_manifest(
                generated_at="2026-07-30T12:00:00Z",
                baseline=BASELINE,
                candidate=CANDIDATE,
                corpus={**CORPUS, "event_count": 0},
                fail_on=FAIL_ON,
            )

    def test_run_id_changes_with_each_semantic_input_class(self) -> None:
        original = self.build()
        changes = [
            {"baseline": {**BASELINE, "sha256": "4" * 64}},
            {"candidate": {**CANDIDATE, "sha256": "4" * 64}},
            {
                "corpus": {
                    **CORPUS,
                    "manifest_sha256": "4" * 64,
                }
            },
            {"fail_on": ["newly-allowed"]},
            {"runner_version": "0.1.1"},
        ]
        for change in changes:
            arguments = {
                "generated_at": "2026-07-30T12:00:00Z",
                "baseline": BASELINE,
                "candidate": CANDIDATE,
                "corpus": CORPUS,
                "fail_on": FAIL_ON,
                **change,
            }
            with self.subTest(change=next(iter(change))):
                changed = build_run_manifest(**arguments)
                self.assertNotEqual(original["run_id"], changed["run_id"])

    def test_output_has_only_portable_declared_fields(self) -> None:
        manifest = self.build()
        self.assertEqual(
            {
                "schema_version",
                "run_id",
                "generated_at",
                "runner_version",
                "baseline",
                "candidate",
                "corpus",
                "fail_on",
            },
            set(manifest),
        )
        serialized = manifest_json_bytes(manifest).decode("utf-8")
        self.assertNotIn("absolute_path", serialized)
        self.assertNotIn("hostname", serialized)
        self.assertNotIn("username", serialized)
        self.assertNotIn("environment", serialized)

        invalid = {**BASELINE, "id": "C:\\private\\policy.py"}
        with self.assertRaises(ManifestError):
            build_run_manifest(
                generated_at="2026-07-30T12:00:00Z",
                baseline=invalid,
                candidate=CANDIDATE,
                corpus=CORPUS,
                fail_on=FAIL_ON,
            )

    def test_validation_rejects_a_run_id_not_bound_to_inputs(self) -> None:
        manifest = self.build()
        manifest["candidate"]["sha256"] = "9" * 64
        with self.assertRaisesRegex(ManifestError, "run_id"):
            validate_run_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
