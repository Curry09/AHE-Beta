#!/usr/bin/env bash
# Spec-0072/T5: frozen configuration, both backends and real consumers; no provider calls.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
uv run --locked --extra experiments --extra dev python backend/scripts/check_experiment_repository.py
uv run --locked --extra experiments --extra dev pytest -q \
  backend/tests/test_experiment_config_v2.py \
  backend/tests/test_experiment_materials.py \
  backend/tests/test_experiment_engine.py \
  backend/tests/test_experiment_lifecycle_v2.py \
  backend/tests/test_experiment_local_backend.py \
  backend/tests/test_experiment_e2b_backend.py \
  backend/tests/test_experiment_e2b_bootstrap.py \
  backend/tests/test_experiment_interactions.py \
  backend/tests/test_experiment_dashboard.py \
  backend/tests/test_experiment_cli_v2.py \
  backend/tests/test_experiment_capability_migration.py \
  backend/tests/test_run_vigil.py \
  backend/tests/test_run_swebench_closed_loop.py \
  backend/tests/test_experiment_repository.py \
  backend/tests/test_experiment_public_examples.py
