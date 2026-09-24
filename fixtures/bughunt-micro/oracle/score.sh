#!/usr/bin/env bash
# Deterministic BH3 score → JSON {passed, total, per_bug:[...]}
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Locate python with pytest
PY="${BH3_PYTHON:-}"
if [[ -z "$PY" ]]; then
  for cand in \
    "$ROOT/../../.venv/bin/python" \
    "$ROOT/../.venv/bin/python" \
    "$ROOT/.venv/bin/python" \
    python3; do
    if [[ -x "$cand" ]] || command -v "$cand" >/dev/null 2>&1; then
      if "$cand" -c "import pytest" 2>/dev/null; then
        PY="$cand"
        break
      fi
    fi
  done
fi
if [[ -z "${PY:-}" ]]; then
  echo '{"error":"pytest not available","passed":0,"total":0,"per_bug":[]}' >&2
  exit 2
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PY" - <<'PY'
import json, re, subprocess, sys
from pathlib import Path
root = Path(".").resolve()
py = sys.executable
r = subprocess.run(
    [py, "-m", "pytest", "tests/test_oracle.py", "-v", "--tb=line", "-p", "no:cacheprovider"],
    cwd=root, capture_output=True, text=True
)
out = r.stdout + "\n" + r.stderr
manifest = json.loads((root / "bugs" / "MANIFEST.json").read_text())
src = (root / "src" / "app.py").read_text()
per = []
passed = 0
for bug in manifest["bugs"]:
    tid = bug["test"]
    m = re.search(rf"::{re.escape(tid)}\s+(PASSED|FAILED|ERROR)", out)
    ok = bool(m and m.group(1) == "PASSED")
    if ok:
        passed += 1
    fp = bug.get("fingerprint_rg")
    fp_hit = None
    if fp:
        try:
            fp_hit = re.search(fp, src) is not None
        except re.error:
            fp_hit = fp in src
    per.append({"id": bug["id"], "test": tid, "passed": ok, "fingerprint_present": fp_hit})
result = {
    "passed": passed,
    "total": len(manifest["bugs"]),
    "per_bug": per,
    "pytest_exit": r.returncode,
    "mode": "all_fixed" if passed == len(manifest["bugs"]) else "bugs_present",
}
print(json.dumps(result, indent=2))
PY
