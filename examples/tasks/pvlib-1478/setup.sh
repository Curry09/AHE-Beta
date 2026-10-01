#!/usr/bin/env bash
# Spec-0069/T6: task dependencies are separate from the controller environment.
set -euo pipefail
: "${TASK_ROOT:?task repository is required}"
: "${TASK_PYTHON:?managed Python is required}"
: "${REQUIREMENTS_LOCK:?frozen dependency lock is required}"
: "${VIRTUAL_ENV:?task virtual environment is required}"
: "${UV_BIN:?pinned uv executable is required}"
cd "$TASK_ROOT"
"$UV_BIN" venv --allow-existing --python "$TASK_PYTHON" "$VIRTUAL_ENV"
"$UV_BIN" pip install --python "$VIRTUAL_ENV/bin/python" --require-hashes -r "$REQUIREMENTS_LOCK"
# This historical Versioneer calls APIs removed in Python 3.12. Restore aliases
# only for its build subprocess; do not patch the frozen task source.
build_compat=$(mktemp -d "$VIRTUAL_ENV/pvlib-build-compat.XXXXXX")
trap 'rm -rf "$build_compat"' EXIT
cat > "$build_compat/sitecustomize.py" <<'PYCOMPAT'
import configparser
configparser.SafeConfigParser = configparser.ConfigParser
configparser.ConfigParser.readfp = configparser.ConfigParser.read_file
PYCOMPAT
PYTHONPATH="$build_compat" "$UV_BIN" pip install --python "$VIRTUAL_ENV/bin/python" --no-deps --no-build-isolation -e .
"$VIRTUAL_ENV/bin/python" -c 'import pvlib; print("task environment ready:", pvlib.__version__)'
