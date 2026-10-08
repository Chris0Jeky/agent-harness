#!/usr/bin/env python3
"""System evaluation: candidate-arm runs against baseline-arm runs.

During a canary the estate runs some work under the candidate and the rest
under the baseline, and every run lands in the experience ledger with its
``variant``. This module compares the two arms on the system metrics the
estate already trusts (success, seven-day maturity, reverts, regressions,
triage verdicts, owner corrections, cost) and writes a ``system-run/v1``
report whose gate is the candidate's ``canary`` result. The candidate's own
training evidence is left out of both arms.

It is a non-regression gate, not a proof of improvement: the candidate passes
when each arm has enough runs and it is no worse than the baseline beyond the
policy's tolerances on success, reverts and owner corrections.
"""

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

_SPEC = importlib.util.spec_from_file_location(
    "learning_contracts", Path(__file__).resolve().with_name("learning_contracts.py")
)
contracts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(contracts)

TOOL = "agent-harness:scripts/learning_system.py@1"
DEFAULT_POLICY = {
    "min_runs": 20,
    "max_success_drop": 0.0,
    "max_revert_rise": 0.0,
    "max_correction_rise": 0.0,
}


class SystemRefusal(Exception):
    """The comparison cannot be made honestly (exit 2)."""


def _rate(hits, total):
    return hits / total if total else None


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def arm(runs):
    """The system metrics of one arm."""
    matured = [r for r in runs if r["outcome"]["matured"] is not None]
    regression = [r for r in runs if r["outcome"]["regression"] is not None]
    signals = [
        f["signal"]
        for r in runs
        for f in r.get("feedback", ())
        if f["kind"] == "triage_verdict"
    ]
    confirmed, refuted = signals.count("confirmed"), signals.count("refuted")
    corrected = [
        r
        for r in runs
        if any(f["kind"] == "owner_correction" for f in r.get("feedback", ()))
    ]
    costs = [r.get("cost") or {} for r in runs]
    return {
        "runs": len(runs),
        "success_rate": _rate(
            sum(map(contracts.experience_succeeded, runs)), len(runs)
        ),
        "matured": len(matured),
        "clean_rate": _rate(
            sum(r["outcome"]["matured"] == "clean" for r in matured), len(matured)
        ),
        "revert_rate": _rate(
            sum(r["outcome"]["matured"] == "reverted" for r in matured), len(matured)
        ),
        "regression_rate": _rate(
            sum(r["outcome"]["regression"] for r in regression), len(regression)
        ),
        "confirmed": confirmed,
        "refuted": refuted,
        "precision": _rate(confirmed, confirmed + refuted),
        "correction_rate": _rate(len(corrected), len(runs)),
        "tokens_mean": _mean(
            (
                (c.get("tokens") or {}).get("input", 0)
                + (c.get("tokens") or {}).get("output", 0)
                if c.get("tokens")
                else None
            )
            for c in costs
        ),
        "seconds_mean": _mean(c.get("seconds") for c in costs),
    }


def _regressions(base, cand, policy):
    reasons = []
    pairs = (
        ("success_rate", -1, "max_success_drop", "success fell"),
        ("revert_rate", 1, "max_revert_rise", "reverts rose"),
        ("correction_rate", 1, "max_correction_rise", "owner corrections rose"),
    )
    for metric, sign, limit, words in pairs:
        if base[metric] is None or cand[metric] is None:
            continue
        change = (cand[metric] - base[metric]) * sign
        if change > policy[limit]:
            reasons.append(
                f"{words}: {base[metric]:.3f} -> {cand[metric]:.3f} (tolerance {policy[limit]})"
            )
    return reasons


