#!/usr/bin/env python3
"""Validator and lifecycle fold for the learning-plane contracts.

The JSON Schemas under ``schemas/learning/`` are the contract; this module is
their standard-library reader. It interprets the subset of JSON Schema those
files use (and refuses a schema that uses anything else), then adds the rules a
schema cannot express: deterministic ids, timestamp order, the promotion-class
floor, a non-placeholder ``future_decision``, legal lifecycle edges, gate
placement, and, across a candidate's promotion records, the activation gates
of its class with an evaluator that is not the learner.

    validate_record(record)          -> [error, ...]
    fold(candidate, records)         -> Fold(state, effect, gates, chain, errors)
    experience_id(kind, key)         -> "exp_<16 hex>"
    split_of(split_key)              -> "dev" | "holdout"

Records are private and live outside every repository (SPECS.md section 15);
this module reads what it is given and writes nothing.
"""

import argparse
from collections import namedtuple
import datetime as dt
import functools
import hashlib
import json
import math
from pathlib import Path
import re
import sys

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "learning"
RECORD_SCHEMAS = {
    "estate-experience/v1": "estate-experience.schema.json",
    "memory-use/v1": "memory-use.schema.json",
    "learning-candidate/v1": "learning-candidate.schema.json",
    "candidate-genome/v1": "candidate-genome.schema.json",
    "promotion-record/v1": "promotion-record.schema.json",
    "eval-case/v1": "eval-case.schema.json",
    "eval-outputs/v1": "eval-outputs.schema.json",
    "eval-labels/v1": "eval-labels.schema.json",
    "eval-run/v1": "eval-run.schema.json",
    "system-run/v1": "system-run.schema.json",
    "decision-resolution/v1": "decision-resolution.schema.json",
    "learning-would-apply/v1": "would-apply.schema.json",
}
SPLIT_SALT = "estate-experience/v1/split"
HOLDOUT_PERCENT = 20
MAX_FILE_BYTES = 64 * 1024 * 1024
# Every keyword the learning schemas may use. Anything else is a schema this
# reader cannot honour, so it refuses rather than silently skipping a rule.
SUPPORTED_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$ref",
        "$defs",
        "title",
        "description",
        "format",
        "type",
        "enum",
        "const",
        "properties",
        "required",
        "additionalProperties",
        "propertyNames",
        "minProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "pattern",
        "anyOf",
        "allOf",
        "if",
        "then",
    }
)
PLACEHOLDERS = frozenset(
    {"n/a", "na", "none", "tbd", "todo", "unknown", "nothing", "same", "-", "?"}
)

Fold = namedtuple("Fold", "state effect gates chain errors")


class ContractError(Exception):
    """The contract files themselves are unusable (exit 2), never a record error."""


# -- loading ----------------------------------------------------------------


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-finite JSON number {value}")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def loads(text):
    """Strict JSON: duplicate keys and non-finite numbers are errors."""
    return json.loads(
        text,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )


def read_records(path):
    """Records from a .json file (object or array) or a .jsonl file."""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"{path}: exceeds the size bound")
    text = raw.decode("utf-8-sig")
    if str(path).endswith(".jsonl"):
        return [loads(line) for line in text.splitlines() if line.strip()]
    value = loads(text)
    return value if isinstance(value, list) else [value]


@functools.lru_cache(maxsize=None)
def _document(name):
    path = SCHEMA_DIR / name
    try:
        document = loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    if name.endswith(".schema.json"):
        _audit_keywords(document, name)
    return document


def _audit_keywords(node, where):
    if isinstance(node, list):
        for item in node:
            _audit_keywords(item, where)
        return
    if not isinstance(node, dict):
        return
    unknown = set(node) - SUPPORTED_KEYWORDS
    if unknown:
        raise ContractError(f"{where}: unsupported schema keywords {sorted(unknown)}")
    for key, value in node.items():
        if key in ("properties", "$defs"):
            for name, child in value.items():
                _audit_keywords(child, f"{where}/{key}/{name}")
        elif key in ("enum", "const", "required", "type"):
            continue
        elif isinstance(value, (dict, list)):
            _audit_keywords(value, f"{where}/{key}")


def lifecycle():
    return _document("lifecycle.json")


def classes():
    return _document("promotion-classes.json")


# -- the JSON Schema subset -------------------------------------------------


