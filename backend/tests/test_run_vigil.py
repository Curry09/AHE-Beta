# Spec-0032/T5 + 0033/T2 + 0040/T1: vigil wiring unit test—config persisted to disk, rfc=agent, keep-alive,
# dual-mode pre-flight and startup/shutdown (mock docker/Popen, no real container invocation).
"""Verify run.py delivery-side wiring: openagents.yml content matches finalized stages, token not persisted to disk, VIGIL_MODE dual modes (container default sandboxing / subprocess explicit integration-test) pre-flight, startup/shutdown, and env injection respectively. Spec-0040/T1: stages.rfc=agent. Spec-0050/T4: VIGIL_KEEP_ALIVE default sandbox removal."""

from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path

import pytest
from ruamel.yaml import YAML

run = importlib.import_module("ahe_beta.experiment.controllers.runtime")

_GITEA = {
    "GITEA_URL": "http://localhost:3000",
    "OWNER": "harness",
    "REPO": "harness",
    "TOKEN": "secret-token",
}


def _load_yaml(path: Path):
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------------
# Declarative config persisted to disk (shared write_openagents_config for both modes).
# --------------------------------------------------------------------------------------------------


def test_write_openagents_config_matches_stage_finalization(tmp_path: Path) -> None:
    path = run.write_openagents_config(repo=tmp_path, gitea=_GITEA)
    assert path == tmp_path / ".openagents" / "openagents.yml"
    data = _load_yaml(path)
    assert data["forge"] == "gitea"
    assert data["coordination"] == "soft"
    assert data["gitea"] == {
        "base_url": "http://localhost:3000",
        "owner": "harness",
        "repo": "harness",
        "token_env": "GITEA_TOKEN",
    }
    # Spec-0040/T1: stages finalized triage/ci/e2e=skip, rfc/conflict/review/merge=agent.
    assert data["stages"] == {
        "triage": "skip",
        "rfc": "agent",
        "conflict": "agent",
        "ci": "skip",
        "e2e": "skip",
        "review": "agent",
        "merge": "agent",
    }
    assert data["release"] == "manual"
    # Owner handoff token = vigil discovered label
    assert data["defaults"]["labels"] == ["openagents"]
    assert data["defaults"]["base"] == "main"
    # Token itself never persisted to disk (only declare env name, vigil process/container env provides it).
    assert "secret-token" not in path.read_text(encoding="utf-8")


def test_ci_stage_env_override(tmp_path: Path, monkeypatch) -> None:
    # Spec-0032/T6: after act_runner validation runs, VIGIL_CI_STAGE=agent enables ci gate; invalid values ignored, fall back to skip.
    monkeypatch.setenv("VIGIL_CI_STAGE", "agent")
    data = _load_yaml(run.write_openagents_config(repo=tmp_path, gitea=_GITEA))
    assert data["stages"]["ci"] == "agent"
    monkeypatch.setenv("VIGIL_CI_STAGE", "banana")
    data = _load_yaml(run.write_openagents_config(repo=tmp_path, gitea=_GITEA))
    assert data["stages"]["ci"] == "skip"


def test_coordination_can_be_disabled_without_restoring_hard_curator(tmp_path, monkeypatch):
    monkeypatch.setenv("VIGIL_COORDINATION", "off")
    data = _load_yaml(run.write_openagents_config(repo=tmp_path, gitea=_GITEA))
    assert data["coordination"] == "off"
    monkeypatch.setenv("VIGIL_COORDINATION", "typo")
    with pytest.raises(ValueError, match="VIGIL_COORDINATION"):
        run.write_openagents_config(repo=tmp_path, gitea=_GITEA)


def test_write_openagents_config_is_idempotent(tmp_path: Path) -> None:
    first = run.write_openagents_config(repo=tmp_path, gitea=_GITEA).read_text(encoding="utf-8")
    second = run.write_openagents_config(repo=tmp_path, gitea=_GITEA).read_text(encoding="utf-8")
    assert first == second


