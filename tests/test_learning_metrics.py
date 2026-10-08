"""Synthetic learning metrics and sealed CLI integration; no private data."""

import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lm = load_module("learning_metrics")
ledger = load_module("outcome_ledger")
lc = lm.contracts
AT = "2026-09-24T00:00:00Z"
ACTIVE = "2026-10-02T00:00:00Z"
AFTER = "2026-10-03T00:00:00Z"
AS_OF = dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc)
PRODUCER = {"lane": "test", "runtime": "codex", "model": None, "session": "learner"}
ORACLE = {"kind": "oracle", "runtime": "tool", "session": "evaluator"}


def split_key(side):
    return next(f"test-{n}" for n in range(1000) if lc.split_of(f"test-{n}") == side)


def experience(key="run", at=AT, runtime="codex", side="dev", **changes):
    record = {
        "schema": lm.EXPERIENCE,
        "id": lc.experience_id("test", key),
        "at": at,
        "observed_at": at,
        "producer": dict(PRODUCER, runtime=runtime),
        "source": {"kind": "test", "key": key},
        "repo": "synthetic",
        "task_kind": "test",
        "split_key": split_key(side),
        "outcome": {"immediate": "completed", "matured": None, "regression": None},
    }
    record.update(changes)
    return record


def memory(ref="memory:synthetic/lesson.md", **changes):
    item = {"ref": ref, "supplied": True, "read": False, "cited": False, "bytes": 100}
    item.update(changes)
    return item


def memory_use(exp, memories=(), skills=(), **changes):
    record = {
        "schema": lm.MEMORY_USE,
        "id": "mu_" + exp["id"][4:],
        "at": exp["at"],
        "observed_at": exp["observed_at"],
        "producer": dict(PRODUCER),
        "experience": exp["id"],
        "memories": list(memories),
        "skills": list(skills),
        "method": {"supplied": "test", "read": None, "cited": None},
    }
    record.update(changes)
    return record


def candidate(key="lesson", kind="semantic", evidence=None, **changes):
    record = {
        "schema": lm.CANDIDATE,
        "id": "lc_test-" + key,
        "at": AT,
        "producer": dict(PRODUCER),
        "kind": kind,
        "trigger": "manual",
        "claim": "Synthetic lesson claim.",
        "evidence": evidence if evidence is not None else [experience()["id"]],
        "future_decision": "Read the relevant lesson before selecting the next action.",
        "scope": {"repos": ["synthetic"]},
        "destination": (
            None if kind == "episodic" else {"repo": "synthetic", "path": "lesson.md"}
        ),
        "promotion_class": lc.classes()["kind_class"][kind],
        "valid_from": AT,
    }
    record.update(changes)
    return record


def move(cand, n, frm, to, at=ACTIVE, prev=None, gates=(), **changes):
    record = {
        "schema": lm.PROMOTION,
        "id": f"prom_{cand['id'][3:]}-{n}",
        "at": at,
        "producer": dict(PRODUCER),
        "candidate": cand["id"],
        "prev": prev,
        "from": frm,
        "to": to,
        "promotion_class": cand["promotion_class"],
        "effect": "shadow",
        "gates": list(gates),
        "reason": "Synthetic transition.",
    }
    if to == "reverted":
        record["revert"] = {
            "blamed": [cand["id"]],
            "regression_evidence": cand["evidence"],
        }
    record.update(changes)
    return record


