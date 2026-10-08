#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

PYTHONPATH=backend .venv/bin/python -m pytest -q \
  backend/tests/test_stage_resume_e2e.py \
  backend/tests/loop/test_recovery.py \
  backend/tests/loop/test_orchestrator.py \
  backend/tests/loop/test_round_gate.py \
  backend/tests/loop/test_sim_user.py \
  backend/tests/user/test_session_store.py \
  backend/tests/demand/test_triage.py \
  backend/tests/demand/test_divergent_gate.py \
  backend/tests/loop/test_synthesizer.py \
  backend/tests/demand/test_grouped_synthesizer.py \
  backend/tests/demand/test_owner.py \
  backend/tests/demand/test_delivery_evidence.py
