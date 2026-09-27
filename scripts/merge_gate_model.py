#!/usr/bin/env python3
"""Executable model of the estate merge gate, with an exhaustive model checker.

The finite merge state machine named by claude-config #432 (Candidate -> ... ->
Merged -> PostMerge -> Closed/Revert/DeadLetter) written as a pure transition
function, so the durable control plane can be conformance-tested against it
instead of re-deriving the laws from prose.

``model_check`` (CLI: ``check``) explores every reachable state for every merge authority and proves:

- no merge unless an INDEPENDENT spec holds: authority ``free``, published
  ready-for-review, proof and green CI for the exact (head, base) pair, a
  review of the current logic, the head aged three minutes, review rounds
  within the ceiling, and the merged SHA equal to the head;
- review rounds never exceed two, plus the single reopen law 2d grants a new
  CRITICAL introduced by fixes;
- every counter stays within its bound;
- no cycle through non-terminal states (only state-preserving no-ops repeat);
- every reachable state can still reach a terminal or owner-decision state.

The spec does not trust the table's bookkeeping: an event-driven observer
automaton, run in product with the table, re-derives review rounds, CRITICAL
reopens, aging, review, proof and CI from the event stream alone, and the spec
also demands the table's evidence identities agree. ``--mutant`` swaps in a
seeded defect so the checker's teeth are themselves tested.
Contract: docs/evals/MERGE_GATE_MODEL.md.
"""

import argparse
from collections import defaultdict, deque
import json
import random
import sys
from typing import NamedTuple

MAX_ATTEMPTS = 3  # worker attempts before dead-letter
MAX_FIXES = 3  # law 11: three genuinely different attempts at a red check
MAX_REFRESHES = 3  # base churn beyond this parks rather than looping
MAX_REVIEW_ROUNDS = 2  # law 2d
AGE_MINUTES = 3  # law 2f

AUTHORITIES = ("free", "gated", "human-only", "none")
TERMINAL = frozenset({"Closed", "Parked", "DeadLetter"})
WAITING_ON_OWNER = frozenset({"OwnerBlocked"})
PUBLISHED_PHASES = frozenset({"Review", "AgeGate", "MergeReady"})
EVENTS = (
    "lease",
    "start",
    "worker_ok",
    "worker_fail",
    "lease_expired",
    "proof_pass",
    "proof_fail",
    "publish",
    "review_pass",
    "review_changes",
    "review_critical",
    "fix_logic",
    "fix_mechanical",
    "fix_failed",
    "tick",
    "ci_green",
    "ci_red",
    "retarget",
    "refresh_merge",
    "refresh_conflict",
    "retarget_semantic",
    "evaluate",
    "merge",
    "postmerge_start",
    "postmerge_pass",
    "postmerge_regression",
    "revert_done",
    "revert_irreversible",
    "owner_answer",
)
MUTANTS = {
    "no_age_gate": "evaluate ignores the three-minute aging floor",
    "stale_review": "a logic fix keeps the previous review",
    "third_round": "the review-round ceiling is off by one, so a third round runs",
    "unbounded_fixes": "fix attempts are not counted",
    "merge_on_red": "evaluate ignores CI state",
    "retarget_keeps_proof": "a retarget keeps the proof and CI of the old base",
    "gated_merges": "gated authority merges autonomously",
    "draft_merge": "publish leaves the PR in draft",
    "age_kept_on_push": "publishing a new head keeps the previous head's age",
    "uncounted_review": "a passing review does not count as a round",
    "changes_reopen": "requested changes set the CRITICAL reopen flag",
    "conflict_keeps_review": "a conflicting base refresh keeps the review",
    "semantic_retarget_keeps_review": "a semantically interacting retarget keeps the review",
    "early_critical": "a CRITICAL in the first round opens the reopen allowance",
    "unfixed_critical": "a CRITICAL on a round with no fix since the last verdict reopens",
    "tick_before_push": "a new head ages from its creation, before it is pushed",
}


