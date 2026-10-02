#!/usr/bin/env bash
# Spec-0047 current shared contracts after Spec-0071 retired the v1 runtime.
# Offline only: manifest journals, context binding and foreign-container isolation.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

PYTHONPATH=backend .venv/bin/pytest -q \
  backend/tests/experiment \
  backend/tests/test_run_vigil.py::test_container_refuses_foreign_experiment_attach \
  backend/tests/test_run_vigil.py::test_apply_experiment_context_overrides_singleton
