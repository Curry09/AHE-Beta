"""Spec-0069/T4: provider acknowledgement, ownership, checksums and recovery boundaries."""

from __future__ import annotations

import hashlib
import io
import json
import os
import pwd
import shlex
import subprocess
import sys
import tarfile
import time
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ahe_beta.experiment.backends.base import BackendError
from ahe_beta.experiment.backends.e2b import COLLECTION_PROGRAM, E2BBackend, _write
from ahe_beta.experiment.backends.e2b_bootstrap import BOOTSTRAP_PROGRAM, bootstrap_command
from ahe_beta.experiment.backends.e2b_template import sandbox_facts


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
                "gitea": {"repository_prefix": "u1"},
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
        "ahe_beta.experiment.backends.e2b.resolve_template",
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


def test_task_workspace_receipt_binds_complete_catalog_and_actual_owned_paths(backend):
    from ahe_beta.experiment.backends.e2b_bootstrap import task_workspace_record
    from ahe_beta.experiment.config import ConfigError
    from ahe_beta.experiment.workload import task_digest

    backend.manifest["workload_contract_version"] = 1
    tasks, registry = [], {}
    for task_id in ("ordinary", "swe"):
        task = {
            "id": task_id,
            "kind": "ordinary",
            "interaction": "direct",
            "package": {
                "id": task_id,
                "kind": "ordinary",
                "interaction": "direct",
                "source": {"kind": "local", "path": "source/tasks/" + task_id},
            },
            "source_snapshot": {"revision": None, "files": {"task.py": "a" * 64}},
            "content_hashes": {},
            "materials": {},
        }
        for name in ("package", "instruction", "script", "requirements_lock", "source_archive"):
            key = f"task:{task_id}:{name}"
            task["materials"][name] = key
            relative = f"materials/tasks/{task_id}/{name}"
            path = backend.run_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(task["package"]) if name == "package" else "frozen " + name)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            registry[key] = {"path": relative, "sha256": digest}
            if name in {"instruction", "script", "requirements_lock"}:
                task["content_hashes"][name] = digest
        task["digest"] = task_digest(task)
        tasks.append(task)
    catalog = {"contract_version": 1, "tasks": tasks}
    catalog_path = backend.run_dir / "materials/task-catalog.json"
    catalog_path.parent.mkdir(exist_ok=True)
    catalog_path.write_text(json.dumps(catalog))
    digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    registry["task_catalog"] = {"path": "materials/task-catalog.json", "sha256": digest}
    backend.manifest.update(catalog_hash=digest, materials=registry)
    tools = {
        "python": backend.root + "/runtime/python/bin/python",
        "uv": backend.root + "/runtime/bin/uv",
        "controller_python": backend.root + "/source/controller/.venv/bin/python",
        "execution_uid": 1000,
        "execution_gid": 1000,
    }
    records = {
        task["id"]: task_workspace_record(task, backend.manifest, backend.root, tools)
        for task in tasks
    }
    receipt = {**tools, "task_workspaces": records}
    assert backend._task_workspaces(receipt) == records
    assert all(record["params"]["workload_contract_version"] == 1 for record in records.values())
    assert records["ordinary"]["recipe_hash"] != records["swe"]["recipe_hash"]
    records["ordinary"]["params"]["source"] = "/another-run/source"
    with pytest.raises(BackendError, match="owned paths"):
        backend._task_workspaces(receipt)
    records.pop("ordinary")
    with pytest.raises(ConfigError, match="catalog"):
        backend._task_workspaces(receipt)


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
    import httpx

    from ahe_beta.experiment.backends.e2b_bootstrap import upload_frozen_inputs

    backend.manifest["materials"] = {"example": {"path": "materials/example.txt"}}
    original = json.dumps({**backend.manifest, "run_dir": "/host/original"})
    (backend.run_dir / "manifest.json").write_text(original)
    material = backend.run_dir / "materials/example.txt"
    material.parent.mkdir()
    material.write_text("frozen")
    monkeypatch.setattr("ahe_beta.experiment.materials.verify_materials", lambda manifest: None)
    sandbox = Mock()
    sandbox.connection_config.proxy = None
    sandbox.upload_url.side_effect = lambda path, user: "https://upload.example" + path
    uploaded = {}

    def post(url, *, files, **_kwargs):
        path = url.removeprefix("https://upload.example")
        uploaded[path] = files["file"][1].read()
        return httpx.Response(200, json=[{"path": path}], request=httpx.Request("POST", url))

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.post.side_effect = post
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))
    upload_frozen_inputs(
        sandbox, run_dir=backend.run_dir, manifest=backend.manifest, root=backend.root
    )
    actual = uploaded[backend.root + "/manifest.json"]
    assert actual == original.encode()
    assert "/host/original" in actual.decode()


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


