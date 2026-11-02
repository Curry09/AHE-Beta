"""Spec-0081/T4: v3 execution bindings, owned probes, and portable private evidence."""

import copy
import hashlib
import json
import logging
import subprocess
import tarfile
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

from ahe_beta.experiment import context, materials, workload
from ahe_beta.experiment.backends import e2b_bootstrap, e2b_template
from ahe_beta.experiment.backends.base import BackendError
from ahe_beta.experiment.collection import (
    collect_archive,
    verify_management_evidence,
)
from ahe_beta.experiment.config import ConfigError
from test_experiment_environment_materials import archive, task
from test_experiment_materials import prepared_inputs as prepared_inputs


@pytest.fixture
def container_run(prepared_inputs, tmp_path):
    config = json.loads(prepared_inputs.read_text())
    package_path = (prepared_inputs.parent / config["workload"]["task_package"]).resolve()
    task(package_path, archive(tmp_path / "input.tar.gz", {"input.csv": b"1,2\n"}))
    config["workload"]["kind"] = "ordinary"
    prepared_inputs.write_text(json.dumps(config))
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    root = Path(manifest["run_dir"])
    record = workload.read_task_catalog(root, manifest)["tasks"][0]
    return root, manifest, record


def tools(root):
    return {
        "controller_python": str(root / "source/controller/.venv/bin/python"),
        "python_root": str(root / "runtime/python/cpython-3.12.13"),
        "python_alias_root": str(root / "runtime/python/cpython-3.12"),
    }


def test_container_workspace_maps_verified_materials_without_source_or_venv(container_run):
    root, manifest, task_record = container_run
    remote = "/opt/cloud/owned-run"
    workspace = e2b_bootstrap.task_workspace_record(
        task_record, manifest, remote, tools(Path(remote)), material_root=root
    )
    workload.verify_task_workspaces(
        {"contract_version": 1, "tasks": [task_record]}, {task_record["id"]: workspace}
    )
    assert workspace["kind"] == "container"
    assert workspace["source_revision"] is None
    assert "source" not in workspace["params"]
    assert "setup_script" not in workspace["params"]
    assert len(workspace["params"]["harness_mounts"]) == 3
    assert workspace["params"]["environment"]["inputs"][0]["material"]["path"].startswith(
        remote + "/materials/"
    )
    assert not (root / "workspace/tasks").exists()
    assert not Path(remote).exists()
    instruction = root / manifest["materials"][task_record["materials"]["instruction"]]["path"]
    assert instruction.read_text() == "Inspect the supplied workbook."


def test_git_metadata_is_forwarded_as_actual_head_requirement(container_run):
    root, manifest, task_record = container_run
    task_record = copy.deepcopy(task_record)
    source = {
        "kind": "git",
        "url": "https://example.test/source.git",
        "repo": "owner/source",
        "revision": "1" * 40,
    }
    task_record["package"]["source"] = source
    result = e2b_bootstrap.task_workspace_record(task_record, manifest, str(root), tools(root))
    assert result["params"]["expected_git_revision"] == source["revision"]
    assert result["params"]["source"] == source
    assert result["params"]["environment"]["patch"] == "git"


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_controller_context_accepts_only_v3_container_bindings(container_run, backend):
    root, manifest, task_record = container_run
    manifest["config"]["runtime"]["backend"] = backend
    workspace = e2b_bootstrap.task_workspace_record(task_record, manifest, str(root), tools(root))
    resources = {
        "gitea": {"url": "https://forge.example", "owner": "owner", "repo": "repo"},
        "task_workspaces": {task_record["id"]: workspace},
    }
    context.write_controller_context(
        run_dir=root,
        manifest=manifest,
        credentials={"GITEA_TOKEN": "private-token"},
        resources=resources,
    )
    actual = json.loads((root / "runtime/task-workspaces.json").read_text())
    assert actual[task_record["id"]]["kind"] == "container"
    resources["task_workspaces"][task_record["id"]]["kind"] = "prebuilt"
    with pytest.raises(ConfigError):
        context.write_controller_context(
            run_dir=root,
            manifest=manifest,
            credentials={"GITEA_TOKEN": "private-token"},
            resources=resources,
        )


