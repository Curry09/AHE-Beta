from pathlib import Path

from scripts import replay_design_from_sessions as module


def test_wis_env_prefers_injected_designer_profile(monkeypatch) -> None:
    monkeypatch.setenv("DESIGNER_LLM_BASE_URL", "http://172.22.64.1:18080/v1")
    monkeypatch.setenv("DESIGNER_LLM_API_KEY", "injected-secret")

    assert module._wis_env() == {
        "wis_base_url": "http://172.22.64.1:18080/v1",
        "wis_api_key": "injected-secret",
    }


def test_gitea_env_path_prefers_isolated_experiment(monkeypatch, tmp_path: Path) -> None:
    isolated = tmp_path / "demand-gitea.env"
    monkeypatch.setenv("AUTO_DESIGNER_GITEA_ENV_FILE", str(isolated))

    assert module._gitea_env_path() == isolated


def test_no_proxy_includes_model_and_gitea_hosts_once() -> None:
    assert (
        module._no_proxy_value(
            "http://172.22.64.1:18080/v1",
            "http://127.0.0.1:32773",
            "http://172.22.64.1:18080/v1",
        )
        == "localhost,127.0.0.1,172.22.64.1"
    )
