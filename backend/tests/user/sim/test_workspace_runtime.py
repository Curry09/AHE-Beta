from __future__ import annotations

import subprocess

import pytest

from ahe_beta.user.sim.runtime import DockerWorkspaceRuntime, LocalWorkspaceRuntime


def test_local_runtime_rejects_escape_and_round_trips_text(tmp_path) -> None:
    runtime = LocalWorkspaceRuntime(str(tmp_path))
    runtime.write_text("nested/x.txt", "hello")
    assert runtime.read_text("nested/x.txt") == "hello"
    with pytest.raises(ValueError, match="escapes"):
        runtime.read_text("../outside")


def test_docker_command_timeout_invalidates_whole_container(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if args[:2] == ["docker", "exec"]:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 1))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("ahe_beta.user.sim.runtime.subprocess.run", fake_run)
    runtime = DockerWorkspaceRuntime(
        container_id="c1",
        container_name="session-1",
        image="seed:runnable",
        image_digest="sha256:x",
        cwd="/workspace/i/repo",
    )

    result = runtime.run("pytest", timeout=1)

    assert result["status"] == "timed_out"
    assert runtime.evidence["invalid_reason"].startswith("command timeout")
    assert ["docker", "kill", "c1"] in calls
    with pytest.raises(RuntimeError, match="invalid"):
        runtime.read_text("x")