def evidence_run(tmp_path):
    root = tmp_path / "run"
    (root / "runtime/task-environments").mkdir(parents=True)
    manifest = {"run_id": "owned", "config_hash": "a" * 64, "materials": {}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root, manifest


def evidence_record(root, manifest, *, attempt=1, ready=True, frozen=True, management=True):
    identity = {
        **{key: manifest[key] for key in ("run_id", "config_hash")},
        "task_id": "task",
        "task_digest": "b" * 64,
        "recipe_hash": "c" * 64,
        "session_id": "session",
        "attempt": attempt,
        "round_no": 1,
        "slot": 0,
    }
    key = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    exports = (
        [{"handle": "measurement", "path": "/results/private.json", "visibility": "management"}]
        if management
        else []
    )
    record = {
        "key": key,
        "identity": identity,
        "phase": "closed" if frozen else "failed",
        "environment": {"services": [{"id": "meter", "exports": exports}]},
        "management_outputs": {},
    }
    if ready:
        record["ready_at"] = "ready"
    if frozen:
        record["frozen_at"] = "frozen"
    else:
        record["failure"] = {"type": "InitializerFailure"}
    if management and frozen:
        data = b'{"private_measurement":"never-project-to-reviewer"}'
        destination = root / "runtime/task-environments" / key / "measurement.data"
        destination.parent.mkdir()
        destination.write_bytes(data)
        record["management_outputs"]["measurement"] = {
            "status": "collected",
            "path": "/remote/private/" + key + "/measurement.data",
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "visibility": "management",
            "required": True,
        }
    (root / "runtime/task-environments" / (key + ".json")).write_text(json.dumps(record))
    return key, record


def collect(root, manifest):
    return collect_archive(
        run_dir=root,
        manifest=manifest,
        snapshot={
            "snapshot_dir": str(root),
            "consistent": True,
            "terminal": True,
            "controller": {"state": "EXITED"},
        },
        credentials={},
    )


def test_private_measurement_survives_separately_and_never_enters_public_archive(tmp_path):
    root, manifest = evidence_run(tmp_path)
    key, _ = evidence_record(root, manifest)
    receipt = collect(root, manifest)
    assert receipt["collection_state"] == "COMPLETE"
    evidence = receipt["management_evidence"]
    private = root / evidence["path"]
    assert private.stat().st_mode & 0o777 == 0o600
    with tarfile.open(private) as archive:
        assert (
            b"never-project-to-reviewer"
            in archive.extractfile("task-environments/" + key + "/measurement.data").read()
        )
    with tarfile.open(receipt["archive"]) as archive:
        assert not any(name.startswith("runtime/task-environments/") for name in archive.getnames())
        assert all(
            b"never-project-to-reviewer" not in archive.extractfile(member).read()
            for member in archive
            if member.isfile()
        )
        assert "runtime/task-environments-public.json" in archive.getnames()
    verify_management_evidence(run_dir=root, receipt=receipt)
    private.write_bytes(b"corrupt")
    with pytest.raises(ConfigError, match="private task evidence"):
        verify_management_evidence(run_dir=root, receipt=receipt)


@pytest.mark.parametrize("before_actor", [True, False])
def test_only_pre_actor_failure_can_be_superseded_by_a_sealed_same_binding(tmp_path, before_actor):
    root, manifest = evidence_run(tmp_path)
    old_key, record = evidence_record(root, manifest, ready=not before_actor, frozen=False)
    if not before_actor:
        record["finalization_error"] = {"type": "FinalizeFailed"}
        (root / "runtime/task-environments" / (old_key + ".json")).write_text(json.dumps(record))
    new_key, _ = evidence_record(root, manifest, attempt=2)
    receipt = collect(root, manifest)
    assert receipt["collection_state"] == ("COMPLETE" if before_actor else "PARTIAL")
    public = json.loads((root / "runtime/task-environments-public.json").read_text())
    old = next(row for row in public["attempts"] if row["environment_key"] == old_key)
    if before_actor:
        assert old["superseded_by"] == new_key and old["outcome"] == "superseded_before_actor"
    else:
        assert "superseded_by" not in old


def test_finalize_failure_with_empty_exports_is_not_complete(tmp_path):
    root, manifest = evidence_run(tmp_path)
    evidence_record(root, manifest, frozen=False, management=False)
    assert collect(root, manifest)["collection_state"] == "PARTIAL"


def test_probe_timeout_removes_only_recorded_owned_container(container_run, monkeypatch):
    root, manifest, task_record = container_run
    workspace = e2b_bootstrap.task_workspace_record(task_record, manifest, str(root), tools(root))
    image = workspace["params"]["environment"]["image"]
    labels = {}
    removed = []

    def run(argv, **kwargs):
        if argv[:2] == ["docker", "info"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "ServerVersion": "27.5.1",
                        "Architecture": "amd64",
                        "NCPU": 8,
                        "MemTotal": 8 * 1024**3,
                    }
                ),
            )
        if argv[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps([{"Id": "image-id", "RepoDigests": [image]}])
            )
        if argv[:2] == ["docker", "run"]:
            intents = list((Path(workspace["params"]["registry_root"]) / "probes").glob("*.json"))
            assert len(intents) == 1
            intent = json.loads(intents[0].read_text())
            labels.update(intent["labels"])
            assert "--name" in argv and "--label" in argv
            raise subprocess.TimeoutExpired(argv, 60)
        if argv[:3] == ["docker", "container", "inspect"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"Id": "owned-probe", "Config": {"Labels": labels}}]),
            )
        if argv[:3] == ["docker", "rm", "-f"]:
            removed.append(argv[-1])
            return SimpleNamespace(returncode=0, stdout="")
        raise AssertionError(argv)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        e2b_bootstrap.probe_container_workspace(workspace)
    assert removed == ["owned-probe"]
    assert not list(root.glob("workspace/**"))
    intent = json.loads(
        next((Path(workspace["params"]["registry_root"]) / "probes").glob("*.json")).read_text()
    )
    assert intent["phase"] == "removed"


