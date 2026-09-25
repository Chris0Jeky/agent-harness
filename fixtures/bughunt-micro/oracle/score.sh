#!/usr/bin/env bash
# Use one interpreter for scoring and --check; Python is also the native Windows entrypoint.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${BH3_PYTHON:-}"
if [[ -z "$PY" ]]; then
  for cand in "$ROOT/.venv/bin/python" "$ROOT/../../.venv/bin/python" python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -I -c "import pytest" 2>/dev/null; then
      PY="$cand"
      break
    fi
  done
fi
if [[ -z "$PY" ]]; then
  echo '{"valid":false,"mode":"invalid","error":"pytest not available","passed":0,"total":0,"per_bug":[]}'
  exit 2
fi
exec "$PY" -I "$ROOT/oracle/score.py" "$@"
