"""Synthetic logical-job accounting, independent of models and live observers."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "ops_cohort.py"
if MODULE.exists():
    spec = importlib.util.spec_from_file_location("ops_cohort", MODULE)
    ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
else:
    ops = None


REVISION = "a" * 40


def attempt(number=1, **changes):
    result = {
        "attempt_id": f"attempt-{number}",
        "source_sha256": f"{number:064x}",
        "verified_revision": REVISION,
        "outcome_pass": True,
        "constraints_pass": True,
        "cost": 2,
        "queue_seconds": 3,
        "execution_seconds": 4,
        "verification_seconds": 5,
        "review_seconds": 6,
    }
    result.update(changes)
    return result


def job(number=1, **changes):
    result = {
        "job_id": f"job-{number}",
        "input_revision": REVISION,
        "admitted": True,
        "disposition": "accepted",
        "accepted_attempt": f"attempt-{number}",
        "attempts": [attempt(number)],
    }
    result.update(changes)
    return result


def cohort(*jobs, **changes):
    result = {"schema": "agent-ops-cohort/1", "currency": "USD", "jobs": list(jobs)}
    result.update(changes)
    return result


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ops, "logical-job accounting has not been implemented")

    def summarize(self, data):
        return ops.summarize_bytes(json.dumps(data).encode())

    def test_two_attempts_are_one_accepted_job_and_both_costs_count(self):
        data = cohort(job(attempts=[attempt(2, outcome_pass=False), attempt(1)]))
        before = copy.deepcopy(data)
        out = self.summarize(data)
        self.assertEqual(out["jobs"]["accepted"], 1)
        self.assertEqual(out["attempts"], 2)
        self.assertEqual(out["cost"]["complete_sum"], 4)
        self.assertEqual(out["cost"]["per_accepted_job"], 4)
        self.assertEqual(data, before)

    def test_rejected_pending_blocked_and_not_admitted_stay_visible(self):
        jobs = [job()]
        for number, state in enumerate(("rejected", "pending", "blocked"), 2):
            jobs.append(job(number, disposition=state, accepted_attempt=None, attempts=[]))
        jobs.append(job(5, admitted=False, disposition="not_admitted", accepted_attempt=None, attempts=[]))
        out = self.summarize(cohort(*jobs))
        self.assertEqual(out["candidates"], 5)
        self.assertEqual(out["admitted"], 4)
        self.assertEqual(out["accepted_per_admitted"], 0.25)
        for key in ("rejected", "pending", "blocked", "not_admitted"):
            self.assertEqual(out["jobs"][key], 1)

    def test_missing_cost_never_becomes_complete_or_zero(self):
        out = self.summarize(cohort(job(attempts=[attempt(2, cost=None), attempt(1)])))
        self.assertEqual(out["cost"]["observed_sum"], 2)
        self.assertEqual(out["cost"]["missing"], 1)
        self.assertIsNone(out["cost"]["complete_sum"])
        self.assertIsNone(out["cost"]["per_accepted_job"])

    def test_rejected_attempt_cost_is_not_dropped(self):
        out = self.summarize(cohort(job(), job(2, disposition="rejected", accepted_attempt=None)))
        self.assertEqual(out["cost"]["per_accepted_job"], 4)
        self.assertEqual(out["review_seconds"]["per_accepted_job"], 12)

    def test_zero_cost_is_observed_and_unknown_currency_does_not_imply_usd(self):
        out = self.summarize(cohort(job(attempts=[attempt(cost=0)])))
        self.assertEqual(out["cost"]["complete_sum"], 0)
        self.assertEqual(out["cost"]["observed"], 1)
        out = self.summarize(cohort(job(attempts=[attempt(cost=None)]), currency=None))
        self.assertIsNone(out["currency"])
        self.assertIsNone(out["cost"]["observed_sum"])
        with self.assertRaises(ValueError):
            self.summarize(cohort(job(), currency=None))

    def test_empty_and_no_accepted_cohorts_have_undefined_rates(self):
        for data in (cohort(), cohort(job(disposition="rejected", accepted_attempt=None))):
            out = self.summarize(data)
            self.assertIsNone(out["cost"]["per_accepted_job"])
        out = self.summarize(cohort())
        self.assertIsNone(out["accepted_per_admitted"])
        self.assertIsNone(out["cost"]["complete_sum"])

    def test_stale_acceptance_is_not_counted_as_current(self):
        out = self.summarize(cohort(job(attempts=[attempt(verified_revision="b" * 40)])))
        self.assertEqual(out["jobs"]["stale_acceptance"], 1)
        self.assertEqual(out["jobs"]["accepted"], 0)
        self.assertEqual(out["accepted_per_admitted"], 0)
        self.assertEqual(out["cost"]["complete_sum"], 2)

    def test_missing_and_contradicted_acceptance_have_distinct_buckets(self):
        for patch in ({"verified_revision": None}, {"constraints_pass": None}):
            out = self.summarize(cohort(job(attempts=[attempt(**patch)])))
            self.assertEqual(out["jobs"]["unverified_acceptance"], 1)
        out = self.summarize(cohort(job(attempts=[attempt(outcome_pass=False)])))
        self.assertEqual(out["jobs"]["contradicted_acceptance"], 1)

    def test_successful_attempt_does_not_promote_pending_job(self):
        out = self.summarize(cohort(job(disposition="pending", accepted_attempt=None)))
        self.assertEqual(out["jobs"]["pending"], 1)
        self.assertEqual(out["jobs"]["accepted"], 0)

    def test_duplicate_jobs_attempts_and_receipts_refuse(self):
        cases = [cohort(job(), job()),
                 cohort(job(), job(2, attempts=[attempt(1)])),
                 cohort(job(), job(2, attempts=[attempt(2, source_sha256="1".zfill(64))]))]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.summarize(data)

    def test_acceptance_reference_must_point_to_own_attempt(self):
        for data in (cohort(job(accepted_attempt="absent")),
                     cohort(job(accepted_attempt="attempt-2"), job(2)),
                     cohort(job(disposition="pending"))):
            with self.assertRaises(ValueError):
                self.summarize(data)

    def test_nonadmitted_jobs_cannot_have_attempts_or_accepted_state(self):
        for changes in ({"admitted": False},
                        {"admitted": False, "disposition": "not_admitted", "accepted_attempt": None}):
            with self.assertRaises(ValueError):
                self.summarize(cohort(job(**changes)))

    def test_all_observation_fields_are_required_and_nullable(self):
        for key in ("cost", "queue_seconds", "execution_seconds", "verification_seconds", "review_seconds",
                    "outcome_pass", "constraints_pass", "verified_revision"):
            row = attempt()
            del row[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.summarize(cohort(job(attempts=[row])))

    def test_numbers_types_and_aggregate_overflow_refuse(self):
        for value in (True, "2", -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.summarize(cohort(job(attempts=[attempt(cost=value)])))
        with self.assertRaises(ValueError):
            self.summarize(cohort(job(attempts=[attempt(1, cost=1e308), attempt(2, cost=1e308)])))

    def test_unknown_keys_ids_and_digests_refuse_without_echo(self):
        for data in (cohort(job(), secret="PRIVATE_SENTINEL"),
                     cohort(job(job_id="PRIVATE SENTINEL")),
                     cohort(job(attempts=[attempt(source_sha256="wrong")])),
                     cohort(job(input_revision="short")),
                     cohort(job(), currency="credits")):
            with self.assertRaises(ValueError) as caught:
                self.summarize(data)
            self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_duplicate_json_keys_and_payload_limits(self):
        for raw in (b'{"schema":1,"schema":2}', b' ' * (ops.MAX_BYTES + 1),
                    b'[' * 80 + b'0' + b']' * 80, b'\xff'):
            with self.assertRaises(ValueError):
                ops.summarize_bytes(raw)
        with self.assertRaises(ValueError):
            self.summarize(cohort(*[job() for _ in range(ops.MAX_JOBS + 1)]))

    def test_four_clocks_are_separate_and_missing_is_preserved(self):
        out = self.summarize(cohort(job(attempts=[attempt(queue_seconds=None)])))
        self.assertIsNone(out["queue_seconds"]["complete_sum"])
        self.assertEqual(out["execution_seconds"]["complete_sum"], 4)
        self.assertEqual(out["verification_seconds"]["complete_sum"], 5)
        self.assertEqual(out["review_seconds"]["complete_sum"], 6)

    def test_record_order_does_not_change_counts(self):
        data = cohort(job(), job(2, disposition="blocked", accepted_attempt=None))
        first = self.summarize(data)
        data["jobs"].reverse()
        second = self.summarize(data)
        first.pop("source_sha256")
        second.pop("source_sha256")
        self.assertEqual(first, second)

    def test_output_binds_source_but_does_not_publish_identifiers(self):
        data = cohort(job(job_id="PRIVATE_SENTINEL"))
        raw = json.dumps(data).encode()
        out = ops.summarize_bytes(raw)
        self.assertEqual(out["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(out))
        self.assertEqual(out["authority"], "none")
        self.assertIs(out["gate_eligible"], False)
        self.assertIs(out["observer_authenticated"], False)

    def test_real_cli_and_sanitized_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "observations.json"
            path.write_text(json.dumps(cohort(job())), encoding="utf-8")
            before = path.read_bytes()
            result = subprocess.run([sys.executable, str(MODULE), str(path)],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["jobs"]["accepted"], 1)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(temp).iterdir()), [path])
            path.write_text("PRIVATE_SENTINEL", encoding="utf-8")
            result = subprocess.run([sys.executable, str(MODULE), str(path)],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("PRIVATE_SENTINEL", result.stderr)


if __name__ == "__main__":
    unittest.main()
