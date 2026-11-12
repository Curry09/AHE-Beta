#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

.venv/bin/pytest -q \
  backend/tests/tracker/test_gitea_timeline.py \
  backend/tests/web/test_api.py \
  backend/tests/loop/test_architect.py

./tools/spec-driven-development/spec validate
./tools/spec-driven-development/spec render
./tools/spec-driven-development/spec graph --package-root backend/ahe_beta
