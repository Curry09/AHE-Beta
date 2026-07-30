# Spec-0032/T5 + 0033/T2：vigil 接线单测——配置落盘、双模式预检与启停（mock docker/Popen，不触真容器）。
"""验证 run.py 的交付面接线：openagents.yml 内容与 stages 定稿一致、token 不落盘、
VIGIL_MODE 双模式（container 缺省围堵盒 / subprocess 显式联调）各自的预检、启停与 env 注入。"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest
from ruamel.yaml import YAML

run = importlib.import_module("run")

_GITEA = {
    "GITEA_URL": "http://localhost:3000",
    "OWNER": "harness",
    "REPO": "harness",
    "TOKEN": "secret-token",
}


def _load_yaml(path: Path):
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------------
# 声明式配置落盘（两模式共用 write_openagents_config）。
# --------------------------------------------------------------------------------------------------


def test_write_openagents_config_matches_stage_finalization(tmp_path: Path) -> None:
    path = run.write_openagents_config(repo=tmp_path, gitea=_GITEA)
    assert path == tmp_path / ".openagents" / "openagents.yml"
    data = _load_yaml(path)
    assert data["forge"] == "gitea"
    assert data["gitea"] == {
        "base_url": "http://localhost:3000",
        "owner": "harness",
        "repo": "harness",
        "token_env": "GITEA_TOKEN",
    }
    # stages 定稿（Spec-0032 §4.4）：triage/rfc/ci/e2e=skip、conflict/review/merge=agent。
    assert data["stages"] == {
        "triage": "skip",
        "rfc": "skip",
        "conflict": "agent",
        "ci": "skip",
        "e2e": "skip",
        "review": "agent",
        "merge": "agent",
    }
    assert data["release"] == "manual"
    assert data["defaults"]["labels"] == ["openagents"]  # Owner 交接令牌 = vigil 发现标签
    assert data["defaults"]["base"] == "main"
    # token 本体绝不落盘（只声明 env 名，由 vigil 进程/容器 env 提供）。
    assert "secret-token" not in path.read_text(encoding="utf-8")


def test_ci_stage_env_override(tmp_path: Path, monkeypatch) -> None:
    # Spec-0032/T6：act_runner 验证在跑后，VIGIL_CI_STAGE=agent 开启 ci 闸；非法值忽略回落 skip。
    monkeypatch.setenv("VIGIL_CI_STAGE", "agent")
    data = _load_yaml(run.write_openagents_config(repo=tmp_path, gitea=_GITEA))
    assert data["stages"]["ci"] == "agent"
    monkeypatch.setenv("VIGIL_CI_STAGE", "banana")
    data = _load_yaml(run.write_openagents_config(repo=tmp_path, gitea=_GITEA))
    assert data["stages"]["ci"] == "skip"


def test_write_openagents_config_is_idempotent(tmp_path: Path) -> None:
    first = run.write_openagents_config(repo=tmp_path, gitea=_GITEA).read_text(encoding="utf-8")
    second = run.write_openagents_config(repo=tmp_path, gitea=_GITEA).read_text(encoding="utf-8")
    assert first == second


def test_remote_tag_refs_skips_peeled_entries() -> None:
    # 实证修复：附注 tag 的 peeled 行（^{}）不是真 ref，push 删除会以 128 崩掉复位流程。
    ls = "aaa\trefs/tags/v1\nbbb\trefs/tags/v1^{}\nccc\trefs/tags/v2\nddd\trefs/heads/main\n"
    assert run._remote_tag_refs(ls) == ["refs/tags/v1", "refs/tags/v2"]
    assert run._remote_tag_refs("") == []


# --------------------------------------------------------------------------------------------------
# 模式解析与预检。
# --------------------------------------------------------------------------------------------------


def test_vigil_mode_defaults_to_container(monkeypatch) -> None:
    monkeypatch.delenv("VIGIL_MODE", raising=False)
    assert run.vigil_mode() == "container"  # 围堵形态是缺省（Spec-0033）


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
    with pytest.raises(SystemExit, match="claude 凭证"):
        run._ensure_vigil_container_prereqs()
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "long-lived")  # 订阅 token 也算
    run._ensure_vigil_container_prereqs()  # 不抛
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "bearer-x")  # 网关 Bearer 也算（三选一）
    run._ensure_vigil_container_prereqs()  # 不抛


# --------------------------------------------------------------------------------------------------
# container 模式：docker run 参数形状 / 内网配置 / 启停。
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
    """container 模式打桩：docker 预检放行、subprocess.run/Popen 记录、staging 重定向 tmp。"""
    calls: dict = {"runs": []}
    monkeypatch.setenv("VIGIL_MODE", "container")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
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
        repo=tmp_path / "unused-host-repo",  # container 模式不碰宿主仓（零挂载自 clone）
        parallel=2,
        gitea=_GITEA,
        log_path=tmp_path / "data" / "vigil.log",
    )
    docker_run = next(argv for argv in calls["runs"] if argv[:2] == ["docker", "run"])
    joined = " ".join(docker_run)
    assert handle.mode == "container"
    assert f"--network {run._VIGIL_NETWORK}" in joined  # internal 网络（直连外网物理不通）
    assert "/config:ro" in joined and "/entrypoint.sh:ro" in joined  # 仅两处只读挂载
    assert "GITEA_TOKEN=secret-token" in joined  # 凭证只经容器 env
    assert "ANTHROPIC_API_KEY=sk-test" in joined
    assert f"HTTPS_PROXY={run._VIGIL_PROXY_URL}" in joined  # 出网只走 egress 代理
    assert "VIGIL_PARALLEL=2" in joined
    # clone 地址是容器内网视角（服务名），带凭证、不落任何宿主盘文件。
    assert "VIGIL_REPO_URL=http://harness:secret-token@gitea:3000/harness/harness.git" in joined
    assert calls["popen"][:3] == ["docker", "logs", "-f"]  # 日志跟随器
    # 宿主仓不被写入（零挂载：配置只进 staging）。
    assert not (tmp_path / "unused-host-repo" / ".openagents").exists()


def test_container_config_uses_internal_gitea_url(tmp_path: Path, monkeypatch) -> None:
    _container_rig(monkeypatch, tmp_path)
    run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    data = _load_yaml(tmp_path / "staging" / ".openagents" / "openagents.yml")
    assert data["gitea"]["base_url"] == "http://gitea:3000"  # 容器视角，非宿主 localhost


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
    handle = run.start_vigil(
        repo=tmp_path / "r", parallel=1, gitea=_GITEA, log_path=tmp_path / "d" / "v.log"
    )
    run.stop_vigil(handle)
    assert ["docker", "rm", "-f", run._VIGIL_CONTAINER] in calls["runs"]
    assert calls.get("terminated") and calls.get("waited")


# --------------------------------------------------------------------------------------------------
# subprocess 模式（显式 opt-in 联调）：既有行为保留。
# --------------------------------------------------------------------------------------------------


def test_subprocess_start_spawns_with_token_env_and_cwd(tmp_path: Path, monkeypatch) -> None:
    calls: dict = {}
    monkeypatch.setenv("VIGIL_MODE", "subprocess")
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
    assert calls["env"]["GITEA_TOKEN"] == "secret-token"  # token 只经子进程 env，不落配置
    assert (repo / ".openagents" / "openagents.yml").is_file()  # 联调模式配置写进宿主仓（既有行为）

    run.stop_vigil(handle)
    assert calls.get("terminated") and calls.get("waited")


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

    run.stop_vigil(run.VigilHandle(mode="subprocess", proc=_Stuck(), log_handle=_Log()))
    assert events == ["terminate", "wait-timeout", "killed", "wait-after-kill", "log-closed"]
