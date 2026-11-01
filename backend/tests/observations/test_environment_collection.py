"""Spec-0081/T3: frozen public outputs cannot leak private service exports."""

from auto_designer.evaluation.artifacts import collect_session_artifacts


def identity():
    return {
        "run_id": "run",
        "round_no": 1,
        "slot": 0,
        "task_id": "task",
        "task_digest": "a" * 64,
        "harness_sha": "b" * 40,
    }


def declaration(**changes):
    return {
        "id": "report",
        "source": "managed_service",
        "handle": "report",
        "content_type": "text/plain",
        "required": True,
        "max_bytes": 128,
        **changes,
    }


class Environment:
    def __init__(self):
        self.calls = []

    def quiesce(self):
        self.calls.append("quiesce")

    def finalize_task(self):
        self.calls.append("finalize")

    def export_service_file(self, handle, max_bytes):
        self.calls.append("export")
        assert self.calls[:2] == ["quiesce", "finalize"]
        if handle == "management":
            raise PermissionError("private")
        return b"original output"

    def service_export_provenance(self, handle):
        return {"handle": handle, "visibility": "task", "service_id": "owned"}


def collect(tmp_path, environment, declarations):
    return collect_session_artifacts(
        workspace=environment,
        sessions_root=tmp_path / "data/sessions",
        session_id="session",
        provenance=identity(),
        declarations=declarations,
    )


def test_public_output_retained_after_seal_and_provenance_attached(tmp_path):
    environment = Environment()
    receipt = collect(tmp_path, environment, [declaration()])
    assert receipt["complete"] is True
    item = receipt["entries"][0]
    assert item["metadata"]["service_id"] == "owned"
    assert item["metadata"]["handle"] == "report"
    assert (tmp_path / "data" / item["path"]).read_bytes() == b"original output"
    assert environment.calls == ["quiesce", "finalize", "export"]


def test_finalizer_failure_never_looks_complete_even_without_artifacts(tmp_path):
    environment = Environment()

    def failure():
        raise TimeoutError("workload did not finish sealing")

    environment.finalize_task = failure
    receipt = collect(tmp_path, environment, [])
    assert receipt["complete"] is False
    assert receipt["collection_error"] == "TimeoutError"
    assert receipt["entries"] == []
    assert environment.calls == ["quiesce"]


def test_management_handle_cannot_be_published(tmp_path):
    receipt = collect(tmp_path, Environment(), [declaration(handle="management")])
    item = receipt["entries"][0]
    assert receipt["complete"] is False and item["status"] == "collection_failed"
    assert item["reason"] == "PermissionError" and "path" not in item
    assert not (tmp_path / "data/evaluation-artifacts").exists()


def test_managed_output_without_ownership_capability_is_incomplete(tmp_path):
    environment = Environment()
    environment.service_export_provenance = None
    receipt = collect(tmp_path, environment, [declaration()])
    assert receipt["complete"] is False
    assert receipt["entries"][0]["reason"] == "NotImplementedError"
    assert not (tmp_path / "data/evaluation-artifacts").exists()


def test_actor_wrong_workspace_type_is_task_failure_but_transport_is_infrastructure(tmp_path):
    from auto_designer.user.sim.runtime import LocalWorkspaceRuntime

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "report").symlink_to(root / "elsewhere")
    environment = LocalWorkspaceRuntime(str(root))
    receipt = collect(tmp_path, environment, [declaration(source="workspace", path="report")])
    assert receipt["complete"] is False
    assert receipt["entries"][0]["status"] == "invalid"
    assert receipt["entries"][0]["reason"] == "invalid_task_artifact"
    managed = Environment()

    def invalid_service(handle, max_bytes):
        raise ValueError("trusted service output contract broke")

    managed.export_service_file = invalid_service
    receipt = collect(tmp_path / "managed", managed, [declaration()])
    assert receipt["entries"][0]["status"] == "collection_failed"


def test_published_observation_recovery_verifies_version_and_retained_bytes(tmp_path):
    import json

    import pytest

    from auto_designer.observations.publication import publish, verify_published

    version = {"harness_sha": "a" * 40, "image_digest": "sha256:" + "b" * 64}
    files = {
        "manifest.json": json.dumps(
            {"status": "complete", "reading": "READING.md", "files": [{"path": "READING.md"}]}
        ).encode(),
        "READING.md": b"original",
    }
    publish(root=tmp_path, session_id="session", run_id="run", version=version, files=files)
    (tmp_path / "session/manifest.json").unlink()
    assert (
        verify_published(root=tmp_path, session_id="session", run_id="run", version=version)[
            "status"
        ]
        == "complete"
    )
    assert (tmp_path / "session/manifest.json").is_file()
    with pytest.raises(ValueError, match="provenance"):
        verify_published(root=tmp_path, session_id="session", run_id="run", version={})
    (tmp_path / "session/runs/run/READING.md").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="content changed"):
        verify_published(root=tmp_path, session_id="session", run_id="run", version=version)
