#!/usr/bin/env bash
# Spec-0073/T6: real experiment core, with offline model/provider boundaries.
set -euo pipefail
cd "$(dirname "$0")/../.."
if (($#)); then
  echo "Usage: $0 (offline verification; does not launch Docker/E2B/Gitea or models)" >&2
  exit 2
fi
echo "Offline verification: compilation, material identity, sessions, demand, delivery and recovery."
uv run --locked --extra experiments --extra dev python backend/scripts/check_experiment_repository.py
uv run --locked --extra experiments --extra dev pytest -q \
  backend/tests/test_experiment_config_v2.py \
  backend/tests/test_experiment_materials.py \
  backend/tests/test_experiment_workload.py \
  backend/tests/test_experiment_public_examples.py \
  backend/tests/test_experiment_repository.py \
  backend/tests/test_experiment_multitask_controller.py \
  backend/tests/test_experiment_multitask_e2e.py
