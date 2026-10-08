#!/usr/bin/env python3
"""Replay evaluator: baseline against candidate over the sealed hold-out.

The evaluator never runs a variant. Whoever runs the baseline and the candidate
records what each produced per case (``eval-outputs/v1``); this module selects
the cases a candidate may be judged on, grades both outputs with the case's
oracle, compares them pair by pair and emits an ``eval-run/v1`` report whose
``gate`` block drops straight into a ``promotion-record/v1``.

Selection is the hold-out separation the learning plane depends on:

- a case is on the hold-out side when ``split_of(case.split_key)`` says so,
  the same derivation an experience gets, so a case built from an experience
  shares its side;
- a case anchored to a known experience must carry that experience's
  effective split key, so a producer cannot move a case across the split;
- every case built from the candidate's training evidence (its ``evidence``
  plus its genome's ``training_evidence``) is dropped, and so is every case
  sharing a split key with that evidence, so a re-worded duplicate of the
  training run that keeps its split key does not leak back in;
- the training evidence must resolve in the supplied experience ledger, or
  the run refuses: exclusion that cannot be proven is not claimed.

Deterministic oracles grade first. A ``judge`` case takes its grade from an
``eval-labels/v1`` file, and any run that used one carries that evaluator's
kind, never ``oracle``.
"""

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

_SPEC = importlib.util.spec_from_file_location(
    "learning_contracts", Path(__file__).resolve().with_name("learning_contracts.py")
)
contracts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(contracts)

RUN_SCHEMA = "eval-run/v1"
TOOL = "agent-harness:scripts/learning_eval.py@1"
GATES = ("offline_eval", "replay", "retrieval_regression")


def default_policy(gate):
    """The pinned minima for this gate (promotion-classes.json eval_minima)."""
    pinned = contracts.classes()["eval_minima"][gate]
    return {k: pinned[k] for k in ("min_cases", "min_delta", "max_sign_p")}


class EvalRefusal(Exception):
    """The run cannot be judged honestly (exit 2); no report is written."""


# -- inputs -----------------------------------------------------------------


def _valid(record, what):
    errors = contracts.validate_record(record)
    if errors:
        raise EvalRefusal(f"{what} is invalid: {errors[0]}")
    return record


def load(paths, schema):
    """Every record of one schema from the given files, validated."""
    records = []
    for path in paths:
        for record in contracts.read_records(path):
            if not isinstance(record, dict) or record.get("schema") != schema:
                raise EvalRefusal(f"{path}: expected {schema} records")
            records.append(_valid(record, f"{path}: {record.get('id', schema)}"))
    return records


def latest_experiences(records):
    """The experience ledger folded by id; any inconsistency refuses the run."""
    by_id, errors = contracts.fold_experiences(records)
    if errors:
        raise EvalRefusal(f"experience ledger is inconsistent: {errors[0]}")
    return by_id


effective_split_key = contracts.experience_split_key


def training_set(candidate, genome, experiences, ran=None):
    """(experience ids, split keys) the candidate learned from; refuse if unresolved.

    ``ran`` is the candidate outputs' variant_ref: a ``gen:`` ref names the
    genome that actually produced them, whose training evidence is excluded too.
    """
    named = candidate.get("genome")
    if ran and ran.startswith("gen:"):
        if named and named != ran[4:]:
            raise EvalRefusal(
                f"the outputs came from {ran[4:]}, the candidate names {named}"
            )
        named = ran[4:]
    if named and (genome is None or genome["id"] != named):
        raise EvalRefusal(
            f"{candidate['id']} runs as {named}: pass exactly that genome"
        )
    if genome is not None and candidate["id"] not in genome["candidates"]:
        raise EvalRefusal(f"{genome['id']} does not implement {candidate['id']}")
    ids = set(candidate["evidence"])
    if genome is not None:
        ids |= set(genome["training_evidence"]["experiences"])
    missing = sorted(ids - set(experiences))
    if missing:
        raise EvalRefusal(
            f"training evidence not in the experience ledger, exclusion unprovable: {missing[:5]}"
        )
    return ids, {effective_split_key(experiences[i]) for i in ids}


