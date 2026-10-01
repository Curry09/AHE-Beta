"""Spec-0069/T5: provider facts, recoverable identity and collection are independent."""

import json
import tarfile

import pytest

from auto_designer.experiment import runtime
from auto_designer.experiment.collection import collect_archive
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.manifest import read_runtime, update_runtime
from auto_designer.experiment.materials import sha256_file


class Adapter:
    def __init__(self, root):
        self.root = root
        self.receipt = {
            "controller": {"state": "ABSENT", "running": False},
            "resource_state": "ABSENT",
        }
        self.calls = []

    def inspect(self):
        return self.receipt

    def provision(self):
        self.calls.append("provision")
        return {}

    def preflight(self):
        self.calls.append("preflight")
        return {}

    def launch(self, *, mode):
        self.calls.append(mode)
        self.receipt = {
            "controller": {"state": "RUNNING", "running": True, "nonce": "owned"},
            "resource_state": "RUNNING",
        }
        return self.receipt

    def collect(self):
        controller = self.receipt["controller"]
        return {
            "snapshot_dir": str(self.root),
            "controller": controller,
            "consistent": True,
            "terminal": controller["state"] in {"STOPPED", "EXITED"},
            "files": {},
        }

    def stop(self, **kwargs):
        self.calls.append("stop")
        self.receipt = {
            "controller": {"state": "STOPPED", "running": False},
            "resource_state": "STOPPED",
        }
        return self.receipt

    def destroy(self):
        self.calls.append("destroy")
        self.receipt["resource_state"] = "DESTROYED"
        return self.receipt


@pytest.fixture
def run(tmp_path, monkeypatch):
    run_id = "20260930T120000Z-abc12345"
    directory = tmp_path / run_id
    directory.mkdir()
    for child in ("runtime", "checkpoints", "materials", "secrets"):
        (directory / child).mkdir()
    material = directory / "materials/task.txt"
    material.write_text("frozen")
    manifest = {
        "schema_version": 2,
        "run_id": run_id,
        "run_dir": str(directory),
        "config_hash": "fixed",
        "secrets_file": None,
        "config": {
            "runtime": {"backend": "local"},
            "models": {
                name: {"model": "test", "base_url_env": "TEST_URL", "api_key_env": "TEST_KEY"}
                for name in ("user", "harness", "demand", "delivery")
            },
        },
        "materials": {"task": {"path": "materials/task.txt", "sha256": sha256_file(material)}},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    update_runtime(
        run_dir=directory,
        action="prepare",
        changes={"experiment_state": "PREPARED", "preparation_complete": True},
    )
    adapter = Adapter(directory)
    monkeypatch.setattr(runtime, "backend_v2", lambda **kwargs: adapter)
    monkeypatch.setenv("TEST_URL", "https://example.test")
    monkeypatch.setenv("TEST_KEY", "model-secret")
    from auto_designer.experiment import materials

    monkeypatch.setattr(materials, "verify_materials", lambda value: None)
    return tmp_path, directory, manifest, adapter


def test_incomplete_preparation_cannot_contact_or_provision_provider(run, monkeypatch):
    base, directory, manifest, adapter = run
    update_runtime(
        run_dir=directory,
        action="prepare-failed",
        changes={"preparation_complete": False},
    )
    monkeypatch.setattr(
        adapter,
        "inspect",
        lambda: (_ for _ in ()).throw(AssertionError("must not contact provider")),
    )
    with pytest.raises(ConfigError, match="preparation is incomplete"):
        runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)
    assert adapter.calls == []


def test_prepare_is_observable_and_serialized_until_images_ready(run, monkeypatch):
    import threading

    from auto_designer.experiment import materials
    from auto_designer.experiment.backends import local

    base, directory, manifest, _ = run
    monkeypatch.setattr(materials, "prepare_materials", lambda *args: manifest)
    entered, release = threading.Event(), threading.Event()
    errors = []

    def images(**kwargs):
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(local, "prepare_images", images)

    def prepare():
        try:
            runtime.prepare_v2(config_path=directory / "unused.json", root=base)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=prepare)
    worker.start()
    try:
        assert entered.wait(5)
        status = runtime.status_v2(run_id=manifest["run_id"], root=base)
        assert status["observation"] == "OPERATION_IN_PROGRESS"
        assert status["experiment_state"] == "PREPARING"
        assert status["preparation_complete"] is False
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert errors == []
    assert read_runtime(run_dir=directory)["preparation_complete"] is True
    assert read_runtime(run_dir=directory)["experiment_state"] == "PREPARED"


