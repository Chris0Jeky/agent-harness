#!/usr/bin/env python3
"""Turn gate results into a candidate's next promotion record.

The generator proposes; the fold decides. Given a candidate, its promotion
records so far and the gate results of the stay it is in (raw
``promotion-record/v1`` gate results or ``eval-run/v1`` reports carrying one),
it names the next legal state along the class's path and writes the record
that moves there. Before returning it folds the chain with that record
appended; anything the fold refuses is refused here too, so a generated
record is never one the store would reject.

Scope, by design:

- every generated move is shadow; turning a candidate live is the owner's;
- any failed gate moves the candidate to ``rejected``; reverts, reinforcement,
  supersession and decay need blame or judgment, so they are never generated;
- the id is derived from the move (candidate, prev, target, gates), so a
  retried generation is byte-identical and the fold counts it once.
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

# Gates judged outside the evaluating stay; everything else required is an
# evaluation gate the candidate must pass before it leaves evaluating.
STAY_GATES = {"canary": "canary", "maturity": "probation"}


class PromotionRefusal(Exception):
    """No legal next record can be generated from these inputs (exit 2)."""


def gate_results(items):
    """Gate results from raw gate objects or eval-run/v1 reports, validated."""
    schema = contracts._document("promotion-record.schema.json")["$defs"]["gate_result"]
    gates = []
    for item in items:
        if isinstance(item, dict) and item.get("schema") == "eval-run/v1":
            problems = contracts.validate_record(item)
            if problems:
                raise PromotionRefusal(f"eval run {item.get('id')}: {problems[0]}")
            if item["gate"] is None:
                raise PromotionRefusal(
                    f"eval run {item['id']} emitted no gate ({item['verdict']})"
                )
            item = item["gate"]
        problems = contracts._schema_errors(
            item, schema, "promotion-record.schema.json", ""
        )
        if problems:
            raise PromotionRefusal(f"gate result: {problems[0]}")
        gates.append(item)
    return gates


def _evaluation_gates(candidate):
    return [
        g
        for g in contracts.required_gates(candidate)
        if g not in STAY_GATES and g != "owner"
    ]


def target_state(candidate, state, gates):
    """The next state along the class's path, or a refusal naming what is missing."""
    names = {g["gate"] for g in gates}
    if any(g["result"] == "fail" for g in gates):
        if state in ("evaluating", "canary", "probation"):
            return "rejected"
        raise PromotionRefusal(
            f"a failed gate leaving {state} needs a steward's decision"
        )
    required = contracts.required_gates(candidate)
    if state == "candidate":
        return "active" if not required else "evaluating"
    if state == "evaluating":
        missing = [g for g in _evaluation_gates(candidate) if g not in names]
        if missing:
            raise PromotionRefusal(f"evaluating still awaits {', '.join(missing)}")
        return "canary" if "canary" in required else "probation"
    if state == "canary":
        if "canary" not in names:
            raise PromotionRefusal("canary still awaits its canary result")
        return "probation"
    if state == "probation":
        missing = [g for g in ("maturity", "owner") if g in required and g not in names]
        if "maturity" not in missing and "owner" in missing:
            # The owner's own pass may have landed earlier in the chain; the
            # fold decides whether it still counts.
            missing.remove("owner")
        if missing:
            raise PromotionRefusal(f"probation still awaits {', '.join(missing)}")
        return "active"
    raise PromotionRefusal(
        f"{state} moves only by a steward's decision (reinforce, supersede, decay or revert)"
    )


def next_record(candidate, records, gates, producer, at, reason=None):
    """The next promotion-record/v1 for this candidate, already proven to fold."""
    current = contracts.fold(candidate, records)
    if current.errors:
        raise PromotionRefusal(f"the chain does not fold cleanly: {current.errors[0]}")
    target = target_state(candidate, current.state, gates)
    prev = current.chain[-1] if current.chain else None
    basis = json.dumps(
        [
            candidate["id"],
            prev,
            target,
            sorted(json.dumps(g, sort_keys=True) for g in gates),
        ]
    )
    record = {
        "schema": "promotion-record/v1",
        "id": "prom_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16],
        "at": at,
        "producer": producer,
        "candidate": candidate["id"],
        "prev": prev,
        "from": current.state,
        "to": target,
        "promotion_class": candidate["promotion_class"],
        "effect": "shadow",
        "gates": list(gates),
        "reason": reason or _reason(current.state, target, gates),
    }
    if candidate.get("genome"):
        record["genome"] = candidate["genome"]
    after = contracts.fold(candidate, list(records) + [record])
    if after.errors or after.state != target:
        problem = after.errors[0] if after.errors else f"folded to {after.state}"
        raise PromotionRefusal(f"the fold refuses the move to {target}: {problem}")
    return record


def _reason(state, target, gates):
    passed = ", ".join(sorted(g["gate"] for g in gates if g["result"] == "pass"))
    failed = ", ".join(sorted(g["gate"] for g in gates if g["result"] == "fail"))
    if failed:
        return f"{failed} failed while {state}"[:280]
    return (f"{state} -> {target}" + (f" on {passed}" if passed else ""))[:280]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--records", type=Path, help="the candidate's promotion records"
    )
    parser.add_argument(
        "--gates",
        type=Path,
        nargs="*",
        default=(),
        help="gate results or eval-run/v1 reports",
    )
    parser.add_argument("--lane", required=True, help="producer lane of the new record")
    parser.add_argument("--session", required=True, help="producer session")
    parser.add_argument("--at", help="record timestamp (default: now)")
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    try:
        candidates = contracts.read_records(args.candidate)
        if len(candidates) != 1:
            raise PromotionRefusal("expected exactly one candidate")
        records = contracts.read_records(args.records) if args.records else []
        gates = gate_results(
            [g for path in args.gates for g in contracts.read_records(path)]
        )
        at = args.at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if contracts.parse_time(at) is None:
            raise PromotionRefusal(f"--at is not a contract timestamp: {at}")
        producer = {
            "lane": args.lane,
            "runtime": "tool",
            "model": None,
            "session": args.session,
        }
        record = next_record(candidates[0], records, gates, producer, at, args.reason)
    except (
        PromotionRefusal,
        contracts.ContractError,
        OSError,
        ValueError,
        RecursionError,
    ) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
