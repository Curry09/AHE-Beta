"""Spec-0081/T4: continuation validates v3 inputs without inventing task source trees."""

import copy
import hashlib
from types import SimpleNamespace

import pytest

from auto_designer.experiment import materials, workload
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.continuation import source
from auto_designer.experiment.task_environments.contract import environment_identity
from test_experiment_environment_lifecycle import container_run as container_run
from test_experiment_materials import prepared_inputs as prepared_inputs


def material_bytes(root, manifest):
    return {
        row["path"]: (root / row["path"]).read_bytes() for row in manifest["materials"].values()
    }


def test_continuation_validates_complete_container_inputs_without_source_archive(container_run):
    root, manifest, task = container_run
    files = material_bytes(root, manifest)
    actual, cards, plan = source._validate_materials(
        files, {}, manifest, {"material_keys": list(manifest["materials"])}
    )
    assert actual == [task]
    assert cards and plan["rounds"][0][0]["task_digest"] == task["digest"]
    assert "source_archive" not in task["materials"]
    assert "source" not in task["package"]
    material_key = task["materials"]["input:data"]
    files[manifest["materials"][material_key]["path"]] = b"corrupt input"
    with pytest.raises(ConfigError, match="content hash mismatch"):
        source._validate_materials(
            files, {}, manifest, {"material_keys": list(manifest["materials"])}
        )


def test_parent_refreeze_restores_exact_inputs_recipe_and_digest_in_fresh_root(
    container_run, tmp_path, monkeypatch
):
    root, manifest, task = container_run
    files = material_bytes(root, manifest)
    files.update(
        {
            "manifest.json": (root / "manifest.json").read_bytes(),
            "collection.json": b"{}",
            "checkpoints/recovery.json": b"{}",
            "runtime/continuation-export.json": b"{}",
            "runtime/harness.tar.gz": b"frozen-harness",
            "runtime/forge.json": b"{}",
        }
    )
    plan = workload.read_session_plan(root, manifest)
    pair = plan["rounds"][-1][0]
    parent = SimpleNamespace(
        manifest={**manifest, "controller_sha": "a" * 40},
        tasks=[task],
        export={
            "harness": {"archive": "runtime/harness.tar.gz", "tree_id": "b" * 40},
            "forge": {"path": "runtime/forge.json"},
            "boundary": {"sessions": [], "lineage_round": 6, "user_sha": "c" * 40},
            "material_keys": list(manifest["materials"]),
        },
        pairs=[pair],
        archive_sha256="d" * 64,
        files=files,
        read=lambda path: files[path],
        summary=lambda: {"valid": True},
    )
    monkeypatch.setattr(source, "load_continuation_source", lambda **kwargs: parent)
    fresh = tmp_path / "child"
    fresh.mkdir()
    registry = {}
    result = materials._freeze_parent_materials(
        stage=fresh,
        config={"continuation": {"archive": "/parent.tar.gz", "sha256": "d" * 64}},
        materials=registry,
    )
    assert result["tasks"] == [task]
    assert result["tasks"][0]["digest"] == task["digest"]
    assert not (fresh / "source/tasks").exists()
    for key in task["materials"].values():
        assert (fresh / registry[key]["path"]).read_bytes() == files[
            manifest["materials"][key]["path"]
        ]
    moved = copy.deepcopy(task)
    assert environment_identity(moved["package"]) == environment_identity(task["package"])
    actual = workload.compile_session_plan(
        {"workload": {"source": "parent"}, "rounds": {"count": 2, "sessions_per_round": 1}},
        {"contract_version": 1, "tasks": [moved]},
        hashlib.sha256(b"child-catalog").hexdigest(),
        [pair],
    )
    assert [round_[0]["round_no"] for round_ in actual["rounds"]] == [1, 2]
    assert all(round_[0]["task_digest"] == task["digest"] for round_ in actual["rounds"])
