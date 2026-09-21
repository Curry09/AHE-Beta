#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python "$ROOT/evaluation/harness-suite-20260920/run_n1_e2b.py" --resume "$@"
