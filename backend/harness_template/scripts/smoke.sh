#!/usr/bin/env bash
# Run deterministic harness self-tests. Does not require a live model endpoint.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
exec "$PYTHON" -m unittest discover -s tests -p 'test_*.py'