def test_remote_tag_refs_skips_peeled_entries() -> None:
    # Empirical fix: peeled line (^{}) with annotated tag is not a real ref; push deletion exits with 128 and resets process failure.
    ls = "aaa\trefs/tags/v1\nbbb\trefs/tags/v1^{}\nccc\trefs/tags/v2\nddd\trefs/heads/main\n"
    assert run._remote_tag_refs(ls) == ["refs/tags/v1", "refs/tags/v2"]
    assert run._remote_tag_refs("") == []


# --------------------------------------------------------------------------------------------------
# Mode parsing and pre-flight.
# --------------------------------------------------------------------------------------------------


def test_vigil_mode_defaults_to_container(monkeypatch) -> None:
    monkeypatch.delenv("VIGIL_MODE", raising=False)
    assert run.vigil_mode() == "container"  # Sandboxing mode is default (Spec-0033)


def test_vigil_keep_alive_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("VIGIL_KEEP_ALIVE", raising=False)
    assert run.vigil_keep_alive() is False
    monkeypatch.setenv("VIGIL_KEEP_ALIVE", "0")
    assert run.vigil_keep_alive() is False
    monkeypatch.setenv("VIGIL_KEEP_ALIVE", "1")
    assert run.vigil_keep_alive() is True
    monkeypatch.setenv("VIGIL_KEEP_ALIVE", "true")
    assert run.vigil_keep_alive() is True


def test_stop_vigil_model_processes_is_scoped_to_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AHE_BETA_RUN_ID", "target-run")
    monkeypatch.setattr(run.os, "getpgrp", lambda: 900)
    killed_groups: list[int] = []
    killed_pids: list[int] = []
    monkeypatch.setattr(run.os, "killpg", lambda pgid, _sig: killed_groups.append(pgid))
    monkeypatch.setattr(run.os, "kill", lambda pid, _sig: killed_pids.append(pid))

    def process(pid: int, parent: int, group: int, cmd: str, run_id: str) -> None:
        directory = tmp_path / str(pid)
        directory.mkdir()
        (directory / "stat").write_text(f"{pid} (process) S {parent} {group} 0\n")
        (directory / "cmdline").write_bytes(cmd.encode() + b"\0")
        (directory / "environ").write_bytes(f"AHE_BETA_RUN_ID={run_id}".encode() + b"\0")

    process(101, 77, 101, "claude -p --verbose", "target-run")
    process(102, 101, 102, "python -m unittest", "target-run")
    process(103, 1, 103, "claude -p --verbose", "target-run")  # old orphan
    process(104, 1, 104, "claude -p --verbose", "another-run")
    process(105, 77, 900, "sleep 300", "target-run")  # task service, not a model call

    run._stop_vigil_model_processes(vigil_pid=77, proc_root=tmp_path)

    assert set(killed_groups) == {101, 102, 103}
    assert set(killed_pids) == {101, 102, 103}


def test_vigil_mode_invalid_fails_loud(monkeypatch) -> None:
    monkeypatch.setenv("VIGIL_MODE", "yolo")
    with pytest.raises(SystemExit, match="VIGIL_MODE"):
        run.vigil_mode()


def test_ensure_openagents_cli_missing_fails_loud(monkeypatch) -> None:
    monkeypatch.setattr(run.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="openagents"):
        run.ensure_openagents_cli()


def test_container_prereqs_missing_image_hints_build(monkeypatch) -> None:
    monkeypatch.setattr(run.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        run.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "no such image"),
    )
    with pytest.raises(SystemExit, match="build.sh"):
        run._ensure_vigil_container_prereqs()


def test_container_prereqs_require_claude_credential(monkeypatch) -> None:
    monkeypatch.setattr(run.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        run.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
    )
    for key in run._CLAUDE_CRED_ENVS:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit, match="Claude credentials"):
        run._ensure_vigil_container_prereqs()
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "long-lived")  # Subscription tokens also count
    run._ensure_vigil_container_prereqs()  # Do not raise
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    # Gateway Bearer also counts (one of three)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "bearer-x")
    run._ensure_vigil_container_prereqs()  # Do not raise


# --------------------------------------------------------------------------------------------------
# Container mode: docker run parameter shape / internal network config / start/stop.
# --------------------------------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, calls: dict) -> None:
        self._calls = calls

    def terminate(self):
        self._calls["terminated"] = True

    def wait(self, timeout=None):
        self._calls["waited"] = True

    def kill(self):
        self._calls["killed"] = True


