"""Spec-0083/T2: public task sources and bounded collection declarations."""

import pytest

from ahe_beta.experiment.config import ConfigError, load_task_package
from ahe_beta.experiment.workload import task_artifact_declarations, task_provenance
from test_experiment_config_v2 import package, write


def artifact(**updates):
    return {
        "id": "workbook",
        "source": "workspace",
        "path": "output/report.xlsx",
        "content_type": "application/octet-stream",
        "required": True,
        "max_bytes": 8192,
        **updates,
    }


def benchmark_package():
    task = package()
    task.update(
        schema_version=2,
        kind="benchmark",
        benchmark={
            "suite": "tua-bench",
            "instance_id": "010-pivot-product-revenue",
            "revision": "a" * 40,
        },
        artifacts={"version": 1, "exports": [artifact()]},
    )
    task.pop("not_in_benchmark")
    return task


def test_v1_normalization_retains_old_shape(tmp_path):
    task = load_task_package(write(tmp_path / "task.json", package()))
    expected = package()
    expected["instruction_file"] = str(tmp_path / "instruction.md")
    expected["setup"] = {name: str(tmp_path / value) for name, value in expected["setup"].items()}
    expected["source"]["path"] = str(tmp_path / "repo")
    expected["interaction"] = "simulated_user"
    assert task == expected
    assert task_artifact_declarations(task) == []
    assert "artifacts" not in task and "benchmark" not in task


def test_v2_provenance_and_artifacts_are_not_operator_paths(tmp_path):
    task = load_task_package(write(tmp_path / "task.json", benchmark_package()))
    assert task_provenance(task) == task["benchmark"]
    declarations = task_artifact_declarations(task)
    assert declarations == [artifact()]
    declarations[0]["path"] = "modified"
    assert task["artifacts"]["exports"][0]["path"] == "output/report.xlsx"


@pytest.mark.parametrize(
    "target",
    [
        "/etc/passwd",
        "../report",
        "output/../report",
        "./report",
        "output//report",
        "C:/report",
        r"output\report",
        "~/.ssh/id_rsa",
        "output/*.json",
        "output/[ab].json",
        "output/?.json",
        "output/file\nname",
        "output/",
    ],
)
def test_workspace_path_rejects_escape_alias_and_glob(tmp_path, target):
    task = benchmark_package()
    task["artifacts"]["exports"][0]["path"] = target
    with pytest.raises(ConfigError, match="Artifact path"):
        load_task_package(write(tmp_path / "task.json", task))


@pytest.mark.parametrize(
    "change",
    [
        {"source": "managed_service"},
        {"handle": "/results/results.json"},
        {"required": "true"},
        {"max_bytes": 0},
        {"max_bytes": True},
        {"content_type": "shell script"},
        {"hidden_tests": "grader.sh"},
    ],
)
def test_invalid_declarations_fail_schema(tmp_path, change):
    task = benchmark_package()
    task["artifacts"]["exports"][0].update(change)
    with pytest.raises(ConfigError):
        load_task_package(write(tmp_path / "task.json", task))


@pytest.mark.parametrize("change", [{"id": "workbook", "path": "output/other"}, {"id": "other"}])
def test_artifact_ids_and_targets_must_be_unique(tmp_path, change):
    task = benchmark_package()
    task["artifacts"]["exports"].append(artifact(**change))
    with pytest.raises(ConfigError, match="unique"):
        load_task_package(write(tmp_path / "task.json", task))


@pytest.mark.parametrize("kind", ["ordinary", "swebench"])
def test_benchmark_provenance_cannot_be_hidden_as_another_kind(tmp_path, kind):
    task = benchmark_package()
    task["kind"] = kind
    with pytest.raises(ConfigError):
        load_task_package(write(tmp_path / "task.json", task))


@pytest.mark.parametrize(
    "change", [{"not_in_benchmark": True}, {"benchmark": {"suite": "tua-bench"}}]
)
def test_benchmark_source_requires_fixed_identity(tmp_path, change):
    task = benchmark_package()
    task.update(change)
    with pytest.raises(ConfigError):
        load_task_package(write(tmp_path / "task.json", task))


def test_managed_reference_is_handle_not_task_supplied_host_path(tmp_path):
    task = benchmark_package()
    item = artifact(source="managed_service", handle="loadgen-results")
    item.pop("path")
    task["artifacts"]["exports"] = [item]
    assert load_task_package(write(tmp_path / "task.json", task))["artifacts"]["exports"] == [item]
    task["artifacts"]["exports"][0]["handle"] = "../../host/results"
    with pytest.raises(ConfigError):
        load_task_package(write(tmp_path / "task.json", task))


def test_benchmark_session_provenance_roundtrips_and_rejects_wrong_task():
    from ahe_beta.models import (
        FeelingScore,
        Persona,
        SeedScenario,
        Session,
        Transcript,
        WorkspaceSpec,
        validate_session_provenance,
    )

    provenance = {
        "contract_version": 1,
        "run_id": "run",
        "round_no": 1,
        "slot": 0,
        "persona_id": "person",
        "task_id": "local-alias",
        "task_digest": "a" * 64,
        "task_kind": "benchmark",
        "interaction": "direct",
        "harness_sha": "b" * 40,
    }
    params = {
        key: provenance[key] for key in ("task_id", "task_digest", "task_kind", "interaction")
    }
    params.update(benchmark="tua-bench", instance_id="010-pivot-product-revenue")
    session = Session(
        persona=Persona("person", "expert", "office", "fix workbook", "direct"),
        scenario=SeedScenario("Fix workbook", WorkspaceSpec(params=params)),
        transcript=Transcript(),
        feeling=FeelingScore(3, "done"),
        session_provenance=provenance,
    )
    saved = Session.from_dict(session.to_dict())
    validate_session_provenance(saved, expected=provenance)
    assert saved.scenario.workspace.params["instance_id"] == "010-pivot-product-revenue"
    saved.scenario.workspace.params["task_id"] = "another-task"
    with pytest.raises(ValueError, match="task_id provenance mismatch"):
        validate_session_provenance(saved, expected=provenance)
