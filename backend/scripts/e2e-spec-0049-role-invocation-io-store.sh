#!/usr/bin/env bash
# Spec-0049/T5：角色调用落盘与冻结重放 e2e——无密钥、不启真 Gitea/vigil。
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

PYTHONPATH=backend .venv/bin/pytest -q \
  backend/tests/test_invocation.py \
  backend/tests/demand/test_agent_runtime.py \
  backend/tests/guards/test_workspace_jail.py \
  backend/tests/test_run_vigil.py::test_install_role_runs_does_not_delete_prior_slice \
  backend/tests/test_run_vigil.py::test_reset_to_initial_leaves_role_runs \
  backend/tests/test_run_vigil.py::test_container_mounts_only_delivery_role_runs \
  backend/tests/test_run_vigil.py::test_container_rebuilds_when_run_id_changes \
  backend/tests/scripts/test_replay_role_invocations.py \
  backend/tests/test_delivery_invocation_contract.py
