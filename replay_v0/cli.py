"""Dependency-free command line entry point for replay v0."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import sys
from typing import Any

from replay_v0.compare import ComparisonError, compare_decisions
from replay_v0.corpus import (
    ValidationError,
    validate_charter_cases,
    validate_command_events,
)
from replay_v0.digests import sha256_bytes, sha256_file
from replay_v0.manifests import (
    ManifestError,
    build_run_manifest,
    load_corpus_manifest,
    write_manifest,
)
from replay_v0.policy_sources import (
    PolicySourceResult,
    ProcessDecisionSource,
    RecordedDecisionSource,
    validate_recorded_manifest,
)
from replay_v0.reports import (
    build_json_report,
    render_markdown_report,
    report_json_bytes,
)

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_INPUT_INVALID = 2
EXIT_SOURCE_FAILED = 3

DEFAULT_FAIL_ON = ("newly-allowed", "newly-indeterminate")
SUPPORTED_FAIL_ON = frozenset({"newly-allowed", "newly-denied", "newly-indeterminate"})


class ReplayInputError(ValueError):
    """A CLI input cannot satisfy the replay v0 contract."""


@dataclass(frozen=True)
class LoadedCharterCorpus:
    events: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    corpus_id: str
    event_count: int
    manifest_sha256: str


@dataclass(frozen=True)
class LoadedPolicySource:
    kind: str
    source: RecordedDecisionSource | ProcessDecisionSource
    identity: dict[str, str]


def _parse_fail_on(value: str) -> tuple[str, ...]:
    choices = value.split(",") if value else []
    if not choices or any(choice not in SUPPORTED_FAIL_ON for choice in choices):
        expected = ", ".join(sorted(SUPPORTED_FAIL_ON))
        raise argparse.ArgumentTypeError(
            f"expected a comma-separated selection from: {expected}"
        )
    if len(set(choices)) != len(choices):
        raise argparse.ArgumentTypeError("--fail-on values must not be duplicated")
    return tuple(choices)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m replay_v0.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay = subparsers.add_parser("replay", help="compare two policy sources")
    replay.add_argument("--baseline", required=True)
    replay.add_argument("--candidate", required=True)
    replay.add_argument("--corpus", required=True)
    replay.add_argument("--output", required=True)
    replay.add_argument(
        "--fail-on",
        type=_parse_fail_on,
        default=DEFAULT_FAIL_ON,
        metavar="CLASS[,CLASS...]",
    )
    replay.add_argument("--timeout", type=float, default=30.0)

    validate = subparsers.add_parser("validate", help="validate a charter corpus")
    validate.add_argument("--corpus", required=True)
    return parser


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ReplayInputError(f"JSON object contains duplicate key {key!r}")
        value[key] = item
    return value


def _read_jsonl(path: Path, label: str) -> list[object]:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReplayInputError(f"{label} is not readable UTF-8") from exc
    records: list[object] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            records.append(json.loads(line, object_pairs_hook=_unique_json_object))
        except json.JSONDecodeError as exc:
            raise ReplayInputError(
                f"{label} line {line_number} is not valid JSON"
            ) from exc
    return records


def _resolve_manifest_path(value: str) -> Path:
    path = Path(value)
    if path.is_dir():
        return path / "corpus-manifest.json"
    if path.name == "corpus-manifest.json":
        return path
    return path.parent / "corpus-manifest.json"


def _load_charter_corpus(value: str) -> LoadedCharterCorpus:
    manifest_path = _resolve_manifest_path(value)
    loaded = load_corpus_manifest(manifest_path)
    entries = {entry["path"]: entry for entry in loaded.value["files"]}
    required_paths = {"events.jsonl", "cases.jsonl"}
    if set(entries) != required_paths:
        raise ReplayInputError(
            "charter corpus manifest must list exactly events.jsonl and cases.jsonl"
        )

    events = validate_command_events(
        _read_jsonl(manifest_path.parent / "events.jsonl", "events.jsonl")
    )
    cases = validate_charter_cases(
        _read_jsonl(manifest_path.parent / "cases.jsonl", "cases.jsonl")
    )
    if len(events) != loaded.value["event_count"]:
        raise ReplayInputError("corpus event_count does not match events.jsonl")
    if {event["event_id"] for event in events} != {case["event_id"] for case in cases}:
        raise ReplayInputError("charter cases do not match corpus event ids")
    return LoadedCharterCorpus(
        events=events,
        cases=cases,
        corpus_id=loaded.value["corpus_id"],
        event_count=loaded.value["event_count"],
        manifest_sha256=loaded.manifest_sha256,
    )


def _load_recorded_source(raw_path: str) -> LoadedPolicySource:
    path = Path(raw_path)
    manifest_path = Path(f"{path}.manifest.json")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_value = json.loads(
            manifest_bytes.decode("utf-8"), object_pairs_hook=_unique_json_object
        )
        manifest = validate_recorded_manifest(manifest_value)
        decision_bytes = path.read_bytes()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayInputError(
            "recorded source or sidecar is not readable JSON"
        ) from exc
    if manifest.decisions_file != path.name:
        raise ReplayInputError("recorded sidecar names a different decisions file")
    if sha256_bytes(decision_bytes) != manifest.decisions_sha256:
        raise ReplayInputError("recorded source does not match its sidecar digest")
    try:
        line_count = len(decision_bytes.decode("utf-8").splitlines())
    except UnicodeDecodeError as exc:
        raise ReplayInputError("recorded source is not valid UTF-8") from exc
    if line_count != manifest.decision_count:
        raise ReplayInputError("recorded source count does not match its sidecar")
    return LoadedPolicySource(
        kind="recorded",
        source=RecordedDecisionSource(path, manifest_path),
        identity={
            "kind": "recorded",
            "id": manifest.policy_id,
            "sha256": sha256_bytes(manifest_bytes),
        },
    )


def _load_process_source(raw_argv: str, timeout: float) -> LoadedPolicySource:
    argv = raw_argv.split(",")
    if len(argv) < 2 or any(not item or "\r" in item or "\n" in item for item in argv):
        raise ReplayInputError(
            "process source must be a comma-separated argv ending in a policy file"
        )
    policy_path = Path(argv[-1])
    if not policy_path.is_file():
        raise ReplayInputError("process source must end in a readable policy file")
    try:
        policy_digest = sha256_file(policy_path)
    except OSError as exc:
        raise ReplayInputError("process policy file could not be read") from exc
    try:
        source = ProcessDecisionSource(argv, timeout_seconds=timeout)
    except ValueError as exc:
        raise ReplayInputError(str(exc)) from exc
    return LoadedPolicySource(
        kind="process",
        source=source,
        identity={
            "kind": "process",
            "id": policy_path.stem,
            "sha256": policy_digest,
        },
    )


def _load_policy_source(value: str, timeout: float) -> LoadedPolicySource:
    kind, separator, payload = value.partition(":")
    if not separator or not payload:
        raise ReplayInputError(
            "policy source must use recorded:<path> or process:<argv>"
        )
    if kind == "recorded":
        return _load_recorded_source(payload)
    if kind == "process":
        return _load_process_source(payload, timeout)
    raise ReplayInputError("policy source kind must be recorded or process")


def _generated_at() -> str:
    raw_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if raw_epoch is None:
        timestamp = datetime.now(timezone.utc).replace(microsecond=0)
    else:
        try:
            epoch = int(raw_epoch)
            if epoch < 0:
                raise ValueError
            timestamp = datetime.fromtimestamp(epoch, timezone.utc)
        except (ValueError, OSError, OverflowError) as exc:
            raise ReplayInputError(
                "SOURCE_DATE_EPOCH must be a non-negative supported integer"
            ) from exc
    return timestamp.isoformat().replace("+00:00", "Z")


def _reproduction_command(args: argparse.Namespace) -> str:
    parts = [
        "python",
        "-m",
        "replay_v0.cli",
        "replay",
        "--baseline",
        args.baseline,
        "--candidate",
        args.candidate,
        "--corpus",
        args.corpus,
        "--output",
        args.output,
        "--fail-on",
        ",".join(args.fail_on),
        "--timeout",
        str(args.timeout),
    ]
    return shlex.join(parts)


def _run_validate(args: argparse.Namespace) -> int:
    corpus = _load_charter_corpus(args.corpus)
    print(
        f"valid corpus {corpus.corpus_id}: {corpus.event_count} events; "
        f"manifest sha256 {corpus.manifest_sha256}"
    )
    return EXIT_OK


def _run_replay(args: argparse.Namespace) -> int:
    corpus = _load_charter_corpus(args.corpus)
    baseline = _load_policy_source(args.baseline, args.timeout)
    candidate = _load_policy_source(args.candidate, args.timeout)
    run_manifest = build_run_manifest(
        generated_at=_generated_at(),
        baseline=baseline.identity,
        candidate=candidate.identity,
        corpus={
            "id": corpus.corpus_id,
            "manifest_sha256": corpus.manifest_sha256,
            "event_count": corpus.event_count,
        },
        fail_on=args.fail_on,
    )

    sources = (("baseline", baseline), ("candidate", candidate))
    results: dict[str, PolicySourceResult] = {}
    for name, loaded_source in sources:
        if loaded_source.kind != "recorded":
            continue
        result = loaded_source.source.evaluate(corpus.events)
        if result.failures:
            raise ReplayInputError(
                f"recorded {name} failed validation: "
                + ", ".join(failure.code for failure in result.failures)
            )
        results[name] = result
    for name, loaded_source in sources:
        if loaded_source.kind == "process":
            results[name] = loaded_source.source.evaluate(corpus.events)

    baseline_result = results["baseline"]
    candidate_result = results["candidate"]
    comparison = compare_decisions(
        corpus.events,
        list(baseline_result.decisions),
        list(candidate_result.decisions),
        case_values=corpus.cases,
    )
    report = build_json_report(
        comparison,
        run_manifest,
        _reproduction_command(args),
        baseline_failures=baseline_result.failures,
        candidate_failures=candidate_result.failures,
    )

    output = Path(args.output)
    try:
        output.mkdir(parents=True, exist_ok=True)
        write_manifest(output / "run-manifest.json", run_manifest)
        (output / "report.json").write_bytes(report_json_bytes(report))
        (output / "report.md").write_bytes(
            render_markdown_report(report).encode("utf-8")
        )
    except OSError as exc:
        print(f"replay output failed: {exc}", file=sys.stderr)
        return EXIT_SOURCE_FAILED

    if baseline_result.failures or candidate_result.failures:
        return EXIT_SOURCE_FAILED
    if report["gate"]["triggered"]:
        return EXIT_REGRESSION
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its documented 0-3 exit code."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            return _run_validate(args)
        return _run_replay(args)
    except (ReplayInputError, ManifestError, ValidationError, ComparisonError) as exc:
        print(f"replay input invalid: {exc}", file=sys.stderr)
        return EXIT_INPUT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
