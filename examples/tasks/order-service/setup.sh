#!/usr/bin/env bash
# Spec-0073/T6: run in the final, isolated task environment.
set -euo pipefail
: "${TASK_ROOT:?task repository is required}"
: "${TASK_PYTHON:?managed Python is required}"
: "${REQUIREMENTS_LOCK:?frozen dependency lock is required}"
: "${VIRTUAL_ENV:?task virtual environment is required}"
: "${UV_BIN:?pinned uv executable is required}"
cd "$TASK_ROOT"
"$UV_BIN" venv --allow-existing --python "$TASK_PYTHON" "$VIRTUAL_ENV"
UV_LINK_MODE=copy "$UV_BIN" pip install --python "$VIRTUAL_ENV/bin/python" --require-hashes -r "$REQUIREMENTS_LOCK"
"$VIRTUAL_ENV/bin/python" -c 'import orders; print("order service task environment ready")'