def test_probe_cleanup_refuses_foreign_label_and_never_scans_all_containers(tmp_path, monkeypatch):
    registry = tmp_path / "registry"
    (registry / "probes").mkdir(parents=True)
    labels = {
        "io.ahe-beta.preflight.run_id": "owned",
        "io.ahe-beta.preflight.config_hash": "hash",
        "io.ahe-beta.preflight.nonce": "nonce",
    }
    intent = {
        "run_id": "owned",
        "config_hash": "hash",
        "nonce": "nonce",
        "name": "probe",
        "labels": labels,
        "phase": "launching",
    }
    (registry / "probes/nonce.json").write_text(json.dumps(intent))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(
            returncode=0, stdout=json.dumps([{"Id": "foreign", "Config": {"Labels": {}}}])
        )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="different ownership"):
        e2b_bootstrap.cleanup_container_probes(
            registry_root=registry, run_id="owned", config_hash="hash"
        )
    assert calls == [["docker", "container", "inspect", "probe"]]


def test_template_adds_checksum_pinned_docker_only_for_container_tasks():
    class Template:
        def __init__(self):
            self.calls = []

        def from_base_image(self):
            return self

        def run_cmd(self, text, **kwargs):
            self.calls.append(("run", text))
            return self

        def set_user(self, user):
            self.calls.append(("user", user))
            return self

        def set_start_cmd(self, command, ready):
            self.calls.append(("start", command, ready))
            return self

    old = e2b_template._build_template(Template, container_tasks=False)
    new = e2b_template._build_template(Template, container_tasks=True)
    assert len(old.calls) == 1 and "docker" not in old.calls[0][1]
    assert e2b_template.DOCKER_SHA256 in new.calls[1][1]
    assert new.calls[-1][0] == "start" and "dockerd" in new.calls[-1][1]


