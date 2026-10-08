#!/usr/bin/env bash
# Spec-0074/T5: offline production-runtime integration, no provider/model credentials.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Install the locked experiment dependencies first: uv sync --locked --extra experiments --extra dev' >&2
  exit 1
fi
.venv/bin/python -m pytest -q \
  backend/tests/test_experiment_batch_config.py \
  backend/tests/test_experiment_batch_store.py \
  backend/tests/test_experiment_batch.py \
  backend/tests/test_experiment_batch_e2e.py \
  backend/tests/test_experiment_batch_examples.py