def test_launch_ack_and_duplicate_run_dont_reprovision(run):
    base, directory, manifest, adapter = run
    before = (directory / "manifest.json").read_bytes()
    result = runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)
    assert result["experiment_state"] == "RUNNING"
    assert result["provider"]["controller"]["state"] == "RUNNING"
    assert adapter.calls == ["provision", "preflight", "fresh"]
    assert runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)["action"] == "attach"
    assert adapter.calls == ["provision", "preflight", "fresh"]
    assert (directory / "manifest.json").read_bytes() == before


def test_status_exposes_only_public_gitea_fields(run):
    base, directory, manifest, _ = run
    (directory / "resources.json").write_text(
        json.dumps(
            {
                "gitea": {
                    "url": "http://localhost:3000",
                    "owner": "experiment",
                    "repo": "harness",
                    "repository_id": 42,
                    "token": "must-not-appear",
                    "password": "private",
                }
            }
        )
    )
    result = runtime.status_v2(run_id=manifest["run_id"], root=base)
    assert result["gitea"] == {
        "url": "http://localhost:3000",
        "owner": "experiment",
        "repo": "harness",
        "repository_id": 42,
    }
    assert "must-not-appear" not in json.dumps(result)


def test_exit_zero_without_seals_is_failed(run):
    base, _, manifest, adapter = run
    adapter.receipt["controller"] = {
        "state": "EXITED",
        "running": False,
        "exit_code": 0,
        "experiment_complete": False,
    }
    result = runtime.status_v2(run_id=manifest["run_id"], root=base)
    assert result["experiment_state"] == "FAILED"
    assert result["collection_state"] == "NONE"


def test_completed_requires_engine_seal_receipt(run):
    base, _, manifest, adapter = run
    adapter.receipt["controller"] = {
        "state": "EXITED",
        "running": False,
        "exit_code": 0,
        "experiment_complete": True,
    }
    assert (
        runtime.status_v2(run_id=manifest["run_id"], root=base)["experiment_state"] == "COMPLETED"
    )


def test_unknown_provider_retains_last_known_outcome(run, monkeypatch):
    base, directory, manifest, adapter = run
    update_runtime(
        run_dir=directory,
        action="launch",
        changes={"experiment_state": "RUNNING", "resource_state": "RUNNING"},
    )
    monkeypatch.setattr(
        adapter, "inspect", lambda: (_ for _ in ()).throw(ConnectionError("offline"))
    )
    result = runtime.status_v2(run_id=manifest["run_id"], root=base)
    assert result["experiment_state"] == "RUNNING"
    assert result["observation"] == "UNKNOWN"
    with pytest.raises(ConfigError, match="unknown"):
        runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)


def test_stop_collect_resume_preserves_id_and_manifest(run):
    base, directory, manifest, adapter = run
    before = (directory / "manifest.json").read_bytes()
    runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)
    result = runtime.stop_v2(run_id=manifest["run_id"], root=base)
    assert result["experiment_state"] == "STOPPED"
    assert result["collection_state"] == "COMPLETE"
    with pytest.raises(ConfigError, match="resume"):
        runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)
    assert (
        runtime.run_v2(run_id=manifest["run_id"], root=base, resume_run=True, monitor=False)[
            "experiment_state"
        ]
        == "RUNNING"
    )
    assert adapter.calls[-1] == "resume"
    assert (directory / "manifest.json").read_bytes() == before


def test_collect_and_destroy_dont_require_model_keys_or_source_git(run, monkeypatch):
    base, directory, manifest, adapter = run
    monkeypatch.delenv("TEST_KEY")
    monkeypatch.delenv("TEST_URL")
    adapter.receipt["controller"] = {"state": "STOPPED", "running": False}
    assert (
        runtime.collect_v2(run_id=manifest["run_id"], root=base)["collection_state"] == "COMPLETE"
    )
    result = runtime.destroy_v2(run_id=manifest["run_id"], confirm=manifest["run_id"], root=base)
    assert result["resource_state"] == "DESTROYED"
    assert (directory / "archive/artifacts.tar.gz").is_file()


@pytest.mark.parametrize(
    "previous_error, remaining_error",
    [
        ("Collection failed; previous archive retained", None),
        ("Automatic collection failed; compute retained for manual recovery", None),
        (
            "Controller launch failed; inputs/resources retained",
            "Controller launch failed; inputs/resources retained",
        ),
    ],
)
def test_successful_collection_clears_only_collection_errors(run, previous_error, remaining_error):
    base, directory, manifest, adapter = run
    adapter.receipt["controller"] = {"state": "STOPPED", "running": False}
    update_runtime(run_dir=directory, action="failed", changes={"last_error": previous_error})
    runtime.collect_v2(run_id=manifest["run_id"], root=base)
    assert read_runtime(run_dir=directory)["last_error"] == remaining_error


