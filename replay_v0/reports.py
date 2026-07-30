"""Machine-readable and human-readable replay v0 reports."""

from __future__ import annotations

import json
from typing import Any

from replay_v0.compare import ComparisonResult, DIFF_CLASSES
from replay_v0.policy_sources import SourceFailure

REPORT_VERSION = "replay-report.v1"
DECISION_REPLAY_LIMITATION = (
    "This report compares policy decisions for supplied command text; it does not "
    "execute commands or prove that a command is safe, unsafe, or reproduced."
)


def build_json_report(
    comparison: ComparisonResult,
    run_manifest: dict[str, Any],
    reproduction_command: str,
    *,
    baseline_failures: tuple[SourceFailure, ...] = (),
    candidate_failures: tuple[SourceFailure, ...] = (),
) -> dict[str, Any]:
    """Build the complete JSON source of truth for a replay run."""

    fail_on = list(run_manifest["fail_on"])
    triggered = [name for name in fail_on if comparison.counts[name] > 0]
    source_failures = {
        "baseline": [failure.as_dict() for failure in baseline_failures],
        "candidate": [failure.as_dict() for failure in candidate_failures],
    }
    has_source_failure = bool(baseline_failures or candidate_failures)
    gate_status = "error" if has_source_failure else "fail" if triggered else "pass"
    return {
        "schema_version": REPORT_VERSION,
        "run_id": run_manifest["run_id"],
        "generated_at": run_manifest["generated_at"],
        "counts": {name: comparison.counts[name] for name in DIFF_CLASSES},
        "gate": {
            "status": gate_status,
            "fail_on": fail_on,
            "triggered": triggered,
        },
        "policies": {
            "baseline": dict(run_manifest["baseline"]),
            "candidate": dict(run_manifest["candidate"]),
        },
        "corpus": dict(run_manifest["corpus"]),
        "reproduction_command": reproduction_command,
        "limitations": [DECISION_REPLAY_LIMITATION],
        "source_failures": source_failures,
        "results": [result.as_dict() for result in comparison.results],
    }


def report_json_bytes(report: dict[str, Any]) -> bytes:
    """Serialize a report with stable ordering, indentation, and LF termination."""

    return (
        json.dumps(
            report, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n"
    ).encode("utf-8")


def _table_cell(value: object) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render a compact report whose opening records all operational identity."""

    counts = report["counts"]
    gate = report["gate"]
    baseline = report["policies"]["baseline"]
    candidate = report["policies"]["candidate"]
    corpus = report["corpus"]
    triggered = ", ".join(gate["triggered"]) or "none"
    count_summary = "; ".join(f"{name}={counts[name]}" for name in DIFF_CLASSES)

    lines = [
        "# Replay v0 comparison",
        "",
        f"Counts: {count_summary}.",
        f"Gate: **{gate['status'].upper()}**; triggered: {triggered}.",
        (
            f"Baseline: `{baseline['id']}` ({baseline['kind']}, SHA-256 "
            f"`{baseline['sha256']}`)."
        ),
        (
            f"Candidate: `{candidate['id']}` ({candidate['kind']}, SHA-256 "
            f"`{candidate['sha256']}`)."
        ),
        (
            f"Corpus: `{corpus['id']}` ({corpus['event_count']} events, manifest "
            f"SHA-256 `{corpus['manifest_sha256']}`)."
        ),
        "Reproduce:",
        "",
        f"    {report['reproduction_command']}",
        "",
        "## Event results",
        "",
        "| Event | Classification | Baseline | Candidate |",
        "|---|---|---|---|",
    ]
    for result in report["results"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    _table_cell(result["event"]["event_id"]),
                    _table_cell(result["classification"]),
                    _table_cell(
                        f"{result['baseline']['effect']}: {result['baseline']['reason']}"
                    ),
                    _table_cell(
                        f"{result['candidate']['effect']}: {result['candidate']['reason']}"
                    ),
                )
            )
            + " |"
        )

    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report["limitations"])
    if report["source_failures"]["baseline"] or report["source_failures"]["candidate"]:
        lines.extend(["", "## Source failures", ""])
        for source_name in ("baseline", "candidate"):
            for failure in report["source_failures"][source_name]:
                event = f" for `{failure['event_id']}`" if "event_id" in failure else ""
                lines.append(
                    f"- {source_name}{event}: `{failure['code']}` — "
                    f"{failure['message']}"
                )
    return "\n".join(lines) + "\n"
