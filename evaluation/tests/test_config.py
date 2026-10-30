"""The public entry accepts current Harbor plans and rejects retired framework inputs."""

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.config import HarborEvaluationPlan, PlanError, load_plan
from evaluation.tests.test_execution import payload, task


def plan_payload(harness: Path, digest: str) -> dict:
    root = task(harness.parent / "task")
    raw = payload(root)
    runtime = raw["harnesses"][0]["runtime"]
    for key, sha_key in (
        ("runtime_wheel", "runtime_sha256"),
        ("runtime_lock", "runtime_lock_sha256"),
        ("python_archive", "python_sha256"),
    ):
        p = harness.parent / runtime[key]
        p.write_bytes(b"runtime")
        runtime[key] = str(p)
        runtime[sha_key] = hashlib.sha256(p.read_bytes()).hexdigest()
    raw["harnesses"][0].update(archive=str(harness), sha256=digest)
    raw["measurement"] = {"repetitions": 3, "scheduling_seed": 7}
    return raw


def test_json_and_yaml_keep_current_local_task_entry(tmp_path):
    raw = payload(task(tmp_path))
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(raw))
    plan = load_plan(source)
    assert plan.schema_version == 2
    assert plan.cases[0].benchmark == "Harbor"
    assert plan.interactions[0].mode.value == "direct"
    from ruamel.yaml import YAML

    source = tmp_path / "plan.yaml"
    with source.open("w") as out:
        YAML().dump(raw, out)
    assert load_plan(source) == plan


@pytest.mark.parametrize(
    "replacement",
    [
        {"schema_version": 1},
        {"interactions": [{"mode": "simulated_user"}]},
        {"interactions": [{"mode": "direct", "model": "user-model"}]},
        {"budgets": {"fallback_agent_seconds": 360}},
    ],
)
def test_retired_configuration_is_rejected(tmp_path, replacement):
    raw = payload(task(tmp_path)) | replacement
    with pytest.raises(PlanError):
        HarborEvaluationPlan.from_mapping(raw, tmp_path / "plan.json")


def test_public_cli_does_not_accept_legacy_executor():
    from evaluation.cli import main

    with pytest.raises(SystemExit) as error:
        main(["run", "unused.json", "--executor", "old:executor"])
    assert error.value.code == 2
