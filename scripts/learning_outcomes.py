#!/usr/bin/env python3
"""One immutable outcome stream for the coordinator, lessons and learning metrics."""

import argparse
from collections import Counter
import copy
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


def _event_order(event):
    return contracts.parse_time(event["observed_at"]), event["id"]


def _run_id(event):
    return f"{event['run']['kind']}|{event['run']['key']}"


def events_from_experiences(records):
    """Project changed observations, refusing identity drift just like the fold.

    Input order is immaterial; equal timestamps use the fold's canonical tie-break.
    Events own their data, so later edits to the input cannot rewrite history.
    """
    first, previous, events, problems = {}, {}, [], []
    observations = []
    for record in records:
        if isinstance(record, dict):
            observations.append(record)
        else:
            problems.extend(
                f"?: {error}" for error in contracts.validate_record(record)
            )
    ordered = sorted(
        observations,
        key=lambda record: (
            contracts.parse_time(record.get("observed_at"))
            or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            contracts._canonical(record),
        ),
    )
    for record in ordered:
        ident = record.get("id", "?")
        # Reuse the fold's validation and first-observation identity refusals.
        _, errors = contracts.fold_experiences(
            [first[ident], record]
            if isinstance(ident, str) and ident in first
            else [record]
        )
        if errors:
            problems.extend(errors)
            continue
        first.setdefault(ident, record)
        feedback = record.get("feedback", ())
        content = {
            "outcome": record["outcome"],
            "verdicts": {
                signal: sum(
                    item["kind"] == "triage_verdict" and item["signal"] == signal
                    for item in feedback
                )
                for signal in ("confirmed", "refuted")
            },
            "corrections": sorted(
                {
                    item["key"]
                    for item in feedback
                    if item["kind"] == "owner_correction" and "key" in item
                }
            ),
            "failure_keys": sorted(record.get("failure_keys", ())),
            "variant": record.get("variant"),
        }
        # Routing metadata is projected too: a re-observation that only moves
        # the run to another repo, recipe or model is a new version, so every
        # consumer keys it where it now belongs.
        projected = {
            **content,
            "repo": record["repo"],
            "task_kind": record["task_kind"],
            "recipe": record.get("recipe"),
            "runtime": record["producer"]["runtime"],
            "model": record["producer"]["model"],
        }
        prior = previous.get(ident)
        if prior and all(prior[field] == value for field, value in projected.items()):
            continue
        version = prior["version"] + 1 if prior else 1
        # Outcome run identity excludes optional experience attribution.
        run = {key: record["source"][key] for key in ("kind", "key")}
        digest = hashlib.sha256(
            f"{run['kind']}|{run['key']}|{version}".encode("utf-8")
        ).hexdigest()[:16]
        event = copy.deepcopy(
            {
                "schema": "outcome-event/v1",
                "id": "oev_" + digest,
                "at": record["at"],
                "observed_at": record["observed_at"],
                "producer": record["producer"],
                "run": run,
                "experience": ident,
                "version": version,
                "supersedes": prior["id"] if prior else None,
                "repo": record["repo"],
                "task_kind": record["task_kind"],
                "recipe": record.get("recipe"),
                "runtime": record["producer"]["runtime"],
                "model": record["producer"]["model"],
                "success": contracts.experience_succeeded(record),
                **content,
            }
        )
        previous[ident] = event
        events.append(event)
    return sorted(events, key=_event_order), problems


def stream_errors(events):
    """Diagnose malformed records, incomplete runs and impossible chronology.

    This is a complete-history check, not authenticity or tail-completeness
    proof. A missing newest version leaves no gap; callers must obtain the
    whole stream from their trusted source rather than infer it from a cursor.
    """
    errors, seen, runs = [], set(), {}
    for index, event in enumerate(events):
        problems = contracts.validate_record(event)
        if problems:
            errors.extend(f"event {index}: {problem}" for problem in problems)
            continue
        if event["schema"] != "outcome-event/v1":
            errors.append(f"event {index}: expected outcome-event/v1")
            continue
        ident = event["id"]
        if ident in seen:
            errors.append(f"{ident}: appears twice")
        seen.add(ident)
        outcome = event["outcome"]
        if outcome["matured"] is not None and outcome["immediate"] != "merged":
            errors.append(f"{ident}: only a merged run matures")
        runs.setdefault(_run_id(event), []).append(event)
    for run, records in sorted(runs.items()):
        ordered = sorted(records, key=lambda event: event["version"])
        versions = [event["version"] for event in ordered]
        if versions != list(range(1, len(versions) + 1)):
            errors.append(f"{run}: versions {versions} are not 1..{len(versions)}")
        for previous, current in zip(ordered, ordered[1:]):
            if contracts.parse_time(current["observed_at"]) < contracts.parse_time(
                previous["observed_at"]
            ):
                errors.append(
                    f"{current['id']}: observed_at moves backward across versions"
                )
    return errors