def test_native_companion_probe_keeps_image_runtime_and_receives_no_harness_mounts(
    container_run, monkeypatch
):
    root, manifest, task_record = container_run
    workspace = e2b_bootstrap.task_workspace_record(task_record, manifest, str(root), tools(root))
    params = workspace["params"]
    native = "example.test/native@sha256:" + "b" * 64
    params["environment"]["services"].append(
        {
            "id": "native",
            "placement": "companion",
            "image": native,
            "resources": {},
        }
    )
    commands = []

    def run(argv, **kwargs):
        if argv[:2] == ["docker", "info"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "ServerVersion": "27.5.1",
                        "Architecture": "amd64",
                        "NCPU": 8,
                        "MemTotal": 8 * 1024**3,
                    }
                ),
            )
        if argv[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "Id": "image-" + argv[-1][-8:],
                            "RepoDigests": [
                                "canonical.example/repository@" + argv[-1].rsplit("@", 1)[1]
                            ],
                        }
                    ]
                ),
            )
        if argv[:2] == ["docker", "run"]:
            commands.append(argv)
            return SimpleNamespace(returncode=0, stdout='{"ready":true}\n')
        if argv[:3] == ["docker", "container", "inspect"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="No such container")
        raise AssertionError(argv)

    monkeypatch.setattr(subprocess, "run", run)
    result = e2b_bootstrap.probe_container_workspace(workspace)
    actor, companion = commands
    assert "--mount" in actor and params["harness_python"] in actor
    assert "--mount" not in companion and params["harness_python"] not in companion
    assert companion[companion.index("--entrypoint") + 1] == "/bin/sh"
    assert result["images"][native]["native_service_ready"] is True
    assert "harness_ready" not in result["images"][native]


@pytest.mark.parametrize("field", ["source", "expected_git_revision", "source_revision"])
def test_frozen_git_requirement_cannot_be_removed_from_prepared_workspace(container_run, field):
    root, manifest, task_record = container_run
    task_record = copy.deepcopy(task_record)
    task_record["package"]["source"] = {
        "kind": "git",
        "url": "https://example.test/source.git",
        "repo": "owner/source",
        "revision": "1" * 40,
    }
    task_record["source_snapshot"]["revision"] = "1" * 40
    task_record["digest"] = workload.task_digest(task_record)
    workspace = e2b_bootstrap.task_workspace_record(task_record, manifest, str(root), tools(root))
    catalog = {"contract_version": 1, "tasks": [task_record]}
    workload.verify_task_workspaces(catalog, {task_record["id"]: workspace})
    if field == "source_revision":
        workspace[field] = None
    else:
        workspace["params"].pop(field)
    with pytest.raises(ConfigError, match="Git source"):
        workload.verify_task_workspaces(catalog, {task_record["id"]: workspace})


def test_source_free_workspace_cannot_inject_git_metadata(container_run):
    root, manifest, task_record = container_run
    workspace = e2b_bootstrap.task_workspace_record(task_record, manifest, str(root), tools(root))
    workspace["params"]["expected_git_revision"] = "1" * 40
    with pytest.raises(ConfigError, match="Git source"):
        workload.verify_task_workspaces(
            {"contract_version": 1, "tasks": [task_record]}, {task_record["id"]: workspace}
        )


def test_lost_previously_collected_optional_log_keeps_sidecar_incomplete(tmp_path):
    root, manifest = evidence_run(tmp_path)
    key, record = evidence_record(root, manifest, management=False)
    record["management_outputs"]["meter.stdout"] = {
        "status": "collected",
        "sha256": hashlib.sha256(b"log").hexdigest(),
        "bytes": 3,
        "visibility": "management",
        "required": False,
    }
    (root / "runtime/task-environments" / (key + ".json")).write_text(json.dumps(record))
    receipt = collect(root, manifest)
    assert receipt["collection_state"] == "PARTIAL"
    assert receipt["management_evidence"]["complete"] is False


@pytest.fixture
def transport_run(tmp_path):
    from ahe_beta.experiment.config import config_hash

    root = tmp_path / "transport-run"
    (root / "materials").mkdir(parents=True)
    small = root / "materials/small.txt"
    small.write_bytes(b"small frozen input\n")
    large = root / "materials/large.bundle"
    with large.open("wb") as stream:
        for _ in range(65):
            stream.write(b"x" * 65536)
        stream.write(b"end")
    config = {"runtime": {"backend": "e2b"}}
    manifest = {
        "run_dir": str(root),
        "config": config,
        "config_hash": config_hash(data=config),
        "materials": {
            name: {"path": str(path.relative_to(root)), "sha256": materials.sha256_file(path)}
            for name, path in (("small", small), ("large", large))
        },
    }
    original = (json.dumps(manifest, indent=3) + "\n").encode()
    (root / "manifest.json").write_bytes(original)
    return root, manifest, original