def _numeric_normal(value):
    """JSON Schema instance equality: 1 and 1.0 are the same number."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_numeric_normal(v) for v in value]
    if isinstance(value, dict):
        return {k: _numeric_normal(v) for k, v in value.items()}
    return value


def _canonical(value):
    return json.dumps(_numeric_normal(value), sort_keys=True, separators=(",", ":"))


def _is_type(value, name):
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        if isinstance(value, float):
            return value.is_integer()
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    raise ContractError(f"unknown JSON type {name!r}")


@functools.lru_cache(maxsize=None)
def _regex(pattern):
    return re.compile(pattern)


def _pattern_matches(pattern, value):
    """ECMA-262 search semantics: a final $ does not match before a trailing newline."""
    match = _regex(pattern).search(value)
    if match is None:
        return False
    anchored_end = pattern.endswith("$") and not pattern.endswith("\\$")
    return not (anchored_end and match.end() != len(value))


def _resolve(ref, base):
    target, _, pointer = ref.partition("#")
    name = target or base
    node = _document(name)
    for part in [p for p in pointer.split("/") if p]:
        try:
            node = node[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError) as exc:
            raise ContractError(f"unresolvable $ref {ref!r} from {base}") from exc
    return node, name


def _schema_errors(value, schema, base, path):
    if "$ref" in schema:
        target, target_base = _resolve(schema["$ref"], base)
        errors = _schema_errors(value, target, target_base, path)
        rest = {k: v for k, v in schema.items() if k != "$ref"}
        return errors + _schema_errors(value, rest, base, path) if rest else errors
    errors = []
    where = path or "$"
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            return [f"{where}: expected {'|'.join(names)}"]
    if "const" in schema and _canonical(value) != _canonical(schema["const"]):
        errors.append(f"{where}: must be {_canonical(schema['const'])}")
    if "enum" in schema and _canonical(value) not in {
        _canonical(v) for v in schema["enum"]
    }:
        errors.append(f"{where}: not one of {_canonical(schema['enum'])}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{where}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{where}: longer than {schema['maxLength']}")
        if "pattern" in schema and not _pattern_matches(schema["pattern"], value):
            errors.append(f"{where}: does not match {schema['pattern']}")
    if _is_type(value, "number") and "minimum" in schema:
        if value < schema["minimum"]:
            errors.append(f"{where}: below {schema['minimum']}")
    if _is_type(value, "number") and "maximum" in schema:
        if value > schema["maximum"]:
            errors.append(f"{where}: above {schema['maximum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{where}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = [_canonical(v) for v in value]
            if len(set(seen)) != len(seen):
                errors.append(f"{where}: items are not unique")
        if "items" in schema:
            for index, item in enumerate(value):
                errors += _schema_errors(
                    item, schema["items"], base, f"{where}[{index}]"
                )
    if isinstance(value, dict):
        errors += _object_errors(value, schema, base, where)
    for branch in schema.get("allOf", ()):
        errors += _schema_errors(value, branch, base, path)
    if "anyOf" in schema:
        attempts = [_schema_errors(value, b, base, path) for b in schema["anyOf"]]
        if all(attempts):
            closest = min(attempts, key=len)
            errors.append(f"{where}: matches no allowed form ({closest[0]})")
    if "if" in schema and not _schema_errors(value, schema["if"], base, path):
        errors += _schema_errors(value, schema.get("then", {}), base, path)
    return errors


def _object_errors(value, schema, base, where):
    errors = []
    for name in schema.get("required", ()):
        if name not in value:
            errors.append(f"{where}: missing required {name!r}")
    if len(value) < schema.get("minProperties", 0):
        errors.append(f"{where}: fewer than {schema['minProperties']} properties")
    properties = schema.get("properties", {})
    extra = schema.get("additionalProperties", True)
    for name, item in value.items():
        child = f"{where}.{name}"
        if "propertyNames" in schema:
            for problem in _schema_errors(name, schema["propertyNames"], base, child):
                errors.append(f"{child}: property name invalid ({problem})")
        if name in properties:
            errors += _schema_errors(item, properties[name], base, child)
        elif extra is False:
            errors.append(f"{child}: unexpected property")
        elif isinstance(extra, dict):
            errors += _schema_errors(item, extra, base, child)
    return errors


def schema_errors(record, schema_name):
    """Structural errors of ``record`` against one schema file."""
    return _schema_errors(record, _document(schema_name), schema_name, "")


# -- rules a schema cannot express ------------------------------------------


def parse_time(value):
    """A contract timestamp as an aware datetime, or None if it is not one."""
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def _digest16(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def experience_id(kind, key):
    """The deterministic experience id: one run, one id, however often observed."""
    return "exp_" + _digest16(f"{kind}|{key}")


def split_of(split_key):
    """Sealed hold-out membership; runs sharing a split_key share a side."""
    digest = hashlib.sha256(f"{SPLIT_SALT}|{split_key}".encode("utf-8")).hexdigest()
    return "holdout" if int(digest[:8], 16) % 100 < HOLDOUT_PERCENT else "dev"


SUCCEEDING = ("completed", "published", "merged")


def experience_succeeded(record):
    """The one success definition: it finished well and nothing later undid it."""
    outcome = record["outcome"]
    return (
        outcome["immediate"] in SUCCEEDING
        and outcome["matured"] != "reverted"
        and outcome["regression"] is not True
    )


def experience_split_key(record):
    """The split key in force: split_key, else source.kind|source.key."""
    source = record["source"]
    return record.get("split_key") or f"{source['kind']}|{source['key']}"


def experience_split(record):
    return split_of(experience_split_key(record))


def class_rank(name):
    return int(name[1:])


def _time_errors(record, fields):
    errors = []
    for field in fields:
        if record.get(field) is not None and parse_time(record[field]) is None:
            errors.append(f"$.{field}: not a real UTC instant")
    return errors


def _ordered(record, early, late):
    a, b = parse_time(record.get(early)), parse_time(record.get(late))
    if a and b and a > b:
        return [f"$.{late}: earlier than {early}"]
    return []


def _experience_rules(record):
    errors = _time_errors(record, ("at", "observed_at", "started_at"))
    errors += _ordered(record, "started_at", "at") + _ordered(
        record, "at", "observed_at"
    )
    source = record["source"]
    expected = experience_id(source["kind"], source["key"])
    if record["id"] != expected:
        errors.append(
            f"$.id: must be {expected} (exp_ + sha256(source.kind|source.key)[:16])"
        )
    outcome = record["outcome"]
    if outcome["matured"] is not None and outcome["immediate"] != "merged":
        errors.append("$.outcome.matured: only a merged run matures")
    for index, item in enumerate(record.get("feedback", ())):
        errors += [f"$.feedback[{index}]{e[1:]}" for e in _time_errors(item, ("at",))]
    return errors


def _memory_use_rules(record):
    errors = _time_errors(record, ("at", "observed_at"))
    errors += _ordered(record, "at", "observed_at")
    if record["id"][3:] != record["experience"][4:]:
        errors.append("$.id: must be mu_ + the experience id's suffix")
    for index, item in enumerate(record["memories"]):
        if item["cited"] and not (item["supplied"] or item["read"]):
            errors.append(f"$.memories[{index}]: cited but never supplied or read")
    for field in ("memories", "skills"):
        for index, item in enumerate(record[field]):
            judge = item.get("effect", {}).get("evaluator")
            if judge and (
                judge["kind"] == "self"
                or judge["session"] == record["producer"]["session"]
            ):
                errors.append(f"$.{field}[{index}].effect: judged by the run itself")
    return errors


def _words(text):
    return re.findall(r"\w+", text.casefold())


# -- class is the blast radius (K2) ------------------------------------------


def _max_class(*names):
    return max(names, key=class_rank)


def destination_class(destination):
    """(class, reasons): the lowest class whose allowlist admits the destination.

    No destination is an episodic record (P0). A destination on no allowlist,
    or one that cannot be checked, is P8: unknown blast radius fails closed.
    """
    if destination is None:
        return "P0", []
    rules = classes()["destinations"]
    where = f"{destination.get('repo')}:{destination.get('path')}"
    try:
        admitted = [
            rule["class"]
            for rule in rules["allow"]
            if _pattern_matches(rule["repo"], destination["repo"])
            and _pattern_matches(rule["path"], destination["path"])
        ]
    except (KeyError, TypeError, re.error):
        return rules["default_class"], [f"destination {where} cannot be checked"]
    if not admitted:
        return rules["default_class"], [
            f"destination {where} is on no class's allowlist"
        ]
    cls = min(admitted, key=class_rank)
    return cls, [f"destination {where} is a {cls} surface"]


def content_class(texts):
    """(class, reasons): authority or permission language anywhere makes it P8."""
    rules = classes()["content"]
    found = []
    for text in texts:
        if not isinstance(text, str):
            continue
        folded = text.casefold()
        for pattern in rules["patterns"]:
            try:
                hit = re.search(pattern, folded)
            except re.error:
                return rules["class"], [f"content pattern {pattern!r} is broken"]
            if hit:
                found.append(f"authority language {hit.group(0).strip()!r}")
    if found:
        return rules["class"], sorted(set(found))
    return "P0", []


def effective_class(candidate):
    """(class, reasons): max(kind, destination, content), the candidate's blast radius."""
    kind_cls = classes()["kind_class"][candidate["kind"]]
    reasons = [f"kind {candidate['kind']} is {kind_cls}"]
    dest_cls, why = destination_class(candidate["destination"])
    reasons += why
    destination = candidate["destination"] or {}
    context = candidate.get("context") or {}
    texts = [
        candidate["claim"],
        candidate["future_decision"],
        destination.get("path"),
        context.get("preceding_action"),
    ]
    text_cls, why = content_class(texts)
    reasons += why
    return _max_class(kind_cls, dest_cls, text_cls), reasons


