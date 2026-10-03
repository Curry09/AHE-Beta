#!/usr/bin/env bash
# Spec-0075/T3: real sessions/collector/evaluator wiring, scripted official Docker boundary.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Install locked dependencies: uv sync --locked --extra experiments --extra dev' >&2
  exit 1
fi
.venv/bin/python -m pytest -q \
  backend/tests/user/test_prediction_artifacts.py \
  backend/tests/evaluation/test_swebench.py \
  backend/tests/test_experiment_grading.py \
  backend/tests/test_experiment_grading_e2e.py \
  backend/tests/test_experiment_cli_v2.py \
  backend/tests/test_experiment_repository.py