def _container_rig(monkeypatch, tmp_path: Path) -> dict:
    """Container mode stubbing: docker preflight allowlist, subprocess.run/Popen recording, staging redirect to tmp."""
    calls: dict = {"runs": []}
    monkeypatch.setenv("VIGIL_MODE", "container")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAGENTS_PERMISSION_MODE", raising=False)
    monkeypatch.delenv("AHE_BETA_RUN_ID", raising=False)
    monkeypatch.delenv("ROLE_RUNS_DIR", raising=False)
    # Clear host-set base_url/model to avoid polluting assertions
    for key in run._CLAUDE_CONFIG_ENVS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", raising=False)
    monkeypatch.setattr(run, "_VIGIL_CONFIG_STAGING", tmp_path / "staging")
    monkeypatch.setattr(run.shutil, "which", lambda name: f"/usr/bin/{name}")

    def _fake_run(argv, **kw):
        calls["runs"].append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "container-id", "")

    monkeypatch.setattr(run.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        run.subprocess,
        "Popen",
        lambda argv, **kw: calls.update(popen=list(argv)) or _FakeProc(calls),
    )
    return calls


def test_container_start_shapes_docker_run(tmp_path: Path, monkeypatch) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    handle = run.start_vigil(
        # Container mode does not touch host repo (zero mounts, self-clone)
        repo=tmp_path / "unused-host-repo",
        parallel=2,
        gitea=_GITEA,
        log_path=tmp_path / "data" / "vigil.log",
    )
    docker_run = next(argv for argv in calls["runs"] if argv[:2] == ["docker", "run"])
    joined = " ".join(docker_run)
    assert handle.mode == "container"
    # Internal network (direct connection to external network physically unavailable)
    assert f"--network {run._VIGIL_NETWORK}" in joined
    assert "/config:ro" in joined and "/entrypoint.sh:ro" in joined  # Two read-only mounts
    assert "/role_runs" not in joined  # Do not mount delivery when ROLE_RUNS_DIR is not set
    assert "sessions" not in joined and "/demand" not in joined
    # Inspect container destinations, not incidental words in the host checkout name.
    mounts = [docker_run[i + 1] for i, value in enumerate(docker_run) if value == "-v"]
    assert {value.rsplit(":", 2)[-2] for value in mounts} == {"/config", "/entrypoint.sh"}
    assert "GITEA_TOKEN=secret-token" in joined  # Credentials only via container env
    assert "GITEA_USER=harness" in joined
    assert "ANTHROPIC_API_KEY=sk-test" in joined
    assert f"HTTPS_PROXY={run._VIGIL_PROXY_URL}" in joined  # Outbound traffic only via egress proxy
    # Claude inside container must bypass (otherwise headless git rejected by permission gate); containment is container's responsibility.
    assert "OPENAGENTS_PERMISSION_MODE=bypassPermissions" in joined
    assert "VIGIL_PARALLEL=2" in joined
    # Clone address is from container's internal network perspective (service name), includes credentials, no host disk files.
    assert "VIGIL_REPO_URL=http://harness:secret-token@gitea:3000/harness/harness.git" in joined
    assert calls["popen"][:3] == ["docker", "logs", "-f"]  # Log follower
    # Host repo not written to (zero mounts: config only goes to staging).
    assert not (tmp_path / "unused-host-repo" / ".openagents").exists()


def test_container_passes_through_claude_config_envs(tmp_path: Path, monkeypatch) -> None:
    # Third-party Anthropic protocol gateway: base_url + model overrides (including small/fast models) must be passed through to container; if absent, claude uses official default.
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example.top")
    monkeypatch.setenv("ANTHROPIC_MODEL", "vendor/Model-Pro")
    monkeypatch.setenv("ANTHROPIC_SMALL_FAST_MODEL", "vendor/Model-Pro")
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    joined = " ".join(next(a for a in calls["runs"] if a[:2] == ["docker", "run"]))
    assert "ANTHROPIC_BASE_URL=https://gw.example.top" in joined
    assert "ANTHROPIC_MODEL=vendor/Model-Pro" in joined
    assert "ANTHROPIC_SMALL_FAST_MODEL=vendor/Model-Pro" in joined
    assert "CLAUDE_CODE_SUBAGENT_MODEL=vendor/Model-Pro" in joined
    assert "CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1" in joined


