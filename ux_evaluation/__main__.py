"""Offline UX contract checks. Never invokes browsers, models, Git or publication."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .common import ContractError, load_json
from .scenarios import bind_pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    bind = commands.add_parser("bind", help="Validate scenario declarations; does not run a journey")
    bind.add_argument("--pack", type=Path, required=True)
    bind.add_argument("--expected-repository", required=True)
    bind.add_argument("--expected-revision", required=True)
    bind.add_argument("--fixture-ref", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        result = bind_pack(load_json(args.pack), expected_repository=args.expected_repository,
                           expected_revision=args.expected_revision, allowed_fixtures=args.fixture_ref)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        return 0
    except ContractError as exc:
        print(f"UX contract refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
