# Spec-0021/T2：run.py 进程级 git 凭证隔离单测——多信道封堵，防 dev 逃逸后推到 GitHub。
"""_isolate_git_credentials 应：掐 ssh、禁终端提示、清 askpass/ssh-agent 静默信道、
重置 credential.helper。合法 Gitea HTTP（token in URL）流程不依赖这些信道，不受影响。"""

from __future__ import annotations

import importlib

import pytest

run = importlib.import_module("auto_designer.experiment.controllers.ordinary")


@pytest.fixture
def clean_git_env(monkeypatch):
    for k in (
        "GIT_SSH_COMMAND",
        "GIT_TERMINAL_PROMPT",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "SSH_AUTH_SOCK",
        "VSCODE_GIT_ASKPASS_NODE",
        "VSCODE_GIT_ASKPASS_MAIN",
        "VSCODE_GIT_ASKPASS_EXTRA_ARGS",
        "VSCODE_GIT_IPC_HANDLE",
        "GIT_CONFIG_COUNT",
    ):
        monkeypatch.delenv(k, raising=False)


def test_blocks_ssh_and_terminal_prompt(clean_git_env) -> None:
    run._isolate_git_credentials()
    import os

    assert os.environ["GIT_SSH_COMMAND"] == "false"
    assert os.environ["GIT_TERMINAL_PROMPT"] == "0"


def test_clears_askpass_channels(clean_git_env, monkeypatch) -> None:
    import os

    # 模拟 VS Code + WSL 注入的静默凭证信道
    monkeypatch.setenv("GIT_ASKPASS", "/vscode/askpass.sh")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/ssh-agent.sock")
    monkeypatch.setenv("VSCODE_GIT_ASKPASS_MAIN", "/vscode/main.js")

    run._isolate_git_credentials()

    for k in ("GIT_ASKPASS", "SSH_ASKPASS", "SSH_AUTH_SOCK", "VSCODE_GIT_ASKPASS_MAIN"):
        assert k not in os.environ  # 静默信道全清


def test_resets_credential_helper(clean_git_env) -> None:
    import os

    run._isolate_git_credentials()
    n = int(os.environ["GIT_CONFIG_COUNT"])
    keys = {os.environ[f"GIT_CONFIG_KEY_{i}"] for i in range(n)}
    assert "credential.helper" in keys
    # 对应 value 为空串 = 重置 helper 列表（禁用 store/manager/keychain）
    idx = next(i for i in range(n) if os.environ[f"GIT_CONFIG_KEY_{i}"] == "credential.helper")
    assert os.environ[f"GIT_CONFIG_VALUE_{idx}"] == ""


def test_setdefault_preserves_operator_override(clean_git_env, monkeypatch) -> None:
    import os

    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /custom/key")  # 运维显式配置
    run._isolate_git_credentials()
    assert os.environ["GIT_SSH_COMMAND"] == "ssh -i /custom/key"  # setdefault 不覆盖


def test_appends_to_existing_git_config_injection(clean_git_env, monkeypatch) -> None:
    import os

    # 已有一条 GIT_CONFIG 注入 → 追加而非覆盖
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")

    run._isolate_git_credentials()

    assert os.environ["GIT_CONFIG_COUNT"] == "2"
    assert os.environ["GIT_CONFIG_KEY_0"] == "core.autocrlf"  # 既有保留
    assert os.environ["GIT_CONFIG_KEY_1"] == "credential.helper"  # 新增在末尾
