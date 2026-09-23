#!/usr/bin/env python3
"""Bounded advisory accounting of explicitly normalized logical-job observations.

This is an offline study projection, not a native receipt schema, scheduler,
observer, routing gate, or financial ledger. No receipt paths are opened.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

MAX_BYTES = 4 * 1024 * 1024
MAX_JOBS = 1000
MAX_ATTEMPTS = 5000
NUMBERS = (
    "cost",
    "queue_seconds",
    "execution_seconds",
    "verification_seconds",
    "review_seconds",
)
STATES = ("not_admitted", "pending", "blocked", "rejected", "accepted")
BUCKETS = (*STATES, "stale_acceptance", "unverified_acceptance", "contradicted_acceptance")
JOB_KEYS = {
    "job_id",
    "input_revision",
    "admitted",
    "disposition",
    "accepted_attempt",
    "attempts",
}
ATTEMPT_KEYS = {
    "attempt_id",
    "source_sha256",
    "verified_revision",
    "outcome_pass",
    "constraints_pass",
    *NUMBERS,
}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("non-finite JSON number")


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("unexpected observation fields")


def _matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _identity(value):
    if not _matches(value, r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"):
        raise ValueError("invalid observation identity")


def _revision(value):
    if not _matches(value, r"(?:[0-9a-f]{40}|[0-9a-f]{64})"):
        raise ValueError("revision must be a full lowercase object identity")


def _number(value):
    if value is None:
        return
    if type(value) not in (int, float):
        raise ValueError("observation must be a nonnegative number or null")
    try:
        valid = value >= 0 and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("observation must be a finite nonnegative number or null")


def _validate_attempt(row, ids, sources, currency):
    _keys(row, ATTEMPT_KEYS)
    _identity(row["attempt_id"])
    if row["attempt_id"] in ids:
        raise ValueError("duplicate attempt identity")
    ids.add(row["attempt_id"])
    digest = row["source_sha256"]
    if not _matches(digest, r"[0-9a-f]{64}") or digest in sources:
        raise ValueError("invalid or duplicate source receipt identity")
    sources.add(digest)
    if row["verified_revision"] is not None:
        _revision(row["verified_revision"])
    for key in ("outcome_pass", "constraints_pass"):
        if row[key] is not None and type(row[key]) is not bool:
            raise ValueError("acceptance observation must be boolean or null")
    for key in NUMBERS:
        _number(row[key])
    if currency is None and row["cost"] is not None:
        raise ValueError("observed cost requires an explicit currency")


def _acceptance_bucket(job):
    state = job["disposition"]
    chosen = job["accepted_attempt"]
    if state != "accepted":
        if chosen is not None:
            raise ValueError("only accepted jobs may select an accepted attempt")
        return state
    _identity(chosen)
    accepted = next((row for row in job["attempts"] if row["attempt_id"] == chosen), None)
    if accepted is None:
        raise ValueError("accepted attempt is absent from this job")
    if accepted["outcome_pass"] is False or accepted["constraints_pass"] is False:
        return "contradicted_acceptance"
    if accepted["verified_revision"] is None:
        return "unverified_acceptance"
    if accepted["verified_revision"] != job["input_revision"]:
        return "stale_acceptance"
    if accepted["outcome_pass"] is None or accepted["constraints_pass"] is None:
        return "unverified_acceptance"
    return "accepted"


def _statistics(rows, key, accepted):
    observed = [row[key] for row in rows if row[key] is not None]
    missing = len(rows) - len(observed)
    try:
        total = math.fsum(observed) if observed else None
    except OverflowError as exc:
        raise ValueError("observation aggregate exceeds the finite range") from exc
    if total is not None and not math.isfinite(total):
        raise ValueError("observation aggregate exceeds the finite range")
    complete = total if observed and missing == 0 else None
    return {
        "observed": len(observed),
        "missing": missing,
        "observed_sum": total,
        "complete_sum": complete,
        "per_accepted_job": complete / accepted if complete is not None and accepted else None,
    }


def summarize_bytes(raw: bytes) -> dict:
    """Validate a fixed observation cohort and return aggregate-only diagnostics.

    The normalization owner supplies source hashes and observations. This function
    checks internal consistency, not provenance or completeness of the real estate.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("cohort must be bounded bytes")
    try:
        data = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid cohort JSON") from exc
    _keys(data, {"schema", "currency", "jobs"})
    if data["schema"] != "agent-ops-cohort/1":
        raise ValueError("unsupported cohort schema")
    currency = data["currency"]
    if currency is not None and not _matches(currency, r"[A-Z]{3}"):
        raise ValueError("currency must be a three-letter code or null")
    jobs = data["jobs"]
    if not isinstance(jobs, list) or len(jobs) > MAX_JOBS:
        raise ValueError("jobs must be a bounded list")
    job_ids, attempt_ids, sources = set(), set(), set()
    counts = Counter({state: 0 for state in BUCKETS})
    rows = []
    admitted = 0
    for job in jobs:
        _keys(job, JOB_KEYS)
        _identity(job["job_id"])
        if job["job_id"] in job_ids:
            raise ValueError("duplicate job identity")
        job_ids.add(job["job_id"])
        _revision(job["input_revision"])
        if type(job["admitted"]) is not bool or job["disposition"] not in STATES:
            raise ValueError("invalid admission or disposition")
        attempts = job["attempts"]
        if not isinstance(attempts, list) or len(rows) + len(attempts) > MAX_ATTEMPTS:
            raise ValueError("attempts must be a bounded list")
        if not job["admitted"]:
            if job["disposition"] != "not_admitted" or attempts:
                raise ValueError("nonadmitted jobs cannot contain execution")
        elif job["disposition"] == "not_admitted":
            raise ValueError("admission and disposition disagree")
        admitted += int(job["admitted"])
        for row in attempts:
            _validate_attempt(row, attempt_ids, sources, currency)
        rows.extend(attempts)
        counts[_acceptance_bucket(job)] += 1
    result = {
        "schema": "agent-ops-cohort-summary/1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "authority": "none",
        "gate_eligible": False,
        "observer_authenticated": False,
        "currency": currency,
        "candidates": len(jobs),
        "admitted": admitted,
        "attempts": len(rows),
        "jobs": dict(counts),
        "accepted_per_admitted": counts["accepted"] / admitted if admitted else None,
        "limitations": [
            "externally_normalized_observations",
            "receipt_hashes_are_not_fetched_or_authenticated",
            "unknown_attempts_outside_the_cohort_are_not_measured",
            "not_a_model_ranking_or_financial_ledger",
            "acceptance_is_consistency_checked_not_independently_verified",
        ],
    }
    for key in NUMBERS:
        result[key] = _statistics(rows, key, counts["accepted"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort", type=Path)
    args = parser.parse_args(argv)
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(args.cohort, flags)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
                raise ValueError("cohort must be a bounded regular file")
            raw = source.read(MAX_BYTES + 1)
        result = summarize_bytes(raw)
    except (OSError, ValueError):
        print(
            "ops-cohort: invalid, unsupported or unavailable observations", file=sys.stderr
        )
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
