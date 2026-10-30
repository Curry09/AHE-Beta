#!/usr/bin/env bash
# Spec-0071/T6: public material, frozen-source, and retired-entry contracts, offline.
set -euo pipefail
cd "$(dirname "$0")/../.."
if (($#)); then
  echo "Usage: $0 (offline only; live experiment verification uses e2e-spec-0069-experiment-entry.sh)" >&2
  exit 2
fi
uv run --locked --extra experiments --extra dev python backend/scripts/check_experiment_repository.py
uv run --locked --extra experiments --extra dev --extra harbor-evaluation pytest -q \
  backend/tests/test_experiment_repository.py \
  backend/tests/test_replay_roles_from_sessions.py \
  backend/tests/test_prepare_openagents_validation.py \
  backend/tests/test_prepare_openagents_from_summary.py \
  evaluation/tests
bash backend/scripts/e2e-spec-0069-experiment-entry.sh
