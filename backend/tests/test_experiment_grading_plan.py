"""Spec-0083/T5: private plan identity, retirement and early rejection."""

import hashlib
import json

import pytest

from ahe_beta.experiment.cli import build_parser
from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.grading_inputs import load_grading_plan


def write_plan(tmp_path):
    data = tmp_path / "tests.txt"
    data.write_bytes(b"fixed verifier")
    document = {
        "schema_version": 1,
        "materials": {
            "tests": {"path": "tests.txt", "sha256": hashlib.sha256(data.read_bytes()).hexdigest()}
        },
        "graders": [
            {
                "adapter": "custom",
                "contract_version": 1,
                "task_ids": ["task"],
                "inputs": {"script": "tests"},
                "timeout_seconds": 30,
                "config": {},
            }
        ],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(document))
    return path, document, data


def test_plan_freezes_material_bytes_and_resolves_relative_to_plan(tmp_path):
    path, _, data = write_plan(tmp_path)
    plan = load_grading_plan(path)
    assert plan.materials["tests"]["path"] == data
    assert plan.digest == hashlib.sha256(path.read_bytes()).hexdigest()
    data.write_bytes(b"changed after preparation")
    assert plan.materials["tests"]["payload"] == b"fixed verifier"


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_material",
        "unknown_task",
        "duplicate_task",
        "boolean_version",
        "boolean_timeout",
        "bad_hash",
        "extra_field",
    ],
)
def test_invalid_plan_rejected_before_allocation(tmp_path, mutation):
    path, document, _ = write_plan(tmp_path)
    grader = document["graders"][0]
    if mutation == "unknown_material":
        grader["inputs"]["script"] = "missing"
    elif mutation == "unknown_task":
        grader["task_ids"] = ["other"]
    elif mutation == "duplicate_task":
        document["graders"].append(dict(grader))
    elif mutation == "boolean_version":
        document["schema_version"] = True
    elif mutation == "boolean_timeout":
        grader["timeout_seconds"] = True
    elif mutation == "bad_hash":
        document["materials"]["tests"]["sha256"] = "f" * 64
    elif mutation == "extra_field":
        grader["import"] = "arbitrary.module"
    path.write_text(json.dumps(document))
    with pytest.raises(ConfigError):
        load_grading_plan(path).selections({"task"})
    assert not (tmp_path / "evaluation").exists()


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--dataset", "official.json", "--dataset-sha256", "a" * 64],
        ["--plan", "plan.json", "--dataset", "official.json"],
    ],
)
def test_old_dataset_cli_and_missing_plan_rejected(flags):
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["grade", "run", *flags])
    assert error.value.code == 2


def test_plan_symlink_and_duplicate_keys_rejected(tmp_path):
    path, _, _ = write_plan(tmp_path)
    linked = tmp_path / "linked.json"
    linked.symlink_to(path)
    with pytest.raises(ConfigError, match="symlink"):
        load_grading_plan(linked)
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ConfigError, match="Duplicate"):
        load_grading_plan(path)


def test_private_grading_attempts_are_excluded_from_experiment_collection():
    from pathlib import Path

    from ahe_beta.experiment.collection import _public_file

    assert not _public_file(Path("evaluation/grade-attempt/materials/hidden-tests.tar"))
    assert not _public_file(Path("evaluation/grade-attempt/plan.json"))
    assert _public_file(Path("data/role_runs/trial/evaluation-artifacts/session/attempt/workbook"))
