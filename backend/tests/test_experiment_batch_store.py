"""Spec-0074/T1: publication, child recovery and durable batch ownership."""

import json
import multiprocessing
from pathlib import Path

import pytest

from ahe_beta.experiment import materials
from ahe_beta.experiment.batch_config import load_batch_config
from ahe_beta.experiment.batch_store import BatchStore
from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.manifest import update_runtime
from test_experiment_batch_config import batch_path as batch_inputs
from test_experiment_materials import prepared_inputs as material_inputs


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    return material_inputs.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def batch_path(prepared_inputs, tmp_path):
    return batch_inputs.__wrapped__(prepared_inputs, tmp_path)


@pytest.fixture
def store(batch_path, tmp_path):
    return BatchStore.create(load_batch_config(batch_path), tmp_path / "runs")


def prepare_children(store):
    for entry in store.intent["config"]["entries"]:
        manifest = materials.prepare_materials(entry["config_path"], store.child_root(entry["id"]))
        update_runtime(
            run_dir=Path(manifest["run_dir"]),
            action="test-prepared",
            changes={"preparation_complete": True, "experiment_state": "PREPARED"},
        )
        store.update(
            "prepared", {}, {entry["id"]: {"run_id": manifest["run_id"], "phase": "PREPARED"}}
        )


def test_unique_child_recovery_final_publication_and_input_independence(store, tmp_path):
    store.update("intent", {}, {"first": {"prepare_intent": True}})
    prepare_children(store)
    value = store.publish()
    assert len(value["members"]) == 2
    (tmp_path / "instruction.md").unlink()
    (tmp_path / "configs/example.json").unlink()
    restored = BatchStore.load(store.batch_id, tmp_path / "runs")
    assert restored.manifest() == value
    assert restored.state()["revision"] == 3
    with pytest.raises(ConfigError, match="already exists"):
        restored.publish()


def test_preparing_only_and_multiple_children_fail_closed(store):
    entry = store.intent["config"]["entries"][0]
    root = store.child_root(entry["id"])
    (root / ".preparing-orphan").mkdir(parents=True)
    assert store.find_child(entry) is None
    with pytest.raises(ConfigError, match="partially"):
        store.publish()
    materials.prepare_materials(entry["config_path"], root)
    materials.prepare_materials(entry["config_path"], root)
    with pytest.raises(ConfigError, match="Multiple"):
        store.find_child(entry)


def test_frozen_but_unprepared_is_not_ready(store):
    for entry in store.intent["config"]["entries"]:
        materials.prepare_materials(entry["config_path"], store.child_root(entry["id"]))
    with pytest.raises(ConfigError, match="partially"):
        store.publish()


def test_child_identity_and_material_mutation_rejected(store, tmp_path):
    entry = store.intent["config"]["entries"][0]
    (tmp_path / "instruction.md").write_text("new input")
    materials.prepare_materials(entry["config_path"], store.child_root(entry["id"]))
    with pytest.raises(ConfigError, match="materials differ"):
        store.find_child(entry)


@pytest.mark.parametrize("name", ["intent.json", "runtime.json"])
def test_document_hash_tamper(store, tmp_path, name):
    path = store.directory / name
    document = json.loads(path.read_text())
    document["batch_id"] = "replacement"
    path.write_text(json.dumps(document))
    with pytest.raises(ConfigError, match="hash"):
        BatchStore.load(store.batch_id, tmp_path / "runs")


def test_final_child_manifest_drift(store):
    prepare_children(store)
    store.publish()
    entry = store.intent["config"]["entries"][0]
    child = store.find_child(entry)
    path = Path(child["run_dir"]) / "manifest.json"
    child["created_at"] = "changed"
    path.write_text(json.dumps(child))
    with pytest.raises(ConfigError, match="manifest changed"):
        store.manifest()


def test_runid_is_single_assignment_and_receipts_reject_secret(store):
    store.update("child", {}, {"first": {"run_id": "original"}})
    with pytest.raises(ConfigError, match="cannot change"):
        store.update("child", {}, {"first": {"run_id": "other"}})
    with pytest.raises(ConfigError, match="Credential"):
        store.update("bad", {"api_key": "not-persisted"})
    assert "not-persisted" not in (store.directory / "runtime.json").read_text()


def attempt_lock(directory, intent, result):
    try:
        with BatchStore(Path(directory), intent).lock("scheduler", blocking=False):
            result.put("acquired")
    except ConfigError:
        result.put("blocked")


def test_cross_process_scheduler_lock_and_short_control_lock(store):
    ctx = multiprocessing.get_context("fork")
    result = ctx.Queue()
    with store.lock("scheduler"):
        process = ctx.Process(
            target=attempt_lock, args=(str(store.directory), store.intent, result)
        )
        process.start()
        process.join(5)
        assert process.exitcode == 0 and result.get(timeout=1) == "blocked"
        store.update("stop-intent", {"paused": True})
    assert store.state()["paused"] is True


def test_paths_cannot_escape_or_use_symlinks(store, tmp_path):
    with pytest.raises(ConfigError):
        store.child_root("../other")
    with pytest.raises(ConfigError):
        BatchStore.load("../other", tmp_path / "runs")
    (store.directory / "children").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ConfigError, match="Symbolic"):
        store.child_root("first")


def test_create_never_publishes_only_intent(batch_path, tmp_path, monkeypatch):
    from ahe_beta.experiment import batch_store

    original = batch_store._atomic
    root = tmp_path / "atomic-runs"

    def interrupted(path, payload, exclusive):
        if path.name == "runtime.json":
            assert all(path.name.startswith(".creating-") for path in (root / ".batches").iterdir())
            raise KeyboardInterrupt("crash before initial receipt")
        return original(path, payload, exclusive)

    monkeypatch.setattr(batch_store, "_atomic", interrupted)
    with pytest.raises(KeyboardInterrupt):
        BatchStore.create(load_batch_config(batch_path), root)
    assert not list((root / ".batches").iterdir())


def test_missing_runtime_of_published_batch_is_corruption(store, tmp_path):
    (store.directory / "runtime.json").unlink()
    with pytest.raises(ConfigError):
        BatchStore.load(store.batch_id, tmp_path / "runs")


def test_stale_derived_state_cannot_overwrite_pause(store):
    from ahe_beta.experiment.batch_store import BatchRevisionConflict

    original = store.state()
    store.update("pause", {"paused": True, "batch_state": "PAUSING"})
    with pytest.raises(BatchRevisionConflict):
        store.update("derived", {"batch_state": "RUNNING"}, expected_revision=original["revision"])
    assert store.state()["batch_state"] == "PAUSING"
