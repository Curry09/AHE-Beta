#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$root"
exec python evaluation/harness-suite-20260920/run_n1_e2b.py "$@"