def select(cases, split, training_ids, training_keys, experiences):
    """Cases the candidate may be judged on, and why the others were dropped."""
    counts = {
        "total": len(cases),
        "other_split": 0,
        "excluded_training": 0,
        "excluded_cluster": 0,
        "unanchored": 0,
    }
    seen, chosen = set(), []
    for case in cases:
        if case["id"] in seen:
            raise EvalRefusal(f"duplicate case id {case['id']}")
        seen.add(case["id"])
        anchor = experiences.get(case["experience"]) if case["experience"] else None
        if case["experience"] and anchor is None:
            raise EvalRefusal(
                f"{case['id']}: its experience is not in the ledger, so its split cannot be proven"
            )
        if case["oracle"]["kind"] == "regex":
            try:
                re.compile(case["oracle"]["pattern"])
            except re.error as exc:
                raise EvalRefusal(f"{case['id']}: invalid pattern ({exc})") from exc
        if anchor is not None and effective_split_key(anchor) != case["split_key"]:
            raise EvalRefusal(
                f"{case['id']}: split_key differs from its experience's; a case cannot move across the split"
            )
        if contracts.split_of(case["split_key"]) != split:
            counts["other_split"] += 1
        elif case["experience"] in training_ids:
            counts["excluded_training"] += 1
        elif case["split_key"] in training_keys:
            counts["excluded_cluster"] += 1
        else:
            counts["unanchored"] += anchor is None
            chosen.append(case)
    counts["evaluated"] = len(chosen)
    # Clones of one task are one piece of evidence, however many ids they carry.
    counts["distinct_inputs"] = len(
        {(c["input_ref"], json.dumps(c["oracle"], sort_keys=True)) for c in chosen}
    )
    return chosen, counts


# -- oracles ----------------------------------------------------------------


def _fold_text(value):
    return (value or "").casefold()


def grade(case, output):
    """(passed, detail) for one output under the case's deterministic oracle."""
    oracle = case["oracle"]
    kind = oracle["kind"]
    if output is None:
        return False, {"missing": True}
    if output.get("error"):
        return False, {"error": output["error"]}
    if (
        kind in ("exact", "contains_all", "contains_none", "regex")
        and "text" not in output
    ):
        return False, {"missing_text": True}
    if kind == "abstain" and "abstained" not in output:
        return False, {"missing_abstained": True}
    text = _fold_text(output.get("text"))
    if kind == "exact":
        return (output.get("text") or "").strip() == oracle["expected"].strip(), {}
    if kind == "contains_all":
        return all(_fold_text(n) in text for n in oracle["needles"]), {}
    if kind == "contains_none":
        return not any(_fold_text(n) in text for n in oracle["needles"]), {}
    if kind == "regex":
        return re.search(oracle["pattern"], output.get("text") or "") is not None, {}
    if kind == "abstain":
        return bool(output.get("abstained")) == oracle["expected_abstain"], {}
    if kind == "procedure":
        detail = {k: output.get(k) for k in ("completed", "turns", "recovered")}
        passed = output.get("completed") is True
        if "max_turns" in oracle:
            turns = output.get("turns")
            passed = passed and turns is not None and turns <= oracle["max_turns"]
        if oracle.get("require_recovery"):
            passed = passed and output.get("recovered") is True
        return passed, detail
    if kind == "numeric":
        value = output.get("value")
        if value is None:
            return False, {"missing_value": True}
        low, high = oracle.get("at_least"), oracle.get("at_most")
        return (low is None or value >= low) and (high is None or value <= high), {}
    if "items" not in output:
        return False, {"missing_items": True}  # never a vacuous pass
    items = output["items"]
    expected = oracle.get("expected_items", [])
    if kind == "set_match":
        hits = len(set(items) & set(expected))
        recall = hits / len(expected) if expected else 1.0
        precision = hits / len(set(items)) if items else 0.0
        reported = sorted(set(items) & set(oracle.get("forbidden_items", ())))
        passed = (
            recall >= oracle.get("min_recall", 1.0)
            and precision >= oracle.get("min_precision", 0.0)
            and not reported
        )
        return passed, {
            "recall": recall,
            "precision": precision,
            "forbidden": len(reported),
        }
    if kind == "ranked_recall":
        top = items[: oracle["k"]]
        recall = len(set(top) & set(expected)) / len(expected)
        rank = next((i for i, item in enumerate(items, 1) if item in expected), None)
        detail = {"recall_at_k": recall, "reciprocal_rank": 1 / rank if rank else 0.0}
        return recall >= oracle.get("min_recall", 1.0), detail
    raise EvalRefusal(f"{case['id']}: no deterministic oracle for {kind}")


