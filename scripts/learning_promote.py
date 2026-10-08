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
- the id is derived from the move (candidate, prev, target, gates) and the
  gates are stored sorted, so a retry with the same time, producer and reason
  is byte-identical and the fold counts it once; pass ``--at`` to make a retry
  reproducible.
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


REPORTS = ("eval-run/v1", "system-run/v1")


def gate_results(items, candidate=None):
    """Gate results from raw gate objects or run reports, validated.

    A report (eval-run/v1, system-run/v1) must be about this candidate, and an
    eval run must have evaluated the genome the candidate names.
    """
    schema = contracts._document("promotion-record.schema.json")["$defs"]["gate_result"]
    gates = []
    for item in items:
        if isinstance(item, dict) and item.get("schema") in REPORTS:
            problems = contracts.validate_record(item)
            if problems:
                raise PromotionRefusal(f"report {item.get('id')}: {problems[0]}")
            if candidate is not None and item["candidate"] != candidate["id"]:
                raise PromotionRefusal(
                    f"report {item['id']} judged {item['candidate']}, not {candidate['id']}"
                )
            named = candidate.get("genome") if candidate else None
            if named and item.get("genome", named) != named:
                raise PromotionRefusal(
                    f"report {item['id']} evaluated {item.get('genome')}, not {named}"
                )
            if item["gate"] is None:
                raise PromotionRefusal(
                    f"report {item['id']} emitted no gate ({item['verdict']})"
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


def target_state(candidate, state, gates, resolve=None):
    """The next state along the class's path, or a refusal naming what is missing.

    Only a pass the fold would count moves the candidate forward: a gate judged
    by the learner, by itself or by nobody independent would strand it in
    probation, because an evaluation gate cannot be recorded again later.
    """
    names = {g["gate"] for g in gates if contracts._counts(g, candidate, resolve)}
    evaluation = _evaluation_gates(candidate)
    # Only the counted, required evaluation passes can vouch for independence.
    judged = [
        g
        for g in gates
        if g["gate"] in evaluation and contracts._counts(g, candidate, resolve)
    ]
    independent = contracts.classes()["evaluators"]["independent"]
    if any(g["result"] == "fail" for g in gates):
        if state in ("candidate", "evaluating", "canary", "probation"):
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
            raise PromotionRefusal(
                f"evaluating still awaits a counted pass of {', '.join(missing)}"
            )
        if judged and not any(g["evaluator"]["kind"] in independent for g in judged):
            raise PromotionRefusal(
                "evaluating needs an oracle, owner or independent model, not only an LLM judge"
            )
        return "canary" if "canary" in required else "probation"
    if state == "canary":
        if "canary" not in names:
            raise PromotionRefusal("canary still awaits a counted canary result")
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


def next_record(
    candidate, records, gates, producer, at, reason=None, as_of=None, resolve=None
):
    """The next promotion-record/v1 for this candidate, already proven to fold.

    ``as_of`` (default now) bounds every timestamp, as the fold CLI does, so a
    future-dated maturity pass is refused rather than written.
    """
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    instant = contracts.parse_time(at)
    if instant is None or instant > as_of:
        raise PromotionRefusal(f"the record's time {at} is not a past contract instant")
    gates = sorted(gate_results(gates, candidate), key=lambda g: g["gate"])
    current = contracts.fold(candidate, records, as_of=as_of, resolve=resolve)
    if current.errors:
        raise PromotionRefusal(f"the chain does not fold cleanly: {current.errors[0]}")
    if current.effect == "live":
        raise PromotionRefusal("a live candidate moves only by its owner's records")
    target = target_state(candidate, current.state, gates, resolve)
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
    after = contracts.fold(
        candidate, list(records) + [record], as_of=as_of, resolve=resolve
    )
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
    parser.add_argument(
        "--resolutions",
        type=Path,
        help="decision-resolution/v1 records read from agent-hq origin/main (owner gates count only through these)",
    )
    args = parser.parse_args(argv)
    try:
        candidates = contracts.read_records(args.candidate)
        if len(candidates) != 1:
            raise PromotionRefusal("expected exactly one candidate")
        records = contracts.read_records(args.records) if args.records else []
        gates = [g for path in args.gates for g in contracts.read_records(path)]
        at = args.at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if contracts.parse_time(at) is None:
            raise PromotionRefusal(f"--at is not a contract timestamp: {at}")
        producer = {
            "lane": args.lane,
            "runtime": "tool",
            "model": None,
            "session": args.session,
        }
        resolve = (
            contracts.resolver_from(contracts.read_records(args.resolutions))
            if args.resolutions
            else None
        )
        record = next_record(
            candidates[0], records, gates, producer, at, args.reason, resolve=resolve
        )
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
