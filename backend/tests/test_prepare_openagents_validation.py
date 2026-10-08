from __future__ import annotations

import pytest
from tools.dev.delivery.prepare_openagents_validation import validate_delivery_selection


def test_delivery_selection_preflight_rejects_unsafe_plan() -> None:
    snapshots = [{"number": 1}, {"number": 2}]
    validate_delivery_selection(
        source_repo="source", target_repo="target", snapshots=snapshots, selected={2}
    )
    with pytest.raises(SystemExit, match="must differ"):
        validate_delivery_selection(
            source_repo="same", target_repo="same", snapshots=snapshots, selected={1}
        )
    with pytest.raises(SystemExit, match="do not exist"):
        validate_delivery_selection(
            source_repo="source", target_repo="target", snapshots=snapshots, selected={3}
        )


def test_copy_git_authenticates_by_environment_and_retains_cleanup(tmp_path, monkeypatch):
    import base64
    import subprocess
    from pathlib import Path

    from tools.dev import delivery
    from tools.dev.delivery import prepare_openagents_validation as module

    token = "private-token-value"
    gitea = {
        "GITEA_URL": "https://selected.example/gitea",
        "OWNER": "selected-owner",
        "TOKEN": token,
    }
    calls = []

    def git(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs["capture_output"] is True
        assert token not in " ".join(command)
        assert (
            kwargs["env"]["GIT_CONFIG_KEY_1"] == "http.https://selected.example/gitea/.extraHeader"
        )
        header = kwargs["env"]["GIT_CONFIG_VALUE_1"]
        assert (
            base64.b64decode(header.removeprefix("Authorization: Basic ")).decode()
            == f"selected-owner:{token}"
        )
        if command[1] == "clone":
            checkout = Path(command[-1])
            checkout.mkdir()
            (checkout / "generated.pyc").write_bytes(b"bytecode")
        if "ls-files" in command:
            stdout = b"generated.pyc\0"
        elif "rev-parse" in command:
            checkout = Path(command[command.index("-C") + 1])
            assert not (checkout / "generated.pyc").exists()
            assert "__pycache__/" in (checkout / ".gitignore").read_text()
            stdout = "final-main-sha\n"
        else:
            stdout = b""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(delivery.subprocess, "run", git)
    assert module._copy_git(gitea=gitea, source="source", target="target") == "final-main-sha"
    assert calls[0][0][4] == "https://selected.example/gitea/selected-owner/source.git"
    remotes = [command[-1] for command, _ in calls if "set-url" in command]
    assert remotes == ["https://selected.example/gitea/selected-owner/target.git"]
    assert any("push" in command for command, _ in calls)


def test_copy_git_failure_with_sensitive_output_has_no_secret_diagnostics(monkeypatch, capsys):
    import base64
    import subprocess

    from tools.dev import delivery
    from tools.dev.delivery import prepare_openagents_validation as module

    token = "private-token-value"
    encoded = base64.b64encode(f"selected-owner:{token}".encode()).decode()
    gitea = {"GITEA_URL": "https://selected.example", "OWNER": "selected-owner", "TOKEN": token}

    def reject(command, **kwargs):
        assert token not in " ".join(command)
        return subprocess.CompletedProcess(
            command, 128, stdout=token.encode(), stderr=encoded.encode()
        )

    monkeypatch.setattr(delivery.subprocess, "run", reject)
    with pytest.raises(SystemExit, match="exit 128") as error:
        module._copy_git(gitea=gitea, source="source", target="target")
    captured = capsys.readouterr()
    rendered = str(error.value) + captured.out + captured.err
    assert token not in rendered
    assert encoded not in rendered


def test_git_transport_rejects_embedded_url_credentials():
    from tools.dev.delivery import git_remote_url

    with pytest.raises(SystemExit, match="without embedded credentials"):
        git_remote_url({"GITEA_URL": "https://owner:token@example.com", "OWNER": "owner"}, "repo")


def test_git_auth_configuration_applies_only_to_selected_provider_url():
    import subprocess

    from tools.dev.delivery import git_environment

    env = git_environment(
        {"GITEA_URL": "https://selected.example/gitea", "OWNER": "owner", "TOKEN": "fake-token"}
    )
    selected = subprocess.run(
        [
            "git",
            "config",
            "--get-urlmatch",
            "http.extraHeader",
            "https://selected.example/gitea/owner/repo.git",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    other = subprocess.run(
        [
            "git",
            "config",
            "--get-urlmatch",
            "http.extraHeader",
            "https://other.example/owner/repo.git",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert selected.returncode == 0
    assert selected.stdout.startswith("Authorization: Basic ")
    assert other.returncode == 1 and not other.stdout
