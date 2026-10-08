#!/usr/bin/env bash
# Offline acceptance for spec-0051. It never calls a real LLM or starts an experiment.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

export TMPDIR=/tmp
export TEMP=/tmp
export TMP=/tmp
export PYTHONPATH=backend

.venv/bin/pytest -q \
  backend/tests/user/sim/test_workspace_runtime.py \
  backend/tests/user/sim/test_docker_seed_source.py \
  backend/tests/harness/test_launcher.py \
  backend/tests/loop/test_orchestrator.py \
  backend/tests/loop/test_sim_user.py \
  backend/tests/evaluation/test_swebench_runner.py \
  backend/tests/user/test_session_store.py \
  backend/tests/test_models.py

runtime_image="${SWEBENCH_RUNTIME_SEED_IMAGE:-auto-designer-seed:swebench-medium-hard-16-runtime-v1}"
label="$(docker image inspect \
  --format '{{ index .Config.Labels "org.auto-designer.seed-runtime" }}' \
  "$runtime_image")"
test "$label" = 1

before="$(docker ps -aq --filter label=auto-designer.session | sort)"
PYTHONPATH=backend .venv/bin/python - "$runtime_image" <<'PY'
import json
import subprocess
import sys

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.seed_source import provision

image = sys.argv[1]
probe = subprocess.run(
    ["docker", "run", "--rm", image, "cat", "/build-state.json"],
    capture_output=True,
    text=True,
    check=True,
)
instance_id = next(iter(json.loads(probe.stdout)["instances"]))
runtime = provision(
    WorkspaceSpec(kind="docker-seed", params={"image": image, "instance_id": instance_id})
)
try:
    result = runtime.run("test -d .git && git status --short", timeout=30)
    assert result["status"] == "completed", result
    _, digest = runtime.export_patch()
    assert len(digest) == 64
    assert runtime.cwd.startswith("/workspace/")
    assert runtime.evidence["container_name"].startswith("ad-session-")
finally:
    runtime.close()
assert runtime.evidence.get("closed_at")
PY
after="$(docker ps -aq --filter label=auto-designer.session | sort)"
test "$before" = "$after"

./tools/spec-driven-development/spec validate
./tools/spec-driven-development/spec render
./tools/spec-driven-development/spec graph --package-root backend/auto_designer