class State(NamedTuple):
    phase: str
    authority: str
    # identities: the pushed SHA, the base it is measured against, and the logic version
    head: int = 0
    base: int = 0
    logic: int = 0
    pushed_head: int = -1
    ready: bool = False  # published ready-for-review, never draft (law 2e)
    # table bookkeeping; the spec never trusts these (an event-driven observer re-derives
    # each, and the evidence identities below must agree with it)
    proven: bool = False
    ci: str = "none"  # none | pending | green | red
    reviewed: bool = False
    age: int = 0
    # evidence identities, which the spec reads
    proven_for: tuple = ()
    ci_for: tuple = ()
    reviewed_logic: int = -1
    age_head: int = -1
    # bounded counters
    attempts: int = 0
    fixes: int = 0
    refreshes: int = 0
    review_rounds: int = 0
    reopened: bool = False
    fixed_since_verdict: bool = False  # a fix landed after the last review verdict
    merged_head: int = -1
    reverted: bool = False


def initial(authority):
    return State(phase="Candidate", authority=authority)


def _rounds_allowed(s, mutants):
    return (
        MAX_REVIEW_ROUNDS
        + (1 if s.reopened else 0)
        + (1 if "third_round" in mutants else 0)
    )


def _enter_fixing(s, **changes):
    if s.fixes >= MAX_FIXES:
        return s._replace(phase="Parked", **changes)
    return s._replace(phase="Fixing", **changes)


def _new_head(s, logic_changed, mutants, counted=True):
    """A new pushed candidate: proof, CI and aging restart; review survives only a mechanical change."""
    keep_review = not logic_changed or "stale_review" in mutants
    return s._replace(
        phase="Proving",
        head=s.head + 1,
        logic=s.logic + (1 if logic_changed else 0),
        proven=False,
        ci="none",
        reviewed=s.reviewed and keep_review,
        fixes=s.fixes + (1 if counted and "unbounded_fixes" not in mutants else 0),
        # the mutant ages from the head change instead of the push
        age=0 if "tick_before_push" in mutants else s.age,
    )


