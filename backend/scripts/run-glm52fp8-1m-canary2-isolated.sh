#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
config="/root/src/auto-designer-experiment-configs/glm52fp8-1m-canary2-isolated.yaml"

export EXPERIMENTS_ROOT="${EXPERIMENTS_ROOT:-/root/src/auto-designer-experiments}"
export PYTHONPATH="$repo_root/backend${PYTHONPATH:+:$PYTHONPATH}"

exec "$repo_root/.venv/bin/python" \
  "$repo_root/backend/scripts/run_auditable_experiment.py" \
  --config "$config" \
  "$@"
