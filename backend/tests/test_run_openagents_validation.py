import sys
from pathlib import Path

import pytest

from scripts import run_openagents_validation as module

gateway_environment = module.gateway_environment


def test_gateway_environment_accepts_spaced_assignments(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('wis_base_url = "https://gateway.example/api/v1"\nwis_api_key = secret\n')
    assert gateway_environment(env_file, "z-ai/glm-5.2") == {
        "ANTHROPIC_BASE_URL": "https://gateway.example/api",
        "ANTHROPIC_AUTH_TOKEN": "secret",
        "ANTHROPIC_MODEL": "z-ai/glm-5.2",
        "ANTHROPIC_SMALL_FAST_MODEL": "z-ai/glm-5.2",
    }


def test_gateway_environment_preserves_anthropic_base_without_v1(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("wis_base_url=https://gateway.example/api\nwis_api_key=secret\n")
    assert gateway_environment(env_file, "model")["ANTHROPIC_BASE_URL"] == (
        "https://gateway.example/api"
    )


def test_gateway_environment_fails_before_start_when_incomplete(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("wis_base_url = https://gateway.example/api\n")
    with pytest.raises(SystemExit, match="wis_api_key"):
        gateway_environment(env_file, "model")


def test_main_passes_credentials_only_through_environment(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "openagents.yml").write_text("forge: gitea\n", encoding="utf-8")
    gateway_file = tmp_path / "gateway.env"
    gateway_file.touch()
    secret = "gateway-secret-value"

    def load_env(path: Path) -> dict[str, str]:
        if path == gateway_file:
            return {"wis_base_url": "https://gateway.example/api/v1", "wis_api_key": secret}
        return {
            "GITEA_URL": "http://localhost:3000",
            "OWNER": "owner",
            "REPO": "source",
            "TOKEN": "gitea-secret-value",
        }

    calls = []
    monkeypatch.setattr(module.run_mod, "_load_env", load_env)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--repo",
            "target",
            "--config-dir",
            str(config),
            "--container",
            "validation-one",
            "--gateway-env",
            str(gateway_file),
            "--model",
            "model-a",
            "--parallel",
            "2",
        ],
    )

    assert module.main() == 0
    command, kwargs = calls[0]
    rendered = " ".join(command)
    assert secret not in rendered and "gitea-secret-value" not in rendered
    assert ["-e", "ANTHROPIC_AUTH_TOKEN"] == command[
        command.index("ANTHROPIC_AUTH_TOKEN") - 1 : command.index("ANTHROPIC_AUTH_TOKEN") + 1
    ]
    assert f"{config.resolve()}:/config:ro" in command
    assert "HTTPS_PROXY=http://egress-proxy:3128" in command
    assert "https_proxy=http://egress-proxy:3128" in command
    assert kwargs["env"]["ANTHROPIC_AUTH_TOKEN"] == secret
    assert kwargs["env"]["GITEA_TOKEN"] == "gitea-secret-value"
    assert kwargs["check"] is True