def _candidate_rules(record):
    errors = _time_errors(record, ("at", "valid_from", "valid_until"))
    decision = record["future_decision"].strip()
    if decision.lower().strip(" .") in PLACEHOLDERS or len(_words(decision)) < 4:
        errors.append("$.future_decision: must name a concrete future decision")
    elif _words(decision) == _words(record["claim"]):
        errors.append("$.future_decision: restates the claim instead of the decision")
    episodic = record["kind"] == "episodic"
    if record["destination"] is None and not episodic:
        errors.append("$.destination: only an episodic candidate may have none")
    if record["destination"] is not None and episodic:
        errors.append(
            "$.destination: an episodic candidate has none; it writes no surface"
        )
    floor, reasons = effective_class(record)
    if class_rank(record["promotion_class"]) < class_rank(floor):
        errors.append(
            f"$.promotion_class: the candidate is at least {floor} ({'; '.join(reasons)}); "
            "a class is never lowered"
        )
    start, end = parse_time(record["valid_from"]), parse_time(record.get("valid_until"))
    if start and end and end <= start:
        errors.append("$.valid_until: must be after valid_from")
    for field in ("supersedes", "contradicts"):
        if record["id"] in record.get(field, ()):
            errors.append(f"$.{field}: names the candidate itself")
    return errors


def _genome_rules(record):
    errors = _time_errors(record, ("at",))
    if record["parent_genome"] == record["id"]:
        errors.append("$.parent_genome: a genome is not its own parent")
    return errors


def _gate_placement(record):
    errors = []
    life = lifecycle()
    policy = classes()["evaluators"]
    forward = record["to"] in life["forward"]
    names = [gate["gate"] for gate in record["gates"]]
    for name in sorted({n for n in names if names.count(n) > 1}):
        # One result per gate per record: array order is not time order.
        errors.append(f"$.gates: {name} is recorded more than once")
    for index, gate in enumerate(record["gates"]):
        where = f"$.gates[{index}]"
        if parse_time(gate["at"]) is None:
            errors.append(f"{where}.at: not a real UTC instant")
        if record["from"] not in life["gate_sources"][gate["gate"]]:
            errors.append(
                f"{where}: {gate['gate']} is not recorded leaving {record['from']}"
            )
        evaluator = gate["evaluator"]
        if gate["gate"] == "owner" and evaluator["kind"] not in policy["owner_gate"]:
            errors.append(f"{where}: the owner gate is judged only by the owner")
        if (evaluator["kind"] == "owner") != (evaluator["runtime"] == "owner"):
            errors.append(
                f"{where}.evaluator: owner kind and owner runtime go together"
            )
        if forward and gate["result"] == "fail":
            errors.append(f"{where}: a failed gate cannot move the candidate forward")
    return errors


