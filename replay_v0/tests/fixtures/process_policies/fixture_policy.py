"""Synthetic process-policy modes used by the replay v0 contract tests."""

from __future__ import annotations

import json
import sys
import time


def decision(event: dict[str, object]) -> dict[str, str]:
    effect = "deny" if "--force" in str(event["command"]) else "allow"
    return {
        "schema_version": "policy-decision.v1",
        "event_id": str(event["event_id"]),
        "effect": effect,
        "reason": f"Synthetic fixture returned {effect}.",
    }


events = [json.loads(line) for line in sys.stdin if line.strip()]
mode = sys.argv[1]
rows = [decision(event) for event in events]

if mode == "timeout":
    time.sleep(2)
elif mode == "malformed":
    print("{not-json")
    print(json.dumps(rows[1], sort_keys=True, separators=(",", ":")))
elif mode == "duplicate":
    print(json.dumps(rows[0], sort_keys=True, separators=(",", ":")))
    print(json.dumps(rows[0], sort_keys=True, separators=(",", ":")))
    print(json.dumps(rows[1], sort_keys=True, separators=(",", ":")))
elif mode == "partial":
    print(json.dumps(rows[0], sort_keys=True, separators=(",", ":")))
elif mode == "nonzero":
    print(json.dumps(rows[0], sort_keys=True, separators=(",", ":")))
    raise SystemExit(7)
elif mode == "reversed":
    for row in reversed(rows):
        print(json.dumps(row, sort_keys=True, separators=(",", ":")))
elif mode == "success":
    print("synthetic diagnostic", file=sys.stderr)
    for row in rows:
        print(json.dumps(row, sort_keys=True, separators=(",", ":")))
else:
    raise SystemExit(64)