def step(s, event, mutants=frozenset()):
    """Return the successor state, or None when ``event`` is not enabled in ``s``."""
    p = s.phase
    if p in TERMINAL:
        return None
    if p == "Candidate":
        return s._replace(phase="Tasked") if event == "lease" else None
    if p == "Tasked":
        if event != "start":
            return None
        if s.attempts >= MAX_ATTEMPTS:
            return s._replace(phase="DeadLetter")
        return s._replace(phase="Running", attempts=s.attempts + 1)
    if p == "Running":
        if event == "worker_ok":
            return _new_head(s, True, mutants, counted=False)
        if event in ("worker_fail", "lease_expired"):
            return s._replace(phase="Tasked")
        return None
    if p in ("Proving", "Proven") and event == "tick" and "tick_before_push" in mutants:
        return s._replace(age=min(s.age + 1, AGE_MINUTES))
    if p == "Proving":
        if event == "proof_pass":
            return s._replace(phase="Proven", proven=True, proven_for=(s.head, s.base))
        if event == "proof_fail":
            return _enter_fixing(s) if s.ready else s._replace(phase="Tasked")
        return None
    if p == "Proven":
        if event != "publish":
            return None
        pushed = s.pushed_head != s.head
        s = s._replace(
            ready=s.ready or "draft_merge" not in mutants,
            pushed_head=s.head,
            ci="pending" if pushed or s.ci != "green" else s.ci,
            age=(
                0
                if pushed
                and not {"age_kept_on_push", "tick_before_push"} & set(mutants)
                else s.age
            ),
            age_head=s.head if pushed else s.age_head,
        )
        if s.reviewed:
            return s._replace(phase="AgeGate")
        if s.review_rounds >= _rounds_allowed(s, mutants):
            # Logic changed after the last round the law allows: it cannot be reviewed, so park.
            return s._replace(phase="Parked")
        return s._replace(phase="Review")
    if p == "Fixing":
        if event == "fix_logic":
            return _new_head(s, True, mutants)._replace(fixed_since_verdict=True)
        if event == "fix_mechanical":
            return _new_head(s, False, mutants)._replace(fixed_since_verdict=True)
        if event == "fix_failed":
            return s._replace(phase="Parked")
        return None
    if p in PUBLISHED_PHASES:
        shared = _published_event(s, event, mutants)
        if shared is not None:
            return shared
    if p == "Review":
        allowed = _rounds_allowed(s, mutants)
        fixed = s.fixed_since_verdict
        s = s._replace(fixed_since_verdict=False) if event in REVIEW_VERDICTS else s
        if event == "review_pass":
            return s._replace(
                phase="AgeGate",
                reviewed=True,
                reviewed_logic=s.logic,
                review_rounds=s.review_rounds
                + (0 if "uncounted_review" in mutants else 1),
            )
        if event == "review_changes":
            rounds = s.review_rounds + 1
            reopen = s.reopened or "changes_reopen" in mutants
            if rounds < allowed:
                return _enter_fixing(s, review_rounds=rounds, reopened=reopen)
            return s._replace(phase="Parked", review_rounds=rounds)
        # law 2d: only a CRITICAL introduced by the fixes reopens, so it needs a round
        # behind it and a fix since that round's verdict
        introduced = s.review_rounds >= 1 and (fixed or "unfixed_critical" in mutants)
        if event == "review_critical" and (introduced or "early_critical" in mutants):
            rounds = s.review_rounds + 1
            if not s.reopened:
                return _enter_fixing(s, review_rounds=rounds, reopened=True)
            return s._replace(phase="Parked", review_rounds=rounds)
        return None
    if p == "AgeGate":
        if event != "evaluate":
            return None
        aged = s.age >= AGE_MINUTES or "no_age_gate" in mutants
        green = s.ci == "green" or "merge_on_red" in mutants
        if not (s.proven and s.reviewed and aged and green):
            return None
        if s.authority == "free" or "gated_merges" in mutants:
            return s._replace(phase="MergeReady")
        return s._replace(phase="OwnerBlocked")
    if p == "MergeReady":
        return (
            s._replace(phase="Merged", merged_head=s.head) if event == "merge" else None
        )
    if p == "Merged":
        return s._replace(phase="PostMerge") if event == "postmerge_start" else None
    if p == "PostMerge":
        if event == "postmerge_pass":
            return s._replace(phase="Closed")
        if event == "postmerge_regression":
            return s._replace(phase="Revert")
        return None
    if p == "Revert":
        if event == "revert_done":
            return s._replace(phase="Closed", reverted=True)
        if event == "revert_irreversible":
            return s._replace(phase="OwnerBlocked")
        return None
    if p == "OwnerBlocked":
        return s._replace(phase="Closed") if event == "owner_answer" else None
    raise ValueError(f"unknown phase {p!r}")


def _published_event(s, event, mutants):
    if event == "tick":
        return s._replace(age=min(s.age + 1, AGE_MINUTES))
    if event == "ci_green" and s.ci == "pending":
        return s._replace(ci="green", ci_for=(s.head, s.base))
    if event == "ci_red" and s.ci == "pending":
        return _enter_fixing(s, ci="red")
    if event in ("retarget", "retarget_semantic", "refresh_merge", "refresh_conflict"):
        if s.refreshes >= MAX_REFRESHES:
            return s._replace(phase="Parked")
        if event == "retarget_semantic":
            # Same head, new base that interacts with the change: law 2g owes a review.
            keep_review = "semantic_retarget_keeps_review" in mutants
            return s._replace(
                phase="Proving",
                base=s.base + 1,
                logic=s.logic + (0 if keep_review else 1),
                refreshes=s.refreshes + 1,
                proven=False,
                ci="none",
                reviewed=s.reviewed and keep_review,
            )
        if event == "retarget":
            keep = "retarget_keeps_proof" in mutants
            return s._replace(
                phase="Proving" if not keep else s.phase,
                base=s.base + 1,
                refreshes=s.refreshes + 1,
                proven=s.proven and keep,
                ci=s.ci if keep else "none",
            )
        # A merge commit from the base is a new pushed head. Law 2g keeps the review
        # unless the new base brings a conflict, semantic interaction or new logic.
        logic_changed = (
            event == "refresh_conflict" and "conflict_keeps_review" not in mutants
        )
        return _new_head(s, logic_changed, mutants, counted=False)._replace(
            base=s.base + 1, refreshes=s.refreshes + 1
        )
    return None


