"""Spec-0069/T4: provider acknowledgement, ownership, checksums and recovery boundaries."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from auto_designer.experiment.backends.base import BackendError
from auto_designer.experiment.backends.e2b import COLLECTION_PROGRAM, E2BBackend, _write
from auto_designer.experiment.backends.e2b_bootstrap import BOOTSTRAP_PROGRAM, bootstrap_command
from auto_designer.experiment.backends.e2b_template import sandbox_facts


@pytest.fixture
def manifest():
    return {
        "run_id": "20260930T000000Z-abc12345",
        "config_hash": "f" * 64,
        "task_package": {"id": "pvlib"},
        "config": {
            "runtime": {
                "backend": "e2b",
                "e2b": {"cpu_count": 4, "memory_mb": 8192, "timeout_seconds": 3600},
                "gitea": {"repository_prefix": "n1"},
            }
        },
    }


@pytest.fixture
def backend(tmp_path, manifest):
    return E2BBackend(
        tmp_path, manifest, {"E2B_API_KEY": "provider-secret", "GITEA_TOKEN": "gitea-secret"}
    )


def info(manifest, **changes):
    values = dict(
        sandbox_id="sandbox-owned",
        template_id="template-1",
        metadata={"run_id": manifest["run_id"], "config_hash": manifest["config_hash"]},
        cpu_count=4,
        memory_mb=8192,
        allow_internet_access=True,
        started_at=datetime.now(UTC),
        end_at=datetime.now(UTC),
        state="running",
    )
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"cpu_count": 2},
        {"memory_mb": 2048},
        {"allow_internet_access": False},
        {"metadata": {"run_id": "foreign"}},
    ],
)
def test_actual_provider_facts_reject_unowned_or_insufficient(manifest, changes):
    with pytest.raises(BackendError):
        sandbox_facts(
            info(manifest, **changes), manifest=manifest, template={"template_id": "template-1"}
        )


def test_actual_provider_facts_come_from_observation(manifest):
    observed = sandbox_facts(
        info(manifest),
        manifest=manifest,
        template={"template_id": "template-1", "build_id": "known-build"},
    )
    assert observed["cpu_count"] == 4 and observed["sandbox_id"] == "sandbox-owned"
    assert "provider-secret" not in json.dumps(observed)


def test_list_paginator_not_nonexistent_all_method(backend, monkeypatch):
    pages = Mock(has_next=True)

    def next_page():
        pages.has_next = False
        return ["observed"]

    pages.next_items.side_effect = next_page
    monkeypatch.setattr("e2b.Sandbox.list", Mock(return_value=pages))
    assert backend._owned_sandboxes() == ["observed"]


def test_lost_sandbox_never_recreates(backend, monkeypatch):
    _write(backend.resource_file, {"sandbox_id": "lost", "template": {}})
    monkeypatch.setattr(backend, "_owned_sandboxes", lambda: [])
    create = Mock()
    monkeypatch.setattr("e2b.Sandbox.create", create)
    with pytest.raises(BackendError, match="LOST"):
        backend.provision()
    create.assert_not_called()


def test_paused_sandbox_not_implicitly_resumed(backend, monkeypatch):
    _write(backend.resource_file, {"sandbox_id": "paused", "template": {}})
    monkeypatch.setattr(
        backend, "_owned_sandboxes", lambda: [SimpleNamespace(sandbox_id="paused", state="paused")]
    )
    connect = Mock()
    monkeypatch.setattr("e2b.Sandbox.connect", connect)
    with pytest.raises(BackendError, match="paused"):
        backend._sandbox()
    connect.assert_not_called()


def test_creation_intent_survives_provider_ack_loss(backend, monkeypatch):
    monkeypatch.setattr(
        "auto_designer.experiment.backends.e2b.resolve_template",
        lambda **kw: {"selection": "template", "template_id": "template"},
    )
    monkeypatch.setattr(backend, "_owned_sandboxes", lambda: [])
    monkeypatch.setattr(
        "e2b.Sandbox.create", Mock(side_effect=TimeoutError("lost acknowledgement"))
    )
    with pytest.raises(TimeoutError):
        backend.provision()
    persisted = json.loads(backend.resource_file.read_text())
    assert persisted["creation_intent"]["metadata"] == backend.metadata
    assert "provider-secret" not in backend.resource_file.read_text()


def test_unknown_connection_not_reported_lost(backend, monkeypatch):
    _write(backend.resource_file, {"sandbox_id": "owned", "bootstrap_complete": True})
    monkeypatch.setattr(backend, "_engine", Mock(side_effect=TimeoutError()))
    observed = backend.inspect()
    assert observed["controller"]["state"] == "UNKNOWN"
    assert observed["resource_state"] == "UNKNOWN"


def test_stopped_controller_keeps_billable_resource_running(backend, monkeypatch):
    _write(backend.resource_file, {"sandbox_id": "owned", "bootstrap_complete": True})
    monkeypatch.setattr(
        backend, "_engine", lambda action, **kwargs: {"state": "STOPPED", "running": False}
    )
    assert backend.inspect()["resource_state"] == "RUNNING"
    assert backend.stop()["controller"]["state"] == "STOPPED"


def test_destroy_partial_bootstrap_can_cleanup_without_controller_import(backend, monkeypatch):
    sandbox = Mock()
    _write(backend.resource_file, {"sandbox_id": "owned", "bootstrap_complete": False})
    monkeypatch.setattr(backend, "_sandbox", lambda **kwargs: sandbox)
    monkeypatch.setattr(backend, "_owned_sandboxes", lambda: [])
    stop = Mock()
    monkeypatch.setattr(backend, "stop", stop)
    assert backend.destroy()["resource_state"] == "DESTROYED"
    sandbox.kill.assert_called_once()
    stop.assert_not_called()


def test_remote_collection_omits_secrets_and_hashes_archive(tmp_path):
    for relative, text in [
        ("data/harness_sandbox/harness_repo/entry.py", "final harness"),
        ("checkpoints/recovery.json", "sealed"),
        ("secrets/provider.env", "private"),
        ("data/.openagents/state.db", "private runtime"),
        ("runtime/controller.json", "owned"),
    ]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    result = subprocess.run(
        [sys.executable, "-c", COLLECTION_PROGRAM, str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["consistent"]
    assert "checkpoints/recovery.json" in receipt["files"]
    assert not any("secrets" in p or ".openagents" in p for p in receipt["files"])
    data = (tmp_path / "runtime/collection.tar.gz").read_bytes()
    assert hashlib.sha256(data).hexdigest() == receipt["archive_sha256"]
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        assert set(archive.getnames()) == set(receipt["files"])


def test_portable_bootstrap_program_compiles_and_pins_downloads():
    compile(BOOTSTRAP_PROGRAM, "bootstrap.py", "exec")
    assert "uv-x86_64-unknown-linux-gnu.tar.gz" in BOOTSTRAP_PROGRAM
    assert "--locked" in BOOTSTRAP_PROGRAM
    assert "/home/wydlinux" not in BOOTSTRAP_PROGRAM
    assert "Python 3.12.13" in BOOTSTRAP_PROGRAM
    assert "'DISABLE_UPDATES'" not in BOOTSTRAP_PROGRAM  # runtime environment supplies this
    assert bootstrap_command("/tmp/a b").endswith("'/tmp/a b'")


def test_destroyed_resource_retains_completed_exit_receipt(backend, monkeypatch):
    _write(backend.resource_file, {"sandbox_id": "owned", "resource_state": "DESTROYED"})
    _write(
        backend.run_dir / "runtime/e2b-collection.json",
        {
            "controller": {
                "state": "EXITED",
                "running": False,
                "experiment_complete": True,
                "nonce": "verified",
            }
        },
    )
    remote = Mock(side_effect=AssertionError("destroyed compute must not be contacted"))
    monkeypatch.setattr(backend, "_sandbox", remote)
    observed = backend.inspect()
    assert observed["resource_state"] == "DESTROYED"
    assert observed["controller"]["experiment_complete"] is True
    remote.assert_not_called()


def test_preserved_collection_reverified_after_compute_destroyed(backend):
    snapshot = backend.run_dir / "runtime/cloud-snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / "result.json").write_text("sealed")
    _write(backend.resource_file, {"sandbox_id": "owned", "resource_state": "DESTROYED"})
    receipt = {
        "snapshot_dir": str(snapshot),
        "controller": {"state": "EXITED"},
        "consistent": True,
        "terminal": True,
        "files": {"result.json": hashlib.sha256(b"sealed").hexdigest()},
    }
    _write(backend.run_dir / "runtime/e2b-collection.json", receipt)
    assert backend.collect() == receipt
    (snapshot / "result.json").write_text("tampered")
    with pytest.raises(BackendError, match="checksum"):
        backend.collect()


def test_tampered_download_preserves_previous_snapshot(backend, monkeypatch):
    snapshot = backend.run_dir / "runtime/cloud-snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / "previous.txt").write_text("valid prior collection")
    sandbox = Mock()
    sandbox.files.read.return_value = b"changed download"
    monkeypatch.setattr(backend, "_sandbox", lambda: sandbox)
    monkeypatch.setattr(backend, "inspect", lambda: {"state": "RUNNING", "nonce": "same"})
    monkeypatch.setattr(
        backend,
        "_command",
        lambda *a, **kw: json.dumps(
            {
                "archive_sha256": hashlib.sha256(b"actual archive").hexdigest(),
                "files": {},
                "consistent": False,
            }
        ),
    )
    with pytest.raises(BackendError, match="checksum"):
        backend.collect()
    assert (snapshot / "previous.txt").read_text() == "valid prior collection"


def test_uploaded_frozen_manifest_is_not_relocated(backend, monkeypatch):
    from auto_designer.experiment.backends.e2b_bootstrap import upload_frozen_inputs

    backend.manifest["materials"] = {"example": {"path": "materials/example.txt"}}
    original = json.dumps({**backend.manifest, "run_dir": "/host/original"})
    (backend.run_dir / "manifest.json").write_text(original)
    material = backend.run_dir / "materials/example.txt"
    material.parent.mkdir()
    material.write_text("frozen")
    monkeypatch.setattr(
        "auto_designer.experiment.materials.verify_materials", lambda manifest: None
    )
    sandbox = Mock()
    upload_frozen_inputs(
        sandbox, run_dir=backend.run_dir, manifest=backend.manifest, root=backend.root
    )
    args = sandbox.files.write.call_args_list[0]
    assert args.args[1] == original.encode()
    assert "/host/original" in args.args[1].decode()


def test_resume_rejects_changed_gitea_account_before_creating_repository(backend, monkeypatch):
    _write(backend.resource_file, {"gitea": {"owner": "original", "repository_id": 123}})
    api = Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {"login": "different"}))
    monkeypatch.setattr(backend, "_api", api)
    with pytest.raises(BackendError, match="identity changed"):
        backend._gitea()
    assert api.call_count == 1


def test_cloud_stop_forwards_requested_grace_period(backend, monkeypatch):
    call = Mock(return_value={"state": "STOPPED", "running": False})
    monkeypatch.setattr(backend, "_engine", call)
    backend.stop(grace_seconds=1.75)
    call.assert_called_once_with("stop_controller", grace_seconds=1.75)


def test_cloud_engine_program_reads_progress_without_model_or_provider_calls(backend, monkeypatch):
    import shlex

    _write(backend.resource_file, {"bootstrap": {"controller_python": "/managed/python"}})
    monkeypatch.setattr(backend, "_sandbox", lambda: object())
    observed = []

    def command(sandbox, program):
        script = shlex.split(program)[2]
        compile(script, "cloud-inspect", "exec")
        observed.append(script)
        return '{"state":"STOPPED","progress":{"current_round":3}}'

    monkeypatch.setattr(backend, "_command", command)
    receipt = backend._engine("stop_controller", grace_seconds=2)
    assert receipt["progress"]["current_round"] == 3
    assert "progress_v2(root)" in observed[0]
    assert "grace_seconds=2.0" in observed[0]
