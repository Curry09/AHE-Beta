"""Spec-0081/T3: owned resources, durable startup and ordered service lifecycle."""

import json
import subprocess
from pathlib import Path

import pytest

from ahe_beta.experiment.task_environments.contract import (
    container_environment,
    environment_identity,
)
from ahe_beta.experiment.task_environments.docker import (
    _START_NATIVE_SERVICE,
    _START_SERVICE,
    LABEL,
    ContainerTaskRuntime,
    DockerTaskEnvironmentManager,
    TaskEnvironmentError,
    destroy_registered,
    inspect_registered,
)


class FakeManager(DockerTaskEnvironmentManager):
    """Keep lifecycle/journal code real, replace only the Docker transport."""

    def __init__(self, **values):
        super().__init__(**values)
        self.commands = []
        self.start_count = 0
        self.interrupt_start = False
        self.hooks = []

    def _ensure_network(self, *, record):
        record["resources"]["network"] = {"name": "network", "id": "network"}
        self._save(value=record)

    def _ensure_container(self, *, record, identifier, image, cwd, user, resources, ptrace):
        record["resources"]["containers"].setdefault(
            identifier,
            {
                "name": identifier,
                "id": identifier,
                "image": image,
                "image_id": "sha256:" + "f" * 64,
                "keepers": [],
            },
        )
        self._save(value=record)
        return identifier

    def _owned(self, *, kind, name, running):
        return {"Id": name, "State": {"Running": True}}

    def _exec_in(self, *, container, argv, cwd, user, environment, timeout):
        self.commands.append((container, argv, environment))
        if len(argv) > 2 and argv[2] in {_START_SERVICE, _START_NATIVE_SERVICE}:
            self.start_count += 1
            if self.interrupt_start:
                raise KeyboardInterrupt("interrupted after provider side effect")
            value = {"pid": 12, "start_ticks": "42", "sid": 12, "protect_session": True}
            return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    def _docker(self, *, argv, timeout, check):
        self.commands.append(("docker", argv, {}))
        return subprocess.CompletedProcess(argv, 0, "", "")

    def _hook(self, *, container, command, cwd, user, environment):
        self.hooks.append((container, command["argv"], environment))

    def _read_file(self, *, container, root, path, max_bytes):
        return b"sealed"


def manager(tmp_path, **changes):
    toolchain = tmp_path / "toolchain"
    toolchain.mkdir(exist_ok=True)
    image = "example.org/task@sha256:" + "a" * 64
    daemon = {
        "id": "customer",
        "placement": "companion",
        "image": image,
        "argv": ["server"],
        "readiness": {"argv": ["ready"], "timeout_seconds": 2},
        "finalize": {"argv": ["seal"], "timeout_seconds": 2},
        "exports": [
            {"handle": "public", "path": "/result", "visibility": "task"},
            {"handle": "private", "path": "/measurement", "visibility": "management"},
        ],
    }
    seed = {
        "id": "seed",
        "placement": "task",
        "mode": "oneshot",
        "depends_on": ["customer"],
        "argv": ["seed"],
        "timeout_seconds": 2,
    }
    environment = {
        "kind": "container",
        "image": image,
        "workdir": "/app",
        "inputs": [],
        "variables": {"CUSTOMER": "customer"},
        "services": [seed, daemon],
        "readiness": {"argv": ["task-ready"], "timeout_seconds": 2},
        **changes,
    }
    package = {"schema_version": 3, "environment": environment}
    normalized = container_environment(package)
    identity = {
        "run_id": "run",
        "config_hash": "b" * 64,
        "task_id": "task",
        "task_digest": "c" * 64,
        "recipe_hash": environment_identity(package),
        "session_id": "session",
        "attempt": 1,
        "round_no": 2,
        "slot": 3,
    }
    return FakeManager(
        environment=normalized,
        identity=identity,
        registry_root=tmp_path / "registry",
        harness_python=str(toolchain / "python"),
        harness_mounts=[{"source": str(toolchain), "target": str(toolchain)}],
    )


def test_dependencies_and_once_hooks_survive_controller_reopen(tmp_path):
    m = manager(tmp_path)
    runtime = m.open()
    assert isinstance(runtime, ContainerTaskRuntime)
    assert [command[1] for command in m.hooks] == [["ready"], ["seed"], ["task-ready"]]
    assert m._record()["services"]["seed"]["phase"] == "complete"
    m.open()
    assert m.start_count == 1
    assert [command[1] for command in m.hooks].count(["seed"]) == 1
    m.quiesce()
    with pytest.raises(TaskEnvironmentError, match="frozen"):
        runtime.run("rewrite output")
    m.finalize()
    m.finalize()
    assert [command[1] for command in m.hooks].count(["seal"]) == 1
    assert m._record()["services"]["customer"]["phase"] == "finalized"


