"""Read-only, deterministic metrics over the estate's private learning records."""

from collections import Counter, defaultdict
import hashlib
import importlib.util
from pathlib import Path
import statistics

_spec = importlib.util.spec_from_file_location(
    "learning_contracts", Path(__file__).with_name("learning_contracts.py")
)
contracts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contracts)

EXPERIENCE = "estate-experience/v1"
MEMORY_USE = "memory-use/v1"
CANDIDATE = "learning-candidate/v1"
PROMOTION = "promotion-record/v1"


def _latest(records):
    latest = {}
    for record in records:
        prior = latest.get(record["id"])
        if prior is None or contracts.parse_time(record["observed_at"]) >= (
            contracts.parse_time(prior["observed_at"])
        ):
            latest[record["id"]] = record
    return list(latest.values())


def load_learning(paths):
    """Load sorted files, reporting invalid records without aborting the dataset."""
    result = {name: [] for name in contracts.RECORD_SCHEMAS}
    result["problems"] = []
    for source in paths:
        source = Path(source)
        files = sorted(source.rglob("*")) if source.is_dir() else [source]
        for path in files:
            if path.is_dir() or path.suffix not in (".json", ".jsonl"):
                continue
            try:
                records = contracts.read_records(path)
            except (OSError, ValueError, RecursionError) as exc:
                result["problems"].append(
                    {"file": str(path), "index": None, "error": str(exc)}
                )
                continue
            for index, record in enumerate(records):
                try:
                    errors = contracts.validate_record(record)
                except (TypeError, ValueError, RecursionError) as exc:
                    errors = [str(exc)]
                if errors:
                    result["problems"].append(
                        {"file": str(path), "index": index, "error": errors[0]}
                    )
                else:
                    result[record["schema"]].append(record)
    # Overlapping --learning paths load a candidate twice; count it once.
    unique = {}
    for record in result[CANDIDATE]:
        held = unique.setdefault(record["id"], record)
        if held != record:
            result["problems"].append(
                {
                    "file": None,
                    "index": None,
                    "error": f"{record['id']}: two different records",
                }
            )
    result[CANDIDATE] = list(unique.values())
    # Experiences fold through the contract, which also refuses a later
    # observation that moves a run across the split.
    folded, errors = contracts.fold_experiences(result[EXPERIENCE])
    result["problems"] += [{"file": None, "index": None, "error": e} for e in errors]
    result[EXPERIENCE] = list(folded.values())
    result[MEMORY_USE] = _latest(result[MEMORY_USE])
    return result


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


_success = contracts.experience_succeeded


def _success_block(experiences):
    return {
        "n": len(experiences),
        "success_rate": _rate(sum(map(_success, experiences)), len(experiences)),
    }


def _ref(ref):
    return ref.rsplit("@", 1)[0]


def _supplied_refs(experience, memory_use):
    if experience["id"] in memory_use:
        return {
            _ref(item["ref"])
            for item in memory_use[experience["id"]]["memories"]
            if item["supplied"] is True
        }
    return {_ref(ref) for ref in experience.get("memory_used", ())}


def _completion(items):
    completed = sum(item["completed"] is True for item in items)
    return {
        "n": len(items),
        "completed": completed,
        "rate": _rate(completed, len(items)),
    }


def _quantile(values, q):
    # Same order statistic and rounding as outcome_ledger._quantile.
    values = sorted(values)
    return (
        round(values[min(len(values) - 1, int(q * len(values)))], 1) if values else None
    )


def _recurrence(experiences, keys):
    occurrences = defaultdict(list)
    for experience in sorted(
        experiences, key=lambda exp: (contracts.parse_time(exp["at"]), exp["id"])
    ):
        for key in keys(experience):
            occurrences[key].append(experience["producer"]["runtime"])
    runtime = Counter(r for group in occurrences.values() for r in group[1:])
    recurred = sum(len(group) > 1 for group in occurrences.values())
    return {
        "keys": len(occurrences),
        "recurred_keys": recurred,
        "rate": _rate(recurred, len(occurrences)),
        "recurrences": sum(runtime.values()),
        "by_runtime": dict(sorted(runtime.items())),
    }


