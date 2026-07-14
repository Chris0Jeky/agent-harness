#!/usr/bin/env python3
"""Regenerate the pinned curl option-arity fixture from tool_getparam.c."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/curl/curl/" "curl-8_21_0/src/tool_getparam.c"
)
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "curl_8_21_0_option_arity.json"
)
VALUE_KINDS = {"ARG_FILE", "ARG_SECS", "ARG_STRG", "ARG_UNUM"}
ALIAS_PATTERN = re.compile(r'\{"([^"]+)",\s*([^,]+),\s*\'(.)\'')


def parse_fixture(source: bytes, source_url: str) -> dict[str, object]:
    rows = ALIAS_PATTERN.findall(source.decode("utf-8"))
    if len(rows) != 283:
        raise ValueError(f"expected 283 curl aliases, found {len(rows)}")
    long_options = []
    short_options = set()
    for name, descriptor, short_option in rows:
        if not VALUE_KINDS.intersection(descriptor.split("|")):
            continue
        long_options.append(f"--{name}")
        if short_option != " ":
            short_options.add(short_option)
    if len(long_options) != 147 or len(short_options) != 27:
        raise ValueError(
            "unexpected curl value-option counts: "
            f"{len(long_options)} long, {len(short_options)} short"
        )
    return {
        "source_url": source_url,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "long_options_with_value": long_options,
        "short_options_with_value": "".join(sorted(short_options)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    with urlopen(args.source_url, timeout=30) as response:
        source = response.read()
    fixture = parse_fixture(source, args.source_url)
    args.output.write_text(
        json.dumps(fixture, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
