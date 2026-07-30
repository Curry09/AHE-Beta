# Spec-0032/T5：vigil 接线单测——声明式配置落盘、CLI 预检、子进程启停（mock Popen，不触真 vigil）。
"""验证 run.py 的交付面接线：openagents.yml 内容与 stages 定稿一致、token 不落盘、
start/stop 生命周期与 env 传递正确、CLI 缺失 fail-loud。"""

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


def test_write_openagents_config_matches_stage_finalization(tmp_path: Path) -> None:
    path = run.write_openagents_config(repo=tmp_path, gitea=_GITEA)
    assert path == tmp_path / ".openagents" / "openagents.yml"
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
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
    # token 本体绝不落盘（只声明 env 名，由 vigil 子进程 env 提供）。
    assert "secret-token" not in path.read_text(encoding="utf-8")


def test_write_openagents_config_is_idempotent(tmp_path: Path) -> None:
    first = run.write_openagents_config(repo=tmp_path, gitea=_GITEA).read_text(encoding="utf-8")
    second = run.write_openagents_config(repo=tmp_path, gitea=_GITEA).read_text(encoding="utf-8")
    assert first == second


def test_ensure_openagents_cli_missing_fails_loud(monkeypatch) -> None:
    monkeypatch.setattr(run.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="openagents"):
        run.ensure_openagents_cli()


def test_ensure_openagents_cli_present_is_noop(monkeypatch) -> None:
    monkeypatch.setattr(run.shutil, "which", lambda name: "/usr/bin/openagents")
    run.ensure_openagents_cli()  # 不抛


def test_start_vigil_spawns_with_token_env_and_cwd(tmp_path: Path, monkeypatch) -> None:
    calls = {}

    class _FakeProc:
        def terminate(self):
            calls["terminated"] = True

        def wait(self, timeout=None):
            calls["waited"] = True

        def kill(self):
            calls["killed"] = True

    def _fake_popen(argv, *, cwd, env, stdout, stderr):
        calls.update(argv=argv, cwd=cwd, env=env)
        return _FakeProc()

    monkeypatch.setattr(run.subprocess, "Popen", _fake_popen)
    proc, log = run.start_vigil(
        repo=tmp_path, parallel=3, gitea_token="tkn", log_path=tmp_path / "data" / "vigil.log"
    )
    assert calls["argv"] == ["openagents", "vigil", "--parallel", "3"]
    assert calls["cwd"] == str(tmp_path)
    assert calls["env"]["GITEA_TOKEN"] == "tkn"  # token 只经子进程 env，不落配置
    assert (tmp_path / "data").is_dir()  # 日志目录已备好

    run.stop_vigil(proc, log)
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

    run.stop_vigil(_Stuck(), _Log())
    assert events == ["terminate", "wait-timeout", "killed", "wait-after-kill", "log-closed"]