def _promotion_rules(record):
    errors = _time_errors(record, ("at",))
    life = lifecycle()
    if record["to"] not in life["edges"][record["from"]]:
        errors.append(f"$: {record['from']} -> {record['to']} is not a lifecycle edge")
    errors += _gate_placement(record)
    for field, state in (
        ("merged_into", "merged"),
        ("superseded_by", "superseded"),
        ("revert", "reverted"),
    ):
        if field in record and record["to"] != state:
            errors.append(f"$.{field}: only on a move to {state}")
    if record.get("merged_into") == record["candidate"]:
        errors.append("$.merged_into: a candidate is not merged into itself")
    if record["effect"] == "live" and record["to"] not in life["live_capable"]:
        errors.append(f"$.effect: nothing is live once a candidate is {record['to']}")
    return errors


def _labels_rules(record):
    errors = _time_errors(record, ("at",))
    if record["evaluator"]["kind"] in ("self", "oracle"):
        errors.append(
            "$.evaluator: labels come from a judge, the owner or an independent model, never self or oracle"
        )
    return errors


def _run_rules(record):
    errors = _time_errors(record, ("at",))
    gate = record["gate"]
    if record["tier"] != record["evaluator"]["kind"]:
        errors.append("$.tier: must be the run evaluator's kind")
    if (
        gate is None
        and record["split"] == "holdout"
        and record["verdict"] != "insufficient"
    ):
        errors.append("$.gate: a hold-out pass or fail emits its gate")
    if gate is not None:
        if gate["gate"] != record["gate_name"]:
            errors.append("$.gate.gate: must be the run's gate_name")
        if record["split"] != "holdout" or record["verdict"] != gate["result"]:
            errors.append(
                "$.gate: only a hold-out pass or fail emits a gate, matching the verdict"
            )
        if gate["holdout_digest"] != record["holdout_digest"] or sorted(
            gate["anchors"]
        ) != sorted(record["anchors"]):
            errors.append("$.gate: digest and anchors must match the run's")
    return errors


def _system_rules(record):
    errors = _time_errors(record, ("at",))
    gate = record["gate"]
    if (gate is None) != (record["verdict"] == "insufficient"):
        errors.append("$.gate: a pass or fail emits its canary gate, insufficient none")
    elif gate is not None and (
        gate["gate"] != "canary" or gate["result"] != record["verdict"]
    ):
        errors.append("$.gate: a canary gate matching the verdict")
    return errors


SEMANTIC_RULES = {
    "estate-experience/v1": _experience_rules,
    "memory-use/v1": _memory_use_rules,
    "learning-candidate/v1": _candidate_rules,
    "candidate-genome/v1": _genome_rules,
    "promotion-record/v1": _promotion_rules,
    "eval-case/v1": lambda record: [],
    "eval-outputs/v1": lambda record: _time_errors(record, ("at",)),
    "eval-labels/v1": _labels_rules,
    "eval-run/v1": _run_rules,
    "system-run/v1": _system_rules,
    "decision-resolution/v1": lambda record: _resolution_rules(record),
    "learning-would-apply/v1": lambda record: _would_apply_rules(record),
}


def validate_record(record):
    """Every contract error in one record; [] means valid."""
    if not isinstance(record, dict):
        return ["$: a record is a JSON object"]
    name = record.get("schema")
    if not isinstance(name, str) or name not in RECORD_SCHEMAS:
        return [f"$.schema: unknown record schema {name!r}"]
    errors = schema_errors(record, RECORD_SCHEMAS[name])
    if errors:
        return errors
    return SEMANTIC_RULES[name](record)


# -- the lifecycle fold -----------------------------------------------------


def required_gates(candidate):
    """Gates that must hold a latest pass before the candidate may activate."""
    spec = classes()["classes"][candidate["promotion_class"]]
    gates = list(spec["activation_gates"])
    for flag, extra in sorted(spec["conditional_gates"].items()):
        if candidate.get(flag):
            gates += [g for g in extra if g not in gates]
    return gates


# -- authority: resolved, never asserted (K1) --------------------------------
#
# A record's authority, an owner gate, an approval or a veto window is a
# decision: ref. It means something only when an injected resolver finds the
# decision answered on agent-hq origin/main. The fold stays pure: it never reads
# a file, it asks resolve(ref) and checks the returned decision-resolution/v1.
# Without a resolver nothing is verified, so no live effect above P0 folds and
# no owner gate counts.


def _would_apply_rules(record):
    errors = _time_errors(record, ("at",))
    text = record["bytes"]
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != record["sha256"]:
        errors.append("$.sha256: is not the sha256 of bytes")
    if "\r" in text:
        errors.append("$.bytes: line endings are LF only")
    if (record["op"] == "add") != (record["base"]["blob_sha256"] is None):
        errors.append("$.base.blob_sha256: null exactly when the op adds a file")
    if record["verdict"] == "would_apply":
        authority = record["authority"]
        if not record["eligibility"]["eligible"] or record["eligibility"]["problems"]:
            errors.append(
                "$.verdict: would_apply needs an eligible candidate with no problems"
            )
        if authority["required"] and authority["status"] != "answered":
            errors.append(
                "$.verdict: would_apply needs its required authority answered"
            )
        cls, _ = destination_class(record["destination"])
        if class_rank(record["class"]) < class_rank(cls):
            errors.append(f"$.class: the destination is a {cls} surface")
    return errors


def _resolution_rules(record):
    errors = _time_errors(record, ("answered_at", "created", "expires"))
    decided = record["status"] in ("answered", "defaulted")
    if decided and (record["option"] is None or record["answered_at"] is None):
        errors.append("$: an answered or defaulted decision names its option and time")
    if not decided and record["option"] is not None:
        errors.append(f"$.option: a {record['status']} decision has no option")
    for group in ("exit_bars", "graduation"):
        for name, measure in record["measures"][group].items():
            for field in ("at", "until"):
                value = measure.get(field)
                if value is not None and parse_time(value) is None:
                    errors.append(
                        f"$.measures.{group}.{name}.{field}: not a real UTC instant"
                    )
    return errors