def compare(
    experiences, candidate, baseline_variant, candidate_variant, policy=None, at=None
):
    """The system-run/v1 report for a candidate's canary."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    if policy["min_runs"] < 1 or any(
        policy[k] < 0
        for k in ("max_success_drop", "max_revert_rise", "max_correction_rise")
    ):
        raise SystemRefusal("min_runs is at least 1 and every tolerance at least 0")
    if baseline_variant == candidate_variant:
        raise SystemRefusal("the two arms must be different variants")
    by_id, errors = contracts.fold_experiences(experiences)
    if errors:
        raise SystemRefusal(f"experience ledger is inconsistent: {errors[0]}")
    training = set(candidate["evidence"])
    arms = {"baseline": [], "candidate": []}
    excluded = 0
    for record in by_id.values():
        side = {baseline_variant: "baseline", candidate_variant: "candidate"}.get(
            record.get("variant")
        )
        if side is None:
            continue
        if record["id"] in training:
            excluded += 1
            continue
        arms[side].append(record)
    stats = {side: arm(runs) for side, runs in arms.items()}
    short = [s for s in stats if stats[s]["runs"] < policy["min_runs"]]
    if short:
        verdict = "insufficient"
        reasons = [
            f"{s} arm has {stats[s]['runs']} runs, needs {policy['min_runs']}"
            for s in short
        ]
    else:
        reasons = _regressions(stats["baseline"], stats["candidate"], policy)
        verdict = "fail" if reasons else "pass"
    at = at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    basis = json.dumps(
        [
            candidate["id"],
            baseline_variant,
            candidate_variant,
            policy,
            sorted(r["id"] + r["observed_at"] for runs in arms.values() for r in runs),
        ],
        sort_keys=True,
    )
    run_id = "sys_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    evaluator = {"kind": "oracle", "runtime": "tool", "model": None, "session": run_id}
    report = {
        "schema": "system-run/v1",
        "id": run_id,
        "at": at,
        "producer": {
            "lane": "agent-harness",
            "runtime": "tool",
            "model": TOOL,
            "session": run_id,
        },
        "candidate": candidate["id"],
        "baseline_variant": baseline_variant,
        "candidate_variant": candidate_variant,
        "excluded_training": excluded,
        "arms": stats,
        "policy": policy,
        "verdict": verdict,
        "reasons": reasons,
        "gate": None,
    }
    if verdict != "insufficient":
        base, cand = stats["baseline"], stats["candidate"]
        report["gate"] = {
            "gate": "canary",
            "result": verdict,
            "evaluator": evaluator,
            "at": at,
            "ref": f"system-run:{run_id}",
            "summary": (
                f"{cand['runs']} candidate vs {base['runs']} baseline runs: "
                + ("; ".join(reasons) if reasons else "no regression beyond tolerance")
            )[:280],
            "metrics": {
                key: value
                for side, values in (("baseline", base), ("candidate", cand))
                for key, value in (
                    (f"{side}_runs", values["runs"]),
                    (f"{side}_success_rate", values["success_rate"]),
                    (f"{side}_revert_rate", values["revert_rate"]),
                )
                if value is not None
            },
        }
    problems = contracts.validate_record(report)
    if problems:
        raise SystemRefusal(f"internal: the report breaks system-run/v1: {problems[0]}")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--experiences", type=Path, nargs="+", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-variant", required=True)
    parser.add_argument("--candidate-variant", required=True)
    parser.add_argument("--min-runs", type=int, default=DEFAULT_POLICY["min_runs"])
    parser.add_argument("--at", help="report timestamp (default: now)")
    args = parser.parse_args(argv)
    try:
        experiences = [
            r for path in args.experiences for r in contracts.read_records(path)
        ]
        candidates = contracts.read_records(args.candidate)
        if len(candidates) != 1 or contracts.validate_record(candidates[0]):
            raise SystemRefusal("expected exactly one valid learning candidate")
        if args.at and contracts.parse_time(args.at) is None:
            raise SystemRefusal(f"--at is not a contract timestamp: {args.at}")
        report = compare(
            experiences,
            candidates[0],
            args.baseline_variant,
            args.candidate_variant,
            {"min_runs": args.min_runs},
            args.at,
        )
    except (
        SystemRefusal,
        contracts.ContractError,
        OSError,
        ValueError,
        RecursionError,
    ) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return {"pass": 0, "fail": 1}.get(report["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
