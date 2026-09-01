#!/usr/bin/env bash
# Spec-0050/T5：轮次封口 e2e——无密钥、不启真 vigil。
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

PYTHONPATH=backend .venv/bin/pytest -q \
  backend/tests/loop/test_round_gate.py \
  backend/tests/loop/test_orchestrator.py::test_run_skips_demand_on_last_round \
  backend/tests/loop/test_orchestrator.py::test_blocked_delivery_does_not_start_next_user_round \
  backend/tests/loop/test_live.py::test_live_run_roundtrip_and_defaults \
  backend/tests/test_run_vigil.py::test_vigil_keep_alive_defaults_off \
  backend/tests/test_run_vigil.py::test_container_keep_alive_does_not_remove_container \
  backend/tests/test_run_vigil.py::test_container_stop_removes_container
