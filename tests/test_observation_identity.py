"""Synthetic identity controls, not native telemetry qualification."""

from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "observation_identity.py"
SPEC = importlib.util.spec_from_file_location("observation_identity", SCRIPT)
assert SPEC and SPEC.loader
oi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oi)
A = "agent_harness."


def event(record_id="event:7", instance="origin-a", namespace="synthetic"):
    return {
        "record_kind": "event",
        "name": "agent_harness.request.attempt",
        "time": "2026-09-23T00:00:00Z",
        "attributes": {
            A + "schema.version": "0",
            A + "content.capture": "off",
            A + "normalization.profile": "synthetic-v0",
            A + "source.name": "synthetic",
            A + "source.namespace": namespace,
            A + "source.instance.id": instance,
            A + "source.record.id": record_id,
            A + "source.record.identity": "producer_record",
            A + "outcome": "failure",
            "gen_ai.tool.call.id": "same-call",
        },
    }


def span(span_id="1" * 16):
    return {
        "record_kind": "span",
        "name": "execute_tool test",
        "trace_id": "a" * 32,
        "span_id": span_id,
        "parent_span_id": None,
        "span_kind": "INTERNAL",
        "start_time": "2026-09-23T00:00:00Z",
        "end_time": "2026-09-23T00:00:01Z",
        "duration_ms": 1000,
        "status": "UNSET",
        "attributes": {
            A + "schema.version": "0",
            A + "content.capture": "off",
            A + "normalization.profile": "synthetic-v0",
            A + "source.name": "synthetic",
            A + "source.namespace": "synthetic",
            A + "source.record.identity": "native_span",
            "gen_ai.tool.call.id": "same-call",
        },
    }