def test_new_run_refuses_missing_nonroot_identity_before_upload(backend, monkeypatch):
    # Spec-0072/T3: a missing worker receipt cannot silently restore root execution.
    backend.manifest["config"]["policies"] = {}
    _write(backend.resource_file, {"bootstrap": {"controller_python": sys.executable}})
    sandbox = Mock()
    monkeypatch.setattr(backend, "_sandbox", lambda: sandbox)
    with pytest.raises(BackendError, match="Non-root bootstrap"):
        backend.launch()
    sandbox.files.write.assert_not_called()


@pytest.mark.parametrize(
    "unsafe",
    [
        {"execution_user": "root"},
        {"execution_uid": 0},
        {"execution_uid": True},
        {"execution_gid": 0},
        {"execution_home": "/root"},
    ],
)
def test_worker_receipt_rejects_privileged_or_unowned_identity(backend, monkeypatch, unsafe):
    backend.manifest["config"]["policies"] = {}
    bootstrap = {
        "controller_python": sys.executable,
        "execution_user": "user",
        "execution_uid": 1000,
        "execution_gid": 1000,
        "execution_home": backend.root + "/runtime/home",
        **unsafe,
    }
    _write(backend.resource_file, {"bootstrap": bootstrap})
    sandbox = Mock()
    monkeypatch.setattr(backend, "_sandbox", lambda: sandbox)
    with pytest.raises(BackendError, match="Non-root bootstrap"):
        backend.launch()
    sandbox.files.write.assert_not_called()


def test_frozen_prepolicy_run_preserves_legacy_root_launch(backend, monkeypatch):
    _write(backend.resource_file, {"bootstrap": {"controller_python": sys.executable}})
    sandbox = Mock()
    monkeypatch.setattr(backend, "_sandbox", lambda: sandbox)
    sandbox.commands.run.return_value = SimpleNamespace(
        exit_code=0, stdout='{"state":"RUNNING","runner_pid":42}'
    )
    before = json.dumps(backend.manifest, sort_keys=True)
    assert backend.launch(mode="resume")["runner_pid"] == 42
    assert all(call.kwargs["user"] == "root" for call in sandbox.commands.run.call_args_list)
    assert all(call.kwargs["envs"] is None for call in sandbox.commands.run.call_args_list)
    assert json.dumps(backend.manifest, sort_keys=True) == before