def test_container_maps_explicit_harness_glm_envs_to_product_client_names(
    tmp_path: Path, monkeypatch
) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("HARNESS_LLM_MODEL", "glm-test")
    monkeypatch.setenv("HARNESS_LLM_BASE_URL", "http://172.22.64.1:18080/v1")
    monkeypatch.setenv("HARNESS_LLM_API_KEY", "harness-key")
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    joined = " ".join(next(a for a in calls["runs"] if a[:2] == ["docker", "run"]))
    assert "LLM_MODEL=glm-test" in joined
    assert "LLM_BASE_URL=http://172.22.64.1:18080/v1" in joined
    assert "LLM_API_KEY=harness-key" in joined


def test_container_omits_unset_claude_config_envs(tmp_path: Path, monkeypatch) -> None:
    # Unset config env vars are not passed through (official claude scenario zero noise, no empty values injected).
    calls = _container_rig(monkeypatch, tmp_path)
    for key in run._CLAUDE_CONFIG_ENVS:
        monkeypatch.delenv(key, raising=False)
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    joined = " ".join(next(a for a in calls["runs"] if a[:2] == ["docker", "run"]))
    assert "ANTHROPIC_MODEL" not in joined and "ANTHROPIC_BASE_URL" not in joined
    assert "CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1" in joined
    assert "CLAUDE_CODE_SUBAGENT_MODEL=" not in joined


def test_container_permission_mode_host_overridable(tmp_path: Path, monkeypatch) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAGENTS_PERMISSION_MODE", "acceptEdits")
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    docker_run = next(argv for argv in calls["runs"] if argv[:2] == ["docker", "run"])
    assert "OPENAGENTS_PERMISSION_MODE=acceptEdits" in " ".join(docker_run)


def test_container_config_uses_internal_gitea_url(tmp_path: Path, monkeypatch) -> None:
    _container_rig(monkeypatch, tmp_path)
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    data = _load_yaml(tmp_path / "staging" / ".openagents" / "openagents.yml")
    # From container perspective, not host localhost
    assert data["gitea"]["base_url"] == "http://gitea:3000"


def test_container_internal_url_overridable(tmp_path: Path, monkeypatch) -> None:
    _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("VIGIL_GITEA_INTERNAL_URL", "http://gitea-alt:3001")
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    data = _load_yaml(tmp_path / "staging" / ".openagents" / "openagents.yml")
    assert data["gitea"]["base_url"] == "http://gitea-alt:3001"


def test_container_stop_removes_container(tmp_path: Path, monkeypatch) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("VIGIL_KEEP_ALIVE", "0")
    handle = run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    run.stop_vigil(handle)
    assert ["docker", "rm", "-f", run._VIGIL_CONTAINER] in calls["runs"]
    assert calls.get("terminated") and calls.get("waited")


def test_container_keep_alive_does_not_remove_container(tmp_path: Path, monkeypatch) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("VIGIL_KEEP_ALIVE", "1")
    handle = run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    assert handle.keep_alive is True
    run.stop_vigil(handle)
    assert ["docker", "rm", "-f", run._VIGIL_CONTAINER] not in calls["runs"]
    assert calls.get("terminated") and calls.get("waited")  # Only parse log follower


def test_container_reuses_running_instance(tmp_path: Path, monkeypatch) -> None:
    calls = _container_rig(monkeypatch, tmp_path)

    def _fake_run(argv, **kw):
        calls["runs"].append(list(argv))
        if list(argv)[:3] == ["docker", "inspect", "-f"]:
            return subprocess.CompletedProcess(argv, 0, "true\n", "")
        return subprocess.CompletedProcess(argv, 0, "container-id", "")

    monkeypatch.setattr(run.subprocess, "run", _fake_run)
    handle = run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    assert handle.mode == "container"
    assert not any(argv[:2] == ["docker", "run"] for argv in calls["runs"])
    assert calls["popen"][:3] == ["docker", "logs", "-f"]


