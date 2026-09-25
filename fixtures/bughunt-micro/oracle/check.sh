#!/usr/bin/env bash
# Exit 0 only for a valid, nonempty, complete all-fixed result.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/oracle/score.sh" --check "$@"
