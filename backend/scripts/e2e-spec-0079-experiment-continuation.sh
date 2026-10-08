#!/usr/bin/env bash
# Spec-0079/T6: offline source/freeze/bootstrap/lineage and ordinary recovery contracts.
# Real model feedback and nonempty delivery require the separate validation report.
set -euo pipefail
cd "$(dirname "$0")/../.."
uv run --locked --extra experiments --extra dev pytest -q \
  backend/tests/test_experiment_continuation_*.py \
  backend/tests/test_experiment_config_v2.py \
  backend/tests/test_experiment_materials.py \
  backend/tests/test_experiment_workload.py \
  backend/tests/test_experiment_grading.py \
  backend/tests/test_experiment_grading_e2e.py \
  backend/tests/loop/test_feedback_pipeline.py \
  backend/tests/loop/test_orchestrator.py \
  backend/tests/demand/test_triage.py \
  backend/tests/demand/test_divergent_gate.py \
  backend/tests/demand/test_grouped_synthesizer.py
