"""Offline authoring/binding contracts, not browser or model qualification."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REVISION = "1" * 40
REPOSITORY = "example/product"
FIXTURE = "tests/journey.spec.ts: synthetic fixture"


def pack():
    return {
        "schema": "ux-scenario-pack/0", "pack_id": "continuity", "status": "draft",
        "authority": "advisory", "gate_eligible": False, "local_only": True,
        "subject": {"repository": REPOSITORY, "source_revision": REVISION},
        "journeys": [{
            "id": "keep-draft", "goal": "Preserve an unsaved draft", "fixture_ref": FIXTURE,
            "preconditions": ["Synthetic local state"],
            "steps": [{"id": "switch", "action": "Switch experience",
                       "assertions": ["Draft is unchanged"],
                       "evidence_required": ["action_log", "persisted_state"]}],
            "rubric_dimensions": ["effectiveness", "feel"],
            "budget": {"max_actions": 40, "max_seconds": 600,
                       "max_judge_calls": 1, "max_retries": 0}}]}


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module("ux_evaluation.scenarios")
            self.common = importlib.import_module("ux_evaluation.common")
        except ModuleNotFoundError:
            self.fail("The scoped UX scenario implementation is not present")

    def bind(self, document=None, **overrides):
        options = dict(expected_repository=REPOSITORY, expected_revision=REVISION,
                       allowed_fixtures=[FIXTURE])
        options.update(overrides)
        return self.api.bind_pack(pack() if document is None else document, **options)

    def test_valid_binding_has_no_execution_or_gate_authority(self):
        result = self.bind()
        self.assertEqual(result["schema"], "ux-scenario-binding/0")
        self.assertIs(result["gate_eligible"], False)
        self.assertEqual(result["authority"], "advisory")
        self.assertEqual(result["execution"], "not_run")
        self.assertEqual(result["journey_ids"], ["keep-draft"])
        self.assertEqual(result["pack_sha256"], self.common.digest(pack()))

    def test_does_not_modify_input(self):
        original = pack()
        before = copy.deepcopy(original)
        self.bind(original)
        self.assertEqual(original, before)

    def test_key_order_does_not_change_identity_but_step_order_does(self):
        document = pack()
        result = self.bind(document)
        self.assertEqual(result, self.bind(dict(reversed(list(document.items())))))
        second = copy.deepcopy(document["journeys"][0]["steps"][0])
        second["id"] = "save"
        document["journeys"][0]["steps"].append(second)
        forward = self.bind(document)
        document["journeys"][0]["steps"].reverse()
        self.assertNotEqual(forward["pack_sha256"], self.bind(document)["pack_sha256"])

    def test_subject_mismatch_or_unknown_fixture_refused(self):
        for overrides in ({"expected_repository": "other/product"},
                          {"expected_revision": "2" * 40}, {"allowed_fixtures": []},
                          {"allowed_fixtures": ["different"]},
                          {"allowed_fixtures": FIXTURE}):
            with self.subTest(overrides=overrides), self.assertRaises(self.common.ContractError):
                self.bind(**overrides)

    def test_false_booleans_cannot_be_spelled_as_numbers(self):
        for key, value in (("gate_eligible", 0), ("local_only", 1),
                           ("gate_eligible", True), ("local_only", False)):
            document = pack()
            document[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(self.common.ContractError):
                self.bind(document)

    def test_duplicate_journey_and_step_ids_refused(self):
        for level in ("journeys", "steps"):
            document = pack()
            target = document["journeys"] if level == "journeys" else document["journeys"][0]["steps"]
            target.append(copy.deepcopy(target[0]))
            with self.subTest(level=level), self.assertRaises(self.common.ContractError):
                self.bind(document)

    def test_unknown_keys_at_every_object_level_refused(self):
        selectors = (lambda p: p, lambda p: p["subject"], lambda p: p["journeys"][0],
                     lambda p: p["journeys"][0]["steps"][0], lambda p: p["journeys"][0]["budget"])
        for select in selectors:
            document = pack()
            select(document)["execute"] = "must never run"
            with self.subTest(select=select), self.assertRaises(self.common.ContractError):
                self.bind(document)

    def test_bad_budget_types_and_bounds_refused(self):
        for key, values in {
            "max_actions": [True, 1.0, 0, 101], "max_seconds": [False, -1, 1801],
            "max_judge_calls": [-1, 6], "max_retries": [-1, 3]}.items():
            for value in values:
                document = pack()
                document["journeys"][0]["budget"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(self.common.ContractError):
                    self.bind(document)

    def test_empty_lists_unknown_values_and_duplicates_refused(self):
        cases = [("preconditions", []), ("rubric_dimensions", ["beauty"]),
                 ("rubric_dimensions", ["feel", "feel"]), ("steps", [])]
        for key, value in cases:
            document = pack()
            document["journeys"][0][key] = value
            with self.subTest(key=key), self.assertRaises(self.common.ContractError):
                self.bind(document)
        for key, value in (("assertions", []), ("evidence_required", []),
                           ("evidence_required", ["invented"]), ("action", "   ")):
            document = pack()
            document["journeys"][0]["steps"][0][key] = value
            with self.subTest(key=key), self.assertRaises(self.common.ContractError):
                self.bind(document)

    def test_invalid_revision_and_ids_refused(self):
        for value in ("x" * 40, "a" * 39, "A" * 40, "a" * 40 + "\n"):
            document = pack()
            document["subject"]["source_revision"] = value
            with self.subTest(value=value), self.assertRaises(self.common.ContractError):
                self.bind(document)
        for value in ("../escape", "two words", "ok\n", "a" * 81):
            document = pack()
            document["pack_id"] = value
            with self.subTest(value=value), self.assertRaises(self.common.ContractError):
                self.bind(document)

    def test_json_reader_refuses_duplicate_nonfinite_depth_and_size(self):
        bad = [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}',
               b'[' * 80 + b'0' + b']' * 80, b' ' * (self.common.MAX_JSON_BYTES + 1),
               b'{"x":"\\ud800"}', b'\xff']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            for raw in bad:
                path.write_bytes(raw)
                with self.subTest(raw=raw[:30]), self.assertRaises(self.common.ContractError):
                    self.common.load_json(path)

    def test_cli_binding_and_content_free_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.json"
            path.write_text(json.dumps(pack()), encoding="utf-8")
            args = [sys.executable, "-m", "ux_evaluation", "bind", "--pack", str(path),
                    "--expected-repository", REPOSITORY, "--expected-revision", REVISION,
                    "--fixture-ref", FIXTURE]
            done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(done.stdout), self.bind())
            path.write_text('{"PRIVATE_SENTINEL": NaN}', encoding="utf-8")
            done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(done.returncode, 2)
            self.assertEqual(done.stdout, "")
            self.assertNotIn("PRIVATE_SENTINEL", done.stderr)
            self.assertNotIn(str(path), done.stderr)


if __name__ == "__main__":
    unittest.main()
