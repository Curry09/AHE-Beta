"""Spec-0083/T2: content identity and rejection before preparing resources."""

import copy
import json
from pathlib import Path

import pytest

from auto_designer.experiment import materials, workload
from auto_designer.experiment.config import ConfigError
from test_experiment_config_v2 import write
from test_experiment_grading_task_config import artifact, benchmark_package
from test_experiment_materials import prepared_inputs as base_prepared_inputs


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    return base_prepared_inputs.__wrapped__(tmp_path, monkeypatch)


def use_v2(prepared_inputs, tmp_path, task):
    write(tmp_path / "task.json", task)
    config = json.loads(prepared_inputs.read_text())
    config["workload"].pop("kind")
    config["workload"].pop("task_package")
    config["workload"]["task_packages"] = ["../task.json"]
    write(prepared_inputs, config)
    return config


def test_freeze_preserves_source_and_declarations_in_content_identity(prepared_inputs, tmp_path):
    original = benchmark_package()
    use_v2(prepared_inputs, tmp_path, original)
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    catalog = workload.read_task_catalog(Path(manifest["run_dir"]), manifest)
    task = catalog["tasks"][0]
    assert task["kind"] == "benchmark"
    assert task["package"]["benchmark"] == original["benchmark"]
    assert task["package"]["artifacts"] == original["artifacts"]
    assert task["digest"] == workload.task_digest(task)
    for key in ("benchmark", "artifacts"):
        tampered = copy.deepcopy(task)
        if key == "benchmark":
            tampered["package"][key]["revision"] = "b" * 40
        else:
            tampered["package"][key]["exports"][0]["required"] = False
        assert workload.task_digest(tampered) != task["digest"]
    write(tmp_path / "task.json", {"replaced": True})
    materials.verify_materials(manifest)
    assert workload.read_task_catalog(Path(manifest["run_dir"]), manifest) == catalog


@pytest.mark.parametrize("backend", ["local", "e2b"])
@pytest.mark.parametrize("required", [True, False])
def test_managed_capture_rejected_before_freeze_or_resource_allocation(
    prepared_inputs,
    tmp_path,
    monkeypatch,
    backend,
    required,
):
    task = benchmark_package()
    item = artifact(source="managed_service", handle="loadgen-results", required=required)
    item.pop("path")
    task["artifacts"]["exports"] = [item]
    config = use_v2(prepared_inputs, tmp_path, task)
    if backend == "e2b":
        config["runtime"].update(
            backend="e2b",
            e2b={
                "template": "test-template",
                "cpu_count": 2,
                "memory_mb": 1024,
                "timeout_seconds": 600,
            },
        )
        config["runtime"]["gitea"]["provider"] = "gitea.com"
        write(prepared_inputs, config)
    monkeypatch.setattr(materials, "_checkout_git", lambda **kw: pytest.fail("clone called"))
    before = set(tmp_path.rglob("*"))
    with pytest.raises(ConfigError, match=f"{backend} does not support.*managed_service"):
        materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    assert set(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("target", ["repo", "output"])
def test_existing_directory_is_not_an_export_file(prepared_inputs, tmp_path, target):
    task = benchmark_package()
    task["artifacts"]["exports"][0]["path"] = target
    (tmp_path / "repo" / target).mkdir()
    use_v2(prepared_inputs, tmp_path, task)
    with pytest.raises(ConfigError, match="regular file"):
        materials.check_materials(prepared_inputs)


def test_existing_symlink_parent_cannot_export_host_file(prepared_inputs, tmp_path):
    task = benchmark_package()
    (tmp_path / "repo/output").symlink_to(tmp_path, target_is_directory=True)
    use_v2(prepared_inputs, tmp_path, task)
    with pytest.raises(ConfigError, match="symbolic links"):
        materials.check_materials(prepared_inputs)


def test_old_digest_matches_frozen_schema1_identity():
    task = {
        "id": "original",
        "kind": "ordinary",
        "interaction": "simulated_user",
        "package": {"schema_version": 1, "id": "original", "kind": "ordinary"},
        "source_snapshot": {"revision": None, "files": {"main.py": "a" * 64}},
        "content_hashes": {"instruction": "b" * 64},
        "materials": {"package": "some/path"},
    }
    original_digest = "979fe89dab65671472bba6a0b9303e65e9e3d117bd7e002c3bde9f8d882ef5ff"
    assert workload.task_digest(task) == original_digest
    task["materials"]["package"] = "different/path"
    task["digest"] = original_digest
    assert workload.task_digest(task) == original_digest


def test_rehashed_catalog_still_rejects_unsafe_export_contract(prepared_inputs, tmp_path):
    use_v2(prepared_inputs, tmp_path, benchmark_package())
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    catalog = workload.read_task_catalog(Path(manifest["run_dir"]), manifest)
    task = catalog["tasks"][0]
    task["package"]["artifacts"]["exports"][0]["path"] = "../../host/output"
    task["digest"] = workload.task_digest(task)
    with pytest.raises(ConfigError, match="Artifact path"):
        workload.catalog_tasks(catalog)


def test_existing_file_cannot_be_an_export_parent(prepared_inputs, tmp_path):
    task = benchmark_package()
    (tmp_path / "repo/output").write_text("not a directory")
    use_v2(prepared_inputs, tmp_path, task)
    with pytest.raises(ConfigError, match="parent must be a directory"):
        materials.check_materials(prepared_inputs)


def frozen_legacy_task(kind="ordinary"):
    task = {
        "id": "original",
        "kind": kind,
        "interaction": "simulated_user",
        "package": {"id": "original", "kind": kind},
        "source_snapshot": {"revision": None, "files": {"main.py": "a" * 64}},
        "content_hashes": {"instruction": "b" * 64},
        "materials": {"package": "old/material"},
    }
    task["digest"] = workload.task_digest(task)
    return task


@pytest.mark.parametrize("kind", ["ordinary", "swebench"])
@pytest.mark.parametrize("explicit_version", [False, True])
def test_minimal_frozen_schema1_catalog_keeps_old_identity(kind, explicit_version):
    task = frozen_legacy_task(kind)
    if explicit_version:
        task["package"]["schema_version"] = 1
        task["digest"] = workload.task_digest(task)
    before = copy.deepcopy(task)
    catalog = {"contract_version": 1, "tasks": [task]}
    assert workload.catalog_tasks(catalog) == [before]
    assert catalog["tasks"][0] == before
    assert workload.task_digest(task) == before["digest"]


@pytest.mark.parametrize("version", [None, True, False, 1.0, 0, 3, "1"])
def test_explicit_invalid_frozen_version_cannot_bypass_schema2_checks(version):
    task = frozen_legacy_task()
    task["package"]["schema_version"] = version
    task["digest"] = workload.task_digest(task)
    with pytest.raises(ConfigError, match="schema_version"):
        workload.catalog_tasks({"contract_version": 1, "tasks": [task]})


@pytest.mark.parametrize("field", ["artifacts", "benchmark"])
@pytest.mark.parametrize("explicit_version", [False, True])
def test_legacy_frozen_package_cannot_claim_new_collection_fields(field, explicit_version):
    task = frozen_legacy_task()
    if explicit_version:
        task["package"]["schema_version"] = 1
    task["package"][field] = None
    task["digest"] = workload.task_digest(task)
    with pytest.raises(ConfigError, match="schema 2 fields"):
        workload.catalog_tasks({"contract_version": 1, "tasks": [task]})
