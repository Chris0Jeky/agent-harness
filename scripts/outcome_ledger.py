#!/usr/bin/env python3
"""Deterministic outcome ledger over Muse swarm receipts and coordinator state.

Reads (never writes) a swarm runs root laid out as

    <root>/<lane>/state/waves/<NNN>/run/<repo>--<entry>/result.json
    <root>/<lane>/coordinator/state.json

and projects it into one normalised JSONL dataset: every lens/worker job, every
coordinator turn, and every finding with its origin job (recipe, runtime, model,
effort, base SHA), its triage verdict, the worker and PR that followed, and a
sealed dev/hold-out split. ``metrics`` turns that dataset into finding precision
per repo x recipe x runtime, closure rate, job and turn fault rates, and the
rediscovery waste that verdict memory would remove.

The swarm's files are a data contract, not an import: nothing from claude-config
is loaded. Verdicts are the coordinator judge's labels, not proof; every finding
record keeps the judge and whether the coordinator marked it verified.
Contract: docs/evals/OUTCOME_LEDGER.md.
"""

import argparse
from collections import Counter, defaultdict
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

SCHEMA = "outcome-ledger/v1"
PR_STATES_SCHEMA = "outcome-ledger/pr-states/v1"
PRODUCER = "agent-harness:scripts/outcome_ledger.py@1"
SPLIT_SALT = "outcome-ledger/v1/split"
HOLDOUT_PERCENT = 20
MATURATION_DAYS = 7
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_SIGHTINGS = 50
CLAIM_CHARS = 400
EVIDENCE_CHARS = 1200
TYPE_ORDER = {"job": 0, "turn": 1, "finding": 2}

# Coordinator item status -> ledger verdict. Anything else is kept verbatim as
# status_raw and labelled "unknown", never guessed.
VERDICTS = {
    "new": "pending",
    "classified": "pending",
    "fixing": "confirmed",
    "dropped": "refuted",
    "deferred": "deferred",
}
TURN_DECISIONS = {"fix": "confirmed", "drop": "refuted", "defer": "deferred"}
PUBLICATION = ("published", "merged", "rejected", "deferred")
TERMINAL_PR = {"merged", "rejected"}
STRUCTURE_ERRORS = (TypeError, AttributeError, KeyError, ValueError)
# Finding fields that only a coordinator observation can supply.
LABEL_FIELDS = (
    "coordinated",
    "status_raw",
    "verdict",
    "class",
    "judge",
    "judge_verified",
    "decided_at",
    "reason",
    "worker",
)
PR_FIELDS = ("pr_url", "publication", "worker_verify", "pr")


class LedgerError(Exception):
    """A refusal the caller must see (exit 2), never a partial ledger."""


# -- reading ---------------------------------------------------------------