def _labels_for(labels, variant, suite):
    chosen = [lab for lab in labels if lab["variant"] == variant]
    for label in chosen:
        if label["suite"] != suite:
            raise EvalRefusal(f"labels for {label['suite']} given to suite {suite}")
    if len(chosen) > 1:
        raise EvalRefusal(f"more than one labels file for the {variant}")
    return chosen[0] if chosen else None


# -- comparison -------------------------------------------------------------


def sign_test(wins, losses):
    """Two-sided exact sign test on the discordant pairs."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2**n
    return min(1.0, 2 * tail)


def _rate(passed, total):
    return passed / total if total else None


def _breakdown(rows, key):
    groups = {}
    for row in rows:
        group = groups.setdefault(row[key], {"n": 0, "baseline": 0, "candidate": 0})
        group["n"] += 1
        group["baseline"] += row["baseline"]
        group["candidate"] += row["candidate"]
    for group in groups.values():
        group["baseline_rate"] = _rate(group["baseline"], group["n"])
        group["candidate_rate"] = _rate(group["candidate"], group["n"])
    return dict(sorted(groups.items()))


def _retrieval(rows):
    ranked = [r for r in rows if "recall_at_k" in r["detail"]["candidate"]]
    if not ranked:
        return None
    result = {"n": len(ranked)}
    for variant in ("baseline", "candidate"):
        details = [r["detail"][variant] for r in ranked]
        result[variant] = {
            "recall_at_k": sum(d.get("recall_at_k", 0.0) for d in details)
            / len(ranked),
            "mrr": sum(d.get("reciprocal_rank", 0.0) for d in details) / len(ranked),
        }
    return result


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _procedural(rows, cases, baseline, candidate_outputs):
    """Completion, turns, recovery and cost of procedural cases, per variant."""
    procedural = {c["id"] for c in cases if c["oracle"]["kind"] == "procedure"}
    if not procedural:
        return None
    result = {"n": len(procedural)}
    for variant, outputs in (("baseline", baseline), ("candidate", candidate_outputs)):
        runs = [outputs["outputs"].get(case) or {} for case in sorted(procedural)]
        # Completion agrees with grading (an errored run did not complete), and
        # turns count only completed runs, so giving up early never looks efficient.
        done = [r for r in runs if r.get("completed") is True and not r.get("error")]
        # Recovery is a rate over the cases that injected a failure to recover from.
        needing = [
            outputs["outputs"].get(c["id"]) or {}
            for c in sorted(cases, key=lambda c: c["id"])
            if c["id"] in procedural and c["oracle"].get("require_recovery")
        ]
        recovered = [r.get("recovered") is True for r in needing]
        result[variant] = {
            "completion_rate": len(done) / len(runs),
            "turns_mean": _mean(r.get("turns") for r in done),
            "recovery_rate": (sum(recovered) / len(recovered)) if recovered else None,
            "tokens_mean": _mean(r.get("tokens") for r in runs),
            "seconds_mean": _mean(r.get("seconds") for r in runs),
        }
    return result


def _cost(outputs, cases):
    tokens = [
        outputs[c["id"]]["tokens"]
        for c in cases
        if "tokens" in outputs.get(c["id"], {})
    ]
    seconds = [
        outputs[c["id"]]["seconds"]
        for c in cases
        if "seconds" in outputs.get(c["id"], {})
    ]
    return {
        "tokens_mean": sum(tokens) / len(tokens) if tokens else None,
        "seconds_mean": sum(seconds) / len(seconds) if seconds else None,
    }


def _digest(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def evaluate(
    cases,
    baseline,
    candidate_outputs,
    candidate,
    experiences,
    genome=None,
    labels=(),
    split="holdout",
    gate="offline_eval",
    policy=None,
    at=None,
):
    """Judge a candidate against the baseline; returns an eval-run/v1 report."""
    if gate not in GATES:
        raise EvalRefusal(f"gate must be one of {GATES}")
    policy = {**default_policy(gate), **(policy or {})}
    if policy["min_cases"] < 1 or not 0 < policy["max_sign_p"] <= 1:
        raise EvalRefusal("min_cases is at least 1 and max_sign_p in (0, 1]")
    suites = {c["suite"] for c in cases}
    if len(suites) != 1:
        raise EvalRefusal(f"one suite per run, got {sorted(suites)}")
    suite = suites.pop()
    for outputs, variant in ((baseline, "baseline"), (candidate_outputs, "candidate")):
        if outputs["variant"] != variant or outputs["suite"] != suite:
            raise EvalRefusal(
                f"the {variant} outputs are for {outputs['variant']}/{outputs['suite']}"
            )
    experiences = latest_experiences(experiences)
    training_ids, training_keys = training_set(
        candidate, genome, experiences, candidate_outputs["variant_ref"]
    )
    chosen, counts = select(cases, split, training_ids, training_keys, experiences)
    label_files = {v: _labels_for(labels, v, suite) for v in ("baseline", "candidate")}
    graders = set()
    rows = []
    for case in chosen:
        row = {
            "case": case["id"],
            "category": case["category"],
            "layer": case["layer"],
            "detail": {},
        }
        for variant, outputs in (
            ("baseline", baseline),
            ("candidate", candidate_outputs),
        ):
            output = outputs["outputs"].get(case["id"])
            if case["oracle"]["kind"] == "judge":
                label_file = label_files[variant]
                label = label_file["labels"].get(case["id"]) if label_file else None
                if label is None:
                    raise EvalRefusal(
                        f"{case['id']}: judge case without a {variant} label"
                    )
                graders.add(json.dumps(label_file["evaluator"], sort_keys=True))
                usable = output is not None and not output.get("error")
                passed, detail = (usable and label == "pass"), {"label": label}
            else:
                passed, detail = grade(case, output)
            row[variant] = int(passed)
            row["detail"][variant] = detail
        rows.append(row)
    learners = {candidate["producer"]["session"]}
    if genome is not None:
        learners.add(genome["producer"]["session"])
    for label_file in label_files.values():
        if label_file and label_file["evaluator"]["session"] in learners:
            raise EvalRefusal("the labels come from the learner's own session")
    wins = sum(r["candidate"] and not r["baseline"] for r in rows)
    losses = sum(r["baseline"] and not r["candidate"] for r in rows)
    base_rate = _rate(sum(r["baseline"] for r in rows), len(rows))
    cand_rate = _rate(sum(r["candidate"] for r in rows), len(rows))
    delta = cand_rate - base_rate if rows else None
    if counts["distinct_inputs"] < policy["min_cases"]:
        verdict = "insufficient"
    elif (
        delta >= policy["min_delta"]
        and contracts.sign_p(wins, losses) < policy["max_sign_p"]
    ):
        verdict = "pass"
    else:
        verdict = "fail"
    at = at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    evaluated = [r["case"] for r in rows]
    holdout_digest = _digest(evaluated)
    run_id = (
        "run_"
        + _digest(
            [
                candidate["id"],
                genome["id"] if genome else "",
                baseline["variant_ref"],
                candidate_outputs["variant_ref"],
                split,
                gate,
                holdout_digest,
                json.dumps(policy, sort_keys=True),
                _digest(
                    [
                        json.dumps(o["outputs"], sort_keys=True)
                        for o in (baseline, candidate_outputs)
                    ]
                ),
                _digest(sorted(json.dumps(lab, sort_keys=True) for lab in labels)),
            ]
        )[:16]
    )
    evaluator = _run_evaluator(graders, run_id)
    anchors = sorted({c["experience"] for c in chosen if c["experience"]})
    report = {
        "schema": RUN_SCHEMA,
        "id": run_id,
        "at": at,
        "producer": {
            "lane": "agent-harness",
            "runtime": "tool",
            "model": TOOL,
            "session": run_id,
        },
        "suite": suite,
        "split": split,
        "gate_name": gate,
        "candidate": candidate["id"],
        "genome": genome["id"] if genome else None,
        "baseline_ref": baseline["variant_ref"],
        "candidate_ref": candidate_outputs["variant_ref"],
        "tier": evaluator["kind"],
        "evaluator": evaluator,
        "training": {
            "experiences": len(training_ids),
            "split_keys": len(training_keys),
        },
        "cases": counts,
        "holdout_digest": holdout_digest,
        "anchors": anchors,
        "policy": policy,
        "results": {
            "baseline": {"passed": sum(r["baseline"] for r in rows), "rate": base_rate},
            "candidate": {
                "passed": sum(r["candidate"] for r in rows),
                "rate": cand_rate,
            },
            "delta": delta,
            "wins": wins,
            "losses": losses,
            "ties": len(rows) - wins - losses,
            "sign_test_p": sign_test(wins, losses),
            "by_category": _breakdown(rows, "category"),
            "by_layer": _breakdown(rows, "layer"),
            "retrieval": _retrieval(rows),
            "procedural": _procedural(rows, chosen, baseline, candidate_outputs),
            "cost": {
                "baseline": _cost(baseline["outputs"], chosen),
                "candidate": _cost(candidate_outputs["outputs"], chosen),
            },
        },
        "verdict": verdict,
        "gate": None,
    }
    if split == "holdout" and verdict in ("pass", "fail"):
        report["gate"] = {
            "gate": gate,
            "result": verdict,
            "evaluator": evaluator,
            "at": at,
            "ref": f"eval-run:{run_id}",
            "summary": (
                f"{len(rows)} hold-out cases: candidate {cand_rate:.3f} vs baseline "
                f"{base_rate:.3f}, {wins} wins, {losses} losses (policy: min_delta "
                f"{policy['min_delta']}, max_sign_p {policy['max_sign_p']})"
            )[:280],
            "holdout_digest": holdout_digest,
            "training_excluded": True,
            "anchors": anchors,
            "metrics": {
                "delta": delta,
                "wins": wins,
                "losses": losses,
                "cases": len(rows),
                "anchored": sum(1 for c in chosen if c["experience"]),
                "min_cases": policy["min_cases"],
                "min_delta": policy["min_delta"],
                "max_sign_p": policy["max_sign_p"],
                "sign_p": contracts.sign_p(wins, losses),
            },
        }
    problems = contracts.validate_record(report)
    if problems:
        raise EvalRefusal(f"internal: the report breaks eval-run/v1: {problems[0]}")
    return report


def _run_evaluator(graders, run_id):
    """The weakest grader names the run: any label demotes it from oracle."""
    if not graders:
        return {"kind": "oracle", "runtime": "tool", "model": None, "session": run_id}
    if len(graders) > 1:
        kinds = {json.loads(g)["kind"] for g in graders}
        if kinds != {json.loads(next(iter(graders)))["kind"]}:
            raise EvalRefusal(
                "baseline and candidate were labelled by different kinds of evaluator"
            )
    order = {"llm_judge": 0, "independent_model": 1, "owner": 2}
    # Sorted first, so the same inputs always name the same evaluator.
    return min(
        (json.loads(g) for g in sorted(graders)),
        key=lambda e: order.get(e["kind"], -1),
    )


# -- command line -----------------------------------------------------------


def _one(paths, schema):
    records = load(paths, schema)
    if len(records) != 1:
        raise EvalRefusal(f"expected exactly one {schema}")
    return records[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cases", type=Path, nargs="+", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate-outputs", type=Path, required=True)
    parser.add_argument(
        "--candidate", type=Path, required=True, help="learning-candidate/v1"
    )
    parser.add_argument(
        "--genome",
        type=Path,
        help="candidate-genome/v1 (required when the candidate names one)",
    )
    parser.add_argument("--experiences", type=Path, nargs="+", required=True)
    parser.add_argument("--labels", type=Path, nargs="*", default=())
    parser.add_argument("--split", choices=("holdout", "dev"), default="holdout")
    parser.add_argument("--gate", choices=GATES, default="offline_eval")
    parser.add_argument(
        "--min-cases", type=int, help="default: the gate's pinned minimum"
    )
    parser.add_argument(
        "--min-delta", type=float, help="default: the gate's pinned minimum"
    )
    parser.add_argument(
        "--max-sign-p", type=float, help="default: the gate's pinned minimum"
    )
    parser.add_argument("--at", help="report timestamp (default: now)")
    args = parser.parse_args(argv)
    try:
        if args.at and contracts.parse_time(args.at) is None:
            raise EvalRefusal(f"--at is not a contract timestamp: {args.at}")
        report = evaluate(
            load(args.cases, "eval-case/v1"),
            _one([args.baseline], "eval-outputs/v1"),
            _one([args.candidate_outputs], "eval-outputs/v1"),
            _one([args.candidate], "learning-candidate/v1"),
            load(args.experiences, "estate-experience/v1"),
            genome=_one([args.genome], "candidate-genome/v1") if args.genome else None,
            labels=load(args.labels, "eval-labels/v1"),
            split=args.split,
            gate=args.gate,
            policy={
                k: v
                for k, v in (
                    ("min_cases", args.min_cases),
                    ("min_delta", args.min_delta),
                    ("max_sign_p", args.max_sign_p),
                )
                if v is not None
            },
            at=args.at,
        )
    except (EvalRefusal, contracts.ContractError, OSError, ValueError) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return {"pass": 0, "fail": 1}.get(report["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
