# Spec-0021/T2: run.py process-level git credential isolation unit test—multiple channel blocking, prevent dev escape and push to GitHub.
"""_isolate_git_credentials should: cut SSH, disable terminal prompts, clear askpass/ssh-agent silent channels, reset credential.helper. Legitimate Gitea HTTP (token in URL) workflow does not depend on these channels and is unaffected."""

from __future__ import annotations

import importlib

import pytest

run = importlib.import_module("ahe_beta.experiment.controllers.runtime")


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

    # Simulate VS Code + WSL injected silent credential channel
    monkeypatch.setenv("GIT_ASKPASS", "/vscode/askpass.sh")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/ssh-agent.sock")
    monkeypatch.setenv("VSCODE_GIT_ASKPASS_MAIN", "/vscode/main.js")

    run._isolate_git_credentials()

    for k in ("GIT_ASKPASS", "SSH_ASKPASS", "SSH_AUTH_SOCK", "VSCODE_GIT_ASKPASS_MAIN"):
        assert k not in os.environ  # Clear all silent channels


def test_resets_credential_helper(clean_git_env) -> None:
    import os

    run._isolate_git_credentials()
    n = int(os.environ["GIT_CONFIG_COUNT"])
    keys = {os.environ[f"GIT_CONFIG_KEY_{i}"] for i in range(n)}
    assert "credential.helper" in keys
    # Corresponding value as empty string = reset helper list (disable store/manager/keychain)
    idx = next(i for i in range(n) if os.environ[f"GIT_CONFIG_KEY_{i}"] == "credential.helper")
    assert os.environ[f"GIT_CONFIG_VALUE_{idx}"] == ""


def test_setdefault_preserves_operator_override(clean_git_env, monkeypatch) -> None:
    import os

    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /custom/key")  # Operations explicitly configured
    run._isolate_git_credentials()
    assert os.environ["GIT_SSH_COMMAND"] == "ssh -i /custom/key"  # setdefault does not override


def test_appends_to_existing_git_config_injection(clean_git_env, monkeypatch) -> None:
    import os

    # One GIT_CONFIG injection already present → append rather than replace
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")

    run._isolate_git_credentials()

    assert os.environ["GIT_CONFIG_COUNT"] == "2"
    assert os.environ["GIT_CONFIG_KEY_0"] == "core.autocrlf"  # Existing retained
    assert os.environ["GIT_CONFIG_KEY_1"] == "credential.helper"  # New additions at end
