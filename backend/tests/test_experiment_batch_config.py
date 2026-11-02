"""Spec-0074/T1: offline batch identities include real inputs, never provider calls."""

import copy
import json

import pytest

from ahe_beta.experiment.batch_config import load_batch_config, verify_entry_inputs
from ahe_beta.experiment.config import ConfigError
from test_experiment_config_v2 import write
from test_experiment_materials import prepared_inputs as material_inputs


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    return material_inputs.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def batch_path(prepared_inputs, tmp_path):
    return write(
        tmp_path / "batch.json",
        {
            "schema_version": 1,
            "name": "comparison",
            "entries": [
                {"id": "first", "config": str(prepared_inputs)},
                {"id": "second", "config": str(prepared_inputs)},
            ],
        },
    )


def test_offline_load_does_not_fetch_or_create_paths(batch_path, tmp_path, monkeypatch):
    from ahe_beta.experiment import runtime

    def forbidden(*args, **kwargs):
        raise AssertionError("provider called")

    monkeypatch.setattr(runtime, "backend_v2", forbidden)
    before = {str(path) for path in tmp_path.rglob("*")}
    value = load_batch_config(batch_path)
    assert value["backend"] == "local" and value["max_parallel_runs"] == 1
    assert value["entries"][0]["config"]["workload"]["task_packages"] == [
        str(tmp_path / "task.json")
    ]
    assert before == {str(path) for path in tmp_path.rglob("*")}


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", "1"),
        ("schema_version", 2),
        ("max_parallel_runs", True),
        ("max_parallel_runs", 1.0),
        ("max_parallel_runs", 0),
        ("name", " "),
        ("entries", []),
        ("api_key", "sensitive"),
    ],
)
def test_strict_fields_and_types(batch_path, field, value):
    payload = json.loads(batch_path.read_text())
    payload[field] = value
    write(batch_path, payload)
    with pytest.raises(ConfigError):
        load_batch_config(batch_path)


@pytest.mark.parametrize("id_value", ["../x", "", "A", "a/b", "x" * 49])
def test_entry_path_segments(batch_path, id_value):
    payload = json.loads(batch_path.read_text())
    payload["entries"][0]["id"] = id_value
    write(batch_path, payload)
    with pytest.raises(ConfigError):
        load_batch_config(batch_path)


def test_duplicate_id_and_unknown_entry_field(batch_path):
    payload = json.loads(batch_path.read_text())
    payload["entries"][1]["id"] = "first"
    write(batch_path, payload)
    with pytest.raises(ConfigError, match="unique"):
        load_batch_config(batch_path)
    payload["entries"][1]["id"] = "second"
    payload["entries"][0]["executor"] = "anything"
    write(batch_path, payload)
    with pytest.raises(ConfigError, match="Additional"):
        load_batch_config(batch_path)


def test_mixed_backend_rejected(batch_path, prepared_inputs, tmp_path):
    payload = json.loads(prepared_inputs.read_text())
    payload["runtime"] = {
        "backend": "e2b",
        "gitea": {"provider": "gitea.com", "repository_prefix": "test"},
        "e2b": {"template": "base", "cpu_count": 2, "memory_mb": 2048, "timeout_seconds": 86400},
    }
    cloud = write(tmp_path / "configs/cloud.json", payload)
    batch = json.loads(batch_path.read_text())
    batch["entries"][1]["config"] = str(cloud)
    write(batch_path, batch)
    with pytest.raises(ConfigError, match="one backend"):
        load_batch_config(batch_path)


@pytest.mark.parametrize(
    "file", ["instruction.md", "setup.sh", "requirements.lock", "repo/main.py", "personas.json"]
)
def test_identity_detects_content_change(batch_path, tmp_path, file):
    entry = load_batch_config(batch_path)["entries"][0]
    path = tmp_path / file
    if file == "personas.json":
        cards = json.loads(path.read_text())
        cards[0]["era"]["basis"] += "changed"
        write(path, cards)
    else:
        path.write_text(path.read_text() + "\n# changed\n")
    with pytest.raises(ConfigError, match="changed"):
        verify_entry_inputs(entry)


def test_config_paths_relative_and_ignored_private_files(batch_path, tmp_path):
    value = json.loads(batch_path.read_text())
    value["entries"][0]["config"] = "configs/example.json"
    write(batch_path, value)
    before = load_batch_config(batch_path)
    (tmp_path / "repo/.env").write_text("changed private value")
    assert load_batch_config(batch_path) == before
    assert "changed private value" not in json.dumps(before)
    verify_entry_inputs(copy.deepcopy(before["entries"][0]))