def test_interrupted_service_launch_never_launches_duplicate(tmp_path):
    m = manager(tmp_path)
    m.interrupt_start = True
    with pytest.raises(KeyboardInterrupt):
        m.open()
    assert m._record()["services"]["customer"]["launch_intent"] == "started"
    assert "process" not in m._record()["services"]["customer"]
    with pytest.raises(TaskEnvironmentError, match="cannot be restarted"):
        m.open()
    assert m.start_count == 1
    # A journal left before exception handling also fails closed; no second Popen.
    state = m._record()
    state["phase"] = "creating"
    m._save(value=state)
    with pytest.raises(TaskEnvironmentError, match="another process"):
        m.open()
    assert m.start_count == 1


def test_interrupted_side_effecting_hook_not_replayed(tmp_path):
    m = manager(tmp_path)
    record = {"stages": {"seed": "started"}}
    with pytest.raises(TaskEnvironmentError, match="Interrupted side-effecting"):
        m._once(
            record=record,
            key="seed",
            container="task",
            command={"argv": ["seed"], "timeout_seconds": 2},
            cwd="/app",
            user=None,
            environment={},
        )
    assert m.hooks == []


def test_finalizer_failure_does_not_claim_frozen(tmp_path):
    m = manager(tmp_path)
    m.open()
    m.quiesce()

    def failure(**kwargs):
        raise TaskEnvironmentError("finalizer failed")

    m._hook = failure
    with pytest.raises(TaskEnvironmentError, match="finalizer failed"):
        m.finalize()
    assert m._record()["phase"] == "quiesced"
    assert m._record()["finalization_error"]["type"] == "TaskEnvironmentError"
    with pytest.raises(TaskEnvironmentError, match="not frozen"):
        m.export_service_file(handle="public", max_bytes=20)


def test_managed_exports_bind_real_ownership_and_hide_private_handles(tmp_path):
    m = manager(tmp_path)
    m.open()
    m.quiesce()
    m.finalize()
    proof = m.service_export_provenance(handle="public")
    assert proof["identity"] == m.identity
    assert proof["environment_key"] == m.key
    assert proof["service"] == "customer"
    assert proof["service_id"] == "customer"
    assert proof["isolated"] is True and proof["agent_stopped"] is True
    assert proof["handle"] == "public" and proof["visibility"] == "task"
    assert m.export_service_file(handle="public", max_bytes=20) == b"sealed"
    with pytest.raises(PermissionError):
        m.export_service_file(handle="private", max_bytes=20)
    with pytest.raises(PermissionError):
        m.service_export_provenance(handle="private")
    m.capture_management()
    private = m._record()["management_outputs"]["private"]
    assert private["required"] is True
    assert Path(private["path"]).read_bytes() == b"sealed"
    assert Path(private["path"]).stat().st_mode & 0o777 == 0o600


def test_task_placement_export_never_claims_measurement_isolation(tmp_path):
    m = manager(
        tmp_path,
        services=[
            {
                "id": "local",
                "placement": "task",
                "argv": ["server"],
                "readiness": {"argv": ["ready"], "timeout_seconds": 2},
                "exports": [{"handle": "output", "path": "/output", "visibility": "task"}],
            }
        ],
    )
    m.open()
    m.quiesce()
    m.finalize()
    assert m.service_export_provenance(handle="output")["isolated"] is False


def test_close_retains_frozen_environment_if_crash_preceded_private_capture(tmp_path, monkeypatch):
    m = manager(tmp_path)
    runtime = m.open()
    m.quiesce()
    m.finalize()
    assert "management_outputs" not in m._record()
    retained = []
    monkeypatch.setattr(m, "close", lambda *, retain: retained.append(retain))
    runtime.close()
    assert retained == [True]


def test_changed_recipe_or_uncovered_python_rejected_before_docker(tmp_path):
    m = manager(tmp_path)
    args = dict(
        environment={**m.environment, "workdir": "/other"},
        identity=m.identity,
        registry_root=tmp_path / "other",
        harness_python=m.harness_python,
        harness_mounts=m.harness_mounts,
    )
    with pytest.raises(TaskEnvironmentError, match="recipe differs"):
        DockerTaskEnvironmentManager(**args)
    args["environment"] = m.environment
    args["harness_python"] = "/unmounted/python"
    with pytest.raises(TaskEnvironmentError, match="outside its readonly"):
        DockerTaskEnvironmentManager(**args)


