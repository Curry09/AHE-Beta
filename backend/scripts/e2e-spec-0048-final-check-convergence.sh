#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

PYTHONPATH=backend .venv/bin/pytest -q \
  backend/tests/user/sim/test_loop.py::test_active_final_check_converges_through_rejudge_and_reintent \
  backend/tests/user/sim/test_loop.py::test_protocol_failure_is_evaluator_invalid_not_accept \
  backend/tests/user/sim/test_persona_client_agentic.py::test_main_act_private_tool_object_is_retried_not_accepted \
  backend/tests/user/sim/test_persona_client_agentic.py::test_run_session_two_illegal_act_tool_objects_yield_zero_accept \
  backend/tests/scripts/test_audit_sim_action_integrity.py

if [[ -n "${USER_LLM_BASE_URL:-}" && -n "${USER_LLM_API_KEY:-}" && -n "${USER_LLM_MODEL:-}" ]]; then
  timeout "${SPEC0048_CANARY_MAX_WALL:-1800}" \
    env PYTHONPATH=backend .venv/bin/python backend/scripts/canary_spec0048_final_check.py
fi