class IdentityTests(unittest.TestCase):
    def report(self, records):
        result = oi.inspect_records(records)
        self.assertIs(result["execution_verified"], False)
        self.assertIs(result["gate_eligible"], False)
        self.assertIsNone(result["merge_verdict"])
        self.assertEqual(result["capture_completeness"], "unknown")
        self.assertEqual(
            result["received_records"],
            result["consistent_records"]
            + result["duplicate_records"]
            + result["conflicting_records"]
            + result["unavailable_identity_records"],
        )
        return result

    def test_reimport_deduplicates_only_one_source_record(self):
        for original in (event(), span()):
            with self.subTest(kind=original["record_kind"]):
                result = self.report([original, copy.deepcopy(original)])
                self.assertEqual(result["consistent_records"], 1)
                self.assertEqual(result["duplicate_records"], 1)
                self.assertEqual(result["deduplicated_records"], 1)
                self.assertEqual(result["identity_state"], "consistent")

    def test_real_retry_with_the_same_call_id_stays_distinct(self):
        for pair in ([span(), span("2" * 16)], [event(), event("event:8")]):
            result = self.report(pair)
            self.assertEqual(result["consistent_records"], 2)
            self.assertEqual(result["duplicate_records"], 0)

    def test_source_instance_restart_and_namespace_separate_events(self):
        result = self.report([event(), event(instance="origin-b"), event(namespace="other")])
        self.assertEqual(result["distinct_keys"], 3)

    def test_namespace_and_source_name_separate_colliding_spans(self):
        records = [span(), span(), span()]
        records[1]["attributes"][A + "source.namespace"] = "other"
        records[2]["attributes"][A + "source.name"] = "other"
        self.assertEqual(self.report(records)["distinct_keys"], 3)

    def test_tuple_boundaries_cannot_alias_through_delimiters(self):
        first, second = event(), event()
        first["attributes"][A + "source.name"] = "one:two"
        first["attributes"][A + "source.namespace"] = "three"
        second["attributes"][A + "source.name"] = "one"
        second["attributes"][A + "source.namespace"] = "two:three"
        self.assertEqual(self.report([first, second])["distinct_keys"], 2)

    def test_events_on_the_same_span_and_time_keep_event_identity(self):
        records = [event(), event("event:8")]
        for record in records:
            record.update(trace_id="a" * 32, span_id="1" * 16)
        self.assertEqual(self.report(records)["consistent_records"], 2)

    def test_conflict_excludes_the_whole_group_in_every_order(self):
        fail, success = event(), event()
        success["attributes"][A + "outcome"] = "success"
        for records in itertools.permutations([fail, success, copy.deepcopy(fail), event("event:8")]):
            result = self.report(records)
            self.assertEqual(result["conflicting_keys"], 1)
            self.assertEqual(result["conflicting_records"], 3)
            self.assertEqual(result["consistent_records"], 1)
            self.assertEqual(result["duplicate_records"], 0)
            self.assertIsNone(result["deduplicated_records"])
            self.assertEqual(result["identity_state"], "conflicting")

    def test_missing_fields_and_changed_usage_version_status_are_conflicts(self):
        variants = [span() for _ in range(5)]
        variants[0].pop("parent_span_id")
        variants[1]["attributes"]["gen_ai.usage.input_tokens"] = 0
        variants[2]["attributes"][A + "source.version"] = "1.0"
        variants[3]["status"] = "ERROR"
        variants[4]["duration_ms"] = 1000.0
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertEqual(self.report([span(), changed])["conflicting_keys"], 1)

    def test_object_key_order_is_not_a_conflict(self):
        first = event()
        second = dict(reversed(list(first.items())))
        second["attributes"] = dict(reversed(list(first["attributes"].items())))
        self.assertEqual(self.report([first, second])["duplicate_records"], 1)

    def test_missing_or_explicit_unavailable_identity_does_not_collapse(self):
        for field in ("source.record.identity", "source.namespace", "source.instance.id", "source.record.id"):
            item = event()
            del item["attributes"][A + field]
            result = self.report([item, copy.deepcopy(item)])
            self.assertEqual(result["unavailable_identity_records"], 2)
            self.assertIsNone(result["deduplicated_records"])
        item = span()
        item["attributes"][A + "source.record.identity"] = "unavailable"
        self.assertEqual(self.report([item])["unavailable_identity_records"], 1)

    def test_instance_metadata_does_not_create_a_second_native_span_key(self):
        first, second = span(), span()
        first["attributes"][A + "source.instance.id"] = "one"
        second["attributes"][A + "source.instance.id"] = "two"
        self.assertEqual(self.report([first, second])["conflicting_keys"], 1)

    def test_profile_changes_conflict_without_changing_source_key(self):
        first, second = event(), event()
        second["attributes"][A + "normalization.profile"] = "synthetic-v1"
        result = self.report([first, second])
        self.assertEqual(result["distinct_keys"], 1)
        self.assertEqual(result["conflicting_records"], 2)
        self.assertIsNone(result["deduplicated_records"])

    def test_missing_profile_is_not_invented_by_the_reader(self):
        item = event()
        del item["attributes"][A + "normalization.profile"]
        result = self.report([item, copy.deepcopy(item)])
        self.assertEqual(result["unavailable_identity_records"], 2)
        self.assertIsNone(result["deduplicated_records"])

    def test_empty_capture_is_not_complete_or_zero_work(self):
        result = self.report([])
        self.assertEqual(result["identity_state"], "empty")
        self.assertEqual(result["received_records"], 0)
        self.assertIsNone(result["deduplicated_records"])

    def test_unavailable_claim_for_a_present_field_is_rejected(self):
        item = event()
        item["attributes"][A + "unavailable"] = {A + "source.instance.id": "not_observed"}
        with self.assertRaises(oi.InputError):
            oi.inspect_records([item])

    def test_gap_reasons_remain_part_of_the_compared_representation(self):
        first, second = event(), event()
        first["attributes"][A + "unavailable"] = {"gen_ai.usage.input_tokens": "not_exposed"}
        second["attributes"][A + "unavailable"] = {"gen_ai.usage.input_tokens": "incomplete"}
        self.assertEqual(self.report([first, second])["conflicting_keys"], 1)

    def test_wrong_identity_mode_does_not_invent_event_span_equivalence(self):
        for item, mode in ((event(), "native_span"), (span(), "producer_record")):
            item["attributes"][A + "source.record.identity"] = mode
            with self.assertRaises(oi.InputError):
                oi.inspect_records([item])

    def test_input_not_mutated_and_output_never_copies_source_values(self):
        item = event()
        item["attributes"][A + "source.namespace"] = "PRIVATE_SENTINEL"
        original = copy.deepcopy(item)
        result = self.report([item])
        self.assertEqual(item, original)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))
        for forbidden in ("cost", "tokens", "tools", "jobs", "source_key", "trace_id"):
            self.assertNotIn(forbidden, result)


    def test_synthetic_fixture_has_the_documented_partition(self):
        path = ROOT / "docs/observability/examples/identity.synthetic.jsonl"
        result = self.report(oi.read_records(path))
        for field, expected in {
            "received_records": 8, "distinct_keys": 4,
            "consistent_records": 3, "duplicate_records": 1,
            "conflicting_keys": 1, "conflicting_records": 3,
            "unavailable_identity_records": 1,
        }.items():
            self.assertEqual(result[field], expected, field)
        self.assertIsNone(result["deduplicated_records"])
        self.assertEqual(result, self.report(reversed(oi.read_records(path))))

    def test_interrupted_event_and_error_span_are_not_success_verdicts(self):
        partial = event()
        partial["attributes"][A + "outcome"] = "unknown"
        partial["attributes"][A + "unavailable"] = {
            "gen_ai.usage.input_tokens": "incomplete"
        }
        failed = span()
        failed["status"] = "ERROR"
        result = self.report([partial, failed])
        self.assertEqual(result["deduplicated_records"], 2)
        self.assertNotIn("success", result)


