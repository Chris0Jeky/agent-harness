"""Offline UX contract checks. Never invokes browsers, models, Git or publication."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .common import ContractError, load_json
from .scenarios import bind_pack
from .evidence import verify_observation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("bind", "Validate scenario declarations; does not run a journey"),
                            ("verify", "Verify frozen artifact identity and declared coverage")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--pack", type=Path, required=True)
        command.add_argument("--expected-repository", required=True)
        command.add_argument("--expected-revision", required=True)
        command.add_argument("--fixture-ref", action="append", default=[])
        if name == "verify":
            command.add_argument("--manifest", type=Path, required=True)
            command.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        options = dict(expected_repository=args.expected_repository,
                       expected_revision=args.expected_revision, allowed_fixtures=args.fixture_ref)
        pack = load_json(args.pack)
        if args.command == "bind":
            result = bind_pack(pack, **options)
        else:
            result = verify_observation(pack=pack, manifest=load_json(args.manifest),
                                        run_root=args.run_root, **options)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        return 3 if args.command == "verify" and not result["coverage_complete"] else 0
    except ContractError as exc:
        print(f"UX contract refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