def learning_metrics(records, split="dev", as_of=None):
    """Aggregate load_learning's dataset; as_of does not alter observed outcomes."""
    if split not in ("dev", "holdout", "all"):
        raise ValueError(f"unknown split: {split}")
    all_experiences = {exp["id"]: exp for exp in _latest(records.get(EXPERIENCE, []))}
    experiences = [
        exp
        for exp in all_experiences.values()
        if split == "all" or contracts.experience_split(exp) == split
    ]
    selected = {exp["id"] for exp in experiences}
    memory_use = {
        mu["experience"]: mu
        for mu in _latest(records.get(MEMORY_USE, []))
        if mu["experience"] in selected
    }
    problems = list(records.get("problems", []))
    promotions = defaultdict(list)
    for record in records.get(PROMOTION, []):
        promotions[record["candidate"]].append(record)
    candidates, lessons, promoted_skills = [], [], set()
    for candidate in records.get(CANDIDATE, []):
        moves = promotions[candidate["id"]]
        folded = contracts.fold(candidate, moves)
        problems.extend(
            {"candidate": candidate["id"], "error": error} for error in folded.errors
        )
        by_id = {move["id"]: move for move in moves}
        chain = [by_id[ident] for ident in folded.chain]
        activation = next((move for move in chain if move["to"] == "active"), None)
        candidates.append((candidate, folded.state, chain, activation))
        landed = next(
            (move["landed"] for move in reversed(chain) if "landed" in move), None
        )
        if activation and landed:
            if candidate["kind"] in ("semantic", "consolidation") and landed.startswith(
                "memory:"
            ):
                lessons.append(
                    (candidate, contracts.parse_time(activation["at"]), _ref(landed))
                )
            if candidate["kind"] == "skill" and landed.startswith("skill:"):
                promoted_skills.add(_ref(landed))

    with_memory, without_memory = [], []
    for exp in experiences:
        (with_memory if _supplied_refs(exp, memory_use) else without_memory).append(exp)
    assisted, unassisted = _success_block(with_memory), _success_block(without_memory)
    items = [item for mu in memory_use.values() for item in mu["memories"]]
    effects = Counter(
        item["effect"]["verdict"]
        for item in items
        if item.get("effect", {}).get("verdict") in ("helped", "harmed", "neutral")
        and item["effect"]["evaluator"]["kind"] != "self"
    )
    measured = [
        item
        for item in items
        if item["supplied"] is True
        and (item["read"] is not None or item["cited"] is not None)
    ]
    wasted = sum(
        item["read"] is not True and item["cited"] is not True for item in measured
    )
    successful = [
        exp for exp in experiences if _success(exp) and exp["id"] in memory_use
    ]
    supplied = [
        item
        for exp in successful
        for item in memory_use[exp["id"]]["memories"]
        if item["supplied"] is True
    ]
    byte_count = sum(
        item["bytes"] for item in supplied if item.get("bytes") is not None
    )
    skills = [
        item
        for mu in memory_use.values()
        for item in mu["skills"]
        if item.get("completed") is not None
    ]
    reuse_counts, same, cross, unknown = [], [], [], 0
    for candidate, activation_at, landed in lessons:
        uses = [
            exp
            for exp in experiences
            if contracts.parse_time(exp["at"]) > activation_at
            and landed in _supplied_refs(exp, memory_use)
        ]
        reuse_counts.append(len(uses))
        runtimes = {
            all_experiences[eid]["producer"]["runtime"]
            for eid in candidate["evidence"]
            if eid in all_experiences
        }
        if not runtimes:
            unknown += len(uses)  # no evidence loaded: the origin runtime is unknown
            continue
        for exp in uses:
            (same if exp["producer"]["runtime"] in runtimes else cross).append(exp)

    by_kind = defaultdict(lambda: {"candidates": 0, "promoted": 0})
    states = Counter()
    promoted = reverted = pre_reverts = missing = 0
    hours = []
    for candidate, state, chain, activation in candidates:
        states[state] += 1
        by_kind[candidate["kind"]]["candidates"] += 1
        pre_reverts += sum(
            move["to"] == "reverted" and move["from"] in ("canary", "probation")
            for move in chain
        )
        if activation is None:
            continue
        promoted += 1
        by_kind[candidate["kind"]]["promoted"] += 1
        reverted += any(
            move["to"] == "reverted"
            and contracts.parse_time(move["at"])
            >= contracts.parse_time(activation["at"])
            for move in chain
        )
        if not all(eid in all_experiences for eid in candidate["evidence"]):
            missing += 1
            continue
        earliest = min(
            contracts.parse_time(all_experiences[eid]["at"])
            for eid in candidate["evidence"]
        )
        hours.append(
            (contracts.parse_time(activation["at"]) - earliest).total_seconds() / 3600
        )

    holdout = sorted(
        exp["id"]
        for exp in all_experiences.values()
        if contracts.experience_split(exp) == "holdout"
    )
    counts = {name: len(records.get(name, [])) for name in contracts.RECORD_SCHEMAS}
    counts[EXPERIENCE] = len(all_experiences)
    counts[MEMORY_USE] = len(_latest(records.get(MEMORY_USE, [])))
    return {
        "schema": "learning-metrics/v1",
        "split": split,
        "holdout_manifest": {
            "experiences": len(holdout),
            "digest": hashlib.sha256("\n".join(holdout).encode("utf-8")).hexdigest(),
        },
        "counts": counts,
        "problems": problems,
        "notes": [
            "memory_assisted_task_delta is observational, confounded by task selection; not a causal estimate.",
            "Candidate-level metrics (candidate_to_promoted_ratio, promotion_to_revert_rate, time_to_learn) are not split: candidates are not experiences.",
            "time_to_learn requires all evidence experiences loaded; missing_evidence counts promoted candidates with incomplete evidence.",
        ],
        "metrics": {
            "memory_assisted_task_delta": {
                "with_memory": assisted,
                "without_memory": unassisted,
                "delta": (
                    assisted["success_rate"] - unassisted["success_rate"]
                    if with_memory and without_memory
                    else None
                ),
                "basis": "observational",
            },
            "memory_harm_rate": {
                "n": sum(effects.values()),
                "harmed": effects["harmed"],
                "helped": effects["helped"],
                "harm_rate": _rate(effects["harmed"], sum(effects.values())),
                "help_rate": _rate(effects["helped"], sum(effects.values())),
            },
            "retrieval_waste": {
                "n": len(measured),
                "wasted": wasted,
                "rate": _rate(wasted, len(measured)),
            },
            "memory_bytes_per_successful_task": {
                "n": len(successful),
                "bytes": byte_count,
                "unknown_bytes": sum(item.get("bytes") is None for item in supplied),
                "per_task": _rate(byte_count, len(successful)),
            },
            "lesson_reuse": {
                "lessons": len(lessons),
                "reused": sum(n > 0 for n in reuse_counts),
                "uses": sum(reuse_counts),
                "uses_per_lesson_median": (
                    statistics.median(reuse_counts) if reuse_counts else None
                ),
            },
            "skill_reuse_success": {
                **_completion(skills),
                "promoted": _completion(
                    [item for item in skills if _ref(item["ref"]) in promoted_skills]
                ),
            },
            "candidate_to_promoted_ratio": {
                "candidates": len(candidates),
                "promoted": promoted,
                "ratio": _rate(promoted, len(candidates)),
                "by_kind": dict(sorted(by_kind.items())),
                "by_state": dict(sorted(states.items())),
            },
            "promotion_to_revert_rate": {
                "promoted": promoted,
                "reverted": reverted,
                "rate": _rate(reverted, promoted),
                "pre_promotion_reverts": pre_reverts,
            },
            "time_to_learn": {
                "n": len(hours),
                "missing_evidence": missing,
                "median_hours": _quantile(hours, 0.5),
                "p90_hours": _quantile(hours, 0.9),
            },
            "cross_runtime_transfer": {
                "lessons": len(lessons),
                "cross": _success_block(cross),
                "same": _success_block(same),
                "unknown_origin": unknown,
            },
            "owner_correction_recurrence": _recurrence(
                experiences,
                lambda exp: [
                    item["key"]
                    for item in exp.get("feedback", ())
                    if item["kind"] == "owner_correction" and "key" in item
                ],
            ),
            "same_failure_recurrence": _recurrence(
                experiences, lambda exp: exp.get("failure_keys", ())
            ),
        },
    }