def candidate_digest(candidate):
    """sha256 of the canonical candidate: what an approval may bind to."""
    return hashlib.sha256(_canonical(candidate).encode("utf-8")).hexdigest()


def resolution(ref, resolve):
    """(decision-resolution/v1, None) or (None, why it does not resolve)."""
    if resolve is None:
        return None, "nothing is verified without a resolver"
    if not isinstance(ref, str) or not ref.startswith("decision:"):
        return None, f"{ref!r} is not a decision: ref"
    try:
        resolved = resolve(ref)
    except Exception as exc:  # the resolver is a seam: any failure fails closed
        return None, f"the resolver failed on {ref} ({type(exc).__name__})"
    if resolved is None:
        return None, f"{ref} does not resolve to an agent-hq decision"
    problems = validate_record(resolved)
    if not problems and resolved.get("schema") != "decision-resolution/v1":
        problems = ["not a decision-resolution/v1"]
    if problems:
        return None, f"{ref} resolved to an invalid answer ({problems[0]})"
    if resolved["decision"] != ref[len("decision:") :]:
        return None, f"{ref} resolved to {resolved['decision']}"
    return resolved, None


def _answered_by(resolved, at, allow_default):
    statuses = ("answered", "defaulted") if allow_default else ("answered",)
    if resolved["status"] not in statuses:
        return [
            f"decision {resolved['decision']} is {resolved['status']}, not answered"
        ]
    answered = parse_time(resolved["answered_at"])
    if at is None or answered is None or answered > at:
        return [f"decision {resolved['decision']} was answered after the move"]
    return []


def meaning(resolved):
    """What a per-candidate answer means: its option label, lower-cased.

    The owner answers single-letter keys (a, b); an approval or a veto window
    carries its meaning in the label (Approve or Decline, Allow or Veto).
    """
    label = resolved.get("option_label")
    return label.strip().casefold() if isinstance(label, str) else resolved["option"]


def _subject_errors(ref, resolved, candidate):
    subject = resolved["subject"] or {}
    if subject.get("candidate") != candidate["id"]:
        return [f"{ref} is about {subject.get('candidate')}, not {candidate['id']}"]
    if "digest" in subject and subject["digest"] != candidate_digest(candidate):
        return [f"{ref} approved another version of {candidate['id']}"]
    return []


def approval_errors(ref, candidate, at, resolve):
    """Why ref is not the owner's approval of this candidate by instant at."""
    resolved, why = resolution(ref, resolve)
    if why:
        return [why]
    errors = _answered_by(resolved, at, allow_default=False)
    errors += _subject_errors(ref, resolved, candidate)
    if meaning(resolved) not in classes()["approval"]["grant"]:
        errors.append(
            f"{ref} answered {resolved['option']!r}, which is not an approval"
        )
    return errors


def _veto_errors(ref, candidate, at, days, resolve, opened_after):
    """A veto window opened during this stay, open for its full days, not vetoed.

    Option b promotes unless the owner vetoes, so a window that ran its days
    and expired unanswered allows; only an answered veto blocks.
    """
    if ref is None:
        return [
            "a graduated class goes live only after a veto window (veto: decision:<id>)"
        ]
    resolved, why = resolution(ref, resolve)
    if why:
        return [why]
    errors = _subject_errors(ref, resolved, candidate)
    window = dt.timedelta(days=days)
    opened = parse_time(resolved["created"])
    if opened is None or (opened_after and opened < opened_after):
        errors.append(f"veto window {ref} opened before the stay it closes")
    if at is None or opened is None or at - opened < window:
        errors.append(f"the {days}-day veto window of {ref} has not closed")
    veto = classes()["veto"]
    status = resolved["status"]
    if status in ("answered", "defaulted"):
        errors += _answered_by(resolved, at, allow_default=True)
        answered = parse_time(resolved["answered_at"])
        if status == "defaulted" and opened and answered and answered - opened < window:
            errors.append(f"veto window {ref} defaulted before its {days} days ran")
        if meaning(resolved) in veto["veto"]:
            errors.append(f"the owner vetoed through {ref}")
        elif meaning(resolved) not in veto["allow"]:
            errors.append(
                f"{ref} answered {resolved['option']!r}, neither allow nor veto"
            )
    elif status == "expired":
        expired = parse_time(resolved["expires"])
        if (
            expired is None
            or opened is None
            or expired - opened < window
            or expired > at
        ):
            errors.append(f"veto window {ref} expired without running {days} days")
    else:
        errors.append(f"veto window {ref} is {status}")
    return errors


def class_option(cls, resolved):
    """The option semantics the class's decision answer gives this class, or None."""
    decision = classes()["decisions"].get(resolved["decision"])
    if decision is None or cls not in decision["classes"]:
        return None
    option = decision["options"].get(resolved["option"])
    if option is None:
        return None
    return (
        option.get("per_class", {}).get(cls, option)
        if "per_class" in option
        else option
    )


def _owner_gate_on(record, candidate, resolve):
    at = parse_time(record["at"])
    return any(
        g["gate"] == "owner"
        and g["result"] == "pass"
        and not approval_errors(g.get("ref"), candidate, at, resolve)
        for g in record["gates"]
    )


def _holds(measure, flag, at):
    """A measure in force at instant at: true, since its at, and not past its until."""
    if not measure or not measure[flag] or at is None:
        return False
    since, until = parse_time(measure["at"]), parse_time(measure.get("until"))
    return since is not None and since <= at and (until is None or at < until)


