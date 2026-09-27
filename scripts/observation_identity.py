"""Inspect content-off source-record identity; never authenticate execution."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

MAX_RECORDS = 5000
MAX_RECORD_BYTES = 64 * 1024
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_INTEGER = 2**63 - 1
A = "agent_harness."
PROFILE = "agent-harness-observation-identity/0"
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", re.ASCII)
SPAN_NAME = re.compile(
    r"(?:invoke_agent|plan|chat|execute_tool|agent_harness\.tool\.(?:execution|permission_wait))"
    r"(?: [A-Za-z0-9][A-Za-z0-9_.:-]{0,127})?"
)
EVENT_NAMES = frozenset(
    A + suffix
    for suffix in ("edit.applied", "verify.result", "request.attempt", "quota.observed", "subagent.completed")
)
COMMON = frozenset({"record_kind", "name", "attributes"})
CONTEXT = frozenset({"trace_id", "span_id"})
SPAN_FIELDS = frozenset({"span_kind", "start_time", "end_time", "duration_ms", "status"})
TOKEN_ATTRS = frozenset(
    A + suffix
    for suffix in ("normalization.profile", "source.name", "source.version", "source.namespace", "source.instance.id", "source.record.id")
) | frozenset({"gen_ai.tool.call.id", "gen_ai.conversation.id", "gen_ai.response.id"})
USAGE_ATTRS = frozenset(
    "gen_ai.usage." + suffix
    for suffix in ("input_tokens", "output_tokens", "cache_read.input_tokens", "cache_write.input_tokens", "reasoning.output_tokens")
)
ENUM_ATTRS = {
    A + "schema.version": frozenset({"0"}),
    A + "content.capture": frozenset({"off"}),
    A + "source.record.identity": frozenset({"native_span", "producer_record", "unavailable"}),
    A + "outcome": frozenset({"success", "failure", "cancelled", "denied", "unknown"}),
    A + "phase": frozenset({"plan", "tool", "edit", "verify"}),
    A + "verify.result": frozenset({"pass", "fail", "error", "not_run"}),
}
ATTEMPTS = A + "request.attempt_count"
GAPS = A + "unavailable"
ATTRS = TOKEN_ATTRS | USAGE_ATTRS | ENUM_ATTRS.keys() | {ATTEMPTS, GAPS}
GAP_REASONS = frozenset({"not_exposed", "not_observed", "not_applicable", "redacted", "incomplete", "invalid"})


class InputError(ValueError):
    """A content-free diagnostic; never include input values or paths."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise InputError(code)


def _enum(value: Any, choices: Iterable[str]) -> bool:
    return type(value) is str and value in choices


def _token(value: Any) -> bool:
    return type(value) is str and TOKEN.fullmatch(value) is not None


def _hex_id(value: Any, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and re.fullmatch(r"[0-9a-f]+", value) is not None
        and value != "0" * length
    )


def _timestamp(value: Any) -> None:
    require(type(value) is str and TIMESTAMP.fullmatch(value) is not None, "invalid_timestamp")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise InputError("invalid_timestamp") from None


def _validate(record: Any) -> tuple[str, ...] | None:
    require(type(record) is dict and COMMON <= record.keys(), "invalid_record")
    kind = record["record_kind"]
    require(_enum(kind, {"span", "event"}), "invalid_record_kind")
    allowed = COMMON | CONTEXT | (SPAN_FIELDS | {"parent_span_id"} if kind == "span" else {"time"})
    require(record.keys() <= allowed, "unsupported_field")
    if kind == "span":
        require(CONTEXT | SPAN_FIELDS <= record.keys(), "incomplete_span")
        require(type(record["name"]) is str and SPAN_NAME.fullmatch(record["name"]) is not None, "unsupported_name")
        require(_enum(record["span_kind"], {"INTERNAL", "CLIENT"}), "invalid_span_kind")
        require(_enum(record["status"], {"UNSET", "OK", "ERROR"}), "invalid_status")
        for field in ("start_time", "end_time"):
            _timestamp(record[field])
        duration = record["duration_ms"]
        require(type(duration) in (int, float) and 0 <= duration <= MAX_INTEGER and math.isfinite(duration), "invalid_duration")
        if "parent_span_id" in record and record["parent_span_id"] is not None:
            require(_hex_id(record["parent_span_id"], 16), "invalid_context")
    else:
        require("time" in record, "missing_time")
        _timestamp(record["time"])
        require(_enum(record["name"], EVENT_NAMES), "unsupported_name")
    require(("trace_id" in record) == ("span_id" in record), "incomplete_context")
    if "trace_id" in record:
        require(_hex_id(record["trace_id"], 32) and _hex_id(record["span_id"], 16), "invalid_context")

    attrs = record["attributes"]
    required_attrs = {A + "schema.version", A + "source.name", A + "content.capture"}
    require(type(attrs) is dict and required_attrs <= attrs.keys(), "invalid_attributes")
    require(attrs.keys() <= ATTRS, "unsupported_attribute")
    for name, value in attrs.items():
        if name in TOKEN_ATTRS:
            require(_token(value), "invalid_identifier")
        elif name in ENUM_ATTRS:
            require(_enum(value, ENUM_ATTRS[name]), "unsupported_attribute_value")
        elif name in USAGE_ATTRS or name == ATTEMPTS:
            require(type(value) is int and (1 if name == ATTEMPTS else 0) <= value <= MAX_INTEGER, "invalid_count")
        elif name == GAPS:
            require(type(value) is dict and len(value) <= len(ATTRS) + len(allowed), "invalid_unavailable")
            for field, reason in value.items():
                require(type(field) is str and field in (ATTRS | allowed) - {GAPS}, "unsupported_unavailable_field")
                require(field not in record and field not in attrs, "contradictory_unavailable")
                require(_enum(reason, GAP_REASONS), "invalid_unavailable_reason")
    mode = attrs.get(A + "source.record.identity", "unavailable")
    require(mode != "native_span" or kind == "span", "identity_kind_mismatch")
    require(mode != "producer_record" or kind == "event", "identity_kind_mismatch")
    namespace = attrs.get(A + "source.namespace")
    if mode == "unavailable" or namespace is None or A + "normalization.profile" not in attrs:
        return None
    prefix = (attrs[A + "source.name"], namespace, kind, mode)
    if mode == "native_span":
        return prefix + (record["trace_id"], record["span_id"])
    instance, identity = attrs.get(A + "source.instance.id"), attrs.get(A + "source.record.id")
    return prefix + (instance, identity) if instance is not None and identity is not None else None