class _UploadSink:
    def __init__(self, *, fail_path):
        self.fail_path = fail_path
        self.uploads = {}
        self.streams = []

    def write(self, path, data, *, user, request_timeout):
        assert user == "root"
        assert 0 < request_timeout < 3600
        assert isinstance(data, str)
        self.uploads[path] = {"content": data.encode(), "timeout": request_timeout}

    def post(self, url, *, files, timeout):
        path = urlsplit(url).path
        _, data, content_type = files["file"]
        assert content_type == "application/octet-stream"
        assert not isinstance(data, (bytes, bytearray))
        assert data.readable() and "b" in data.mode
        self.streams.append(data)
        chunks = []
        while chunk := data.read(65536):
            chunks.append(chunk)
        if path == self.fail_path:
            raise httpx.ReadTimeout("Provider upload timed out: " + url)
        self.uploads[path] = {"content": b"".join(chunks), "timeout": timeout}
        return httpx.Response(200, json=[{"path": path}], request=httpx.Request("POST", url))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@pytest.fixture
def upload_transport(monkeypatch):
    def sandbox(sink):
        monkeypatch.setattr(httpx, "Client", lambda **_kwargs: sink)
        return SimpleNamespace(
            files=sink,
            connection_config=SimpleNamespace(proxy=None),
            upload_url=lambda path, user: "https://upload.example" + path + "?signature=secret",
        )

    return sandbox


def test_frozen_upload_streams_exact_verified_bytes_with_size_bounded_wait(
    transport_run, upload_transport, capsys
):
    root, manifest, original = transport_run
    sink = _UploadSink(fail_path=None)
    e2b_bootstrap.upload_frozen_inputs(
        upload_transport(sink), run_dir=root, manifest=manifest, root="/owned/run"
    )
    assert sink.uploads["/owned/run/manifest.json"]["content"] == original
    for record in manifest["materials"].values():
        received = sink.uploads["/owned/run/" + record["path"]]
        assert hashlib.sha256(received["content"]).hexdigest() == record["sha256"]
    assert (
        sink.uploads["/owned/run/materials/large.bundle"]["timeout"]
        > (sink.uploads["/owned/run/materials/small.txt"]["timeout"])
    )
    assert sink.uploads["/owned/run/materials/large.bundle"]["timeout"] > 120
    assert sink.uploads["/owned/run/runtime/bootstrap.py"]["content"] == (
        e2b_bootstrap.BOOTSTRAP_PROGRAM.encode()
    )
    assert len(sink.streams) == 3
    assert all(stream.closed for stream in sink.streams)
    progress = capsys.readouterr().err
    assert "[setup] uploading 3/4: materials/large.bundle" in progress
    assert "[setup] uploaded 4/4: runtime/bootstrap.py" in progress


def test_frozen_upload_rejects_tampered_last_material_before_any_remote_write(
    transport_run, upload_transport
):
    root, manifest, _ = transport_run
    (root / "materials/large.bundle").write_bytes(b"replaced")
    sink = _UploadSink(fail_path=None)
    with pytest.raises(ConfigError, match="hash mismatch"):
        e2b_bootstrap.upload_frozen_inputs(
            upload_transport(sink), run_dir=root, manifest=manifest, root="/owned/run"
        )
    assert sink.uploads == {}
    assert sink.streams == []


def test_frozen_upload_timeout_closes_stream_and_does_not_finish_setup(
    transport_run, upload_transport, capsys
):
    root, manifest, original = transport_run
    sink = _UploadSink(fail_path="/owned/run/materials/large.bundle")
    with pytest.raises(BackendError, match="ReadTimeout"):
        e2b_bootstrap.upload_frozen_inputs(
            upload_transport(sink), run_dir=root, manifest=manifest, root="/owned/run"
        )
    assert "/owned/run/runtime/bootstrap.py" not in sink.uploads
    assert all(stream.closed for stream in sink.streams)
    assert (root / "manifest.json").read_bytes() == original
    progress = capsys.readouterr().err
    assert "[setup] uploading 3/4: materials/large.bundle" in progress
    assert "[setup] uploaded 3/4" not in progress