class InputTests(unittest.TestCase):
    def rejects(self, item):
        with self.assertRaises(oi.InputError):
            oi.inspect_records([item])

    def test_unknown_fields_and_raw_content_are_rejected_not_stripped(self):
        for location, field in (("top", "body"), ("attributes", "prompt"), ("attributes", A + "cost.amount")):
            item = event()
            target = item if location == "top" else item[location]
            target[field] = "PRIVATE_SENTINEL"
            self.rejects(item)

    def test_strict_types_ranges_and_supported_version(self):
        for field, bad_values in {
            A + "schema.version": [0, True, "1", None],
            A + "content.capture": ["redacted", True, None],
            A + "source.record.id": [7, "", "a/b", "a\\b", "x" * 129, "\u00e9", None],
            A + "source.record.identity": ["guess", None, [], False],
            "gen_ai.usage.input_tokens": [-1, True, 1.0, float("nan"), 2**63],
            A + "request.attempt_count": [0, -1, True, 1.0],
            A + "outcome": ["PASS", True, {}, None],
        }.items():
            for value in bad_values:
                item = event()
                item["attributes"][field] = value
                with self.subTest(field=field, value=value):
                    self.rejects(item)

    def test_invalid_and_zero_trace_ids_and_partial_context_rejected(self):
        for field, values in {"trace_id": ["0" * 32, "a" * 31, "A" * 32, None], "span_id": ["0" * 16, "a" * 17, 4]}.items():
            for value in values:
                item = span()
                item[field] = value
                self.rejects(item)
        item = event()
        item["span_id"] = "1" * 16
        self.rejects(item)

    def test_event_and_span_shapes_and_timestamps(self):
        for value in ([], None, {}, {"record_kind": "event"}):
            self.rejects(value)
        for timestamp in ("2026-02-30T00:00:00Z", "2026-09-23", "2026-09-23T00:00:00+01:00", "2026-09-23T00:00:60Z"):
            item = event()
            item["time"] = timestamp
            self.rejects(item)
        item = event()
        item["duration_ms"] = 2
        self.rejects(item)
        for value in (True, -1, float("inf")):
            item = span()
            item["duration_ms"] = value
            self.rejects(item)
        item = span()
        del item["end_time"]
        self.rejects(item)

    def test_limits_for_direct_callers(self):
        with mock.patch.object(oi, "MAX_RECORDS", 1):
            with self.assertRaises(oi.InputError):
                oi.inspect_records([event(), event()])
        with mock.patch.object(oi, "MAX_RECORD_BYTES", 8):
            self.rejects(event())
        with mock.patch.object(oi, "MAX_INPUT_BYTES", 8):
            self.rejects(event())

    def test_reader_strict_json_and_lf_boundaries(self):
        good = json.dumps(event()).encode()
        malformed = [
            good.replace(b'"record_kind": "event"', b'"record_kind": "event", "record_kind": "event"'),
            good.replace(b'"failure"', b'NaN'),
            good.replace(b'"failure"', b'Infinity'),
            good.replace(b'"failure"', b'1e999'),
            b'\xef\xbb\xbf' + good,
            b'\xff', b'\n', good + b'\n\n', good + b'\r' + good,
            b'[' * 1000 + b'0' + b']' * 1000,
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.jsonl"
            for payload in malformed:
                path.write_bytes(payload)
                with self.subTest(payload=payload[:40]), self.assertRaises(oi.InputError):
                    oi.inspect_records(oi.read_records(path))
            for payload in (good, good + b'\n', good + b'\r\n'):
                path.write_bytes(payload)
                self.assertEqual(oi.inspect_records(oi.read_records(path))["received_records"], 1)
            path.write_bytes(b"")
            self.assertEqual(oi.inspect_records(oi.read_records(path))["identity_state"], "empty")

    def test_reader_bounds_and_special_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.jsonl"
            path.write_text(json.dumps(event()), encoding="utf-8")
            with mock.patch.object(oi, "MAX_INPUT_BYTES", 8):
                with self.assertRaises(oi.InputError):
                    oi.read_records(path)
            with self.assertRaises(oi.InputError):
                oi.read_records(Path(tmp))
            with self.assertRaises(oi.InputError):
                oi.read_records(Path(tmp) / "absent")
            link = Path(tmp) / "alias"
            try:
                link.symlink_to(path)
            except OSError:
                pass
            else:
                with self.assertRaises(oi.InputError):
                    oi.read_records(link)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX special file control")
    def test_fifo_is_refused_without_hanging(self):
        with tempfile.TemporaryDirectory() as tmp:
            fifo = Path(tmp) / "fifo"
            os.mkfifo(fifo)
            result = subprocess.run([sys.executable, str(SCRIPT), str(fifo)], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)

    def test_cli_reports_conflicts_with_zero_exit_and_content_free_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "PRIVATE_PATH_SENTINEL.jsonl"
            first, second = event(), event()
            second["attributes"][A + "outcome"] = "success"
            payload = "\n".join(json.dumps(row) for row in (first, second)) + "\n"
            path.write_text(payload, encoding="utf-8")
            before = path.read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["conflicting_keys"], 1)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(tmp).iterdir()), [path])
            path.write_text('{"PRIVATE_PAYLOAD_SENTINEL":true}', encoding="utf-8")
            for args in ([str(path)], [str(path) + "-absent"], ["--PRIVATE_ARGUMENT_SENTINEL"]):
                result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("PRIVATE_", result.stderr)
                self.assertNotIn("Traceback", result.stderr)


    def test_unsupported_gap_targets_and_raw_span_names_are_refused(self):
        for target in ("prompt", "time", "attributes"):
            item = event()
            item["attributes"][A + "unavailable"] = {target: "not_observed"}
            self.rejects(item)
        for name in ("execute_tool cat .env", "execute_tool ../private", "PRIVATE"):
            item = span()
            item["name"] = name
            self.rejects(item)

    def test_numeric_and_utf8_corner_cases_fail_without_a_traceback(self):
        item = span()
        item["duration_ms"] = 0.0
        oi.inspect_records([item])
        item["attributes"]["gen_ai.usage.input_tokens"] = 2**63 - 1
        oi.inspect_records([item])
        for value in (None, "", "\ud800", "x" * 129):
            item = event()
            item["attributes"][A + "normalization.profile"] = value
            self.rejects(item)

    def test_changed_file_between_inspection_and_open_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.jsonl"
            path.write_text(json.dumps(event()), encoding="utf-8")
            real_open = os.open

            def mutate_then_open(*args):
                path.write_bytes(b"changed")
                return real_open(*args)

            with mock.patch.object(oi.os, "open", side_effect=mutate_then_open):
                with self.assertRaises(oi.InputError):
                    oi.read_records(path)

    def test_stable_file_passes_identity_on_repeated_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.jsonl"
            path.write_text(json.dumps(event()), encoding="utf-8")
            for _ in range(50):
                result = oi.inspect_records(oi.read_records(path))
                self.assertEqual(result["received_records"], 1)
                self.assertEqual(result["consistent_records"], 1)

    def test_windows_creation_skew_is_not_a_change_but_content_change_is(self):
        base = mock.Mock(
            st_dev=1,
            st_ino=2,
            st_mode=33188,
            st_size=10,
            st_mtime_ns=100,
            st_ctime_ns=200,
        )
        skewed = mock.Mock(
            st_dev=1,
            st_ino=2,
            st_mode=33188,
            st_size=10,
            st_mtime_ns=100,
            st_ctime_ns=1200000,
        )
        changed = mock.Mock(
            st_dev=1,
            st_ino=2,
            st_mode=33188,
            st_size=11,
            st_mtime_ns=100,
            st_ctime_ns=200,
        )
        with mock.patch.object(oi.os, "name", "nt"):
            self.assertTrue(oi._same_after_open(base, skewed))
            self.assertFalse(oi._same_after_open(base, changed))
        with mock.patch.object(oi.os, "name", "posix"):
            self.assertFalse(oi._same_after_open(base, skewed))
            self.assertFalse(oi._same_after_open(base, changed))

    def test_regular_hard_link_has_no_special_identity_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.jsonl"
            path.write_text(json.dumps(event()), encoding="utf-8")
            alias = Path(tmp) / "hardlink.jsonl"
            try:
                os.link(path, alias)
            except OSError:
                self.skipTest("hard links unavailable on this filesystem")
            result = oi.inspect_records(oi.read_records(alias))
            self.assertEqual(result["consistent_records"], 1)
            self.assertIs(result["execution_verified"], False)


if __name__ == "__main__":
    unittest.main()