def test_resource_label_mismatch_never_deletes_foreign_container(tmp_path, monkeypatch):
    m = manager(tmp_path)
    m.open()
    calls = []
    monkeypatch.setattr(
        m,
        "_inspect",
        lambda **kwargs: {
            "Id": kwargs["name"],
            "Config": {"Labels": {LABEL: "1", LABEL + ".key": "foreign"}},
            "State": {"Running": True},
        },
    )
    monkeypatch.setattr(m, "_owned", DockerTaskEnvironmentManager._owned.__get__(m))
    monkeypatch.setattr(m, "_docker", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(TaskEnvironmentError, match="ownership differs"):
        m.close(retain=False)
    assert calls == []


def test_public_inspection_omits_raw_management_and_variables(tmp_path, monkeypatch):
    m = manager(tmp_path)
    m.open()
    state = m._record()
    state["management_outputs"] = {"secret-measurement": {"bytes": "raw-private-content"}}
    m._save(value=state)
    monkeypatch.setattr(
        DockerTaskEnvironmentManager,
        "_inspect",
        lambda self, **kwargs: {
            "Id": kwargs["name"],
            "Config": {"Labels": self.labels},
            "State": {"Running": True},
        },
    )
    receipt = inspect_registered(registry_root=m.root, run_id="run", config_hash="b" * 64)
    body = json.dumps(receipt)
    assert len(receipt["attempts"]) == 1
    assert "raw-private-content" not in body and "CUSTOMER" not in body
    assert "harness_mounts" not in body and "management_outputs" not in body


def test_removed_toolchain_does_not_block_owned_cleanup_or_allow_actor_restart(
    tmp_path, monkeypatch
):
    m = manager(tmp_path)
    m.open()
    state = m._record()
    Path(m.harness_mounts[0]["source"]).rmdir()
    restored = DockerTaskEnvironmentManager._from_record(value=state, registry_root=m.root)
    with pytest.raises(TaskEnvironmentError, match="cannot provision"):
        restored.open()
    remaining = {"task", "customer", "network"}
    calls = []

    def info(self, *, kind, name):
        if name not in remaining:
            return None
        return {
            "Id": name,
            "Config": {"Labels": self.labels},
            "Labels": self.labels,
            "State": {"Running": True},
        }

    def docker(self, *, argv, timeout, check):
        calls.append(argv)
        if argv[:2] == ["rm", "-f"] or argv[:2] == ["network", "rm"]:
            remaining.remove(argv[-1])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(DockerTaskEnvironmentManager, "_inspect", info)
    monkeypatch.setattr(DockerTaskEnvironmentManager, "_docker", docker)
    result = destroy_registered(registry_root=m.root, run_id="run", config_hash="b" * 64)
    assert remaining == set()
    assert result["attempts"][0]["phase"] == "closed"
    assert all(call[0] != "exec" and call[0] != "run" for call in calls)
    destroy_registered(registry_root=m.root, run_id="run", config_hash="b" * 64)
    assert len(calls) == 3


def test_verified_input_staging_is_once_and_interrupted_copy_is_not_replayed(tmp_path, monkeypatch):
    m = manager(
        tmp_path,
        inputs=[
            {
                "id": "data",
                "target": "/app/fixture.txt",
                "material": {
                    "path": str(tmp_path / "locked"),
                    "sha256": "f" * 64,
                    "format": "file",
                },
            }
        ],
    )
    copies = []

    def materialize(*, material, destination):
        (destination / "input").write_bytes(b"verified")
        return {"input": "f" * 64}

    monkeypatch.setattr(
        "ahe_beta.experiment.task_environments.materials.materialize_input", materialize
    )
    monkeypatch.setattr(m, "_docker", lambda **kwargs: copies.append(kwargs["argv"]))
    m.open()
    state = m._record()
    m._stage_inputs(record=state)
    assert len(copies) == 1
    assert copies[0][-1] == "task:/app/fixture.txt"
    state["inputs"]["data"] = "started"
    with pytest.raises(TaskEnvironmentError, match="Interrupted input staging"):
        m._stage_inputs(record=state)
    assert len(copies) == 1


def test_task_service_readiness_and_relative_finalizer_share_task_workdir(tmp_path, monkeypatch):
    m = manager(
        tmp_path,
        services=[
            {
                "id": "worker",
                "placement": "task",
                "argv": ["server"],
                "readiness": {"argv": ["test", "-f", "ready"], "timeout_seconds": 2},
                "finalize": {"argv": ["test", "-f", "ready"], "timeout_seconds": 2},
            }
        ],
    )
    observed = []
    monkeypatch.setattr(
        m, "_hook", lambda **values: observed.append((values["command"]["argv"], values["cwd"]))
    )
    m.open()
    m.quiesce()
    m.finalize()
    assert observed.count((["test", "-f", "ready"], "/app")) == 2


def test_incomplete_finalization_cannot_be_adopted_as_collection_or_restart_actor(tmp_path):
    from ahe_beta.experiment.task_environments.docker import resume_collection

    m = manager(tmp_path)
    runtime = m.open()
    m.quiesce()
    assert "frozen_at" not in m._record()
    with pytest.raises(TaskEnvironmentError, match="finalization repair"):
        resume_collection(binding=runtime.collection_binding(), expected_provenance=m.identity)
    assert m.start_count == 1
