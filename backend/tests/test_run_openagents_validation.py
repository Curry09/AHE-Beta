import json
import sys

import pytest
from tools.dev.delivery import run_openagents_validation as module


def test_gateway_uses_standard_anthropic_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    profile = tmp_path / "chosen.env"
    profile.write_text(
        'ANTHROPIC_BASE_URL = "https://gateway.example/api"\nANTHROPIC_API_KEY = secret\n'
    )
    values = module.gateway_environment(profile, "selected-model")
    assert values["ANTHROPIC_BASE_URL"] == "https://gateway.example/api"
    assert values["ANTHROPIC_API_KEY"] == "secret"
    assert "ANTHROPIC_AUTH_TOKEN" not in values
    assert values["ANTHROPIC_MODEL"] == "selected-model"


def test_gateway_uses_run_specific_bearer_key(tmp_path):
    profile = tmp_path / "chosen.env"
    profile.write_text("DELIVERY_BASE=https://gateway.example/api\nDELIVERY_KEY=secret\n")
    values = module.gateway_environment(
        profile,
        "selected-model",
        settings={"base_url_env": "DELIVERY_BASE", "api_key_env": "DELIVERY_KEY"},
    )
    assert values["ANTHROPIC_BASE_URL"] == "https://gateway.example/api"
    assert values["ANTHROPIC_AUTH_TOKEN"] == "secret"
    assert "ANTHROPIC_API_KEY" not in values


def test_gateway_fails_without_explicit_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    profile = tmp_path / "chosen.env"
    profile.write_text("ANTHROPIC_BASE_URL=https://gateway.example/api\n")
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        module.gateway_environment(profile, "selected-model")


def configure(tmp_path, monkeypatch, *, container="validation-one"):
    config = tmp_path / "config"
    config.mkdir()
    (config / "openagents.yml").write_text("forge: gitea\nexecution_evidence:\n  required: true\n")
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "config": {
                    "models": {
                        "delivery": {
                            "model": "selected-model",
                            "base_url_env": "DELIVERY_BASE",
                            "api_key_env": "DELIVERY_KEY",
                        }
                    }
                },
            }
        )
    )
    (run / "resources.json").write_text(
        json.dumps(
            {
                "gitea": {
                    "url": "http://127.0.0.1:41234",
                    "internal_url": "http://selected-gitea:3000",
                    "owner": "owner",
                    "repo": "source",
                },
                "vigil": {
                    "image": "selected-image:pin",
                    "network": "selected-network",
                    "container": "controller-delivery",
                },
            }
        )
    )
    profile = tmp_path / "chosen.env"
    profile.write_text(
        "GITEA_TOKEN=gitea-secret-value\nDELIVERY_BASE=https://gateway.example/api\nDELIVERY_KEY=gateway-secret-value\n"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--run-dir",
            str(run),
            "--secrets-file",
            str(profile),
            "--repo",
            "target",
            "--config-dir",
            str(config),
            "--container",
            container,
            "--parallel",
            "2",
        ],
    )
    calls = []
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda *a, **kw: json.dumps(
            {
                "execution_evidence": {
                    "schema_versions": [1],
                    "required_dispatch": True,
                    "context_projection": "all-delivery-roles-v1",
                }
            }
        ),
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))
    )
    return config, calls


def test_main_isolates_run_provider_and_passes_credentials_only_by_environment(
    tmp_path, monkeypatch
):
    config, calls = configure(tmp_path, monkeypatch)
    assert module.main() == 0
    command, kwargs = calls[0]
    rendered = " ".join(command)
    assert "gateway-secret-value" not in rendered
    assert "gitea-secret-value" not in rendered
    assert command[command.index("--network") + 1] == "selected-network"
    assert "selected-image:pin" in command
    assert f"{config.resolve()}:/config:ro" in command
    assert kwargs["env"]["ANTHROPIC_AUTH_TOKEN"] == "gateway-secret-value"
    assert kwargs["env"]["GITEA_TOKEN"] == "gitea-secret-value"
    assert kwargs["env"]["VIGIL_REPO_URL"] == "http://selected-gitea:3000/owner/target.git"
    assert kwargs["env"]["VIGIL_PARALLEL"] == "2"


def test_main_refuses_controller_container(tmp_path, monkeypatch):
    _, calls = configure(tmp_path, monkeypatch, container="controller-delivery")
    with pytest.raises(SystemExit, match="must differ"):
        module.main()
    assert calls == []


def test_validation_refuses_downgraded_required_dispatch(tmp_path, monkeypatch):
    config, calls = configure(tmp_path, monkeypatch)
    (config / "openagents.yml").write_text("forge: gitea\n")
    with pytest.raises(SystemExit, match="required: true"):
        module.main()
    assert calls == []


def test_gateway_does_not_fall_back_to_unrelated_host_auth_for_run_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "unrelated-host-token")
    profile = tmp_path / "chosen.env"
    profile.write_text("DELIVERY_BASE=https://gateway.example/api\n")
    with pytest.raises(SystemExit, match="DELIVERY_KEY"):
        module.gateway_environment(
            profile,
            "selected-model",
            settings={"base_url_env": "DELIVERY_BASE", "api_key_env": "DELIVERY_KEY"},
        )
