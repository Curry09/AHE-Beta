#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "usage: $0 RUN_ID [--gitea-env PATH]" >&2
  exit 2
fi
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$root"
run_id=$1
shift
exec python evaluation/harness-suite-20260920/run_n1_e2b.py --resume --run-id "$run_id" "$@"
