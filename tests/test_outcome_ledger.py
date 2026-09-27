"""Synthetic swarm runs roots for the outcome ledger; no live receipts, no network."""

import datetime as dt
import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "outcome_ledger.py"
spec = importlib.util.spec_from_file_location("outcome_ledger", MODULE)
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)

OBSERVED = "2026-09-27T12:00:00+00:00"
BASE = "b" * 40


def receipt(recipe="bug-hunt", mode="lens", findings=(), status="completed", **extra):
    data = {
        "schema_version": 2,
        "runtime": "muse",
        "model": "muse-spark-1.3-contributor",
        "effort": "high",
        "mode": mode,
        "recipe": recipe,
        "status": status,
        "terminal_reason": (
            None
            if status == "completed"
            else "model stream idle timeout after 180000ms"
        ),
        "exit_code": 0,
        "elapsed_seconds": 100.0,
        "started_at": "2026-09-26T10:00:00+00:00",
        "worktree": {"base": BASE},
        "report_status": "ok",
        "integrity": "ok",
        "report": (
            {"findings": list(findings), "summary": "s"}
            if mode == "lens"
            else {"status": "done"}
        ),
        "verify": None,
        "measured": {"tool_failure_count": 0},
    }
    data.update(extra)
    return data


def finding(claim, file="src/a.py", line=10, severity="high"):
    return {
        "claim": claim,
        "evidence": "trace " + claim,
        "file": file,
        "line": line,
        "severity": severity,
    }