def test_container_mounts_only_delivery_role_runs(tmp_path: Path, monkeypatch) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    run_root = tmp_path / "role_runs" / "run-a"
    (run_root / "sessions").mkdir(parents=True)
    (run_root / "demand").mkdir(parents=True)
    monkeypatch.setenv("ROLE_RUNS_DIR", str(run_root))
    monkeypatch.setenv("AHE_BETA_RUN_ID", "run-a")
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    docker_run = next(argv for argv in calls["runs"] if argv[:2] == ["docker", "run"])
    joined = " ".join(docker_run)
    assert f"{(run_root / 'delivery').resolve()}:/role_runs" in joined
    assert "ROLE_RUNS_DIR=/role_runs" in joined
    assert "--user root" in joined
    assert f"VIGIL_EXEC_UID={os.getuid() or 1000}" in docker_run
    assert f"VIGIL_EXEC_GID={os.getgid() or 1000}" in docker_run
    assert "io.ahe-beta.run_id=run-a" in joined
    assert "AUTO_DESIGNER_RUN_ID=run-a" in docker_run
    assert "sessions" not in joined
    assert "/demand" not in joined


@pytest.mark.parametrize("uid,gid", [(1201, 1302), (0, 0)])
def test_delivery_mount_execution_identity_matches_host_without_running_as_root(
    tmp_path: Path, monkeypatch, uid: int, gid: int
) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path / "role_runs" / "run-a"))
    monkeypatch.setattr(run.os, "getuid", lambda: uid)
    monkeypatch.setattr(run.os, "getgid", lambda: gid)
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    docker_run = next(argv for argv in calls["runs"] if argv[:2] == ["docker", "run"])
    assert f"VIGIL_EXEC_UID={uid or 1000}" in docker_run
    assert f"VIGIL_EXEC_GID={gid or 1000}" in docker_run
    assert "VIGIL_EXEC_UID=0" not in docker_run
    assert "VIGIL_EXEC_GID=0" not in docker_run


@pytest.mark.parametrize("seconds", ["37", "0"])
def test_container_passes_explicit_claude_idle_timeout_and_permissions(
    tmp_path: Path, monkeypatch, seconds: str
) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAGENTS_CLAUDE_IDLE_TIMEOUT", seconds)
    monkeypatch.setenv("OPENAGENTS_PERMISSION_MODE", "acceptEdits")
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    docker_run = next(argv for argv in calls["runs"] if argv[:2] == ["docker", "run"])
    assert f"OPENAGENTS_CLAUDE_IDLE_TIMEOUT={seconds}" in docker_run
    assert "OPENAGENTS_PERMISSION_MODE=acceptEdits" in docker_run
    assert "OPENAGENTS_PERMISSION_MODE=bypassPermissions" not in docker_run


def test_container_rebuilds_when_run_id_changes(tmp_path: Path, monkeypatch) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("AHE_BETA_RUN_ID", "run-b")

    def _fake_run(argv, **kw):
        calls["runs"].append(list(argv))
        if list(argv)[:3] == ["docker", "inspect", "-f"]:
            return subprocess.CompletedProcess(argv, 0, "true|run-a\n", "")
        return subprocess.CompletedProcess(argv, 0, "container-id", "")

    monkeypatch.setattr(run.subprocess, "run", _fake_run)
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    assert ["docker", "rm", "-f", run._VIGIL_CONTAINER] in calls["runs"]
    assert any(argv[:2] == ["docker", "run"] for argv in calls["runs"])


def test_container_refuses_foreign_experiment_attach(tmp_path: Path, monkeypatch) -> None:
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.delenv("AHE_BETA_EXPERIMENT_ID", raising=False)

    def _fake_run(argv, **kw):
        calls["runs"].append(list(argv))
        if list(argv)[:3] == ["docker", "inspect", "-f"]:
            return subprocess.CompletedProcess(argv, 0, "true|run-a|exp-other\n", "")
        return subprocess.CompletedProcess(argv, 0, "container-id", "")

    monkeypatch.setattr(run.subprocess, "run", _fake_run)
    with pytest.raises(SystemExit, match="Refusing to attach"):
        run.start_vigil(
            repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
        )


