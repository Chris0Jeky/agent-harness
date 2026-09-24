#!/usr/bin/env bash
# Exit 0 only when ALL planted bugs are FIXED (score == total).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCORE_JSON="$("$ROOT/oracle/score.sh")"
echo "$SCORE_JSON"
PASS=$(echo "$SCORE_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['passed'])")
TOTAL=$(echo "$SCORE_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['total'])")
if [[ "$PASS" -eq "$TOTAL" ]]; then
  echo "ORACLE OK: $PASS/$TOTAL"
  exit 0
fi
echo "ORACLE FAIL: $PASS/$TOTAL (bugs still present or incomplete fix)"
exit 1