@pytest.mark.skipif(os.geteuid() == 0, reason="SDK emulator executes as the local non-root account")
def test_worker_launch_and_root_management_use_real_owned_process_and_files(
    backend, tmp_path, monkeypatch
):
    # The SDK boundary records root/user; real supervision, files, stop and collection
    # execute locally. A provider test must additionally verify the Unix UID switch.
    remote = tmp_path / "remote"
    remote.mkdir()
    backend.root = str(remote)
    backend.manifest["config"].update(policies={}, rounds={"count": 1})
    (remote / "manifest.json").write_text(json.dumps(backend.manifest))
    (remote / "runtime/home").mkdir(parents=True)
    (remote / "runtime/home/login-cache").write_text("private-session-cache")
    (remote / "runtime/python").mkdir()
    (remote / "runtime/python/interpreter").write_text("runtime-dependency")
    (remote / "runtime/uv-cache").mkdir()
    (remote / "runtime/uv-cache/package").write_text("cached-package")
    (remote / "runtime/task-cache/recipe").mkdir(parents=True)
    (remote / "runtime/task-cache/recipe/wheel").write_text("private-wheel-cache")
    for private in ("workspace/tasks/one/source", "workspace/sessions/user/attempt-1/home"):
        (remote / private).mkdir(parents=True)
        (remote / private / "private.txt").write_text("private-baseline-or-home")
    (remote / "runtime/workspace-receipts").mkdir()
    (remote / "runtime/workspace-receipts/task.json").write_text('{"task_id":"one"}')
    bootstrap = {
        "controller_python": sys.executable,
        "openagents_bin": str(remote / "bin"),
        "bin": str(remote / "bin"),
        "execution_user": "user",
        "execution_uid": os.geteuid(),
        "execution_gid": os.getegid(),
        "execution_home": str(remote / "runtime/home"),
    }
    _write(
        backend.resource_file,
        {"bootstrap": bootstrap, "bootstrap_complete": True, "sandbox_id": "owned"},
    )
    identity = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
    monkeypatch.setattr(pwd, "getpwnam", lambda name: identity)
    observed = []

    def write(path, data, *, user):
        observed.append(("write", user))
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(data)

    def command(command, *, user, envs, timeout):
        observed.append(("command", user))
        argv = shlex.split(command)
        if "-c" not in argv:
            # chmod is a shell command with &&; execute it only in this owned fixture.
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return SimpleNamespace(exit_code=result.returncode, stdout=result.stdout)
        script = argv[argv.index("-c") + 1]
        arguments = argv[argv.index("-c") + 2 :]
        output = io.StringIO()
        with patch.object(sys, "argv", ["remote-program", *arguments]):
            with patch.dict(os.environ, envs or {}), redirect_stdout(output):
                exec(compile(script, "remote-program", "exec"), {"__name__": "__main__"})
        return SimpleNamespace(exit_code=0, stdout=output.getvalue())

    sandbox = SimpleNamespace(
        commands=SimpleNamespace(run=command),
        files=SimpleNamespace(
            write=write,
            read=lambda path, **kwargs: Path(path).read_bytes(),
        ),
    )
    monkeypatch.setattr(backend, "_sandbox", lambda: sandbox)
    from ahe_beta.experiment import context, engine

    monkeypatch.setattr(
        context,
        "build_controller_environment",
        lambda **kwargs: {
            "PATH": "/usr/bin:/bin",
            "OPENAGENTS_PERMISSION_MODE": "bypassPermissions",
        },
    )
    worker = """import json,os,pathlib,sys,time
root=pathlib.Path(sys.argv[1]);out=root/'data/worker.json';out.parent.mkdir()
out.write_text(json.dumps({'uid':os.geteuid(),'home':os.environ['HOME'],'user':os.environ['USER'],'permission':os.environ['OPENAGENTS_PERMISSION_MODE']}))
time.sleep(60)
"""
    monkeypatch.setattr(
        engine, "controller_command", lambda *args: [sys.executable, "-c", worker, str(remote)]
    )
    before = (remote / "manifest.json").read_bytes()
    try:
        receipt = backend.launch()
        assert receipt["running"]
        deadline = time.monotonic() + 5
        while not (remote / "data/worker.json").is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        worker_receipt = json.loads((remote / "data/worker.json").read_text())
        assert worker_receipt == {
            "uid": os.geteuid(),
            "home": bootstrap["execution_home"],
            "user": "user",
            "permission": "bypassPermissions",
        }
        assert (remote / "secrets/launch.json").stat().st_mode & 0o777 == 0o600
        assert backend.inspect()["controller"]["running"]
        assert backend.stop(grace_seconds=1)["state"] == "STOPPED"
        original_scandir = os.scandir
        scans = []
        private_runtime = {
            remote / "runtime/home",
            remote / "runtime/python",
            remote / "runtime/uv-cache",
            remote / "runtime/task-cache",
            remote / "workspace",
        }

        def scandir(path):
            candidate = Path(path)
            scans.append(candidate)
            if any(candidate.is_relative_to(private) for private in private_runtime):
                raise AssertionError("Collector entered a private runtime subtree")
            return original_scandir(path)

        monkeypatch.setattr(os, "scandir", scandir)
        collection = backend.collect()
        assert remote / "runtime" in scans
        assert "data/worker.json" in collection["files"]
        assert "runtime/workspace-receipts/task.json" in collection["files"]
        assert not any(path.startswith("secrets/") for path in collection["files"])
        assert not any(
            path.startswith(
                (
                    "runtime/home/",
                    "runtime/python/",
                    "runtime/uv-cache/",
                    "runtime/task-cache/",
                    "workspace/",
                )
            )
            for path in collection["files"]
        )
        assert observed.count(("command", "user")) == 1
        assert observed[-1] == ("command", "root")
        assert (remote / "manifest.json").read_bytes() == before
    finally:
        engine.stop_controller(remote, grace_seconds=1)