def test_apply_experiment_context_overrides_singleton(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run, "DATA", run.DATA)
    monkeypatch.setattr(run, "HARNESS_REPO", run.HARNESS_REPO)
    monkeypatch.setattr(run, "_SANDBOX_ROOT", run._SANDBOX_ROOT)
    monkeypatch.setattr(run, "_VIGIL_CONTAINER", run._VIGIL_CONTAINER)
    monkeypatch.setattr(run, "_VIGIL_NETWORK", run._VIGIL_NETWORK)
    monkeypatch.setattr(run, "_VIGIL_CONFIG_STAGING", run._VIGIL_CONFIG_STAGING)

    class _Ctx:
        experiment_id = "exp-z"
        data_root = tmp_path / "data"
        harness_repo = tmp_path / "data" / "harness_sandbox" / "harness_repo"
        vigil_container = "adx-exp-z-xxxx-vigil-1"
        vigil_network = "adx-exp-z-xxxx_vigil_net"
        vigil_config_root = tmp_path / "infra" / "vigil-config"

    run.apply_experiment_context(ctx=_Ctx())
    assert run.DATA == _Ctx.data_root
    assert run._VIGIL_CONTAINER == _Ctx.vigil_container
    assert os.environ["AHE_BETA_EXPERIMENT_ID"] == "exp-z"