def activation(cand, landed="memory:synthetic/lesson.md", at=ACTIVE, until="active"):
    """Build a legal path (or prefix), with each gate judged in its source stay."""
    needed = lc.required_gates(cand)
    states = ["candidate"]
    if cand["promotion_class"] != "P0":
        states.append("evaluating")
        if "canary" in needed or until == "canary":
            states.append("canary")
        states.append("probation")
    states.append("active")
    chain = []
    evaluated_at = (lc.parse_time(cand["at"]) + dt.timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    for frm, to in zip(states, states[1:]):
        when = (
            at if to == "active" else cand["at"] if frm == "candidate" else evaluated_at
        )
        gates = []
        for name in needed:
            if frm not in lc.lifecycle()["gate_sources"][name]:
                continue
            if name == "owner" and to != "active":
                continue
            item = {
                "gate": name,
                "result": "pass",
                "at": when,
                "evaluator": dict(ORACLE),
            }
            if name in ("offline_eval", "replay", "retrieval_regression"):
                item.update(holdout_digest="a" * 64, training_excluded=True, anchors=[])
            if name == "owner":
                item.update(
                    evaluator={"kind": "owner", "runtime": "owner", "session": "owner"},
                    ref="decision:synthetic-approval",
                )
            gates.append(item)
        record = move(
            cand,
            len(chain) + 1,
            frm,
            to,
            at=when,
            prev=chain[-1]["id"] if chain else None,
            gates=gates,
        )
        if to == "active":
            record["landed"] = landed
        chain.append(record)
        if to == until:
            break
    folded = lc.fold(cand, chain, as_of=lc.parse_time(at))
    if folded.errors or folded.state != until:
        raise AssertionError(folded.errors or f"path did not reach {until}")
    return chain


def dataset(*records):
    result = {name: [] for name in lc.RECORD_SCHEMAS}
    result["problems"] = []
    for record in records:
        errors = lc.validate_record(record)
        if errors:
            raise AssertionError(errors)
        result[record["schema"]].append(record)
    return result


def aggregate(*records, split="dev"):
    return lm.learning_metrics(dataset(*records), split)["metrics"]


class MetricTests(unittest.TestCase):
    def test_assisted_delta_uses_supplied_and_rejects_reverted_or_regressed_success(
        self,
    ):
        good = experience("good", memory_used=["memory:synthetic/fallback.md"])
        reverted = experience(
            "reverted",
            outcome={"immediate": "merged", "matured": "reverted", "regression": False},
        )
        regressed = experience(
            "regressed",
            outcome={"immediate": "published", "matured": None, "regression": True},
        )
        plain = experience("plain")
        overridden = experience(
            "overridden", memory_used=["memory:synthetic/fallback.md"]
        )
        result = aggregate(
            good,
            reverted,
            regressed,
            plain,
            overridden,
            memory_use(reverted, [memory()]),
            memory_use(regressed, [memory()]),
            memory_use(overridden, [memory(supplied=False)]),
        )["memory_assisted_task_delta"]
        self.assertEqual(result["with_memory"], {"n": 3, "success_rate": 1 / 3})
        self.assertEqual(result["without_memory"], {"n": 2, "success_rate": 1.0})
        self.assertAlmostEqual(result["delta"], -2 / 3)
        self.assertEqual(result["basis"], "observational")

    def test_harm_excludes_self_and_unknown_but_keeps_neutral(self):
        exp = experience()
        items = [
            memory(effect={"verdict": verdict, "evaluator": dict(ORACLE, kind=kind)})
            for verdict, kind in (
                ("harmed", "oracle"),
                ("helped", "oracle"),
                ("neutral", "oracle"),
                ("harmed", "self"),
                ("unknown", "oracle"),
            )
        ]
        mu = memory_use(exp, items)
        self.assertTrue(
            any("judged by the run itself" in e for e in lc.validate_record(mu))
        )
        # Ingestion rejects self judgments; inject one to exercise the metric's
        # own exclusion as well, rather than weakening this negative fixture.
        records = dataset(exp)
        records[lm.MEMORY_USE].append(mu)
        result = lm.learning_metrics(records)["metrics"]["memory_harm_rate"]
        self.assertEqual(
            result,
            {"n": 3, "harmed": 1, "helped": 1, "harm_rate": 1 / 3, "help_rate": 1 / 3},
        )

    def test_waste_requires_supplied_and_at_least_one_measured_signal(self):
        exp = experience()
        result = aggregate(
            exp,
            memory_use(
                exp,
                [
                    memory(),
                    memory(read=None, cited=False),
                    memory(read=True),
                    memory(cited=True),
                    memory(read=None, cited=None),
                    memory(supplied=False),
                ],
            ),
        )["retrieval_waste"]
        self.assertEqual(result, {"n": 4, "wasted": 2, "rate": 0.5})

    def test_bytes_uses_successful_tasks_with_records_and_counts_unknown(self):
        good, empty, fallback, failed = [
            experience(key) for key in ("good", "empty", "fallback", "failed")
        ]
        failed["outcome"]["regression"] = True
        result = aggregate(
            good,
            empty,
            fallback,
            failed,
            memory_use(
                good,
                [
                    memory(bytes=80),
                    memory(bytes=None),
                    memory(bytes=900, supplied=False),
                ],
            ),
            memory_use(empty),
            memory_use(failed, [memory(bytes=999)]),
        )["memory_bytes_per_successful_task"]
        self.assertEqual(
            result, {"n": 2, "bytes": 80, "unknown_bytes": 1, "per_task": 40}
        )

    def test_lesson_reuse_is_after_activation_matches_versions_and_latest_landed(self):
        cand = candidate()
        chain = activation(cand, "memory:synthetic/old.md")
        chain.append(
            move(
                cand,
                len(chain) + 1,
                "active",
                "reinforced",
                prev=chain[-1]["id"],
                landed="memory:synthetic/new.md@v1",
            )
        )
        before = experience("before", memory_used=["memory:synthetic/new.md"])
        equal = experience("equal", at=ACTIVE, memory_used=["memory:synthetic/new.md"])
        after = experience(
            "after", at=AFTER, memory_used=["memory:synthetic/new.md@v2"]
        )
        old = experience("old", at=AFTER, memory_used=["memory:synthetic/old.md"])
        unsupplied = experience(
            "unsupplied", at=AFTER, memory_used=["memory:synthetic/new.md"]
        )
        unused = candidate("unused", kind="consolidation")
        result = aggregate(
            cand,
            *chain,
            unused,
            *activation(unused, "memory:synthetic/unused.md"),
            before,
            equal,
            after,
            old,
            unsupplied,
            memory_use(unsupplied, [memory("memory:synthetic/new.md", supplied=False)]),
        )["lesson_reuse"]
        self.assertEqual(
            result,
            {"lessons": 2, "reused": 1, "uses": 1, "uses_per_lesson_median": 0.5},
        )

    def test_skill_completion_and_promoted_subset_exclude_unmeasured(self):
        exp, cand = experience(), candidate(kind="skill")
        skills = [
            {"ref": ref, "invoked_by": "model", "completed": completed}
            for ref, completed in (
                ("skill:learned@v2", True),
                ("skill:learned", False),
                ("skill:other", True),
                ("skill:learned", None),
            )
        ]
        result = aggregate(
            exp,
            memory_use(exp, skills=skills),
            cand,
            *activation(cand, "skill:learned@v1"),
        )["skill_reuse_success"]
        self.assertEqual(
            result,
            {
                "n": 3,
                "completed": 2,
                "rate": 2 / 3,
                "promoted": {"n": 2, "completed": 1, "rate": 0.5},
            },
        )

    def test_candidate_ratio_counts_ever_active_and_current_folded_state(self):
        cand, pending = candidate(), candidate("pending", kind="skill")
        chain = activation(cand)
        chain.append(
            move(
                cand,
                len(chain) + 1,
                "active",
                "reverted",
                at=AFTER,
                prev=chain[-1]["id"],
            )
        )
        result = aggregate(cand, pending, *chain)["candidate_to_promoted_ratio"]
        self.assertEqual(
            result,
            {
                "candidates": 2,
                "promoted": 1,
                "ratio": 0.5,
                "by_kind": {
                    "semantic": {"candidates": 1, "promoted": 1},
                    "skill": {"candidates": 1, "promoted": 0},
                },
                "by_state": {"candidate": 1, "reverted": 1},
            },
        )

    def test_revert_rate_separates_canary_and_probation_reverts(self):
        promoted, clean = candidate("reverted"), candidate("clean")
        chain = activation(promoted)
        chain.append(
            move(
                promoted,
                len(chain) + 1,
                "active",
                "reverted",
                at=AFTER,
                prev=chain[-1]["id"],
            )
        )
        records = [promoted, clean, *chain, *activation(clean)]
        for state in ("canary", "probation"):
            cand = candidate(state, kind="prompt")
            prefix = activation(cand, until=state)
            records.extend(
                [
                    cand,
                    *prefix,
                    move(
                        cand,
                        len(prefix) + 1,
                        state,
                        "reverted",
                        at=AFTER,
                        prev=prefix[-1]["id"],
                    ),
                ]
            )
        self.assertEqual(
            aggregate(*records)["promotion_to_revert_rate"],
            {"promoted": 2, "reverted": 1, "rate": 0.5, "pre_promotion_reverts": 2},
        )

    def test_time_to_learn_earliest_complete_evidence_and_ledger_quantiles(self):
        early, late = experience("early"), experience("late", at="2026-09-24T12:00:00Z")
        records = [early, late]
        for n, day in enumerate((2, 3, 4, 5)):
            cand = candidate(str(n), evidence=[late["id"], early["id"]])
            records.extend([cand, *activation(cand, at=f"2026-10-0{day}T00:00:00Z")])
        missing = candidate(
            "missing", evidence=[early["id"], experience("unloaded")["id"]]
        )
        records.extend([missing, *activation(missing)])
        self.assertEqual(
            aggregate(*records)["time_to_learn"],
            {"n": 4, "missing_evidence": 1, "median_hours": 240.0, "p90_hours": 264.0},
        )
        self.assertEqual(ledger._quantile([192, 216, 240, 264], 0.5), 240.0)

    def test_cross_runtime_uses_loaded_evidence_runtimes_and_success_definition(self):
        evidence = experience("evidence", runtime="claude", side="holdout")
        cand = candidate(evidence=[evidence["id"]])
        same = experience(
            "same",
            at=AFTER,
            runtime="claude",
            memory_used=["memory:synthetic/lesson.md"],
        )
        cross = experience(
            "cross", at=AFTER, memory_used=["memory:synthetic/lesson.md"]
        )
        cross["outcome"] = {
            "immediate": "merged",
            "matured": "reverted",
            "regression": False,
        }
        result = aggregate(evidence, cand, *activation(cand), same, cross)[
            "cross_runtime_transfer"
        ]
        self.assertEqual(
            result,
            {
                "lessons": 1,
                "cross": {"n": 1, "success_rate": 0.0},
                "same": {"n": 1, "success_rate": 1.0},
                "unknown_origin": 0,
            },
        )

    def test_uses_of_a_lesson_without_loaded_evidence_are_unknown_origin(self):
        cand = candidate(evidence=[experience("absent")["id"]])
        use = experience("use", at=AFTER, memory_used=["memory:synthetic/lesson.md"])
        result = aggregate(cand, *activation(cand), use)["cross_runtime_transfer"]
        self.assertEqual(result["cross"]["n"], 0)
        self.assertEqual(result["unknown_origin"], 1)

    def test_success_needs_a_succeeding_immediate_outcome(self):
        published = experience(
            "published",
            outcome={"immediate": "published", "matured": None, "regression": None},
        )
        clean = experience(
            "clean",
            outcome={"immediate": "merged", "matured": "clean", "regression": False},
        )
        failed = experience(
            "failed",
            outcome={"immediate": "failed", "matured": None, "regression": None},
        )
        result = aggregate(published, clean, failed)["memory_assisted_task_delta"]
        self.assertEqual(result["without_memory"], {"n": 3, "success_rate": 2 / 3})

    def test_a_candidate_loaded_twice_counts_once(self):
        cand = candidate()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps(cand), encoding="utf-8")
            records = lm.load_learning([path, path])
        self.assertEqual(len(records[lm.CANDIDATE]), 1)
        result = lm.learning_metrics(records)["metrics"]
        self.assertEqual(result["candidate_to_promoted_ratio"]["candidates"], 1)

    def test_owner_correction_recurrence_orders_experiences_and_ignores_other_feedback(
        self,
    ):
        correction = {
            "kind": "owner_correction",
            "ref": "decision:test",
            "signal": "wrong",
            "key": "repeat",
        }
        first = experience("first", feedback=[correction])
        second = experience(
            "second", at=ACTIVE, runtime="claude", feedback=[correction]
        )
        third = experience(
            "third",
            at=AFTER,
            runtime="muse",
            feedback=[
                correction,
                dict(correction, key="unique"),
                dict(correction, kind="ci"),
                {k: v for k, v in correction.items() if k != "key"},
            ],
        )
        self.assertEqual(
            aggregate(third, first, second)["owner_correction_recurrence"],
            {
                "keys": 2,
                "recurred_keys": 1,
                "rate": 0.5,
                "recurrences": 2,
                "by_runtime": {"claude": 1, "muse": 1},
            },
        )

    def test_same_failure_recurrence_counts_every_repeat_and_recurring_runtime(self):
        first = experience("first", failure_keys=["repeat", "unique"])
        second = experience(
            "second", at=ACTIVE, runtime="claude", failure_keys=["repeat"]
        )
        third = experience("third", at=AFTER, runtime="claude", failure_keys=["repeat"])
        self.assertEqual(
            aggregate(third, second, first)["same_failure_recurrence"],
            {
                "keys": 2,
                "recurred_keys": 1,
                "rate": 0.5,
                "recurrences": 2,
                "by_runtime": {"claude": 2},
            },
        )

    def test_empty_denominators_are_null(self):
        result = aggregate()
        for name, field in (
            ("memory_harm_rate", "harm_rate"),
            ("retrieval_waste", "rate"),
            ("memory_bytes_per_successful_task", "per_task"),
            ("lesson_reuse", "uses_per_lesson_median"),
            ("skill_reuse_success", "rate"),
            ("candidate_to_promoted_ratio", "ratio"),
            ("promotion_to_revert_rate", "rate"),
            ("time_to_learn", "median_hours"),
            ("owner_correction_recurrence", "rate"),
            ("same_failure_recurrence", "rate"),
        ):
            self.assertIsNone(result[name][field], name)
        self.assertIsNone(result["memory_assisted_task_delta"]["delta"])
        self.assertIsNone(result["cross_runtime_transfer"]["cross"]["success_rate"])
        self.assertIsNone(result["skill_reuse_success"]["promoted"]["rate"])

    def test_fold_error_keeps_applied_prefix_and_excludes_invalid_landed(self):
        cand = candidate()
        chain = activation(cand)
        chain.append(
            move(
                cand,
                len(chain) + 1,
                "reinforced",
                "reinforced",
                at=AFTER,
                prev=chain[-1]["id"],
                landed="memory:synthetic/invalid.md",
            )
        )
        exp = experience("use", at=AFTER, memory_used=["memory:synthetic/lesson.md"])
        result = lm.learning_metrics(dataset(cand, *chain, exp))
        self.assertEqual(result["metrics"]["lesson_reuse"]["uses"], 1)
        self.assertEqual(
            result["metrics"]["candidate_to_promoted_ratio"]["by_state"], {"active": 1}
        )
        self.assertTrue(result["problems"])

    def test_failed_activation_never_counts_as_promoted(self):
        cand = candidate()
        chain = activation(cand)
        chain[-1]["gates"] = []
        result = lm.learning_metrics(dataset(cand, *chain))
        self.assertEqual(
            result["metrics"]["candidate_to_promoted_ratio"]["promoted"], 0
        )
        self.assertEqual(result["metrics"]["lesson_reuse"]["lessons"], 0)
        self.assertTrue(result["problems"])

    def test_split_filters_experiences_and_memory_use_not_candidates(self):
        dev, holdout = experience("dev"), experience("holdout", side="holdout")
        cand = candidate(evidence=[holdout["id"]])
        records = dataset(
            dev,
            holdout,
            memory_use(dev, [memory()]),
            memory_use(holdout, [memory(), memory()]),
            cand,
            *activation(cand),
        )
        result = lm.learning_metrics(records)
        self.assertEqual(result["split"], "dev")
        self.assertEqual(result["metrics"]["retrieval_waste"]["n"], 1)
        self.assertEqual(
            result["holdout_manifest"],
            {
                "experiences": 1,
                "digest": hashlib.sha256(holdout["id"].encode()).hexdigest(),
            },
        )
        for split, n in (("holdout", 2), ("all", 3)):
            other = lm.learning_metrics(records, split)
            self.assertEqual(other["metrics"]["retrieval_waste"]["n"], n)
            for key in (
                "candidate_to_promoted_ratio",
                "promotion_to_revert_rate",
                "time_to_learn",
            ):
                self.assertEqual(other["metrics"][key], result["metrics"][key])
        self.assertTrue(any("not split" in note for note in result["notes"]))

    def test_deterministic_and_does_not_mutate_input(self):
        cand = candidate()
        records = dataset(experience(), cand, *activation(cand))
        before = copy.deepcopy(records)
        result = json.dumps(lm.learning_metrics(records), sort_keys=True)
        self.assertEqual(
            result,
            json.dumps(lm.learning_metrics(records, as_of=AS_OF), sort_keys=True),
        )
        self.assertEqual(records, before)