class Root:
    """A disposable runs root: <root>/<lane>/state/waves/<NNN>/run/<job>/result.json."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "runs"
        self.path.mkdir()

    def cleanup(self):
        self._tmp.cleanup()

    def put(self, lane, wave, job, data):
        target = self.path / lane / "state" / "waves" / wave / "run" / job
        target.mkdir(parents=True, exist_ok=True)
        (target / "result.json").write_text(
            data if isinstance(data, str) else json.dumps(data), encoding="utf-8"
        )

    def coordinator(self, lane, items, turns=()):
        target = self.path / lane / "coordinator"
        target.mkdir(parents=True, exist_ok=True)
        state = {
            "items": items,
            "turns": list(turns),
            "seen_waves": [],
            "workers": {},
            "retired": [],
        }
        (target / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def tree_digest(self):
        digest = hashlib.sha256()
        for path in sorted(self.path.rglob("*")):
            digest.update(str(path.relative_to(self.path)).encode())
            if path.is_file():
                digest.update(path.read_bytes())
        return digest.hexdigest()


def fid(repo, raw):
    return ledger.coordinator_finding_id(repo, raw)


class IdentityTests(unittest.TestCase):
    def test_coordinator_id_matches_the_producer_contract(self):
        # Measured against a live claude-config coordinator item on 2026-09-27.
        claim = (
            "Stale planned brief jobs are never pruned, so every brief edit permanently "
            "orphans a row and brief_jobs grows without bound"
        )
        self.assertEqual(
            ledger.coordinator_finding_id(
                "action-stack", {"file": "server/briefs/store.ts", "claim": claim}
            ),
            "f-a01c6c7c09",
        )

    def test_fingerprint_normalises_path_case_separators_and_line_bucket(self):
        one = ledger.fingerprint("r", "bug-hunt", "Src\\A.py", 41, "The Cache, leaks!")
        two = ledger.fingerprint("r", "bug-hunt", "./src/a.py", 59, "the cache leaks")
        self.assertEqual(one, two)
        self.assertNotEqual(
            one, ledger.fingerprint("r", "bug-hunt", "src/a.py", 60, "the cache leaks")
        )
        self.assertNotEqual(
            one, ledger.fingerprint("r", "test-gaps", "src/a.py", 41, "the cache leaks")
        )

    def test_split_ignores_recipe_so_one_defect_never_straddles(self):
        a = ledger.cluster_key("r", "src/a.py", 3, "same defect")
        self.assertEqual(
            ledger.split_for(a),
            ledger.split_for(ledger.cluster_key("r", "SRC/a.py", 5, "Same defect")),
        )

    def test_holdout_share_is_near_the_declared_percentage(self):
        splits = [
            ledger.split_for(ledger.cluster_key("r", f"f{i}.py", i, f"claim {i}"))
            for i in range(4000)
        ]
        share = splits.count("holdout") / len(splits)
        self.assertAlmostEqual(share, ledger.HOLDOUT_PERCENT / 100, delta=0.03)


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.root = Root()
        self.addCleanup(self.root.cleanup)
        self.real = finding("real defect in parser")
        self.fake = finding("imagined defect", file="src/b.py", line=99, severity="low")
        self.drift = finding("docs claim a flag that exists")
        self.root.put(
            "lane", "001", "app--st-bh1", receipt(findings=[self.real, self.fake])
        )
        self.root.put(
            "lane",
            "002",
            "app--st-dd",
            receipt(recipe="doc-drift", findings=[self.drift]),
        )
        self.root.put("lane", "003", "app--cw-0", receipt(recipe=None, mode="worker"))
        self.root.put(
            "lane",
            "004",
            "app--st-bh1",
            receipt(findings=[self.fake], started_at="2026-09-27T09:00:00+00:00"),
        )
        self.real_id, self.fake_id, self.drift_id = (
            fid("app", f) for f in (self.real, self.fake, self.drift)
        )
        items = {
            self.real_id: {
                "kind": "finding",
                "repo": "app",
                "status": "fixing",
                "class": "medium",
                "decided_by": "codex",
                "verified": False,
                "decided": "2026-09-26T12:00:00+00:00",
                "worker": "cw-0",
                "source": "wave 001 app--st-bh1",
            },
            self.fake_id: {
                "kind": "finding",
                "repo": "app",
                "status": "dropped",
                "class": "low",
                "decided_by": "codex",
                "verified": False,
                "decided": "2026-09-26T12:00:00+00:00",
                "reason": "not reachable",
                "source": "wave 001 app--st-bh1",
            },
            "w-1": {
                "kind": "worktree",
                "repo": "app",
                "status": "published",
                "finding": self.real_id,
                "entry": "cw-0",
                "pr_url": "https://github.com/o/app/pull/7",
                "verify": "passed",
            },
        }
        turns = [
            {
                "kind": "triage",
                "runtime": "codex",
                "status": "ok",
                "seconds": 30.0,
                "dir": "x/20260926T120000",
                "finished": "2026-09-26T12:00:00+00:00",
                "items": [self.real_id, self.fake_id, self.drift_id],
                "attempts": [
                    {"runtime": "codex", "ok": True, "fault": None, "timed_out": False}
                ],
                "outcome": {
                    "fix": [self.real_id],
                    "drop": [self.fake_id, self.drift_id],
                    "defer": [],
                },
            },
            {
                "kind": "publish",
                "runtime": "codex",
                "status": "failed",
                "seconds": 1800.0,
                "dir": "x/20260926T130000",
                "items": ["w-1"],
                "attempts": [
                    {
                        "runtime": "codex",
                        "ok": False,
                        "fault": "timeout",
                        "timed_out": True,
                    }
                ],
                "outcome": {"published": ["w-1"]},
            },
        ]
        self.root.coordinator("lane", items, turns)
        self.root.put(
            "free",
            "001",
            "lib--st-tg",
            receipt(recipe="test-gaps", findings=[finding("untested branch")]),
        )

    def run_extract(self, pr_states=None):
        return ledger.extract(self.root.path, OBSERVED, pr_states)

    def test_extract_joins_receipts_verdicts_workers_and_prs(self):
        records, summary = self.run_extract()
        real = records[f"lane/{self.real_id}"]
        self.assertEqual(real["verdict"], "confirmed")
        self.assertEqual(real["origin"]["recipe"], "bug-hunt")
        self.assertEqual(real["origin"]["base_sha"], BASE)
        self.assertEqual(real["judge"], "codex")
        self.assertEqual(real["pr_url"], "https://github.com/o/app/pull/7")
        self.assertEqual(real["publication"], "published")
        self.assertEqual(records[f"lane/{self.fake_id}"]["verdict"], "refuted")
        self.assertEqual(
            records[f"lane/{self.fake_id}"]["sightings"],
            ["lane/001/app--st-bh1", "lane/004/app--st-bh1"],
        )
        free = [
            r
            for r in records.values()
            if r["type"] == "finding" and r["lane"] == "free"
        ]
        self.assertEqual([r["verdict"] for r in free], ["unjudged"])
        self.assertEqual(summary["counts"]["jobs"], 5)
        self.assertEqual(summary["counts"]["coordinated_lanes"], 1)

    def test_pruned_items_recover_their_verdict_from_turn_outcomes(self):
        records, summary = self.run_extract()
        drift = records[f"lane/{self.drift_id}"]
        self.assertEqual(
            (drift["verdict"], drift["status_raw"], drift["judge"]),
            ("refuted", "pruned", "codex"),
        )
        self.assertEqual(summary["counts"]["verdicts_from_turns"], 1)

    def test_turn_records_carry_faults_and_timeouts(self):
        records, _ = self.run_extract()
        publish = records["lane/turn/20260926T130000"]
        self.assertEqual(
            (publish["status"], publish["timed_out"], publish["faults"]),
            ("failed", True, ["timeout"]),
        )

    def test_unknown_status_is_kept_not_guessed(self):
        state_path = self.root.path / "lane" / "coordinator" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["items"][self.real_id]["status"] = "quarantined"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        records, _ = self.run_extract()
        self.assertEqual(records[f"lane/{self.real_id}"]["verdict"], "unknown")
        self.assertEqual(records[f"lane/{self.real_id}"]["status_raw"], "quarantined")

    def test_unreadable_receipt_is_reported_not_fatal(self):
        self.root.put("lane", "005", "app--broken", "{not json")
        records, summary = self.run_extract()
        self.assertEqual(summary["counts"]["unreadable_receipts"], 1)
        self.assertTrue(summary["problems"][0]["path"].endswith("result.json"))
        self.assertIn(f"lane/{self.real_id}", records)

    def test_ledger_is_deterministic_and_the_runs_root_is_untouched(self):
        before = self.root.tree_digest()
        out_dir = Path(self.root._tmp.name) / "out"
        outputs = []
        for name in ("a.jsonl", "b.jsonl"):
            records, _ = self.run_extract()
            ledger.write_ledger(records, out_dir / name, self.root.path)
            outputs.append((out_dir / name).read_bytes())
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(before, self.root.tree_digest())

    def test_refuses_to_write_inside_the_runs_root(self):
        records, _ = self.run_extract()
        with self.assertRaises(ledger.LedgerError):
            ledger.write_ledger(
                records, self.root.path / "lane" / "ledger.jsonl", self.root.path
            )

    def test_prior_ledger_carries_pruned_records_and_marks_supersession(self):
        records, _ = self.run_extract()
        prior = {k: dict(v) for k, v in records.items()}
        prior["gone/f-0000000000"] = dict(
            records[f"lane/{self.real_id}"], id="gone/f-0000000000"
        )
        prior[f"lane/{self.fake_id}"]["verdict"] = "pending"
        merged, carried = ledger.merge_prior(records, prior)
        self.assertEqual(carried, 1)
        self.assertTrue(merged["gone/f-0000000000"]["carried"])
        self.assertIn("supersedes", merged[f"lane/{self.fake_id}"])
        self.assertNotIn("supersedes", merged[f"lane/{self.real_id}"])

    def test_pr_states_join_on_url(self):
        states = {
            "https://github.com/o/app/pull/7": {
                "state": "MERGED",
                "merged_at": "2026-09-01T00:00:00Z",
                "reverted": False,
            }
        }
        records, _ = self.run_extract(states)
        self.assertEqual(records[f"lane/{self.real_id}"]["pr"]["state"], "MERGED")

    def prune(self, fid):
        path = self.root.path / "lane" / "coordinator" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["items"].pop(fid)
        path.write_text(json.dumps(state), encoding="utf-8")

    def test_a_pruned_item_keeps_its_prior_label_and_pr(self):
        states = {
            "https://github.com/o/app/pull/7": {
                "state": "MERGED",
                "merged_at": "2026-09-01T00:00:00Z",
                "reverted": False,
            }
        }
        prior, _ = self.run_extract(states)
        self.prune(self.real_id)
        # the fix turn survives: current has a weaker, turn-derived label
        current, _ = self.run_extract()
        merged, carried = ledger.merge_prior(current, prior)
        real = merged[f"lane/{self.real_id}"]
        self.assertEqual(carried, 0)
        self.assertEqual(real["verdict"], "confirmed")
        self.assertEqual(real["status_raw"], "fixing")
        self.assertEqual(real["class"], "medium")
        self.assertEqual(real["pr"]["state"], "MERGED")
        self.assertTrue(real["labels_carried"])
        # once the turn has aged out too, the receipt alone still keeps the label
        path = self.root.path / "lane" / "coordinator" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["turns"] = []
        path.write_text(json.dumps(state), encoding="utf-8")
        current, _ = self.run_extract()
        self.assertEqual(current[f"lane/{self.real_id}"]["verdict"], "unjudged")
        merged, _ = ledger.merge_prior(current, prior)
        self.assertEqual(merged[f"lane/{self.real_id}"]["verdict"], "confirmed")
        self.assertTrue(merged[f"lane/{self.real_id}"]["coordinated"])

    def test_a_fresher_item_label_still_wins_over_the_prior(self):
        prior, _ = self.run_extract()
        path = self.root.path / "lane" / "coordinator" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["items"][self.real_id]["status"] = "dropped"
        path.write_text(json.dumps(state), encoding="utf-8")
        current, _ = self.run_extract()
        merged, _ = ledger.merge_prior(current, prior)
        self.assertEqual(merged[f"lane/{self.real_id}"]["verdict"], "refuted")
        self.assertNotIn("labels_carried", merged[f"lane/{self.real_id}"])
        self.assertIn("supersedes", merged[f"lane/{self.real_id}"])

    def test_turn_recovered_verdict_still_joins_the_worktree(self):
        self.prune(self.real_id)
        records, _ = self.run_extract()
        real = records[f"lane/{self.real_id}"]
        self.assertEqual((real["verdict"], real["status_raw"]), ("confirmed", "pruned"))
        self.assertEqual(real["pr_url"], "https://github.com/o/app/pull/7")

    def test_structurally_wrong_json_is_reported_not_fatal(self):
        self.root.put(
            "lane", "006", "app--odd", receipt(report={"findings": 5}, recipe=[1])
        )
        self.root.put("lane", "007", "app--odd2", receipt(worktree="nope"))
        records, summary = self.run_extract()
        # wrong-typed fields degrade to nulls and zero findings rather than aborting
        self.assertEqual(records["lane/006/app--odd"]["findings"], None)
        self.assertIsNone(records["lane/007/app--odd2"]["base_sha"])
        self.assertNotIn("unreadable_receipts", summary["counts"])
        path = self.root.path / "lane" / "coordinator" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["turns"][0]["items"] = 3
        state["turns"][0]["outcome"]["fix"] = 7
        state["items"][self.fake_id]["reason"] = {"nested": True}
        state["items"]["w-2"] = {"kind": "worktree", "finding": ["unhashable"]}
        path.write_text(json.dumps(state), encoding="utf-8")
        records, summary = self.run_extract()
        self.assertNotIn("unreadable_states", summary["counts"])
        self.assertEqual(records[f"lane/{self.real_id}"]["verdict"], "confirmed")
        self.assertEqual(records["lane/turn/20260926T120000"]["items"], 0)

    def test_a_failing_overlay_rolls_back_to_receipt_only_findings(self):
        original = ledger._overlay

        def partial_then_fail(lane, cstate, lane_findings, records, *rest):
            original(lane, cstate, lane_findings, records, *rest)
            raise TypeError("injected after mutation")

        ledger._overlay = partial_then_fail
        self.addCleanup(setattr, ledger, "_overlay", original)
        records, summary = self.run_extract()
        self.assertEqual(summary["counts"]["unreadable_states"], 1)
        self.assertNotIn("coordinated_lanes", summary["counts"])
        self.assertNotIn("lane/turn/20260926T120000", records)
        # no half-applied label set survives the failure
        self.assertEqual(records[f"lane/{self.real_id}"]["verdict"], "unjudged")

    def test_turn_ids_use_the_last_path_component_on_any_platform(self):
        path = self.root.path / "lane" / "coordinator" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["turns"][0]["dir"] = "C:\\runs\\lane\\coordinator\\turns\\20260926T120000"
        del state["turns"][1]["dir"]
        state["turns"][1]["started"] = "2026-09-26T13:00:00+00:00"
        path.write_text(json.dumps(state), encoding="utf-8")
        records, _ = self.run_extract()
        self.assertIn("lane/turn/20260926T120000", records)
        self.assertIn("lane/turn/2026-09-26T13:00:00+00:00-publish", records)


class MetricsTests(unittest.TestCase):
    AS_OF = dt.datetime(2026, 9, 27, tzinfo=dt.timezone.utc)

    def records(self, *findings):
        result = {}
        for index, changes in enumerate(findings):
            record = ledger._new_finding(
                "lane",
                "app",
                f"f-{index:010d}",
                finding(f"claim {index}", line=index * 100),
                None,
            )
            record.update({"coordinated": True, "split": "dev"})
            record.update(changes)
            result[record["id"]] = record
        return result

    def test_precision_counts_only_decided_verdicts(self):
        records = self.records(
            {"verdict": "confirmed"},
            {"verdict": "refuted"},
            {"verdict": "refuted"},
            {"verdict": "pending"},
        )
        block = ledger.metrics(records, "dev", self.AS_OF)["findings"]
        self.assertEqual(
            (block["confirmed"], block["refuted"], block["pending"]), (1, 2, 1)
        )
        self.assertEqual(block["precision"], 0.333)
        self.assertEqual(block["beta"], [2, 3])

    def test_dev_split_excludes_the_holdout(self):
        records = self.records(
            {"verdict": "confirmed"}, {"verdict": "refuted", "split": "holdout"}
        )
        dev = ledger.metrics(records, "dev", self.AS_OF)
        self.assertEqual(dev["findings"]["findings"], 1)
        self.assertEqual(dev["holdout_manifest"]["findings"], 1)
        self.assertEqual(
            ledger.metrics(records, "all", self.AS_OF)["findings"]["findings"], 2
        )

    def test_merge_maturation_and_reverts(self):
        old, new = "2026-09-10T00:00:00Z", "2026-09-25T00:00:00Z"

        late, early = "2026-09-26T00:00:00Z", "2026-09-11T00:00:00Z"

        def pr(merged_at, reverted, observed_at=late):
            return {
                "state": "MERGED",
                "merged_at": merged_at,
                "reverted": reverted,
                "observed_at": observed_at,
            }

        records = self.records(
            {"verdict": "confirmed", "pr_url": "u1", "pr": pr(old, False)},
            {"verdict": "confirmed", "pr_url": "u2", "pr": pr(old, None)},
            {"verdict": "confirmed", "pr_url": "u3", "pr": pr(old, True)},
            {"verdict": "confirmed", "pr_url": "u4", "pr": pr(new, False)},
            # checked one day after merging: a later revert would be invisible
            {"verdict": "confirmed", "pr_url": "u6", "pr": pr(old, False, early)},
            {"verdict": "confirmed", "pr_url": "u5", "publication": "rejected"},
            {"verdict": "confirmed"},
            {"verdict": "refuted"},
        )
        closure = ledger.metrics(records, "dev", self.AS_OF)["closure"]
        self.assertEqual(closure["merged"], 5)
        self.assertEqual(closure["merged_matured"], 1)
        self.assertEqual(closure["merged_maturing"], 1)
        self.assertEqual(closure["merged_revert_unchecked"], 2)
        self.assertEqual(closure["reverted"], 1)
        self.assertEqual(closure["rejected"], 1)
        self.assertEqual(closure["terminal"], 7)
        self.assertEqual(closure["closure_rate"], round(7 / 8, 3))

    def test_decided_fraction_excludes_pending_and_unjudged(self):
        records = self.records(
            {"verdict": "confirmed"},
            {"verdict": "pending"},
            {"verdict": "unjudged", "coordinated": False},
            {"verdict": "refuted"},
        )
        result = ledger.metrics(records, "dev", self.AS_OF)
        self.assertEqual(result["coordinated_fraction"], 0.75)
        self.assertEqual(result["decided_fraction"], 0.5)

    def test_refuted_rediscovery_after_the_verdict_is_counted(self):
        records = self.records(
            {
                "verdict": "refuted",
                "decided_at": "2026-09-26T12:00:00+00:00",
                "sightings": ["j/1", "j/2", "j/3"],
            }
        )
        for job_id, started in (
            ("j/1", "2026-09-26T10:00:00+00:00"),
            ("j/2", "2026-09-26T11:00:00+00:00"),
            ("j/3", "2026-09-27T01:00:00+00:00"),
        ):
            records[job_id] = {
                "type": "job",
                "id": job_id,
                "mode": "lens",
                "recipe": "bug-hunt",
                "runtime": "muse",
                "effort": "high",
                "status": "completed",
                "elapsed_seconds": 1.0,
                "findings": 1,
                "terminal_reason": None,
                "started_at": started,
            }
        rediscovery = ledger.metrics(records, "dev", self.AS_OF)["rediscovery"]
        self.assertEqual(rediscovery["refuted_rediscovered_after_verdict"], 1)
        self.assertEqual(rediscovery["repeat_sightings"], 2)


class FetchTests(unittest.TestCase):
    def test_revert_is_recognised_from_githubs_revert_body(self):
        calls = []

        def runner(path):
            calls.append(path)
            if path.startswith("repos/o/r/pulls/1"):
                return {"state": "closed", "merged_at": "2026-09-01T00:00:00Z"}
            if path.startswith("repos/o/r/pulls/2"):
                return {"state": "open", "merged_at": None}
            if path.startswith("search/issues"):
                return {"items": [{"html_url": "https://github.com/o/r/pull/9"}]}
            raise ValueError("unexpected " + path)

        prs = ledger.fetch_pr_states(
            [
                "https://github.com/o/r/pull/1",
                "https://github.com/o/r/pull/2",
                "not-a-url",
            ],
            runner,
            now=lambda: OBSERVED,
        )
        self.assertEqual(prs["https://github.com/o/r/pull/1"]["reverted"], True)
        self.assertEqual(prs["https://github.com/o/r/pull/1"]["observed_at"], OBSERVED)
        self.assertEqual(
            prs["https://github.com/o/r/pull/2"],
            {
                "state": "OPEN",
                "merged_at": None,
                "reverted": None,
                "revert_url": None,
                "observed_at": OBSERVED,
            },
        )
        self.assertIsNone(prs["not-a-url"]["state"])
        self.assertIn("in%3Abody", calls[1])
        self.assertIn("Reverts%20o%2Fr%231", calls[1])

    def test_non_object_responses_are_reported_not_fatal(self):
        prs = ledger.fetch_pr_states(
            ["https://github.com/o/r/pull/1"], lambda path: [], now=lambda: OBSERVED
        )
        self.assertIsNone(prs["https://github.com/o/r/pull/1"]["state"])

    def test_failed_probe_leaves_the_state_unknown(self):
        def runner(path):
            raise ValueError("HTTP 403")

        prs = ledger.fetch_pr_states(
            ["https://github.com/o/r/pull/1"], runner, now=lambda: OBSERVED
        )
        self.assertEqual(prs["https://github.com/o/r/pull/1"]["state"], None)
        self.assertIn("403", prs["https://github.com/o/r/pull/1"]["error"])


class CliTests(unittest.TestCase):
    def test_holdout_is_sealed_without_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.jsonl"
            path.write_text("", encoding="utf-8")
            err = io.StringIO()
            with redirect_stderr(err):
                code = ledger.main(
                    ["metrics", "--ledger", str(path), "--split", "holdout"]
                )
            self.assertEqual(code, 2)
            self.assertIn("sealed", err.getvalue())
            out = io.StringIO()
            with redirect_stdout(out):
                code = ledger.main(
                    [
                        "metrics",
                        "--ledger",
                        str(path),
                        "--split",
                        "holdout",
                        "--unseal",
                        "final eval",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(out.getvalue())["unsealed_because"], "final eval"
            )

    def test_extract_cli_writes_outside_and_refuses_inside(self):
        root = Root()
        self.addCleanup(root.cleanup)
        root.put("lane", "001", "app--st-bh1", receipt(findings=[finding("x")]))
        out = io.StringIO()
        with redirect_stdout(out):
            code = ledger.main(
                [
                    "extract",
                    "--runs-root",
                    str(root.path),
                    "--out",
                    str(root.path.parent / "l.jsonl"),
                    "--observed-at",
                    OBSERVED,
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["records"], 2)
        with redirect_stderr(io.StringIO()):
            code = ledger.main(
                [
                    "extract",
                    "--runs-root",
                    str(root.path),
                    "--out",
                    str(root.path / "l.jsonl"),
                ]
            )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
