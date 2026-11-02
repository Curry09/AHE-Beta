"""Spec-0081/T4: batch identities bind container bytes without source/setup fiction."""

import copy
import json

import pytest

from ahe_beta.experiment import materials
from ahe_beta.experiment.batch_config import (
    load_batch_config,
    package_input_identity,
    verify_entry_inputs,
)
from ahe_beta.experiment.batch_store import BatchStore
from ahe_beta.experiment.config import ConfigError
from test_experiment_environment_materials import archive, task
from test_experiment_materials import prepared_inputs as prepared_inputs


def container_batch(config, tmp_path):
    document = json.loads(config.read_text())
    package_path = (config.parent / document["workload"]["task_package"]).resolve()
    material = archive(tmp_path / "container-input.tar.gz", {"data.txt": b"pristine"})
    task(package_path, material)
    document["workload"]["kind"] = "ordinary"
    config.write_text(json.dumps(document))
    batch = tmp_path / "container-batch.json"
    batch.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "container-comparison",
                "entries": [{"id": "container", "config": str(config)}],
            }
        )
    )
    return batch, package_path


def test_batch_container_prepare_and_child_identity(prepared_inputs, tmp_path):
    batch_path, _ = container_batch(prepared_inputs, tmp_path)
    before = set(tmp_path.rglob("*"))
    definition = load_batch_config(batch_path)
    assert set(tmp_path.rglob("*")) == before
    store = BatchStore.create(definition, root=tmp_path / "runs")
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "children")
    store.verify_child(definition["entries"][0], manifest)
    assert "setup" not in definition["entries"][0]["input_identity"]["tasks"][0]["package"]
    assert "source" not in definition["entries"][0]["input_identity"]["tasks"][0]["package"]
    verify_entry_inputs(definition["entries"][0])


def test_batch_container_instruction_and_recipe_changes_rejected(prepared_inputs, tmp_path):
    batch_path, package_path = container_batch(prepared_inputs, tmp_path)
    entry = load_batch_config(batch_path)["entries"][0]
    package = json.loads(package_path.read_text())
    package["environment"]["readiness"]["argv"] = ["false"]
    package_path.write_text(json.dumps(package))
    with pytest.raises(ConfigError, match="changed"):
        verify_entry_inputs(entry)


def test_container_identity_ignores_only_material_location(prepared_inputs, tmp_path):
    _, package_path = container_batch(prepared_inputs, tmp_path)
    package = json.loads(package_path.read_text())
    moved = copy.deepcopy(package)
    moved["environment"]["inputs"][0]["material"].pop("path")
    moved["environment"]["inputs"][0]["material"]["url"] = "https://example.test/data.tar.gz"
    assert package_input_identity(package=package) == package_input_identity(package=moved)
    moved["environment"]["inputs"][0]["material"]["sha256"] = "b" * 64
    assert package_input_identity(package=package) != package_input_identity(package=moved)
