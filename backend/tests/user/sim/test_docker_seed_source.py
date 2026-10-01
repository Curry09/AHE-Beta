from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from auto_designer.models import WorkspaceSpec


def test_docker_seed_requires_image_and_instance() -> None:
    from auto_designer.user.sim import seed_source

    with pytest.raises(ValueError, match="params.image"):
        seed_source.provision(WorkspaceSpec(kind="docker-seed"))
    with pytest.raises(ValueError, match="params.instance_id"):
        seed_source.provision(WorkspaceSpec(kind="docker-seed", params={"image": "seed:test"}))
    with pytest.raises(ValueError, match="单路径段"):
        seed_source.provision(
            WorkspaceSpec(
                kind="docker-seed",
                params={"image": "seed:test", "instance_id": "../../workspace"},
            )
        )


def test_docker_seed_reports_create_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_designer.user.sim import seed_source
    from auto_designer.user.sim.sources import docker_seed

    monkeypatch.setattr(
        docker_seed.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "missing image"),
    )
    with pytest.raises(RuntimeError, match="missing image"):
        seed_source.provision(
            WorkspaceSpec(
                kind="docker-seed",
                params={"image": "missing:test", "instance_id": "x"},
            )
        )


def test_docker_seed_starts_runnable_session_without_copying_repo_to_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_designer.user.sim import seed_source
    from auto_designer.user.sim.sources import docker_seed

    calls: list[list[str]] = []

    def fake_docker(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    [
                        {
                            "Id": "sha256:seed",
                            "Config": {"Labels": {"org.auto-designer.seed-runtime": "1"}},
                        }
                    ]
                ),
                "",
            )
        if args[0] == "run":
            return subprocess.CompletedProcess(args, 0, "container-1\n", "")
        if args[:3] == ["exec", "container-1", "cat"]:
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"instances": {"instance-1": {}}}), ""
            )
        if args[:3] == ["exec", "container-1", "python3"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    removed: list[list[str]] = []
    monkeypatch.setattr(docker_seed, "_docker", fake_docker)
    monkeypatch.setattr(
        docker_seed.subprocess,
        "run",
        lambda args, **_kwargs: (
            removed.append(args) or subprocess.CompletedProcess(args, 0, "", "")
        ),
    )

    result = seed_source.provision(
        WorkspaceSpec(
            kind="docker-seed",
            params={"image": "seed:test", "instance_id": "instance-1"},
        ),
        str(tmp_path),
    )

    assert result.container_id == "container-1"
    assert result.cwd == "/workspace/instance-1/repo"
    assert any(call[0] == "run" for call in calls)
    assert not any("cp" in call for call in calls)
    isolate_call = next(call for call in calls if call[:3] == ["exec", "container-1", "python3"])
    assert isolate_call[-1] == "instance-1"
    assert "/build-state.json" in isolate_call[-2]
    assert result.evidence["workspace_scope"] == "single_instance"
    assert removed == []


def test_docker_seed_rejects_storage_only_image(monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_designer.user.sim import seed_source
    from auto_designer.user.sim.sources import docker_seed

    monkeypatch.setattr(
        docker_seed,
        "_docker",
        lambda args: subprocess.CompletedProcess(
            args, 0, json.dumps([{"Id": "sha256:old", "Config": {"Labels": {}}}]), ""
        ),
    )
    with pytest.raises(RuntimeError, match="storage-only"):
        seed_source.provision(
            WorkspaceSpec(
                kind="docker-seed",
                params={"image": "seed:old", "instance_id": "instance-1"},
            )
        )


def test_unified_seed_binds_task_environment_and_owned_harness_interpreter(monkeypatch):
    """Spec-0069/T3: plain task python cannot take over Harness's NexAU interpreter."""
    from auto_designer.user.sim.sources import docker_seed

    calls = []

    def docker(args):
        calls.append(args)
        if args[:2] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    [
                        {
                            "Id": "sha256:seed",
                            "Config": {
                                "Labels": {"org.auto-designer.seed-runtime": "1"},
                                "Env": ["PATH=/opt/controller/.venv/bin:/usr/bin:/bin"],
                            },
                        }
                    ]
                ),
                "",
            )
        if args[0] == "run":
            return subprocess.CompletedProcess(args, 0, "container-id", "")
        if args[:3] == ["exec", "container-id", "cat"]:
            return subprocess.CompletedProcess(args, 0, '{"instances":{"task":{}}}', "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(docker_seed, "_docker", docker)
    monkeypatch.setenv("AUTO_DESIGNER_RUN_ID", "run-123")
    monkeypatch.setenv("AUTO_DESIGNER_EXPERIMENT_ID", "run-123")
    monkeypatch.setenv("AUTO_DESIGNER_CONFIG_HASH", "fixed-config")
    result = docker_seed.DockerSeedSource().provision(
        WorkspaceSpec(
            kind="docker-seed",
            params={
                "image": "fixed-image",
                "instance_id": "task",
                "harness_python": "/opt/controller/.venv/bin/python",
                "network": "owned_vigil_net",
                "env": {
                    "HTTP_PROXY": "http://egress-proxy:3128",
                    "HTTPS_PROXY": "http://egress-proxy:3128",
                    "NO_PROXY": "gitea,127.0.0.1,localhost",
                },
            },
        )
    )
    started = next(argv for argv in calls if argv[0] == "run")
    assert "PATH=/workspace/task/repo/.venv/bin:/opt/controller/.venv/bin:/usr/bin:/bin" in started
    assert "VIRTUAL_ENV=/workspace/task/repo/.venv" in started
    assert "io.auto-designer.run_id=run-123" in started
    assert "io.openagents.manifest_sha=fixed-config" in started
    assert result.evidence["harness_python"] == "/opt/controller/.venv/bin/python"
    assert started[started.index("--network") + 1] == "owned_vigil_net"
    assert "HTTP_PROXY=http://egress-proxy:3128" in started
    assert "HTTPS_PROXY=http://egress-proxy:3128" in started
    assert "NO_PROXY=gitea,127.0.0.1,localhost" in started
    assert result.evidence["proxy_environment"]["HTTPS_PROXY"] == "http://egress-proxy:3128"
