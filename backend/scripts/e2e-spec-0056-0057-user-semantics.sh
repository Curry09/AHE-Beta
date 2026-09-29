#!/usr/bin/env bash
# Offline integration checks: no model calls, external tracker writes, or containers.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
exec "$repo_root/.venv/bin/python" -m pytest -q \
  backend/tests/user/sim/test_goals.py \
  backend/tests/user/sim/test_loop.py \
  backend/tests/user/sim/test_feedback.py \
  backend/tests/user/sim/test_heartbeat.py \
  backend/tests/user/sim/test_prompt.py \
  backend/tests/demand/test_terminal_evidence.py \
  backend/tests/evaluation/test_swebench.py