def test_install_role_runs_does_not_delete_prior_slice(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AHE_BETA_RUN_ID", raising=False)
    first = run.install_role_runs(data_root=tmp_path)
    (first / "sessions" / "old.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("AHE_BETA_RUN_ID", raising=False)
    second = run.install_role_runs(data_root=tmp_path)
    assert first != second
    assert (first / "sessions" / "old.json").is_file()
    assert (tmp_path / "sessions").is_symlink()
    assert (tmp_path / "sessions").resolve() == (second / "sessions").resolve()


def test_reset_to_initial_leaves_role_runs(tmp_path: Path, monkeypatch) -> None:
    kept = tmp_path / "role_runs" / "prior" / "sessions"
    kept.mkdir(parents=True)
    marker = kept / "keep.json"
    marker.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(run, "DATA", tmp_path)
    monkeypatch.setattr(run, "_git", lambda *_a, **_k: None)
    monkeypatch.setattr(
        run.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, "", ""),
    )

    class _Tracker:
        def list_open_issues(self):
            return []

    run._reset_to_initial(tmp_path / "repo", _Tracker())
    assert marker.is_file()


# --------------------------------------------------------------------------------------------------
# Subprocess mode (explicit opt-in for co-debug): existing behavior preserved.
# --------------------------------------------------------------------------------------------------


def test_subprocess_start_spawns_with_token_env_and_cwd(tmp_path: Path, monkeypatch) -> None:
    calls: dict = {}
    monkeypatch.setenv("VIGIL_MODE", "subprocess")
    monkeypatch.setenv("VIGIL_KEEP_ALIVE", "0")
    monkeypatch.setenv("ANTHROPIC_MODEL", "vendor/Model-Pro")
    monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "anthropic/claude-sonnet-5")
    monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "0")
    monkeypatch.setenv("AHE_BETA_RUN_ID", "current-run")
    monkeypatch.setenv("AHE_BETA_ROUND", "3")
    monkeypatch.setenv("AUTO_DESIGNER_RUN_ID", "unrelated-old-run")
    monkeypatch.setattr(run.shutil, "which", lambda name: "/usr/bin/openagents")

    def _fake_popen(argv, *, cwd, env, stdout, stderr):
        calls.update(argv=list(argv), cwd=cwd, env=env)
        return _FakeProc(calls)

    monkeypatch.setattr(run.subprocess, "Popen", _fake_popen)
    repo = tmp_path / "harness-repo"
    repo.mkdir()
    handle = run.start_vigil(
        repo=repo, parallel=3, gitea=_GITEA, log_path=tmp_path / "data" / "vigil.log"
    )
    assert handle.mode == "subprocess"
    assert calls["argv"] == ["openagents", "vigil", "--parallel", "3"]
    assert calls["cwd"] == str(repo)
    # Token only via child process env, not in config
    assert calls["env"]["GITEA_TOKEN"] == "secret-token"
    assert calls["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "vendor/Model-Pro"
    assert calls["env"]["CLAUDE_CODE_SUBAGENT_MODEL_FORCE"] == "1"
    assert calls["env"]["AUTO_DESIGNER_RUN_ID"] == "current-run"
    assert calls["env"]["AUTO_DESIGNER_ROUND"] == "3"
    # Co-debug mode config written to host repo (existing behavior)
    assert (repo / ".openagents" / "openagents.yml").is_file()

    run.stop_vigil(handle)
    assert calls.get("terminated") and calls.get("waited")


def test_subprocess_keep_alive_does_not_kill_proc(tmp_path: Path, monkeypatch) -> None:
    calls: dict = {}
    monkeypatch.setenv("VIGIL_MODE", "subprocess")
    monkeypatch.setenv("VIGIL_KEEP_ALIVE", "1")
    monkeypatch.setattr(run.shutil, "which", lambda name: "/usr/bin/openagents")

    def _fake_popen(argv, *, cwd, env, stdout, stderr):
        calls.update(argv=list(argv), cwd=cwd, env=env)
        return _FakeProc(calls)

    monkeypatch.setattr(run.subprocess, "Popen", _fake_popen)
    repo = tmp_path / "harness-repo"
    repo.mkdir()
    handle = run.start_vigil(
        repo=repo, parallel=1, gitea=_GITEA, log_path=tmp_path / "data" / "vigil.log"
    )
    run.stop_vigil(handle)
    assert not calls.get("terminated")


def test_stop_vigil_kills_on_timeout(tmp_path: Path) -> None:
    events = []

    class _Stuck:
        def terminate(self):
            events.append("terminate")

        def wait(self, timeout=None):
            if "killed" not in events:
                events.append("wait-timeout")
                raise subprocess.TimeoutExpired(cmd="vigil", timeout=timeout)
            events.append("wait-after-kill")

        def kill(self):
            events.append("killed")

    class _Log:
        def close(self):
            events.append("log-closed")

    run.stop_vigil(
        run.VigilHandle(mode="subprocess", proc=_Stuck(), log_handle=_Log(), keep_alive=False)
    )
    assert events == ["terminate", "wait-timeout", "killed", "wait-after-kill", "log-closed"]


# Spec-0070/T3: the checked runtime is the runtime used for actual delivery.
def _hosted_profile(tmp_path, monkeypatch):
    from ahe_beta.observations.transport import (
        freeze_transport_profile,
        make_transport_profile,
    )

    root = tmp_path / "observations"
    monkeypatch.setenv("AHE_BETA_OBSERVATION_ROOT", str(root))
    hosted = {**_GITEA, "GITEA_URL": "https://gitea.com"}
    profile = make_transport_profile(
        repository="https://gitea.com/api/v1/repos/harness/harness",
        encoding="zip",
        download_policy="gitea-com-r2-v1",
    )
    freeze_transport_profile(root=root, profile=profile)
    return hosted, profile


def _reader_capabilities():
    return {
        "schema": "openagents-observation-reader-capabilities-v1",
        "marker": "auto-designer:observation-evidence-v1",
        "encodings": ["gzip", "zip"],
        "zip_profile": "single-evidence-json-v1",
        "download_policies": ["same-origin-v1", "gitea-com-r2-v1"],
        "max_transfer_bytes": 4_000_000,
        "max_expanded_bytes": 24_000_000,
    }


def test_hosted_container_uses_checked_image_public_url_and_no_updates(tmp_path, monkeypatch):
    from ahe_beta.observations import preflight

    calls = _container_rig(monkeypatch, tmp_path)
    hosted, _ = _hosted_profile(tmp_path, monkeypatch)
    identity = "sha256:" + "c" * 64
    monkeypatch.setattr(
        preflight,
        "probe_reader",
        lambda **kw: {
            "capabilities": _reader_capabilities(),
            "runtime": {"mode": "container", "image_id": identity},
        },
    )
    run.start_vigil(repo=tmp_path / "repo", parallel=1, gitea=hosted, log_path=tmp_path / "d/v.log")
    argv = next(a for a in calls["runs"] if a[:2] == ["docker", "run"])
    assert identity in argv and run._VIGIL_IMAGE not in argv
    assert "OPENAGENTS_NO_SELF_UPDATE=1" in argv
    assert "AHE_BETA_OBSERVATION_DOWNLOAD_POLICY=gitea-com-r2-v1" in argv
    data = _load_yaml(tmp_path / "staging/.openagents/openagents.yml")
    assert data["gitea"]["base_url"] == "https://gitea.com"
    assert any("@gitea.com/" in a for a in argv)


def test_hosted_subprocess_uses_exact_checked_executable(tmp_path, monkeypatch):
    from ahe_beta.observations import preflight

    hosted, _ = _hosted_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("VIGIL_MODE", "subprocess")
    monkeypatch.setattr(run, "ensure_openagents_cli", lambda: None)
    monkeypatch.setattr(
        preflight,
        "probe_reader",
        lambda **kw: {
            "capabilities": _reader_capabilities(),
            "runtime": {"mode": "subprocess", "executable": "/verified/bin/openagents"},
        },
    )
    calls = {}

    def spawn(argv, **kw):
        calls.update(argv=argv, env=kw["env"])
        return _FakeProc(calls)

    monkeypatch.setattr(run.subprocess, "Popen", spawn)
    run.start_vigil(repo=tmp_path / "repo", parallel=1, gitea=hosted, log_path=tmp_path / "d/v.log")
    assert calls["argv"][0] == "/verified/bin/openagents"
    assert calls["env"]["OPENAGENTS_NO_SELF_UPDATE"] == "1"


def test_bad_hosted_reader_cannot_start_vigil_or_write_config(tmp_path, monkeypatch):
    from ahe_beta.observations import preflight

    calls = _container_rig(monkeypatch, tmp_path)
    hosted, _ = _hosted_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(preflight, "probe_reader", lambda **kw: {"capabilities": {}})
    with pytest.raises(ValueError, match="capability"):
        run.start_vigil(
            repo=tmp_path / "repo", parallel=1, gitea=hosted, log_path=tmp_path / "d/v.log"
        )
    assert not any(a[:2] == ["docker", "run"] for a in calls["runs"])
    assert not (tmp_path / "staging/.openagents/openagents.yml").exists()


def test_hosted_reuse_probes_actual_container(tmp_path, monkeypatch):
    from ahe_beta.observations import preflight

    _container_rig(monkeypatch, tmp_path)
    hosted, _ = _hosted_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("AHE_BETA_RUN_ID", "our-run")
    monkeypatch.delenv("AHE_BETA_EXPERIMENT_ID", raising=False)
    monkeypatch.setattr(run, "_container_state", lambda **kw: (True, "our-run", ""))
    seen = []

    def probe(**kw):
        seen.append(kw)
        return {
            "capabilities": _reader_capabilities(),
            "runtime": {"image_id": "sha256:" + "d" * 64},
        }

    monkeypatch.setattr(preflight, "probe_reader", probe)
    run._prepare_vigil_evidence(gitea=hosted, mode="container")
    assert seen[0]["container"] == run._VIGIL_CONTAINER


def test_hosted_public_url_keeps_explicit_override(monkeypatch):
    monkeypatch.setenv("VIGIL_GITEA_INTERNAL_URL", "https://explicit.example")
    assert (
        run._vigil_gitea_url(gitea={**_GITEA, "GITEA_URL": "https://gitea.com"})
        == "https://explicit.example"
    )


def test_reused_container_prereqs_do_not_require_old_local_image_tag(tmp_path, monkeypatch):
    calls = _container_rig(monkeypatch, tmp_path)
    monkeypatch.setenv("AHE_BETA_RUN_ID", "our-run")
    monkeypatch.setattr(run, "_container_state", lambda **kw: (True, "our-run", ""))
    run._ensure_vigil_container_prereqs()
    assert not any(a[:3] == ["docker", "image", "inspect"] for a in calls["runs"])