# -- the independent spec -------------------------------------------------------

REVIEW_VERDICTS = frozenset({"review_pass", "review_changes", "review_critical"})
HEAD_EVENTS = frozenset(
    {"worker_ok", "fix_logic", "fix_mechanical", "refresh_merge", "refresh_conflict"}
)
BASE_EVENTS = frozenset(
    {"retarget", "retarget_semantic", "refresh_merge", "refresh_conflict"}
)
FIX_EVENTS = frozenset({"fix_logic", "fix_mechanical"})
LOGIC_EVENTS = frozenset(
    {"worker_ok", "fix_logic", "refresh_conflict", "retarget_semantic"}
)
OBSERVED_ROUND_CAP = MAX_REVIEW_ROUNDS + 2


class Observer(NamedTuple):
    """What the event stream alone says, independent of the table's bookkeeping."""

    rounds: int = 0
    criticals: int = 0
    age: int = 0
    reviewed: bool = False
    proven: bool = False
    green: bool = False
    unpushed: bool = False  # a head exists that has not been published yet
    fixed: bool = False  # a fix event since the last review verdict


def observe(o, event):
    """Advance the observer on an event the table accepted. Bounded, so the product is finite."""
    head_moved = event in HEAD_EVENTS
    moved = head_moved or event in BASE_EVENTS
    return Observer(
        rounds=min(o.rounds + (event in REVIEW_VERDICTS), OBSERVED_ROUND_CAP),
        # law 2d: only a CRITICAL introduced by fixes, i.e. after a first round, reopens
        criticals=min(
            o.criticals + (event == "review_critical" and o.rounds >= 1 and o.fixed), 2
        ),
        fixed=event in FIX_EVENTS or (o.fixed and event not in REVIEW_VERDICTS),
        # aging counts from the push of the current head, never from before it
        age=(
            0
            if head_moved or (event == "publish" and o.unpushed)
            else min(o.age + (event == "tick"), AGE_MINUTES)
        ),
        unpushed=head_moved or (o.unpushed and event != "publish"),
        reviewed=(
            False if event in LOGIC_EVENTS else o.reviewed or event == "review_pass"
        ),
        proven=(
            False
            if moved
            else (o.proven or event == "proof_pass") and event != "proof_fail"
        ),
        green=(
            False if moved else (o.green or event == "ci_green") and event != "ci_red"
        ),
    )


def merge_violations(s, successor, o):
    """Why merging from ``s`` breaks the laws; empty when the merge is lawful.

    Each rule needs both the observer's event-derived fact and the table's evidence
    identity to agree, so neither a bookkeeping slip nor a stale identity certifies.
    Authority and ready-for-review are inputs: configuration and a publish effect.
    """
    reasons = []
    current = (s.head, s.base)
    if s.authority != "free":
        reasons.append(f"authority {s.authority!r} is not free")
    if not s.ready:
        reasons.append("PR is not published ready-for-review")
    if s.pushed_head != s.head:
        reasons.append("head was never pushed")
    if not o.proven or s.proven_for != current:
        reasons.append("no proof for the exact head and base")
    if not o.green or s.ci_for != current:
        reasons.append("no green CI for the exact head and base")
    if not o.reviewed or s.reviewed_logic != s.logic:
        reasons.append("current logic was never reviewed")
    if o.age < AGE_MINUTES or s.age_head != s.head:
        reasons.append("head has not aged three minutes")
    if o.rounds > MAX_REVIEW_ROUNDS + min(o.criticals, 1):
        reasons.append("review rounds exceed the ceiling")
    if successor.merged_head != s.head:
        reasons.append("merged SHA is not the head")
    return reasons