def _landing_errors(record, candidate, channel, cls):
    """An installed live record names where it landed, in its own repository."""
    landed = str(record.get("landed", ""))
    if channel in ("reviewed_pr", "pr"):
        match = re.fullmatch(
            r"pr:https://github[.]com/([^/]+)/([^/]+)/pull/[0-9]+", landed
        )
        repo = (candidate["destination"] or {}).get("repo", "").split("/")[-1]
        if not match or match.group(2) != repo:
            return [
                f"{cls} lands through a reviewed PR in {repo}: landed: pr:<that PR's url> is required"
            ]
    elif not landed:
        return [f"{cls} names where it landed (landed: memory:... or commit:...)"]
    return []


INSTALLED = ("probation", "active", "reinforced")


def _authority_errors(candidate, record, effect_before, resolve, entered_at=None):
    """Why this live record is not backed by the owner's resolved answer.

    The owner's conditions hold on every live record, not only on activation:
    live is legal in canary, probation, active and reinforced, so whichever
    record turns the candidate live or activates it carries the approval or
    the veto window its class requires, and every installed live record names
    where it landed.
    """
    if record["effect"] != "live":
        return []
    cls = candidate["promotion_class"]
    spec = classes()["authority"][cls]
    if spec["mode"] == "none":
        return []
    if spec["mode"] == "no_live":
        return [f"{cls} has no owner decision, so it never goes live"]
    at = parse_time(record["at"])
    deciding = effect_before != "live" or record["to"] in lifecycle()["activating"]
    errors = []
    if record["to"] == "canary" and "canary" not in required_gates(candidate):
        errors.append(f"{cls} has no canary stage: it is live only once installed")
    if spec["mode"] == "per_promotion":
        # P8: the authority is the owner's approval of this very candidate.
        return errors + approval_errors(record.get("authority"), candidate, at, resolve)
    resolved, why = resolution(record.get("authority"), resolve)
    if why:
        return errors + [why]
    errors += _answered_by(resolved, at, allow_default=False)
    if resolved["decision"] != spec["decision"]:
        return errors + [f"{record['authority']} does not decide {cls}"]
    option = class_option(cls, resolved)
    if option is None:
        return errors + [
            f"option {resolved['option']!r} of {spec['decision']} has no meaning for {cls}"
        ]
    if not option["live"]:
        return errors + [
            f"option {resolved['option']} of {spec['decision']} keeps {cls} in shadow"
        ]
    bar = option.get("exit_bar")
    if bar and not _holds(resolved["measures"]["exit_bars"].get(bar), "met", at):
        errors.append(f"exit bar {bar} is not met at {record['at']}")
    approval = option.get("approval", "none")
    graduated = approval == "until_graduated" and _holds(
        resolved["measures"]["graduation"].get(cls), "graduated", at
    )
    needs_approval = (
        approval == "per_promotion"
        or (approval == "until_graduated" and not graduated)
        or (bool(candidate.get("protected")) and option.get("protected_approval", True))
    )
    if needs_approval and deciding and not _owner_gate_on(record, candidate, resolve):
        errors.append(
            f"{cls} goes live and activates only with the owner's approval of this candidate on that record"
        )
    if approval == "until_graduated" and graduated and deciding:
        errors += _veto_errors(
            record.get("veto"), candidate, at, option["veto_days"], resolve, entered_at
        )
    if record["to"] in INSTALLED:
        errors += _landing_errors(record, candidate, option.get("channel"), cls)
    return errors


def exit_bar_status(name, measured):
    """Whether an exit bar is met by its measured values.

    Every target is a floor ("min") or a ceiling ("max"). The resolver calls
    this and reports the result as measures.exit_bars; a measure that was not
    provided is listed under missing, never read as 0.
    """
    bar = classes()["exit_bars"][name]
    targets = bar["targets"]
    missing = sorted(k for k in targets if measured.get(k) is None)
    met = not missing and all(
        measured[k] >= t["min"] if "min" in t else measured[k] <= t["max"]
        for k, t in targets.items()
    )
    return {"met": met, "missing": missing, "targets": targets, "measured": measured}


def graduation_status(name, approved_at, reverted_at, as_of):
    """Whether a class has graduated by as_of: enough approvals, enough days, no revert.

    approved_at and reverted_at are instants of the class's approved
    promotions and reverts; a revert restarts the count. Events after as_of
    never change the status at as_of.
    """
    rule = classes()["graduations"][name]
    approved_at = [a for a in approved_at if a <= as_of]
    reverted_at = [r for r in reverted_at if r <= as_of]
    restart = max(reverted_at) if reverted_at and rule["revert_restarts"] else None
    counted = sorted(a for a in approved_at if restart is None or a > restart)
    if len(counted) < rule["approved_min"]:
        return {"graduated": False, "at": None, "approved": len(counted)}
    when = max(
        counted[rule["approved_min"] - 1],
        counted[0] + dt.timedelta(days=rule["days"]),
    )
    graduated = when <= as_of
    stamp = when.strftime("%Y-%m-%dT%H:%M:%SZ") if graduated else None
    return {"graduated": graduated, "at": stamp, "approved": len(counted)}


def resolver_from(resolutions):
    """A resolver over decision-resolution/v1 records the caller already trusts.

    This is how a caller that read agent-hq origin/main hands its answers to the
    fold; the records themselves are not proof of anything.
    """
    by_ref = {
        f"decision:{r['decision']}": r
        for r in resolutions
        if isinstance(r, dict) and isinstance(r.get("decision"), str)
    }
    return by_ref.get