def _read_json(path):
    """Return (value, sha256) for a bounded JSON file; raise ValueError on anything else."""
    with open(path, "rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("file exceeds the size bound")
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def _wave_key(name):
    return (len(name), name)


def discover(root):
    """Yield (lane, lane_dir) for every lane directory with swarm state, sorted."""
    root = Path(root)
    if not root.is_dir():
        raise LedgerError(f"runs root is not a directory: {root}")
    for lane_dir in sorted(root.iterdir(), key=lambda p: p.name):
        if lane_dir.name.startswith((".", "_")) or not lane_dir.is_dir():
            continue
        if (lane_dir / "state" / "waves").is_dir() or (
            lane_dir / "coordinator" / "state.json"
        ).is_file():
            yield lane_dir.name, lane_dir


def receipts(lane_dir):
    """Yield (wave, job, path) for every result.json under the lane, in wave order."""
    waves = lane_dir / "state" / "waves"
    if not waves.is_dir():
        return
    for wave_dir in sorted(waves.iterdir(), key=lambda p: _wave_key(p.name)):
        if not wave_dir.name.isdigit() or not (wave_dir / "run").is_dir():
            continue
        for job_dir in sorted((wave_dir / "run").iterdir(), key=lambda p: p.name):
            path = job_dir / "result.json"
            if path.is_file():
                yield wave_dir.name, job_dir.name, path


# -- identities --------------------------------------------------------------


def coordinator_finding_id(repo, finding):
    """Reproduce the coordinator's item id: sha1(repo|file|claim[:200])[:10].

    This is claude-config tools/muse_coordinator.py finding_id() restated as a
    data contract; tests pin it. If the producer changes it, joins degrade to
    receipt-only findings and the summary's ``unjoined_items`` rises.
    """
    basis = f"{repo}|{finding.get('file')}|{str(finding.get('claim') or '')[:200]}"
    return "f-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]


def _norm_path(value):
    text = str(value or "").strip().replace("\\", "/").lower()
    while text.startswith("./"):
        text = text[2:]
    return text


def _claim_words(claim, count=12):
    return " ".join(re.findall(r"[a-z0-9]+", str(claim or "").lower())[:count])


def _line_bucket(line):
    return (
        str(line // 20) if isinstance(line, int) and not isinstance(line, bool) else ""
    )


def fingerprint(repo, recipe, path, line, claim):
    """Autonomy-v2 C8 fingerprint: repo|recipe|path|line bucket|first 12 claim words."""
    basis = "|".join(
        (
            str(repo),
            str(recipe or ""),
            _norm_path(path),
            _line_bucket(line),
            _claim_words(claim),
        )
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


def cluster_key(repo, path, line, claim):
    """Recipe-free identity used for the split, so one defect never straddles dev and hold-out."""
    basis = "|".join(
        (str(repo), _norm_path(path), _line_bucket(line), _claim_words(claim))
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


def split_for(cluster):
    digest = hashlib.sha256(f"{SPLIT_SALT}|{cluster}".encode("utf-8")).hexdigest()
    return "holdout" if int(digest[:8], 16) % 100 < HOLDOUT_PERCENT else "dev"


def _clip(value, limit):
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _list(value):
    return value if isinstance(value, list) else []


def _int_or_none(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _provenance(path, sha, observed_at):
    return {
        "producer": PRODUCER,
        "source": str(path),
        "source_sha256": sha,
        "observed_at": observed_at,
    }


# -- extraction -------------------------------------------------------------


def _job_record(lane, wave, job, path, sha, data, observed_at):
    repo, _, entry = job.partition("--")
    report = data.get("report") if isinstance(data.get("report"), dict) else None
    findings = report.get("findings") if report else None
    verify = data.get("verify") if isinstance(data.get("verify"), dict) else None
    measured = data.get("measured") if isinstance(data.get("measured"), dict) else {}
    worktree = data.get("worktree") if isinstance(data.get("worktree"), dict) else {}
    return {
        "type": "job",
        "id": f"{lane}/{wave}/{job}",
        "lane": lane,
        "wave": wave,
        "job": job,
        "repo": repo,
        "entry": entry or None,
        "mode": data.get("mode"),
        "recipe": data.get("recipe"),
        "runtime": data.get("runtime"),
        "model": data.get("model"),
        "effort": data.get("effort"),
        "status": data.get("status"),
        "terminal_reason": _clip(data.get("terminal_reason"), 200) or None,
        "exit_code": _int_or_none(data.get("exit_code")),
        "elapsed_seconds": data.get("elapsed_seconds"),
        "started_at": data.get("started_at"),
        "base_sha": worktree.get("base"),
        "report_status": data.get("report_status"),
        "integrity": data.get("integrity"),
        "findings": len(findings) if isinstance(findings, list) else None,
        "verify": (
            {
                "exit_code": _int_or_none(verify.get("exit_code")),
                "timed_out": verify.get("timed_out"),
            }
            if verify
            else None
        ),
        "tool_failures": _int_or_none(measured.get("tool_failure_count")),
        "provenance": _provenance(path, sha, observed_at),
    }


def _new_finding(lane, repo, fid, raw, job_record):
    recipe = job_record.get("recipe") if job_record else None
    path, line, claim = raw.get("file"), _int_or_none(raw.get("line")), raw.get("claim")
    cluster = cluster_key(repo, path, line, claim)
    return {
        "type": "finding",
        "id": f"{lane}/{fid}",
        "lane": lane,
        "repo": repo,
        "item_id": fid,
        "fingerprint": fingerprint(repo, recipe, path, line, claim),
        "cluster": cluster,
        "split": split_for(cluster),
        "file": path,
        "line": line,
        "severity": str(raw.get("severity") or "").lower() or None,
        "claim": _clip(claim, CLAIM_CHARS),
        "evidence": _clip(raw.get("evidence"), EVIDENCE_CHARS),
        "origin": (
            {
                "job": job_record["id"],
                "recipe": recipe,
                "runtime": job_record.get("runtime"),
                "model": job_record.get("model"),
                "effort": job_record.get("effort"),
                "base_sha": job_record.get("base_sha"),
                "started_at": job_record.get("started_at"),
            }
            if job_record
            else None
        ),
        "sightings": [],
        "coordinated": False,
        "status_raw": None,
        "verdict": "unjudged",
        "class": None,
        "judge": None,
        "judge_verified": None,
        "decided_at": None,
        "reason": None,
        "worker": None,
        "pr_url": None,
        "publication": None,
        "worker_verify": None,
        "pr": None,
        "provenance": None,
    }


def _source_job(lane, source):
    match = re.fullmatch(r"wave (\d+) (\S+)", str(source or ""))
    return f"{lane}/{match.group(1)}/{match.group(2)}" if match else None


def extract(root, observed_at, pr_states=None):
    """Project the runs root into (records, summary). Pure over its inputs."""
    records = {}
    summary = Counter()
    problems = []
    for lane, lane_dir in discover(root):
        lane_findings = {}
        for wave, job, path in receipts(lane_dir):
            try:
                data, sha = _read_json(path)
                if not isinstance(data, dict):
                    raise ValueError("receipt is not an object")
            except (OSError, ValueError) as exc:
                problems.append({"path": str(path), "error": _clip(exc, 200)})
                summary["unreadable_receipts"] += 1
                continue
            try:
                job_record = _job_record(lane, wave, job, path, sha, data, observed_at)
                report = (
                    data.get("report") if isinstance(data.get("report"), dict) else {}
                )
                raws = [
                    raw
                    for raw in _list(report.get("findings"))
                    if isinstance(raw, dict) and raw.get("claim")
                ]
                if data.get("mode") != "lens":
                    raws = []
                staged = [
                    (coordinator_finding_id(job_record["repo"], raw), raw)
                    for raw in raws
                ]
            except STRUCTURE_ERRORS as exc:
                problems.append({"path": str(path), "error": _clip(exc, 200)})
                summary["unreadable_receipts"] += 1
                continue
            records[job_record["id"]] = job_record
            summary["jobs"] += 1
            for fid, raw in staged:
                finding = lane_findings.get(fid)
                if finding is None:
                    finding = _new_finding(
                        lane, job_record["repo"], fid, raw, job_record
                    )
                    finding["provenance"] = _provenance(path, sha, observed_at)
                    lane_findings[fid] = finding
                if len(finding["sightings"]) < MAX_SIGHTINGS:
                    finding["sightings"].append(job_record["id"])
        state_path = lane_dir / "coordinator" / "state.json"
        if state_path.is_file():
            try:
                cstate, sha = _read_json(state_path)
                if not isinstance(cstate, dict) or not isinstance(
                    cstate.get("items"), dict
                ):
                    raise ValueError("coordinator state has no item table")
            except (OSError, ValueError) as exc:
                problems.append({"path": str(state_path), "error": _clip(exc, 200)})
                summary["unreadable_states"] += 1
            else:
                before = (copy.deepcopy(lane_findings), dict(records), summary.copy())
                try:
                    _overlay(
                        lane,
                        cstate,
                        lane_findings,
                        records,
                        state_path,
                        sha,
                        observed_at,
                        summary,
                    )
                except STRUCTURE_ERRORS as exc:
                    lane_findings, records, summary = before
                    problems.append({"path": str(state_path), "error": _clip(exc, 200)})
                    summary["unreadable_states"] += 1
                else:
                    summary["coordinated_lanes"] += 1
        for finding in lane_findings.values():
            records[finding["id"]] = finding
    for record in records.values():
        if record["type"] == "finding" and record["pr_url"] and pr_states:
            record["pr"] = pr_states.get(record["pr_url"])
    summary["findings"] = sum(1 for r in records.values() if r["type"] == "finding")
    summary["turns"] = sum(1 for r in records.values() if r["type"] == "turn")
    return records, {"counts": dict(sorted(summary.items())), "problems": problems}


def _overlay(lane, cstate, lane_findings, records, path, sha, observed_at, summary):
    items = cstate["items"]
    turn_verdicts = {}
    for index, turn in enumerate(_list(cstate.get("turns"))):
        if not isinstance(turn, dict):
            continue
        attempts = [a for a in _list(turn.get("attempts")) if isinstance(a, dict)]
        outcome = turn.get("outcome") if isinstance(turn.get("outcome"), dict) else {}
        name = re.split(r"[\\/]", str(turn.get("dir") or ""))[-1]
        if not name and turn.get("started"):
            name = f"{turn.get('started')}-{turn.get('kind')}"
        turn_id = f"{lane}/turn/{name or index}"
        records[turn_id] = {
            "type": "turn",
            "id": turn_id,
            "lane": lane,
            "kind": turn.get("kind"),
            "class": turn.get("class"),
            "repo": turn.get("repo"),
            "runtime": turn.get("runtime"),
            "status": turn.get("status"),
            "started": turn.get("started"),
            "seconds": turn.get("seconds"),
            "items": len(_list(turn.get("items"))),
            "attempts": len(attempts),
            "faults": sorted({str(a.get("fault")) for a in attempts if a.get("fault")}),
            "timed_out": any(a.get("timed_out") is True for a in attempts),
            "outcome": {
                key: len(value)
                for key, value in sorted(outcome.items())
                if isinstance(value, list)
            },
            "provenance": _provenance(path, sha, observed_at),
        }
        for decision, verdict in TURN_DECISIONS.items():
            for fid in _list(outcome.get(decision)):
                turn_verdicts[str(fid)] = (
                    verdict,
                    turn.get("runtime"),
                    turn.get("finished"),
                )
    by_finding_worktree = {}
    for wid, item in items.items():
        if (
            isinstance(item, dict)
            and item.get("kind") == "worktree"
            and item.get("finding")
        ):
            by_finding_worktree[str(item["finding"])] = (wid, item)
    for fid, item in sorted(items.items()):
        if not isinstance(item, dict) or item.get("kind") != "finding":
            continue
        finding = lane_findings.get(fid)
        if finding is None:
            job_id = _source_job(lane, item.get("source"))
            finding = _new_finding(
                lane, str(item.get("repo")), fid, item, records.get(job_id)
            )
            finding["provenance"] = _provenance(path, sha, observed_at)
            lane_findings[fid] = finding
            summary["unjoined_items"] += 1
        status = str(item.get("status"))
        finding.update(
            {
                "coordinated": True,
                "status_raw": status,
                "verdict": VERDICTS.get(status, "unknown"),
                "class": item.get("class"),
                "judge": item.get("decided_by") or item.get("classified_by"),
                "judge_verified": item.get("verified"),
                "decided_at": item.get("decided"),
                "reason": _clip(item.get("reason"), 600) or None,
                "worker": item.get("worker"),
            }
        )
        if finding["verdict"] == "pending":
            finding["judge"] = None
        _attach_worktree(finding, by_finding_worktree.get(fid))
        turn_verdicts.pop(fid, None)
    # Items the coordinator already pruned survive in its turn outcomes.
    for fid, (verdict, runtime, finished) in sorted(turn_verdicts.items()):
        finding = lane_findings.get(fid)
        if finding is None:
            continue
        finding.update(
            {
                "coordinated": True,
                "status_raw": "pruned",
                "verdict": verdict,
                "judge": runtime,
                "decided_at": finished,
            }
        )
        _attach_worktree(finding, by_finding_worktree.get(fid))
        summary["verdicts_from_turns"] += 1


def _attach_worktree(finding, pair):
    if not pair:
        return
    _, worktree = pair
    finding.update(
        {
            "pr_url": worktree.get("pr_url"),
            "publication": str(worktree.get("status")),
            "worker_verify": worktree.get("verify"),
            "worker": finding["worker"] or worktree.get("entry"),
        }
    )


# -- ledger file --------------------------------------------------------------


def _digest(record):
    body = {
        k: v
        for k, v in record.items()
        if k not in ("provenance", "supersedes", "carried", "labels_carried")
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[
        :16
    ]


def load_ledger(path):
    records = {}
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if (
                not isinstance(record, dict)
                or record.get("type") not in TYPE_ORDER
                or not isinstance(record.get("id"), str)
            ):
                raise LedgerError(f"{path}:{number}: not an outcome-ledger record")
            records[record["id"]] = record
    return records


def _label_rank(record):
    """How much coordinator knowledge a finding carries: item table > turn outcome > none."""
    if not record.get("coordinated"):
        return 0
    return 1 if record.get("status_raw") == "pruned" else 2


def merge_prior(current, prior):
    """Carry what the swarm has since pruned; note what current supersedes.

    A whole record the runs root no longer holds is carried. A finding whose receipt
    survives but whose coordinator item was pruned keeps the prior, richer label and
    PR fields instead of being downgraded by a weaker current observation.
    """
    merged = dict(current)
    carried = 0
    for record_id, old in prior.items():
        new = merged.get(record_id)
        if new is None:
            merged[record_id] = dict(old, carried=True)
            carried += 1
            continue
        if new["type"] == "finding" and old.get("type") == "finding":
            if _label_rank(old) > _label_rank(new):
                new.update({field: old.get(field) for field in LABEL_FIELDS})
                new["labels_carried"] = True
            for field in PR_FIELDS:
                if new.get(field) is None and old.get(field) is not None:
                    new[field] = old[field]
        if _digest(new) != _digest(old):
            new["supersedes"] = _digest(old)
    return merged, carried


def _inside(path, root):
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(root))
    except ValueError:
        return False
    return True


def write_ledger(records, out, root):
    if _inside(out, root):
        raise LedgerError(
            "refusing to write inside the runs root: the ledger never mutates it"
        )
    ordered = sorted(records.values(), key=lambda r: (TYPE_ORDER[r["type"]], r["id"]))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=out.parent, delete=False, suffix=".tmp"
    )
    try:
        with handle:
            for record in ordered:
                handle.write(
                    json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
                )
        os.replace(handle.name, out)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return len(ordered)


def load_pr_states(path):
    data, _ = _read_json(path)
    if not isinstance(data, dict) or data.get("schema") != PR_STATES_SCHEMA:
        raise LedgerError(f"{path}: expected schema {PR_STATES_SCHEMA}")
    prs = data.get("prs")
    if not isinstance(prs, dict):
        raise LedgerError(f"{path}: prs must be an object keyed by PR URL")
    return prs


# -- PR states (optional, networked, injectable) ------------------------------

PR_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)")


def fetch_pr_states(urls, runner=None, pace=None, now=None):
    """Observe PR state and revert evidence over GitHub REST via ``gh api``.

    A revert is recognised only by GitHub's own revert-PR body ("Reverts
    owner/repo#N", searched ``in:body``) on a merged PR; no hit leaves
    ``reverted`` false and a failed probe leaves it null. Each entry records its
    own ``observed_at``: maturation needs the revert check made at least seven
    days after the merge. The real runner is paced under the search rate limit.
    """
    pace = pace if pace is not None else (2.1 if runner is None else 0)
    runner = runner or _gh_api
    now = now or _now
    prs = {}
    searched = False
    for url in sorted(set(urls)):
        match = PR_URL.fullmatch(url)
        if not match:
            prs[url] = {"state": None, "error": "not a GitHub PR URL"}
            continue
        owner, repo, number = match.groups()
        try:
            pull = runner(f"repos/{owner}/{repo}/pulls/{number}")
            if not isinstance(pull, dict):
                raise ValueError("pull response is not an object")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            prs[url] = {"state": None, "error": _clip(exc, 200)}
            continue
        merged_at = pull.get("merged_at")
        state = "MERGED" if merged_at else str(pull.get("state") or "").upper() or None
        entry = {
            "state": state,
            "merged_at": merged_at,
            "reverted": None,
            "revert_url": None,
            "observed_at": now(),
        }
        if merged_at:
            query = (
                f"repo:{owner}/{repo} is:pr is:merged in:body "
                f'"Reverts {owner}/{repo}#{number}"'
            )
            if searched and pace:
                time.sleep(pace)
            searched = True
            try:
                found = runner("search/issues?q=" + _quote(query))
                if not isinstance(found, dict):
                    raise ValueError("search response is not an object")
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                entry["error"] = _clip(exc, 200)
            else:
                hits = [i for i in found.get("items") or [] if isinstance(i, dict)]
                entry["reverted"] = bool(hits)
                entry["revert_url"] = hits[0].get("html_url") if hits else None
        prs[url] = entry
    return prs


def _quote(text):
    from urllib.parse import quote

    return quote(text, safe="")


def _gh_api(path):
    completed = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(_clip(completed.stderr.strip() or "gh api failed", 200))
    return json.loads(completed.stdout)


# -- metrics --------------------------------------------------------------------


def _parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _quantile(values, q):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return None
    return round(values[min(len(values) - 1, int(q * len(values)))], 1)


def _verdict_block(findings):
    counts = Counter(f["verdict"] for f in findings)
    confirmed, refuted = counts["confirmed"], counts["refuted"]
    decided = confirmed + refuted
    return {
        "findings": len(findings),
        "confirmed": confirmed,
        "refuted": refuted,
        "deferred": counts["deferred"],
        "pending": counts["pending"],
        "unjudged": counts["unjudged"],
        "unknown": counts["unknown"],
        "precision": round(confirmed / decided, 3) if decided else None,
        "beta": [1 + confirmed, 1 + refuted],
    }


def _group(findings, key):
    groups = defaultdict(list)
    for finding in findings:
        groups[key(finding)].append(finding)
    return [
        {"key": "|".join(str(part) for part in k), **_verdict_block(v)}
        for k, v in sorted(groups.items(), key=lambda kv: [str(p) for p in kv[0]])
    ]


def _origin(finding, field):
    origin = finding.get("origin") or {}
    return origin.get(field) or "(none)"


def metrics(records, split="dev", as_of=None):
    """Aggregate a ledger. Hold-out findings only enter when split is holdout or all."""
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    all_findings = [r for r in records.values() if r["type"] == "finding"]
    holdout = sorted(f["cluster"] for f in all_findings if f.get("split") == "holdout")
    manifest = {
        "clusters": len(set(holdout)),
        "findings": len(holdout),
        "digest": hashlib.sha256(
            "\n".join(sorted(set(holdout))).encode("utf-8")
        ).hexdigest(),
    }
    findings = [f for f in all_findings if split == "all" or f.get("split") == split]
    jobs = {r["id"]: r for r in records.values() if r["type"] == "job"}
    coordinated = [f for f in findings if f["coordinated"]]
    decided_findings = [
        f for f in coordinated if f["verdict"] in ("confirmed", "refuted")
    ]

    maturation = dt.timedelta(days=MATURATION_DAYS)
    closure = Counter()
    for finding in coordinated:
        closure["collected"] += 1
        pr = finding.get("pr") or {}
        merged_at = _parse_time(pr.get("merged_at"))
        if finding["verdict"] == "refuted":
            closure["terminal"] += 1
        elif finding["verdict"] == "confirmed":
            closure["confirmed"] += 1
            if finding.get("pr_url"):
                closure["with_pr"] += 1
            merged = (
                finding.get("publication") == "merged" or pr.get("state") == "MERGED"
            )
            rejected = (
                finding.get("publication") == "rejected" or pr.get("state") == "CLOSED"
            )
            if merged or rejected:
                closure["terminal"] += 1
            if merged:
                closure["merged"] += 1
                checked_at = _parse_time(pr.get("observed_at"))
                if pr.get("reverted") is True:
                    closure["reverted"] += 1
                elif (
                    merged_at
                    and checked_at
                    and pr.get("reverted") is False
                    and checked_at - merged_at >= maturation
                ):
                    closure["merged_matured"] += 1
                elif merged_at and as_of - merged_at < maturation:
                    closure["merged_maturing"] += 1
                else:
                    closure["merged_revert_unchecked"] += 1
            if rejected and not merged:
                closure["rejected"] += 1

    rediscovered = Counter()
    for finding in findings:
        sightings = finding.get("sightings") or []
        if len(sightings) > 1:
            rediscovered["findings_seen_again"] += 1
            rediscovered["repeat_sightings"] += len(sightings) - 1
        decided = _parse_time(finding.get("decided_at"))
        if finding["verdict"] == "refuted" and decided:
            after = [
                s
                for s in sightings[1:]
                if (_parse_time((jobs.get(s) or {}).get("started_at")) or decided)
                > decided
            ]
            rediscovered["refuted_rediscovered_after_verdict"] += len(after)

    job_groups = defaultdict(list)
    for job in jobs.values():
        job_groups[
            (job["mode"], job["recipe"] or "(none)", job["runtime"], job["effort"])
        ].append(job)
    job_rows = []
    for key, group in sorted(
        job_groups.items(), key=lambda kv: [str(p) for p in kv[0]]
    ):
        failed = [j for j in group if j["status"] != "completed"]
        lens_counts = [j["findings"] for j in group if isinstance(j["findings"], int)]
        job_rows.append(
            {
                "key": "|".join(str(part) for part in key),
                "jobs": len(group),
                "not_completed": len(failed),
                "failure_rate": round(len(failed) / len(group), 3),
                "elapsed_p50": _quantile([j["elapsed_seconds"] for j in group], 0.5),
                "elapsed_p90": _quantile([j["elapsed_seconds"] for j in group], 0.9),
                "findings_per_job": (
                    round(sum(lens_counts) / len(lens_counts), 2)
                    if lens_counts
                    else None
                ),
                "terminal_reasons": dict(
                    Counter(
                        re.sub(r"\d+", "N", j["terminal_reason"])
                        for j in failed
                        if j["terminal_reason"]
                    ).most_common(5)
                ),
            }
        )

    turn_groups = defaultdict(list)
    for turn in (r for r in records.values() if r["type"] == "turn"):
        turn_groups[(turn["kind"], turn["runtime"])].append(turn)
    turn_rows = [
        {
            "key": "|".join(str(part) for part in key),
            "turns": len(group),
            "not_ok": sum(1 for t in group if t["status"] != "ok"),
            "timed_out": sum(1 for t in group if t["timed_out"]),
            "seconds_p50": _quantile([t["seconds"] for t in group], 0.5),
        }
        for key, group in sorted(
            turn_groups.items(), key=lambda kv: [str(p) for p in kv[0]]
        )
    ]

    return {
        "schema": SCHEMA + "/metrics",
        "split": split,
        "as_of": as_of.isoformat(timespec="seconds"),
        "holdout_manifest": manifest,
        "findings": _verdict_block(findings),
        "coordinated_fraction": (
            round(len(coordinated) / len(findings), 3) if findings else None
        ),
        "decided_fraction": (
            round(len(decided_findings) / len(findings), 3) if findings else None
        ),
        "precision_by_recipe": _group(coordinated, lambda f: (_origin(f, "recipe"),)),
        "precision_by_repo_recipe_runtime": _group(
            coordinated,
            lambda f: (
                f["repo"],
                _origin(f, "recipe"),
                _origin(f, "runtime"),
                _origin(f, "effort"),
            ),
        ),
        "precision_by_judge": _group(
            coordinated, lambda f: (f.get("judge") or "(none)",)
        ),
        "closure": dict(
            sorted(closure.items()),
            closure_rate=(
                round(closure["terminal"] / closure["collected"], 3)
                if closure["collected"]
                else None
            ),
        ),
        "rediscovery": dict(sorted(rediscovered.items())),
        "jobs": job_rows,
        "turns": turn_rows,
        "not_measured": {
            "avoidable_idle_fraction": "needs supervisor idle intervals; receipts record only work",
            "review_recall_on_seeded_faults": "needs a seeded-fault corpus; historical verdicts are judge labels",
        },
    }


# -- CLI ---------------------------------------------------------------------------


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ext = sub.add_parser(
        "extract", help="project the runs root into a ledger (read-only over it)"
    )
    ext.add_argument("--runs-root", type=Path, required=True)
    ext.add_argument("--out", type=Path, required=True)
    ext.add_argument(
        "--prior", type=Path, help="earlier ledger whose pruned records are carried"
    )
    ext.add_argument(
        "--pr-states", type=Path, help=f"{PR_STATES_SCHEMA} JSON to join on PR URL"
    )
    ext.add_argument(
        "--observed-at", default=None, help="provenance timestamp (default: now)"
    )
    urls = sub.add_parser("pr-urls", help="list the PR URLs a ledger needs states for")
    urls.add_argument("--ledger", type=Path, required=True)
    fetch = sub.add_parser(
        "fetch-pr-states", help="observe PR state/reverts via gh api (network)"
    )
    fetch.add_argument("--ledger", type=Path, required=True)
    fetch.add_argument("--out", type=Path, required=True)
    met = sub.add_parser(
        "metrics", help="aggregate a ledger; hold-out stays sealed by default"
    )
    met.add_argument("--ledger", type=Path, required=True)
    met.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    met.add_argument(
        "--unseal", metavar="REASON", help="required to read the hold-out split"
    )
    met.add_argument(
        "--as-of", default=None, help="ISO time for merge maturation (default: now)"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "extract":
            pr_states = load_pr_states(args.pr_states) if args.pr_states else None
            records, summary = extract(
                args.runs_root, args.observed_at or _now(), pr_states
            )
            if args.prior:
                records, carried = merge_prior(records, load_ledger(args.prior))
                summary["counts"]["carried_from_prior"] = carried
            summary["records"] = write_ledger(records, args.out, args.runs_root)
            summary["out"] = str(args.out)
            print(json.dumps(summary, sort_keys=True, indent=2))
        elif args.command == "pr-urls":
            records = load_ledger(args.ledger)
            for url in sorted(
                {r["pr_url"] for r in records.values() if r.get("pr_url")}
            ):
                print(url)
        elif args.command == "fetch-pr-states":
            records = load_ledger(args.ledger)
            prs = fetch_pr_states(
                r["pr_url"] for r in records.values() if r.get("pr_url")
            )
            payload = {"schema": PR_STATES_SCHEMA, "observed_at": _now(), "prs": prs}
            Path(args.out).write_text(
                json.dumps(payload, sort_keys=True, indent=2) + "\n", "utf-8"
            )
            print(json.dumps({"prs": len(prs), "out": str(args.out)}))
        else:
            if args.split != "dev" and not args.unseal:
                raise LedgerError(
                    "the hold-out is sealed: pass --unseal REASON to read it"
                )
            as_of = _parse_time(args.as_of) if args.as_of else None
            if args.as_of and as_of is None:
                raise LedgerError(f"--as-of is not an ISO time: {args.as_of}")
            result = metrics(load_ledger(args.ledger), args.split, as_of)
            if args.unseal:
                result["unsealed_because"] = args.unseal
            print(json.dumps(result, sort_keys=True, indent=2))
    except (LedgerError, OSError, ValueError) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
