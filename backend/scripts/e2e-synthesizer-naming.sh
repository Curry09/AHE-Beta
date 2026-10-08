#!/usr/bin/env bash
# Spec-0068/T6: offline role pipeline + interrupted stage resume + guard enforcement.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
python_bin="${PYTHON:-$repo_root/.venv/bin/python}"
"$python_bin" -m pytest -q \
  backend/tests/test_export_experiment_snapshot.py \
  backend/tests/demand/test_role_contract_flow.py \
  backend/tests/test_stage_resume_e2e.py \
  backend/tests/guards
