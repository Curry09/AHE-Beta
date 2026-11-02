from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from ahe_beta.models import WorkspaceSpec


def test_docker_seed_requires_image_and_instance() -> None:
    from ahe_beta.user.sim import seed_source

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
    from ahe_beta.user.sim import seed_source
    from ahe_beta.user.sim.sources import docker_seed

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
    from ahe_beta.user.sim import seed_source
    from ahe_beta.user.sim.sources import docker_seed

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
    started = next(call for call in calls if call[0] == "run")
    assert started[-3:] == ["seed:test", "sleep", "infinity"]
    assert not any("cp" in call for call in calls)
    isolate_call = next(call for call in calls if call[:3] == ["exec", "container-1", "python3"])
    assert isolate_call[-1] == "instance-1"
    assert "/build-state.json" in isolate_call[-2]
    assert result.evidence["workspace_scope"] == "single_instance"
    assert removed == []


def test_docker_seed_rejects_storage_only_image(monkeypatch: pytest.MonkeyPatch) -> None:
    from ahe_beta.user.sim import seed_source
    from ahe_beta.user.sim.sources import docker_seed

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
    from ahe_beta.user.sim.sources import docker_seed

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
    monkeypatch.setenv("AHE_BETA_RUN_ID", "run-123")
    monkeypatch.setenv("AHE_BETA_EXPERIMENT_ID", "run-123")
    monkeypatch.setenv("AHE_BETA_CONFIG_HASH", "fixed-config")
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
    assert "io.ahe-beta.run_id=run-123" in started
    assert "io.openagents.manifest_sha=fixed-config" in started
    assert result.evidence["harness_python"] == "/opt/controller/.venv/bin/python"
    assert started[started.index("--network") + 1] == "owned_vigil_net"
    assert "HTTP_PROXY=http://egress-proxy:3128" in started
    assert "HTTPS_PROXY=http://egress-proxy:3128" in started
    assert "NO_PROXY=gitea,127.0.0.1,localhost" in started
    assert result.evidence["proxy_environment"]["HTTPS_PROXY"] == "http://egress-proxy:3128"


# Spec-0073/T2: the runtime receipt and Docker labels share the logical session identity.
def test_docker_session_carries_bound_task_round_and_stable_session(monkeypatch):
    from ahe_beta.usage import bind_usage_context
    from ahe_beta.user.sim.sources import docker_seed

    calls = []

    def docker(args, **_kwargs):
        calls.append(args)
        if args[:2] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    [
                        {
                            "Id": "sha256:fixed",
                            "Config": {"Labels": {"org.auto-designer.seed-runtime": "1"}},
                        }
                    ]
                ),
                "",
            )
        if args[0] == "run":
            return subprocess.CompletedProcess(args, 0, "container\n", "")
        if args[:3] == ["exec", "container", "cat"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"instances": {"one": {}}}), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(docker_seed, "_docker", docker)
    monkeypatch.setattr(
        docker_seed.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )
    spec = WorkspaceSpec(
        kind="docker-seed",
        params={
            "image": "sha256:fixed",
            "instance_id": "one",
            "task_id": "one",
            "task_digest": "a" * 64,
        },
    )
    with bind_usage_context(session_id="stable-session", round_no=2):
        runtime = docker_seed.DockerSeedSource().provision(spec)
    run = next(args for args in calls if args[0] == "run")
    assert "io.ahe-beta.session_id=stable-session" in run
    assert "io.ahe-beta.task_id=one" in run
    assert "io.ahe-beta.round_no=2" in run
    assert runtime.evidence["session_id"] == "stable-session"
    assert runtime.evidence["task_digest"] == "a" * 64
    runtime.close()


def test_real_docker_seed_quiesce_kills_descendants_and_keeps_frozen_export(tmp_path):
    """Spec-0084/T2: no actor writer survives, while controller export remains usable."""
    if os.environ.get("RUN_SPEC_0084_DOCKER") != "1":
        pytest.skip("set RUN_SPEC_0084_DOCKER=1 for real Docker lifecycle verification")
    from ahe_beta.user.sim.sources.docker_seed import DockerSeedSource

    image = f"ahe-beta-quiesce-test:{uuid.uuid4().hex}"
    # Use an installed image; the opt-in regression never pulls an unpinned remote tag.
    base = subprocess.run(
        ["docker", "image", "inspect", "python:3.13-slim-bookworm", "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    runtime = None
    fixture = None
    try:
        fixture = subprocess.run(
            ["docker", "create", base, "sleep", "infinity"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        root = tmp_path / "root"
        (root / "workspace/task/repo").mkdir(parents=True)
        (root / "build-state.json").write_text('{"instances":{"task":{}}}')
        subprocess.run(
            ["docker", "cp", str(root) + "/.", fixture + ":/"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            [
                "docker",
                "commit",
                "--change",
                "LABEL org.auto-designer.seed-runtime=1",
                fixture,
                image,
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        runtime = DockerSeedSource().provision(
            WorkspaceSpec(kind="docker-seed", params={"image": image, "instance_id": "task"})
        )
        # Two forks create children and grandchildren. Ignore TERM deliberately so
        # the production KILL pass must stop them; orphan descendants still count.
        writer = (
            "import os,signal,time\nfrom pathlib import Path\n"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            "root=Path('/workspace/task/repo')\n"
            "for generation in range(3):\n"
            " root.joinpath(f'pid-{generation}').write_text(str(os.getpid()))\n"
            " if generation==2: break\n"
            " if os.fork():\n"
            "  while True: time.sleep(1)\n"
            "while True:\n"
            " root.joinpath('answer.tmp').write_text(str(time.monotonic_ns()))\n"
            " root.joinpath('answer.tmp').replace(root/'answer.json')\n"
            " time.sleep(.01)\n"
        )
        subprocess.run(
            ["docker", "exec", "-d", runtime.container_id, "python3", "-c", writer],
            check=True,
            capture_output=True,
            timeout=10,
        )
        deadline = time.monotonic() + 5
        while True:
            try:
                pids = [int(runtime.read_text(f"pid-{i}")) for i in range(3)]
                if runtime.export_file("answer.json", 100):
                    break
            except (OSError, ValueError):
                pass
            assert time.monotonic() < deadline, "task writer did not start"
            time.sleep(0.05)

        runtime.quiesce()
        assert len(set(pids)) == 3
        assert (
            runtime._exec(
                [
                    "python3",
                    "-c",
                    "from pathlib import Path\nimport sys\n"
                    "for pid in sys.argv[1:]:\n"
                    " p=Path('/proc')/pid/'stat'\n"
                    " assert not p.exists() or p.read_text().rsplit(')',1)[1].split()[0]=='Z'\n",
                    *map(str, pids),
                ]
            ).returncode
            == 0
        )
        assert (
            subprocess.run(
                ["docker", "inspect", runtime.container_id, "--format", "{{.State.Running}}"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            == "true"
        )
        frozen = runtime.export_file("answer.json", 100)
        time.sleep(0.1)
        assert runtime.export_file("answer.json", 100) == frozen
        (tmp_path / "answer.json").write_bytes(frozen)
        assert (tmp_path / "answer.json").read_bytes() == frozen
    finally:
        if runtime is not None:
            runtime.close()
        if fixture is not None:
            subprocess.run(["docker", "rm", "-f", fixture], capture_output=True, timeout=30)
        subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True, timeout=30)