def _checked_events(events):
    """Materialize a complete stream once; never reduce partially valid evidence."""
    records = list(events)
    problems = stream_errors(records)
    if problems:
        raise ValueError(f"broken outcome stream: {problems[0]}")
    return records


def latest(events):
    """Newest version per run from a validated complete stream, keyed by run."""
    by_run = {}
    for event in _checked_events(events):
        run = _run_id(event)
        if run not in by_run or event["version"] > by_run[run]["version"]:
            by_run[run] = event
    return by_run


def read_since(events, cursor):
    """Read after a cursor in a validated complete stream; retain empty cursors."""
    if not isinstance(cursor, dict) or set(cursor) != {"observed_at", "id"}:
        raise ValueError("cursor must contain exactly observed_at and id")
    timestamp, ident = cursor["observed_at"], cursor["id"]
    if (timestamp is None) != (ident is None):
        raise ValueError("cursor observed_at and id must both be null or both set")
    instant = contracts.parse_time(timestamp) if timestamp is not None else None
    if timestamp is not None and (
        instant is None or not isinstance(ident, str) or not ident
    ):
        raise ValueError("invalid outcome cursor")
    result = [
        event
        for event in sorted(_checked_events(events), key=_event_order)
        if instant is None or _event_order(event) > (instant, ident)
    ]
    new_cursor = (
        {"observed_at": result[-1]["observed_at"], "id": result[-1]["id"]}
        if result
        else dict(cursor)
    )
    return result, new_cursor


def posterior(events, repo, recipe):
    """Muse coordinator consumer of the one stream: latest Beta counts per arm."""
    alpha, beta = 1, 1
    for event in latest(events).values():
        if event["repo"] != repo or event["recipe"] != recipe:
            continue
        outcome = event["outcome"]
        alpha += event["verdicts"]["confirmed"] + (
            outcome["immediate"] == "merged" and outcome["matured"] == "clean"
        )
        beta += event["verdicts"]["refuted"] + (outcome["matured"] == "reverted")
    return alpha, beta


def lesson_eligible(events):
    """Lesson consumer of the one stream: maturity or an owner correction."""
    return {
        run
        for run, event in latest(events).items()
        if event["outcome"]["matured"] in ("clean", "reverted") or event["corrections"]
    }


def recurrences(events, field):
    """Learning metrics consumer of the one stream: keys shared by distinct runs."""
    if field not in ("corrections", "failure_keys"):
        raise ValueError("recurrence field must be corrections or failure_keys")
    counts = Counter(
        key for event in latest(events).values() for key in set(event[field])
    )
    return {key for key, count in counts.items() if count > 1}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    project = sub.add_parser("project", help="project experiences into JSONL events")
    project.add_argument("experiences", nargs="+", type=Path)
    project.add_argument("--out", type=Path)
    post = sub.add_parser("posterior", help="read the coordinator's Beta posterior")
    post.add_argument("--events", type=Path, required=True)
    post.add_argument("--repo", required=True)
    post.add_argument("--recipe", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "project":
            events, problems = events_from_experiences(
                record
                for path in args.experiences
                for record in contracts.read_records(path)
            )
            if problems:
                raise ValueError("; ".join(problems))
            output = "".join(contracts._canonical(event) + "\n" for event in events)
            if args.out:
                args.out.write_text(output, encoding="utf-8", newline="\n")
            else:
                sys.stdout.write(output)
        else:
            events = contracts.read_records(args.events)
            alpha, beta = posterior(events, args.repo, args.recipe)
            print(json.dumps({"alpha": alpha, "beta": beta}, sort_keys=True))
    except (contracts.ContractError, OSError, ValueError) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
