#!/usr/bin/env python3
"""Variant archive and Pareto frontier over candidate genomes (ADAS/DGM style).

The archive is a tree, not a lineage: every ``candidate-genome/v1`` stays in
it, linked to its ``parent_genome``, so a dominated variant can still parent a
better one later. Nothing is optimised as a single scalar. A genome joins
the comparison only when it measured every objective asked for, with the
directions in
``schemas/learning/objectives.json``; the frontier is the set no other
measured genome dominates, and parents for the next generation are frontier
members ranked by crowding distance (NSGA-II), so the extremes and the sparse
regions of the frontier are explored first.

    archive(genomes, objectives=None) -> learning-archive/v1 report
    dominates(a, b, objectives)       -> bool
"""

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys

_SPEC = importlib.util.spec_from_file_location(
    "learning_contracts", Path(__file__).resolve().with_name("learning_contracts.py")
)
contracts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(contracts)

REPORT_SCHEMA = "learning-archive/v1"


def directions():
    return contracts._document("objectives.json")["objectives"]


def _gain(genome, objective):
    """The objective as a larger-is-better number."""
    value = genome["objectives"][objective]
    return value if directions()[objective] == "max" else -value


def dominates(a, b, objectives):
    """a is at least as good as b on every objective and better on one."""
    gains = [(_gain(a, o), _gain(b, o)) for o in objectives]
    return all(x >= y for x, y in gains) and any(x > y for x, y in gains)


def frontier(genomes, objectives):
    """Ids of the genomes no other genome dominates, sorted."""
    return sorted(
        g["id"]
        for g in genomes
        if not any(dominates(o, g, objectives) for o in genomes if o is not g)
    )


def crowding(genomes, objectives):
    """NSGA-II crowding distance per genome id (inf at each objective's extremes)."""
    distance = {g["id"]: 0.0 for g in genomes}
    if len(genomes) < 3:
        return {key: math.inf for key in distance}
    for objective in objectives:
        ranked = sorted(genomes, key=lambda g: (_gain(g, objective), g["id"]))
        low, high = _gain(ranked[0], objective), _gain(ranked[-1], objective)
        if high == low:
            continue  # a constant objective has no extremes to protect
        distance[ranked[0]["id"]] = distance[ranked[-1]["id"]] = math.inf
        for before, current, after in zip(ranked, ranked[1:], ranked[2:]):
            spread = (_gain(after, objective) - _gain(before, objective)) / (high - low)
            distance[current["id"]] += spread
    return distance


def _tree(by_id, problems):
    """children per id, roots and depth; orphans become roots, cycles are cut."""
    children = {key: [] for key in by_id}
    roots = []
    for key, genome in sorted(by_id.items()):
        parent = genome["parent_genome"]
        if parent is None:
            roots.append(key)
        elif parent not in by_id:
            problems.append(f"{key}: parent {parent} is not in the archive")
            roots.append(key)
        else:
            children[parent].append(key)
    depth, frontier_ids = {}, [(root, 0) for root in roots]
    while frontier_ids:
        key, level = frontier_ids.pop()
        depth[key] = level
        frontier_ids += [(child, level + 1) for child in children[key]]
    for key in sorted(set(by_id) - set(depth)):
        problems.append(f"{key}: on or below a parent cycle")
        depth[key] = None
    return children, sorted(roots), depth


def archive(genomes, objectives=None, parents=4):
    """The learning-archive/v1 report over validated genomes."""
    known = directions()
    objectives = list(objectives or known)
    unknown = [o for o in objectives if o not in known]
    if unknown:
        raise ValueError(f"unknown objectives {unknown}; known: {sorted(known)}")
    problems, by_id, clashed = [], {}, set()
    for genome in genomes:
        errors = contracts.validate_record(genome)
        if not errors and genome.get("schema") != "candidate-genome/v1":
            errors = ["not a candidate-genome/v1"]
        if not errors and not all(
            math.isfinite(v) for v in genome.get("objectives", {}).values()
        ):
            errors = ["objectives must be finite numbers"]
        ident = genome.get("id", "?") if isinstance(genome, dict) else "?"
        if errors:
            problems.append(f"{ident}: {errors[0]}")
        elif ident in by_id and by_id[ident] != genome:
            problems.append(f"{ident}: two different genomes share this id")
            clashed.add(ident)
        else:
            by_id[ident] = genome
    # Neither copy of a clashing id is trusted, so input order cannot decide.
    for ident in clashed:
        del by_id[ident]
    children, roots, depth = _tree(by_id, problems)
    measured = [
        g
        for _, g in sorted(by_id.items())
        if all(o in g.get("objectives", {}) for o in objectives)
    ]
    front = frontier(measured, objectives)
    front_genomes = [g for g in measured if g["id"] in front]
    distance = crowding(front_genomes, objectives)
    chosen = sorted(front, key=lambda key: (-distance[key], key))[:parents]
    best = {}
    for objective in objectives:
        scored = [g for g in by_id.values() if objective in g.get("objectives", {})]
        if scored:
            best[objective] = max(scored, key=lambda g: (_gain(g, objective), g["id"]))[
                "id"
            ]
    return {
        "schema": REPORT_SCHEMA,
        "objectives": {o: known[o] for o in objectives},
        "genomes": [
            {
                "id": key,
                "parent": genome["parent_genome"],
                "depth": depth[key],
                "children": sorted(children[key]),
                "layers": sorted(genome["changes"]),
                "objectives": genome.get("objectives", {}),
                "frontier": key in front,
                "evaluation_ref": (genome.get("evaluation") or {}).get("result_ref"),
            }
            for key, genome in sorted(by_id.items())
        ],
        "roots": roots,
        "frontier": front,
        "unmeasured": sorted(set(by_id) - {g["id"] for g in measured}),
        "best": best,
        "parents": chosen,
        "problems": problems,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "genomes", type=Path, nargs="+", help="genome .json/.jsonl files"
    )
    parser.add_argument(
        "--objectives", help="comma-separated subset (default: all of objectives.json)"
    )
    parser.add_argument("--parents", type=int, default=4, help="parents to select")
    args = parser.parse_args(argv)
    try:
        genomes = [g for path in args.genomes for g in contracts.read_records(path)]
        objectives = args.objectives.split(",") if args.objectives else None
        report = archive(genomes, objectives, max(args.parents, 0))
    except (
        contracts.ContractError,
        OSError,
        ValueError,
        RecursionError,
        ArithmeticError,
    ) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