def test_failed_input_upload_retains_owned_resource_without_bootstrap_completion(
    transport_run, upload_transport, monkeypatch
):
    from ahe_beta.experiment.backends.e2b import E2BBackend, _write
    from ahe_beta.experiment.config import config_hash

    root, manifest, _ = transport_run
    manifest.update(run_id="transport-only", task_package={"id": "example"})
    manifest["config"]["runtime"]["e2b"] = {"cpu_count": 4, "memory_mb": 8192}
    manifest["config_hash"] = config_hash(data=manifest["config"])
    (root / "manifest.json").write_text(json.dumps(manifest))
    backend = E2BBackend(root, manifest, {})
    _write(
        backend.resource_file,
        {"sandbox_id": "owned-vm", "template": {"template_id": "clean-template"}},
    )
    info = SimpleNamespace(
        sandbox_id="owned-vm",
        template_id="clean-template",
        metadata={"run_id": manifest["run_id"], "config_hash": manifest["config_hash"]},
        cpu_count=4,
        memory_mb=8192,
        allow_internet_access=True,
        started_at=datetime.now(UTC),
        end_at=datetime.now(UTC),
        state="running",
    )
    sink = _UploadSink(fail_path=backend.root + "/materials/large.bundle")
    sandbox = upload_transport(sink)
    sandbox.get_info = lambda: info
    monkeypatch.setattr(backend, "_sandbox", lambda: sandbox)
    monkeypatch.setattr(backend, "_gitea", lambda: {"owner": "operator", "repo": "experiment"})

    def no_bootstrap(*_args, **_kwargs):
        pytest.fail("Failed upload must not execute bootstrap")

    monkeypatch.setattr(backend, "_command", no_bootstrap)
    with pytest.raises(BackendError, match="ReadTimeout"):
        backend.provision()
    resources = json.loads(backend.resource_file.read_text())
    assert resources["sandbox_id"] == "owned-vm"
    assert resources["metadata"] == info.metadata
    assert "bootstrap_complete" not in resources
    assert "bootstrap" not in resources
    assert backend.root + "/runtime/bootstrap.py" not in sink.uploads


def test_signed_upload_url_is_absent_from_errors_and_transport_logs(
    transport_run, upload_transport, caplog, monkeypatch
):
    root, manifest, _ = transport_run
    caplog.set_level(logging.DEBUG)
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore.http11")]
    states = [(logger.level, logger.disabled) for logger in loggers]
    sink = _UploadSink(fail_path=None)

    def denied(url, **_kwargs):
        for logger in loggers:
            logger.warning("HTTP request: %s", url)
        return httpx.Response(403, text="private body", request=httpx.Request("POST", url))

    monkeypatch.setattr(sink, "post", denied)
    with pytest.raises(BackendError, match="HTTP 403") as failure:
        e2b_bootstrap.upload_frozen_inputs(
            upload_transport(sink), run_dir=root, manifest=manifest, root="/owned/run"
        )
    assert "signature" not in str(failure.value)
    assert "upload.example" not in str(failure.value)
    assert "private body" not in str(failure.value)
    assert "signature" not in caplog.text and "upload.example" not in caplog.text
    assert [(logger.level, logger.disabled) for logger in loggers] == states
    loggers[0].warning("Unrelated logging after upload still works")
    assert "Unrelated logging after upload still works" in caplog.text


def test_upload_io_timeout_is_enforced_by_real_http_transport(transport_run, monkeypatch):
    root, manifest, _ = transport_run
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            release.wait(2)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sandbox = SimpleNamespace(
        connection_config=SimpleNamespace(proxy=None),
        upload_url=lambda path, user: (
            f"http://127.0.0.1:{server.server_port}/upload?signature=secret"
        ),
    )
    monkeypatch.setattr(e2b_bootstrap, "_upload_timeout_seconds", lambda *, size_bytes: 0.05)
    try:
        start = time.monotonic()
        with pytest.raises(BackendError, match="ReadTimeout"):
            e2b_bootstrap.upload_frozen_inputs(
                sandbox, run_dir=root, manifest=manifest, root="/owned/run"
            )
        assert time.monotonic() - start < 1
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