def _counts(gate, candidate, resolve=None):
    """Whether a passing gate result is admissible evidence for this candidate."""
    evaluator = gate["evaluator"]
    policy = classes()["evaluators"]
    if gate["result"] != "pass" or evaluator["kind"] in policy["never_satisfies"]:
        return False
    if gate["gate"] == "owner":
        # The owner gate is the owner's resolved answer, never a claim.
        return not approval_errors(
            gate.get("ref"), candidate, parse_time(gate["at"]), resolve
        )
    # The learner is never its own evaluator, whatever kind it claims to be.
    return evaluator["session"] != candidate["producer"]["session"]


def _independent(gate, candidate, resolve=None):
    """Whether a counted gate vouches as an oracle, the owner or an independent model.

    An evaluator calling itself the owner on an evaluation gate (owner-graded
    labels, say) is a claim the gate's eval-run ref cannot prove, so it
    vouches only when its ref resolves to the owner's approval of this
    candidate; otherwise it counts like any other grader but vouches for nothing.
    """
    kind = gate["evaluator"]["kind"]
    if kind not in classes()["evaluators"]["independent"]:
        return False
    if kind == "owner":
        return not approval_errors(
            gate.get("ref"), candidate, parse_time(gate["at"]), resolve
        )
    return True


def _activation_errors(candidate, latest, record, resolve=None):
    spec = classes()["classes"][candidate["promotion_class"]]
    policy = classes()["evaluators"]
    errors = []
    needed = required_gates(candidate)
    for name in needed:
        gate = latest.get(name)
        if gate is None or not _counts(gate, candidate, resolve):
            errors.append(f"activation needs a latest independent pass of {name}")
    # maturity is a waiting period, not a judgment: it never vouches for the rest.
    judged = [n for n in needed if n not in policy["not_judgment"]]
    satisfied = [
        latest[n]
        for n in judged
        if n in latest and _counts(latest[n], candidate, resolve)
    ]
    if judged and not any(_independent(g, candidate, resolve) for g in satisfied):
        errors.append(
            "activation needs an oracle, owner or independent model, not only an LLM judge"
        )
    if spec["owner_on_activation"] and not any(
        g["gate"] == "owner" and _counts(g, candidate, resolve) for g in record["gates"]
    ):
        errors.append(
            f"{candidate['promotion_class']} is never automatic: the owner pass must be on the activating record"
        )
    return errors


def _chain(records, errors):
    """Order records by prev links; report forks, orphans and cycles."""
    by_prev = {}
    ids = {r["id"] for r in records}
    for record in records:
        by_prev.setdefault(record["prev"], []).append(record)
    for prev, children in by_prev.items():
        if len(children) > 1:
            names = ", ".join(sorted(c["id"] for c in children))
            errors.append(f"fork after {prev or 'creation'}: {names}")
        if prev is not None and prev not in ids:
            errors.append(f"orphan: {children[0]['id']} follows unknown {prev}")
    ordered, cursor, seen = [], None, set()
    while cursor in by_prev and len(by_prev[cursor]) == 1:
        record = by_prev[cursor][0]
        if record["id"] in seen:
            errors.append(f"cycle at {record['id']}")
            break
        seen.add(record["id"])
        ordered.append(record)
        cursor = record["id"]
    if len(ordered) != len(records) and not errors:
        errors.append("records do not form one chain")
    return ordered


def _gate_timing(gate, record, entered_at, left_at, life):
    """A gate is judged while the candidate sits in the state the record leaves."""
    at = parse_time(gate["at"])
    if not (at and entered_at and left_at):
        return []
    problems = []
    if not entered_at <= at <= left_at:
        problems.append(f"{gate['gate']} was judged outside the {record['from']} stay")
    window = dt.timedelta(days=life["maturity_days"])
    if (
        gate["gate"] == "maturity"
        and gate["result"] == "pass"
        and at - entered_at < window
    ):
        problems.append(
            f"maturity passed before {life['maturity_days']} days of probation"
        )
    return problems


def _live_switch_errors(candidate, record, effect, resolve=None):
    """A never-automatic class turns live only with the owner's pass on that record."""
    spec = classes()["classes"][candidate["promotion_class"]]
    if (
        record["effect"] != "live"
        or effect == "live"
        or not spec["owner_on_activation"]
    ):
        return []
    if any(
        g["gate"] == "owner" and _counts(g, candidate, resolve) for g in record["gates"]
    ):
        return []
    return [
        f"{candidate['promotion_class']} is never automatic: the record that turns it live carries the owner pass"
    ]


def _distinct(records):
    """Drop byte-identical retries so an idempotent re-write is not a fork."""
    seen, result = set(), []
    for record in records:
        key = _canonical(record) if isinstance(record, dict) else repr(record)
        if key not in seen:
            seen.add(key)
            result.append(record)
    return result


