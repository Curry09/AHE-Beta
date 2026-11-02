"""Spec-0079/T4: one atomic parent input contract and unchanged ordinary configuration."""

import copy
import json

import pytest

from ahe_beta.experiment.config import (
    ConfigError,
    config_hash,
    delivery_required,
    load_config_v2,
)
from ahe_beta.experiment.materials import check_materials
from test_experiment_config_v2 import definition, package, write
from test_experiment_continuation_source import archive
from test_experiment_continuation_source import parent_files as parent_files_fixture


def child_definition():
    config = definition()
    config.update(
        harness={"source": "continuation"},
        workload={"source": "parent"},
        continuation={"archive": "../parent/artifacts.tar.gz", "sha256": "a" * 64},
    )
    config["rounds"] = {"count": 1, "sessions_per_round": 1, "max_parallel_users": 1}
    return config


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_parent_config_has_no_external_workload_paths_and_requires_one_round_delivery(
    tmp_path,
    monkeypatch,
    backend,
):
    config = child_definition()
    if backend == "e2b":
        config["runtime"].update(
            backend="e2b", e2b={"cpu_count": 2, "memory_mb": 2048, "timeout_seconds": 3600}
        )
        config["runtime"]["gitea"]["provider"] = "gitea.com"
    path = write(tmp_path / "configs/child.json", config)
    monkeypatch.chdir("/")
    loaded = load_config_v2(path)
    assert loaded["workload"] == {"source": "parent"}
    assert loaded["harness"] == {"source": "continuation"}
    assert loaded["continuation"]["archive"] == str(tmp_path / "parent/artifacts.tar.gz")
    assert delivery_required(loaded)


@pytest.mark.parametrize(
    "selectors",
    [
        (a, b, c)
        for a in (False, True)
        for b in (False, True)
        for c in (False, True)
        if 0 < sum((a, b, c)) < 3
    ],
)
def test_parent_selectors_must_be_declared_together(tmp_path, selectors):
    config = definition()
    write(tmp_path / "task.json", package())
    if selectors[0]:
        config["continuation"] = {"archive": "parent.tar.gz", "sha256": "a" * 64}
    if selectors[1]:
        config["harness"] = {"source": "continuation"}
    if selectors[2]:
        config["workload"] = {"source": "parent"}
    with pytest.raises(ConfigError):
        load_config_v2(write(tmp_path / "configs/child.json", config))


@pytest.mark.parametrize(
    "field,value",
    [
        ("persona_ids", ["other"]),
        ("task_packages", ["other.json"]),
        ("interaction_plan", [[["other", "task"]]]),
    ],
)
def test_parent_source_cannot_mix_operator_workload_overrides(tmp_path, field, value):
    config = child_definition()
    config["workload"][field] = value
    with pytest.raises(ConfigError):
        load_config_v2(write(tmp_path / "child.json", config))


def test_no_legacy_import_switches_are_accepted(tmp_path):
    config = child_definition()
    config["continuation"]["format"] = "legacy"
    with pytest.raises(ConfigError):
        load_config_v2(write(tmp_path / "child.json", config))


def test_parent_offline_check_reads_current_archive_without_changing_it(tmp_path):
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    path, digest = archive(parent_root, parent_files_fixture.__wrapped__())
    original = path.read_bytes()
    config = child_definition()
    config["continuation"] = {"archive": str(path), "sha256": digest}
    config["rounds"]["count"] = 3
    child = write(tmp_path / "configs/child.json", config)
    before = set(tmp_path.rglob("*"))
    report = check_materials(child)
    assert report["continuation"]["continuation_ready"] is True
    assert report["interaction_plan"] == [[["persona", "task"]]] * 3
    assert report["config"]["workload"] == {"source": "parent"}
    assert path.read_bytes() == original
    assert set(tmp_path.rglob("*")) == before
    config["rounds"].update(sessions_per_round=2, max_parallel_users=2)
    write(child, config)
    with pytest.raises(ConfigError, match="selected parent boundary"):
        check_materials(child)


def test_ordinary_single_round_hash_and_shape_keep_no_continuation_defaults(tmp_path):
    original = definition()
    original["rounds"]["count"] = 1
    write(tmp_path / "task.json", package())
    path = write(tmp_path / "configs/ordinary.json", original)
    loaded = load_config_v2(path)
    assert "continuation" not in loaded
    assert "source" not in loaded["workload"]
    assert not delivery_required(loaded)
    baseline = copy.deepcopy(loaded)
    loaded_again = load_config_v2(path)
    assert config_hash(data=loaded_again) == config_hash(data=baseline)
    assert json.loads(path.read_text()) == original
    loaded_again["rounds"]["count"] = 2
    assert delivery_required(loaded_again)
