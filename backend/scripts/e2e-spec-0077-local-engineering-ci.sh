#!/usr/bin/env bash
# Spec-0077/T4: offline lifecycle/receipt regressions; real Docker results are recorded separately.
set -euo pipefail
cd "$(dirname "$0")/../.."
uv run --locked --extra experiments --extra dev pytest -q \
  backend/tests/test_experiment_ci_config.py \
  backend/tests/test_experiment_local_ci.py \
  backend/tests/test_experiment_ci_collection.py \
  backend/tests/test_experiment_local_backend.py \
  backend/tests/test_experiment_lifecycle_v2.py \
  backend/tests/experiment/test_infrastructure.py
