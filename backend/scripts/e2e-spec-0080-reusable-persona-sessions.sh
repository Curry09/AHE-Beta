#!/usr/bin/env bash
# Spec-0080/T4: offline compilation, real subprocess workspaces, recovery and archive roundtrip.
# Scripted models verify orchestration, not model quality or cloud readiness.
set -euo pipefail
cd "$(dirname "$0")/../.."
uv run --locked --extra experiments --extra dev pytest -q \
  backend/tests/test_reusable_persona_sessions.py \
  backend/tests/test_experiment_config_v2.py \
  backend/tests/test_experiment_workload.py \
  backend/tests/test_experiment_multitask_controller.py \
  backend/tests/test_experiment_continuation_*.py \
  backend/tests/loop/test_orchestrator.py \
  backend/tests/loop/test_recovery.py