def fold(candidate, records, as_of=None, resolve=None):
    """Replay a candidate's promotion records into its state.

    The state is the one reached by the longest valid prefix of the chain;
    every problem (an invalid record, a fork, an illegal edge, a missing
    activation gate, a record dated after ``as_of``) is reported and stops the
    fold at that record. Any error forces ``effect`` to shadow: a consumer
    stops applying a candidate whose history it cannot fold, so a broken or
    contested revert fails closed.

    ``resolve`` maps a decision: ref to its decision-resolution/v1 on agent-hq
    origin/main (the store supplies it). Every live record above P0 must be
    backed by the class's resolved answer, and an owner gate counts only as
    the owner's resolved approval of this candidate; with no resolver neither
    can be verified, so neither passes.
    """
    if not isinstance(candidate, dict):
        return Fold(None, None, {}, [], ["candidate: not a JSON object"])
    errors = [f"candidate: {e}" for e in validate_record(candidate)]
    if candidate.get("schema") != "learning-candidate/v1":
        return Fold(
            None, None, {}, [], errors or ["candidate: not a learning candidate"]
        )
    life = lifecycle()
    state, effect, latest, applied = life["initial"], "shadow", {}, []
    if errors:
        return Fold(state, effect, latest, applied, errors)
    valid = []
    for record in _distinct(records):
        problems = validate_record(record)
        if not problems and record["schema"] != "promotion-record/v1":
            problems = ["not a promotion-record/v1"]
        elif not problems and record["candidate"] != candidate["id"]:
            problems = [f"belongs to {record['candidate']}"]
        if problems:
            ident = record.get("id", "?") if isinstance(record, dict) else "?"
            errors += [f"{ident}: {p}" for p in problems]
        else:
            valid.append(record)
    # An invalid record leaves a gap, so the chain stops before it.
    ordered = _chain(valid, errors)
    previous_at = parse_time(candidate["at"])
    for record in ordered:
        where = record["id"]
        problems = []
        if record["from"] != state:
            problems.append(f"leaves {record['from']} but the candidate is {state}")
        if record["promotion_class"] != candidate["promotion_class"]:
            problems.append("promotion_class differs from the candidate's")
        at = parse_time(record["at"])
        if previous_at and at and at < previous_at:
            problems.append("is earlier than the record it follows")
        if as_of and at and at > as_of:
            problems.append("is dated after the fold's as_of instant")
        trial = dict(latest)
        for gate in record["gates"]:
            trial[gate["gate"]] = gate
            problems += _gate_timing(gate, record, previous_at, at, life)
            if as_of and (parse_time(gate["at"]) or as_of) > as_of:
                problems.append(f"{gate['gate']} is dated after the fold's as_of")
            leaked = sorted(set(gate.get("anchors", ())) & set(candidate["evidence"]))
            if leaked:
                problems.append(
                    f"{gate['gate']} evaluated the candidate's own evidence: {leaked[:3]}"
                )
        if record["to"] in life["activating"]:
            problems += _activation_errors(candidate, trial, record, resolve)
        problems += _live_switch_errors(candidate, record, effect, resolve)
        problems += _authority_errors(candidate, record, effect, resolve, previous_at)
        if problems:
            errors += [f"{where}: {p}" for p in problems]
            break
        state, effect, latest, previous_at = record["to"], record["effect"], trial, at
        applied.append(where)
    return Fold(state, "shadow" if errors else effect, latest, applied, errors)


def fold_experiences(records):
    """Latest observation per experience id, and the contract errors across them.

    An experience is re-observed as its outcome advances, but its identity
    (source), its split key and its comparison arm (variant) are fixed by its
    first observation: a later observation that changes one would move a run
    across the hold-out or out of its arm.
    """
    by_id, first, errors = {}, {}, []
    ordered = sorted(
        (r for r in records if isinstance(r, dict)),
        key=lambda r: (
            parse_time(r.get("observed_at"))
            or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            _canonical(r),
        ),
    )
    for record in ordered:
        problems = validate_record(record)
        if not problems and record["schema"] != "estate-experience/v1":
            problems = ["not an estate-experience/v1 record"]
        ident = record.get("id", "?")
        if not problems and ident in first:
            origin = first[ident]
            if experience_split_key(origin) != experience_split_key(record):
                problems.append("split_key differs from the first observation")
            if origin["source"] != record["source"]:
                problems.append("source differs from the first observation")
            if origin.get("variant") != record.get("variant"):
                problems.append("variant differs from the first observation")
        if problems:
            errors += [f"{ident}: {p}" for p in problems]
            continue
        first.setdefault(ident, record)
        by_id[ident] = record
    return by_id, errors


# -- command line -----------------------------------------------------------


def _validate_command(paths):
    report, failed = [], 0
    for path in paths:
        for index, record in enumerate(read_records(path)):
            errors = validate_record(record)
            failed += bool(errors)
            ident = record.get("id") if isinstance(record, dict) else None
            report.append(
                {"file": str(path), "index": index, "id": ident, "errors": errors}
            )
    print(
        json.dumps(
            {"records": len(report), "invalid": failed, "results": report}, indent=2
        )
    )
    return 1 if failed else 0


def _fold_command(candidate_path, records_path, as_of, resolutions=None):
    candidates = read_records(candidate_path)
    if len(candidates) != 1:
        raise ValueError(f"{candidate_path}: expected exactly one candidate")
    records = read_records(records_path) if records_path else []
    instant = parse_time(as_of) if as_of else dt.datetime.now(dt.timezone.utc)
    if instant is None:
        raise ValueError(f"--as-of is not a contract timestamp: {as_of}")
    resolve = resolver_from(read_records(resolutions)) if resolutions else None
    result = fold(candidates[0], records, as_of=instant, resolve=resolve)
    print(json.dumps(result._asdict(), indent=2, sort_keys=True))
    return 1 if result.errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    val = sub.add_parser(
        "validate", help="validate .json/.jsonl records by their schema field"
    )
    val.add_argument("paths", nargs="+", type=Path)
    fld = sub.add_parser(
        "fold", help="replay a candidate's promotion records into its state"
    )
    fld.add_argument("--candidate", type=Path, required=True)
    fld.add_argument("--records", type=Path)
    fld.add_argument("--as-of", help="refuse records dated later (default: now)")
    fld.add_argument(
        "--resolutions",
        type=Path,
        help="decision-resolution/v1 records the caller read from agent-hq origin/main",
    )
    eid = sub.add_parser("experience-id", help="print the deterministic experience id")
    eid.add_argument("--kind", required=True)
    eid.add_argument("--key", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return _validate_command(args.paths)
        if args.command == "fold":
            return _fold_command(
                args.candidate, args.records, args.as_of, args.resolutions
            )
        print(experience_id(args.kind, args.key))
        return 0
    except (ContractError, OSError, ValueError, RecursionError) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
