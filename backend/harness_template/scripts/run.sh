#!/usr/bin/env bash
# Start the harness locally. Run from any directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON="${PYTHON:-python3}"
exec "$PYTHON" entry.py