def test_uncollected_destroy_requires_explicit_discard_and_confirmation(run):
    base, _, manifest, adapter = run
    with pytest.raises(ConfigError, match="confirm"):
        runtime.destroy_v2(
            run_id=manifest["run_id"], confirm="another-run", root=base, discard_uncollected=True
        )
    with pytest.raises(ConfigError, match="Collect"):
        runtime.destroy_v2(run_id=manifest["run_id"], confirm=manifest["run_id"], root=base)
    assert "destroy" not in adapter.calls


def test_partial_archive_never_allows_default_destroy(run):
    base, _, manifest, _ = run
    result = runtime.collect_v2(run_id=manifest["run_id"], root=base)
    assert result["collection_state"] == "PARTIAL"
    with pytest.raises(ConfigError, match="Collect"):
        runtime.destroy_v2(run_id=manifest["run_id"], confirm=manifest["run_id"], root=base)


def test_archive_excludes_credentials_symlinks_and_recursion(run):
    _, directory, manifest, adapter = run
    (directory / "secrets/provider.env").write_text("E2B_API_KEY=private-secret")
    (directory / "data").mkdir()
    (directory / "data/log.txt").write_text("echo private-secret")
    (directory / "data/.env.example").write_text("MODEL_API_KEY=\n")
    (directory / "data/.env.local").write_text("MODEL_API_KEY=private-secret\n")
    (directory / "data/external").symlink_to("/etc/passwd")
    receipt = collect_archive(
        run_dir=directory,
        manifest=manifest,
        snapshot=adapter.collect(),
        credentials={"E2B_API_KEY": "private-secret"},
    )
    with tarfile.open(receipt["archive"]) as archive:
        names = archive.getnames()
        assert not any(
            "secrets" in n or "collection-stage" in n or "external" in n or n.startswith("archive/")
            for n in names
        )
        assert "data/.env.example" in names
        assert "data/.env.local" not in names
        assert archive.extractfile("data/log.txt").read() == b"echo [REDACTED]"
        for name, expected in receipt["files"].items():
            import hashlib

            assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == expected


@pytest.mark.parametrize("bad", ["../other", "a/b", "/etc", ".hidden", "a\\b"])
def test_run_id_rejects_traversal(tmp_path, bad):
    with pytest.raises(ConfigError):
        runtime.load_run_v2(run_id=bad, root=tmp_path)


def test_launch_failure_retains_provider_and_manifest(run, monkeypatch):
    base, directory, manifest, adapter = run
    monkeypatch.setattr(adapter, "launch", lambda **kwargs: {"state": "ABSENT", "running": False})
    with pytest.raises(ConfigError, match="launch failed"):
        runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)
    assert read_runtime(run_dir=directory)["experiment_state"] == "FAILED"
    assert "destroy" not in adapter.calls
    assert (directory / "manifest.json").is_file()


def test_successful_resume_clears_resolved_launch_failure(run, monkeypatch):
    base, directory, manifest, adapter = run
    original_launch = adapter.launch
    monkeypatch.setattr(adapter, "launch", lambda **kwargs: {"state": "ABSENT", "running": False})
    with pytest.raises(ConfigError, match="launch failed"):
        runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)
    assert read_runtime(run_dir=directory)["last_error"]
    monkeypatch.setattr(adapter, "launch", original_launch)
    result = runtime.run_v2(run_id=manifest["run_id"], root=base, resume_run=True, monitor=False)
    assert result["experiment_state"] == "RUNNING"
    assert all(result[field] is None for field in ("last_error", "failed_stage", "error_class"))


@pytest.mark.parametrize(
    "error, remaining_error",
    [
        ("Old controller launch failed", None),
        (
            "Collection failed; previous archive retained",
            "Collection failed; previous archive retained",
        ),
    ],
)
def test_observed_running_controller_resolves_older_launch_error(run, error, remaining_error):
    base, directory, manifest, adapter = run
    adapter.launch(mode="resume")
    update_runtime(
        run_dir=directory,
        action="older-launch",
        changes={
            "failed_stage": "controller launch",
            "error_class": "BackendError",
            "last_error": error,
        },
    )
    result = runtime.status_v2(run_id=manifest["run_id"], root=base)
    assert result["experiment_state"] == "RUNNING"
    assert result["failed_stage"] is None
    assert result["error_class"] is None
    assert result["last_error"] == remaining_error