class LoadingTests(unittest.TestCase):
    def test_recursive_sorted_loading_validates_and_latest_observation_wins_ties(self):
        exp = experience()
        newest = dict(
            exp,
            observed_at=AFTER,
            outcome={"immediate": "merged", "matured": "reverted", "regression": False},
        )
        mu = memory_use(exp, [memory(bytes=10)])
        newest_mu = memory_use(exp, [memory(bytes=20)], observed_at=AFTER)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nested").mkdir()
            (root / "a.json").write_text(
                json.dumps([newest, newest_mu]), encoding="utf-8"
            )
            (root / "nested" / "b.jsonl").write_text(
                "\n".join(
                    json.dumps(r)
                    for r in (exp, mu, dict(newest_mu, memories=[]), newest)
                ),
                encoding="utf-8",
            )
            (root / "ignore.txt").write_text("not JSON", encoding="utf-8")
            records = lm.load_learning([root])
        self.assertEqual(records[lm.EXPERIENCE], [newest])
        self.assertEqual(records[lm.MEMORY_USE][0]["memories"], [])
        self.assertEqual(records["problems"], [])

    def test_invalid_records_and_unreadable_files_are_reported_not_fatal(self):
        exp = experience()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "a.json"
            path.write_text(
                json.dumps([exp, {"schema": lm.EXPERIENCE}, 7]), encoding="utf-8"
            )
            (root / "b.jsonl").write_text("{broken", encoding="utf-8")
            records = lm.load_learning([root, root / "missing.json"])
        self.assertEqual(records[lm.EXPERIENCE], [exp])
        self.assertEqual(len(records["problems"]), 4)
        self.assertEqual(records["problems"][0]["file"], str(path))
        self.assertEqual(records["problems"][0]["index"], 1)
        self.assertIn("missing required", records["problems"][0]["error"])
        self.assertEqual(len(lm.learning_metrics(records)["problems"]), 4)

    def test_an_observation_that_moves_the_split_is_a_problem(self):
        exp = experience(side="dev")
        moved = dict(exp, observed_at=AFTER, split_key=split_key("holdout"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            path.write_text(json.dumps([exp, moved]), encoding="utf-8")
            records = lm.load_learning([path])
        self.assertEqual(records[lm.EXPERIENCE], [exp])
        self.assertIn("split_key differs", records["problems"][0]["error"])

    def test_a_missing_path_is_a_problem_not_an_empty_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = lm.load_learning([Path(tmp) / "no-such-ledger"])
        self.assertEqual(records["problems"][0]["error"], "no such file or directory")

    def test_one_bad_jsonl_line_keeps_the_rest(self):
        first, second = experience("one"), experience("two")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            path.write_text(
                "\n".join([json.dumps(first), "{broken", json.dumps(second)]) + "\n",
                encoding="utf-8",
            )
            records = lm.load_learning([path])
        self.assertEqual(len(records[lm.EXPERIENCE]), 2)
        self.assertEqual(records["problems"][0]["index"], 1)
        self.assertIn("undecodable line", records["problems"][0]["error"])

    def test_jsonl_keeps_the_strict_reader_bounds_and_survives_a_bad_byte(self):
        first, second = experience("one"), experience("two")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            path.write_bytes(
                b"\xef\xbb\xbf"
                + json.dumps(first).encode("utf-8")
                + b"\n\xff\xfe torn write\n"
                + json.dumps(second).encode("utf-8")
                + b"\n"
            )
            records = lm.load_learning([path])
            self.assertEqual(len(records[lm.EXPERIENCE]), 2)
            self.assertEqual(records["problems"][0]["index"], 1)
            bound = lc.MAX_FILE_BYTES
            lc.MAX_FILE_BYTES = 10
            try:
                records = lm.load_learning([path])
            finally:
                lc.MAX_FILE_BYTES = bound
            self.assertEqual(records[lm.EXPERIENCE], [])
            self.assertIn("size bound", records["problems"][0]["error"])

    def test_a_run_started_before_activation_is_not_reuse(self):
        cand = candidate()
        straddling = experience(
            "straddling",
            at=AFTER,
            started_at=AT,
            memory_used=["memory:synthetic/lesson.md"],
        )
        result = aggregate(cand, *activation(cand), straddling)["lesson_reuse"]
        self.assertEqual(result["uses"], 0)

    def test_counts_include_all_five_schema_names(self):
        result = lm.learning_metrics(dataset())
        self.assertEqual(result["counts"], {name: 0 for name in lc.RECORD_SCHEMAS})

    def test_wrong_typed_schema_is_invalid_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            path.write_text(
                json.dumps([{"schema": []}, experience()]), encoding="utf-8"
            )
            records = lm.load_learning([path])
        self.assertEqual(len(records[lm.EXPERIENCE]), 1)
        self.assertEqual(len(records["problems"]), 1)
        self.assertEqual(records["problems"][0]["index"], 0)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ledger.main(["metrics", *args])
        return code, out.getvalue(), err.getvalue()

    def test_learning_only_repeatable_and_sealed_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev_path, holdout_path = Path(tmp) / "dev.json", Path(tmp) / "holdout.json"
            dev_path.write_text(json.dumps(experience("dev")), encoding="utf-8")
            holdout_path.write_text(
                json.dumps(experience("holdout", side="holdout")), encoding="utf-8"
            )
            args = ("--learning", str(dev_path), "--learning", str(holdout_path))
            code, out, err = self.run_cli(*args)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(
                json.loads(out)["learning"]["metrics"]["memory_assisted_task_delta"][
                    "without_memory"
                ]["n"],
                1,
            )
            for split in ("holdout", "all"):
                code, out, err = self.run_cli(*args, "--split", split)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("sealed", err)
                code, out, err = self.run_cli(
                    *args, "--split", split, "--unseal", "synthetic evaluation"
                )
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(json.loads(out)["learning"]["split"], split)
                self.assertEqual(
                    json.loads(out)["unsealed_because"], "synthetic evaluation"
                )

    def test_missing_both_inputs_refuses_with_exit_two(self):
        code, out, err = self.run_cli()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("at least one", err)

    def test_ledger_only_bytes_identical_and_does_not_load_learning_module(self):
        job = {
            "schema": ledger.SCHEMA,
            "type": "job",
            "id": "synthetic-job",
            "mode": "lens",
            "recipe": "test",
            "runtime": "codex",
            "effort": "high",
            "status": "completed",
            "findings": 2,
            "elapsed_seconds": 5,
            "terminal_reason": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            path.write_text(json.dumps(job) + "\n", encoding="utf-8")
            expected = (
                json.dumps(
                    ledger.metrics(ledger.load_ledger(path), as_of=AS_OF),
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            )
            with patch.object(
                ledger.importlib.util,
                "spec_from_file_location",
                side_effect=AssertionError("unexpected learning import"),
            ):
                code, out, err = self.run_cli(
                    "--ledger", str(path), "--as-of", AS_OF.isoformat()
                )
        self.assertEqual((code, out, err), (0, expected, ""))

    def test_combined_output_preserves_existing_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, learning = Path(tmp) / "ledger.jsonl", Path(tmp) / "learning.json"
            path.write_text("", encoding="utf-8")
            learning.write_text(json.dumps(experience()), encoding="utf-8")
            code, out, err = self.run_cli(
                "--ledger",
                str(path),
                "--learning",
                str(learning),
                "--as-of",
                AS_OF.isoformat(),
            )
        result = json.loads(out)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(result.pop("learning")["schema"], "learning-metrics/v1")
        self.assertEqual(result, ledger.metrics({}, as_of=AS_OF))


if __name__ == "__main__":
    unittest.main()