def state_violations(s):
    reasons = []
    if s.review_rounds > MAX_REVIEW_ROUNDS + (1 if s.reopened else 0):
        reasons.append("review rounds exceed the ceiling")
    for name, bound in (
        ("attempts", MAX_ATTEMPTS),
        ("fixes", MAX_FIXES),
        ("refreshes", MAX_REFRESHES),
    ):
        if getattr(s, name) > bound:
            reasons.append(f"{name} exceeds {bound}")
    if s.phase in ("Merged", "PostMerge", "Revert") and s.merged_head < 0:
        reasons.append(f"{s.phase} without a merge")
    return reasons


# -- model checking -------------------------------------------------------------


def canonical(s):
    """Collapse a state to what the spec can observe.

    Heads, bases and logic versions only ever increase, so evidence recorded for
    an older one can never become current again. Each evidence identity is
    therefore kept only as current (0) or stale (-1 / ()), which makes the graph
    finite without letting the spec read the table's own flags. Terminal states
    keep only what distinguishes their outcome.
    """
    if s.phase in TERMINAL:
        return State(
            phase=s.phase,
            authority=s.authority,
            merged_head=0 if s.merged_head >= 0 else -1,
            reverted=s.reverted,
        )
    current = (s.head, s.base)
    return s._replace(
        head=0,
        base=0,
        logic=0,
        pushed_head=0 if s.pushed_head == s.head else -1,
        proven_for=(0, 0) if s.proven_for == current else (),
        ci_for=(0, 0) if s.ci_for == current else (),
        reviewed_logic=0 if s.reviewed_logic == s.logic else -1,
        age_head=0 if s.age_head == s.head else -1,
        merged_head=0 if s.merged_head == s.head else -1,
    )


class Graph:
    """Reachable (canonical state, observer) nodes: the table in product with its observer."""

    def __init__(self, mutants=frozenset(), authorities=AUTHORITIES):
        self.parent = {}
        self.edges = defaultdict(list)
        self.merges = []  # (node, raw successor): the table step into Merged
        self.raw_violations = []  # (node, reason) seen on a successor before collapsing
        queue = deque()
        for authority in authorities:
            start = (initial(authority), Observer())
            self.parent[start] = None
            queue.append(start)
        while queue:
            node = queue.popleft()
            state, obs = node
            for event in EVENTS:
                raw = step(state, event, mutants)
                if raw is None:
                    continue  # disabled
                if raw.phase == "Merged" and state.phase != "Merged":
                    self.merges.append((node, raw))
                for reason in state_violations(raw):
                    self.raw_violations.append((node, f"{reason} after {event}"))
                successor = (canonical(raw), observe(obs, event))
                if successor == node:
                    continue  # a state-preserving no-op
                self.edges[node].append((event, successor))
                if successor not in self.parent:
                    self.parent[successor] = (node, event)
                    queue.append(successor)

    def trace(self, node):
        events = []
        while self.parent[node] is not None:
            node, event = self.parent[node]
            events.append(event)
        return node[0].authority, events[::-1]


