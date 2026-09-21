#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python "$ROOT/evaluation/harness-suite-20260920/run_scaling_e2b.py" --start --n 1 "$@"
