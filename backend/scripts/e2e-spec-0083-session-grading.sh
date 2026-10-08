#!/usr/bin/env bash
# Spec-0083/T6: offline production contracts and optional real grader controls.
set -euo pipefail
GRADING_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$GRADING_REPO_ROOT"
export PYTHONPATH="$GRADING_REPO_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Install dependencies: uv sync --locked --extra experiments --extra dev --extra evaluation' >&2
  exit 1
fi
if [[ ${1:-} == --help ]]; then
  echo 'Usage: bash backend/scripts/e2e-spec-0083-session-grading.sh [--official CONTROLS_JSON OUTPUT_DIR]'
  echo 'Default: offline contracts only. --official: execute real registered graders against private fixed controls.'
  exit 0
fi
if [[ $# -ne 0 && ( $# -ne 3 || $1 != --official ) ]]; then
  echo 'Expected no arguments or --official CONTROLS_JSON OUTPUT_DIR' >&2
  exit 2
fi
.venv/bin/python -m pytest -q \
  backend/tests/evaluation/test_grading_contracts.py \
  backend/tests/evaluation/test_grading_adapters.py \
  backend/tests/evaluation/test_swebench_runner.py \
  backend/tests/evaluation/test_session_artifacts.py \
  backend/tests/test_experiment_grading_task_config.py \
  backend/tests/test_experiment_grading_task_materials.py \
  backend/tests/test_experiment_grading_artifact_lifecycle.py \
  backend/tests/test_experiment_grading_plan.py \
  backend/tests/test_experiment_grading.py \
  backend/tests/test_experiment_grading_e2e.py \
  backend/tests/test_experiment_grading_compatibility.py \
  backend/tests/test_experiment_continuation_contract.py \
  backend/tests/test_experiment_continuation_source.py \
  backend/tests/test_experiment_continuation_lifecycle.py
if [[ $# -eq 0 ]]; then
  echo 'Offline contracts completed. Real official/custom grader controls were not run.'
  exit 0
fi
# This is a validation-only driver, not an alternate experiment or grade entry.
# Controls are operator-prepared verifier inputs, never claimed as Harness output.
.venv/bin/python - "$2" "$3" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

from auto_designer.evaluation.contracts import ArtifactInput, GradingRequest, MaterialInput
from auto_designer.evaluation.registry import get_adapter
from auto_designer.experiment.grading_inputs import load_grading_plan, read_material

profile_path = Path(sys.argv[1]).absolute()
profile_payload = profile_path.read_bytes()
profile = json.loads(profile_payload)
if set(profile) != {"plan", "controls"} or not isinstance(profile["controls"], list) or not profile["controls"]:
    raise ValueError("Control profile requires plan and a nonempty controls list")


def local_path(value):
    path = Path(value)
    return path if path.is_absolute() else profile_path.parent / path


plan = load_grading_plan(local_path(profile["plan"]))
selected = plan.selections({row["task_id"] for row in profile["controls"]})
output = Path(sys.argv[2]).absolute()
output.mkdir(parents=True, exist_ok=False)
(output / "control-profile.json").write_bytes(profile_payload)
(output / "grading-plan.json").write_bytes(plan.payload)
results = []
seen = set()
for index, control in enumerate(profile["controls"], 1):
    name = control["name"]
    if name in seen:
        raise ValueError("Control names must be unique")
    seen.add(name)
    grader = selected[control["task_id"]]
    artifacts = {}
    for artifact_id, row in control.get("artifacts", {}).items():
        path = local_path(row["path"])
        payload = read_material(path, row["sha256"])
        artifacts[artifact_id] = ArtifactInput(
            path=path, sha256=row["sha256"], bytes=len(payload),
            source=row.get("source", "workspace"), metadata=row.get("metadata", {}),
        )
    patch = ""
    if "patch_file" in control:
        patch = read_material(local_path(control["patch_file"]), control["patch_sha256"]).decode()
    inputs = {
        key: MaterialInput(path=plan.materials[ref]["path"], sha256=plan.materials[ref]["sha256"])
        for key, ref in grader["inputs"].items()
    }
    request = GradingRequest(
        adapter=grader["adapter"], contract_version=grader["contract_version"],
        task_id=control["task_id"], task_digest=control["task_digest"],
        session_id=f"verifier-control-{index}", source=control["source"],
        instance_id=control.get("instance_id", ""), patch=patch,
        artifacts=artifacts, materials=inputs, config=grader.get("config", {}),
        timeout_seconds=grader["timeout_seconds"], plan_digest=plan.digest,
        session=control.get("session", {}),
    )
    adapter = get_adapter(request.adapter, request.contract_version)
    adapter.validate_inputs(request)
    attempt = output / f"control-{index}"
    attempt.mkdir()
    result = adapter.evaluate(request, attempt).to_dict()
    (attempt / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    row = {"name": name, "adapter": request.adapter, "result": result}
    results.append(row)
    (output / "summary.json").write_text(json.dumps({
        "control_profile_sha256": hashlib.sha256(profile_payload).hexdigest(),
        "plan_digest": plan.digest, "results": results,
        "scope": "real verifier controls; not model-driven Harness trials",
        "complete": False,
    }, indent=2, ensure_ascii=False) + "\n")
    expected = control["expected"]
    if not {"status", "passed"} <= expected.keys():
        raise ValueError("Each control must declare expected status and passed")
    for key, value in expected.items():
        if result.get(key) != value:
            raise AssertionError(f"Control {name}: expected {key}={value!r}, observed {result.get(key)!r}")
summary = json.loads((output / "summary.json").read_text())
summary["complete"] = True
(output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({"complete": True, "controls": len(results), "output": str(output)}))
PY