def _cycles(graph):
    """Strongly connected components with more than one state (iterative Tarjan)."""
    index, low, on_stack, stack, found = {}, {}, set(), [], []
    counter = 0
    for root in graph.parent:
        if root in index:
            continue
        work = [(root, iter(graph.edges[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, successors = work[-1]
            advanced = False
            for _, nxt in successors:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(graph.edges[nxt])))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    found.append(component)
    return found


def model_check(mutants=frozenset()):
    graph = Graph(mutants)
    violations = []

    def add(kind, state, detail):
        authority, events = graph.trace(state)
        violations.append(
            {"kind": kind, "detail": detail, "authority": authority, "trace": events}
        )

    for node, reason in graph.raw_violations:
        add("state", node, reason)
    for node, successor in graph.merges:
        reasons = merge_violations(node[0], successor, node[1])
        if reasons:
            add("illegal_merge", node, "; ".join(reasons))
    for authority in AUTHORITIES:
        if authority == "free" and not any(
            node[0].authority == authority for node, _ in graph.merges
        ):
            add(
                "liveness",
                (initial(authority), Observer()),
                "free authority can never merge",
            )
    for component in _cycles(graph):
        entry = min(component, key=lambda s: len(graph.trace(s)[1]))
        add(
            "unbounded_cycle",
            entry,
            f"{len(component)} states repeat with no counter progress",
        )
    settled = {n for n in graph.parent if n[0].phase in TERMINAL | WAITING_ON_OWNER}
    reverse = defaultdict(list)
    for state, edges in graph.edges.items():
        for _, successor in edges:
            reverse[successor].append(state)
    frontier = deque(settled)
    while frontier:
        for previous in reverse[frontier.popleft()]:
            if previous not in settled:
                settled.add(previous)
                frontier.append(previous)
    trapped = [s for s in graph.parent if s not in settled]
    if trapped:
        add(
            "trap",
            min(trapped, key=lambda s: len(graph.trace(s)[1])),
            "cannot reach a terminal state",
        )
    phases = sorted({n[0].phase for n in graph.parent})
    merges = len(graph.merges)
    return {
        "mutants": sorted(mutants),
        "states": len(graph.parent),
        "transitions": sum(len(e) for e in graph.edges.values()),
        "merge_edges": merges,
        "phases": phases,
        "ok": not violations,
        "violations": violations[:20],
        "violation_count": len(violations),
    }


def random_traces(count, seed, authority=None, max_steps=200, mutants=frozenset()):
    """Seeded random walks: a conformance corpus an implementation must replay identically.

    Each trace carries, per step, the phase reached and the events the model refuses
    in the state before that step (and in the final state), so a permissive
    implementation that accepts a disabled event fails the corpus, not just a
    strict one that rejects an enabled event.
    """
    rng = random.Random(seed)
    for number in range(count):
        state = initial(authority or rng.choice(AUTHORITIES))
        events, phases, refused = [], [], []
        for _ in range(max_steps):
            outcomes = {e: step(state, e, mutants) for e in EVENTS}
            refused.append(sorted(e for e, nxt in outcomes.items() if nxt is None))
            enabled = [e for e, nxt in outcomes.items() if nxt not in (None, state)]
            if not enabled:
                break
            event = rng.choice(enabled)
            events.append(event)
            state = outcomes[event]
            phases.append(state.phase)
        else:
            refused.append(sorted(e for e in EVENTS if step(state, e, mutants) is None))
        yield {
            "trace": number,
            "authority": state.authority,
            "events": events,
            "phases": phases,
            "refused": refused,
            "final": state._asdict(),
        }


def mermaid():
    """Phase-level diagram of the reachable graph, for the contract doc."""
    graph = Graph()
    edges = defaultdict(set)
    for (state, _), out in graph.edges.items():
        for event, (successor, _) in out:
            if successor.phase != state.phase:
                edges[(state.phase, successor.phase)].add(event)
    lines = ["stateDiagram-v2", "  [*] --> Candidate"]
    for (source, target), events in sorted(edges.items()):
        lines.append(f"  {source} --> {target}: {', '.join(sorted(events))}")
    lines.extend(f"  {phase} --> [*]" for phase in sorted(TERMINAL))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", help="exhaustively check the invariants")
    chk.add_argument("--mutant", action="append", choices=sorted(MUTANTS), default=[])
    chk.add_argument(
        "--all-mutants", action="store_true", help="prove each mutant is caught"
    )
    trc = sub.add_parser("traces", help="emit a seeded conformance corpus as JSONL")
    trc.add_argument("--count", type=int, default=100)
    trc.add_argument("--seed", type=int, default=0)
    trc.add_argument("--authority", choices=AUTHORITIES)
    sub.add_parser("diagram", help="print the phase graph as Mermaid")
    args = parser.parse_args(argv)
    if args.command == "check":
        if args.all_mutants:
            baseline = model_check()
            caught = {
                name: not model_check(frozenset({name}))["ok"]
                for name in sorted(MUTANTS)
            }
            result = {
                "model_ok": baseline["ok"],
                "states": baseline["states"],
                "mutants_caught": caught,
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if baseline["ok"] and all(caught.values()) else 1
        result = model_check(frozenset(args.mutant))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.command == "traces":
        for trace in random_traces(args.count, args.seed, args.authority):
            print(json.dumps(trace, sort_keys=True))
        return 0
    print(mermaid())
    return 0


if __name__ == "__main__":
    sys.exit(main())