def inspect_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate only supplied source claims, without returning identifiers."""
    groups: dict[tuple[str, ...], tuple[bytes, int, bool]] = {}
    received = unavailable = total_bytes = 0
    for record in records:
        received += 1
        require(received <= MAX_RECORDS, "too_many_records")
        key = _validate(record)
        # Compare every accepted field. Integer versus float types remain conservative.
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        total_bytes += len(encoded) + 1
        require(len(encoded) <= MAX_RECORD_BYTES and total_bytes <= MAX_INPUT_BYTES, "input_too_large")
        if key is None:
            unavailable += 1
        elif key not in groups:
            groups[key] = (encoded, 1, False)
        else:
            first, count, conflict = groups[key]
            groups[key] = (first, count + 1, conflict or encoded != first)
    consistent = duplicate = conflicting_keys = conflicting_rows = 0
    for _, count, conflict in groups.values():
        if conflict:
            conflicting_keys += 1
            conflicting_rows += count
        else:
            consistent += 1
            duplicate += count - 1
    state = "conflicting" if conflicting_keys else "unavailable" if unavailable else "consistent" if received else "empty"
    return {
        "profile": PROFILE,
        "scope": "supplied_source_records_only",
        "execution_verified": False,
        "gate_eligible": False,
        "merge_verdict": None,
        "capture_completeness": "unknown",
        "identity_state": state,
        "received_records": received,
        "distinct_keys": len(groups),
        "consistent_records": consistent,
        "duplicate_records": duplicate,
        "conflicting_keys": conflicting_keys,
        "conflicting_records": conflicting_rows,
        "unavailable_identity_records": unavailable,
        "deduplicated_records": consistent if state == "consistent" else None,
    }


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _constant(_: str) -> Any:
    raise InputError("nonfinite_json_number")


def _float(value: str) -> float:
    number = float(value)
    require(math.isfinite(number), "nonfinite_json_number")
    return number


def _file_stamp(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _same_after_open(before: os.stat_result, opened: os.stat_result) -> bool:
    """Cross-API (lstat vs fstat) identity for the TOCTOU open check.
    POSIX st_ctime is last-metadata-change time, so exact equality detects replacement.
    Windows st_ctime is creation (birth) time with no content-change signal beyond
    dev/ino/mode/size/mtime, and path lstat vs handle fstat can disagree by ~1ms on
    the same stable file. Exclude creation time only here on Windows; POSIX keeps the
    full stamp and the handle-vs-handle check after the read keeps the full stamp.
    """
    return (
        _file_stamp(before) == _file_stamp(opened)
        if os.name != "nt"
        else (
            (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_size,
                before.st_mtime_ns,
            )
            == (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_size,
                opened.st_mtime_ns,
            )
        )
    )


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read one bounded regular local file. No directories, stdin or raw logs."""
    fd = None
    try:
        require(not str(path).startswith(("//", "\\\\")), "unsupported_path")
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and not (getattr(before, "st_file_attributes", 0) & 0x400), "not_regular_file")
        require(before.st_size <= MAX_INPUT_BYTES, "input_too_large")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags)
        opened = os.fstat(fd)
        require(
            stat.S_ISREG(opened.st_mode) and _same_after_open(before, opened),
            "input_changed",
        )
        with os.fdopen(fd, "rb") as stream:
            fd = None
            payload = stream.read(MAX_INPUT_BYTES + 1)
            require(_file_stamp(os.fstat(stream.fileno())) == _file_stamp(opened), "input_changed")
        require(len(payload) <= MAX_INPUT_BYTES, "input_too_large")
    except (OSError, ValueError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("unreadable_input") from None
    finally:
        if fd is not None:
            os.close(fd)
    if not payload:
        return []
    lines = payload.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    require(len(lines) <= MAX_RECORDS, "too_many_records")
    records = []
    for line in lines:
        require(len(line) <= MAX_RECORD_BYTES, "record_too_large")
        try:
            text = line.decode("utf-8")
            require(not text.startswith("\ufeff") and bool(text.strip()), "invalid_jsonl")
            records.append(json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float))
        except (ValueError, RecursionError):
            raise InputError("invalid_jsonl") from None
    return records


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError("invalid_arguments")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="observation_identity", description=__doc__)
    parser.add_argument("input", type=Path, help="content-off normalized JSONL file")
    try:
        args = parser.parse_args(argv)
        report = inspect_records(read_records(args.input))
    except InputError as exc:
        print("observation_identity: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