def test_private_provider_file_survives_missing_model_file(run, monkeypatch):
    _, directory, manifest, _ = run
    manifest["secrets_file"] = str(directory / "gone.env")
    runtime._persist_provider_credentials(
        directory, {"GITEA_TOKEN": "tok'en\\abc", "E2B_API_KEY": "e2b-secret"}
    )
    assert (directory / "secrets/provider.env").stat().st_mode & 0o777 == 0o600
    credentials = runtime.credentials_v2(manifest=manifest, run_dir=directory)
    assert credentials["GITEA_TOKEN"] == "tok'en\\abc"
    assert credentials["E2B_API_KEY"] == "e2b-secret"


def test_resume_invalidates_previous_terminal_archive(run):
    base, directory, manifest, adapter = run
    runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)
    runtime.stop_v2(run_id=manifest["run_id"], root=base)
    assert read_runtime(run_dir=directory)["collection_state"] == "COMPLETE"
    runtime.run_v2(run_id=manifest["run_id"], root=base, resume_run=True, monitor=False)
    assert read_runtime(run_dir=directory)["collection_state"] == "PARTIAL"
    adapter.receipt["controller"] = {"state": "UNKNOWN", "running": False}
    with pytest.raises(ConfigError):
        runtime.destroy_v2(run_id=manifest["run_id"], confirm=manifest["run_id"], root=base)
    assert "destroy" not in adapter.calls


def test_collect_redacts_available_model_key_after_original_env_disappears(run, monkeypatch):
    base, directory, manifest, adapter = run
    runtime.run_v2(run_id=manifest["run_id"], root=base, monitor=False)
    monkeypatch.delenv("TEST_KEY")
    monkeypatch.delenv("TEST_URL")
    (directory / "data").mkdir()
    (directory / "data/trajectory.txt").write_text("echo model-secret")
    adapter.receipt["controller"] = {"state": "STOPPED", "running": False}
    receipt = runtime.collect_v2(run_id=manifest["run_id"], root=base)
    with tarfile.open(receipt["archive"]) as archive:
        assert archive.extractfile("data/trajectory.txt").read() == b"echo [REDACTED]"
        assert not any("redaction-values" in n for n in archive.getnames())


def test_explicit_secrets_override_process_variables(run, monkeypatch):
    _, directory, manifest, _ = run
    env = directory / "models.env"
    env.write_text("TEST_KEY=file-key\nTEST_URL=https://file.example\n")
    env.chmod(0o600)
    monkeypatch.setenv("TEST_KEY", "process-key")
    credentials = runtime.credentials_v2(manifest=manifest, secrets_file=env, models=True)
    assert credentials["TEST_KEY"] == "file-key"
    assert credentials["TEST_URL"] == "https://file.example"


def test_status_reports_provisioning_without_overwriting_owner_operation(run):
    from auto_designer.experiment.manifest import run_lock

    base, directory, manifest, _ = run
    update_runtime(
        run_dir=directory, action="provision-intent", changes={"resource_state": "PROVISIONING"}
    )
    with run_lock(run_dir=directory):
        result = runtime.status_v2(run_id=manifest["run_id"], root=base)
        assert result["resource_state"] == "PROVISIONING"
        assert result["observation"] == "OPERATION_IN_PROGRESS"
    assert read_runtime(run_dir=directory)["resource_state"] == "PROVISIONING"


def test_destroy_retains_actual_provider_lost_receipt(run, monkeypatch):
    base, directory, manifest, adapter = run
    update_runtime(run_dir=directory, action="collect", changes={"collection_state": "COMPLETE"})
    monkeypatch.setattr(adapter, "destroy", lambda: {"resource_state": "LOST"})
    assert (
        runtime.destroy_v2(run_id=manifest["run_id"], confirm=manifest["run_id"], root=base)[
            "resource_state"
        ]
        == "LOST"
    )


def test_forge_terminal_cache_must_match_controller_attempt(run, monkeypatch):
    import requests

    from auto_designer.experiment.collection import export_gitea_snapshot

    _, directory, _, _ = run
    destination = directory / "runtime/gitea-evidence.json"
    destination.write_text(json.dumps({"terminal": True, "controller_nonce": "old-attempt"}))
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    )
    resources = {"gitea": {"url": "https://gitea.com", "owner": "person", "repo": "owned"}}
    mismatch = export_gitea_snapshot(
        run_dir=directory,
        resources=resources,
        credentials={},
        terminal=True,
        controller_nonce="new-attempt",
    )
    assert mismatch["complete"] is False
    same = export_gitea_snapshot(
        run_dir=directory,
        resources=resources,
        credentials={},
        terminal=True,
        controller_nonce="old-attempt",
    )
    assert same["complete"] is True
