#!/usr/bin/env bash
# Spec-0047：并行实验运行时离线验收（无真实 GLM、不启双栈 live cert）。
# T6 真实模型认证另议；本脚本只跑配置/manifest/compose mock/CLI/容量/健康/run.py 拒 attach。
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

PYTHONPATH=backend .venv/bin/pytest -q \
  backend/tests/experiment \
  backend/tests/test_run_vigil.py::test_container_refuses_foreign_experiment_attach \
  backend/tests/test_run_vigil.py::test_apply_experiment_context_overrides_singleton
