#!/usr/bin/env bash
# Run every test suite. App suites must run from their own directory:
# their modules share top-level names (handler, settings, config), so one
# pytest process over the whole repo would import the wrong files.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python}"
# suites cd into app dirs, so a relative interpreter path must be made absolute
if [[ "$PYTHON" == */* ]]; then
  PYTHON="$(cd "$(dirname "$PYTHON")" && pwd)/$(basename "$PYTHON")"
fi
status=0

run_suite() {
  local dir="$1"
  echo "==> $dir"
  (cd "$ROOT/$dir" && "$PYTHON" -m pytest -q) || status=1
}

run_suite .
run_suite apps/cp_bot
run_suite apps/split_bot
run_suite apps/pinxiang_bot

exit "$status"
