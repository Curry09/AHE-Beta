import json
import os
from pathlib import Path

import pytest
from tools.dev import harness_environment, role_environment, run_inputs
from tools.dev.replay import replay_roles_from_sessions as module


@pytest.fixture(autouse=True)
def isolate_role_profiles(monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    os.environ.pop("AUTO_DESIGNER_DEV_RUN_PROFILE", None)


def prepared_run(tmp_path: Path, *, backend: str = "e2b") -> Path:
    root = tmp_path / "selected-run"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "secrets_file": str(tmp_path / "outside.env"),
                "config": {
                    "runtime": {"backend": backend},
                    "models": {
                        "demand": {
                            "model": "selected-model",
                            "base_url_env": "CUSTOM_BASE",
                            "api_key_env": "CUSTOM_KEY",
                        },
                    },
                },
            }
        )
    )
    (root / "resources.json").write_text(
        json.dumps(
            {
                "gitea": {
                    "url": "https://gitea.com",
                    "owner": "selected-owner",
                    "repo": "selected-repo",
                },
                "vigil": {
                    "network": "selected-network",
                    "image": "selected-image",
                    "container": "controller-delivery",
                },
            }
        )
    )
    (tmp_path / "outside.env").write_text("GITEA_TOKEN=outside-secret\n")
    return root


def test_run_provider_identity_never_comes_from_developer_defaults(tmp_path, monkeypatch):
    root = prepared_run(tmp_path)
    monkeypatch.setenv("GITEA_URL", "http://developer.local")
    monkeypatch.setenv("GITEA_USER", "developer")
    monkeypatch.setenv("GITEA_TOKEN", "injected-token")
    _, _, provider = run_inputs(root)
    assert provider == {
        "GITEA_URL": "https://gitea.com",
        "OWNER": "selected-owner",
        "REPO": "selected-repo",
        "TOKEN": "injected-token",
    }


def test_explicit_run_does_not_discover_external_secrets(tmp_path, monkeypatch):
    root = prepared_run(tmp_path)
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="incomplete Gitea"):
        run_inputs(root)


def test_explicit_profile_maps_frozen_model_keys(tmp_path, monkeypatch):
    root = prepared_run(tmp_path)
    profile = tmp_path / "chosen.env"
    profile.write_text(
        "GITEA_TOKEN=chosen-token\nCUSTOM_BASE=https://model.example/v1\nCUSTOM_KEY=chosen-key\n"
    )
    monkeypatch.delenv("DEMAND_LLM_MODEL", raising=False)
    monkeypatch.delenv("DEMAND_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DEMAND_LLM_API_KEY", raising=False)
    _, _, provider = run_inputs(root, profile)
    assert provider["TOKEN"] == "chosen-token"
    assert os.environ["DEMAND_LLM_MODEL"] == "selected-model"
    assert os.environ["DEMAND_LLM_BASE_URL"] == "https://model.example/v1"
    assert os.environ["DEMAND_LLM_API_KEY"] == "chosen-key"


def test_legacy_run_rejected_before_remote_actions(tmp_path):
    root = tmp_path / "old-run"
    root.mkdir()
    (root / "manifest.json").write_text('{"schema_version": 1}')
    with pytest.raises(SystemExit, match="schema_version=2"):
        run_inputs(root)


def test_no_proxy_includes_model_and_gitea_hosts_once():
    assert (
        module._no_proxy_value(
            "http://172.22.64.1:18080/v1", "http://127.0.0.1:32773", "http://172.22.64.1:18080/v1"
        )
        == "localhost,127.0.0.1,172.22.64.1"
    )


@pytest.mark.parametrize("missing", ["CUSTOM_BASE", "CUSTOM_KEY", "both"])
def test_selected_run_clears_host_role_and_does_not_fall_back_to_common_profile(
    tmp_path, monkeypatch, missing
):
    root = prepared_run(tmp_path)
    for prefix in ("DEMAND_LLM", "USER_LLM", "HARNESS_LLM", "LLM"):
        for suffix in ("MODEL", "BASE_URL", "API_KEY"):
            monkeypatch.setenv(f"{prefix}_{suffix}", f"host-{suffix.lower()}")
    profile = tmp_path / "chosen.env"
    lines = ["GITEA_TOKEN=chosen-token"]
    if missing not in {"CUSTOM_BASE", "both"}:
        lines.append("CUSTOM_BASE=https://selected.example/v1")
    if missing not in {"CUSTOM_KEY", "both"}:
        lines.append("CUSTOM_KEY=selected-key")
    profile.write_text("\n".join(lines) + "\n")
    for key in ("CUSTOM_BASE", "CUSTOM_KEY"):
        monkeypatch.delenv(key, raising=False)
    run_inputs(root, profile)
    assert os.environ["DEMAND_LLM_MODEL"] == "selected-model"
    absent = "BASE_URL" if missing in {"CUSTOM_BASE", "both"} else "API_KEY"
    assert f"DEMAND_LLM_{absent}" not in os.environ
    assert "USER_LLM_API_KEY" not in os.environ
    assert "HARNESS_LLM_API_KEY" not in os.environ
    with pytest.raises(SystemExit, match=f"DEMAND_LLM_{absent}"):
        role_environment("DEMAND")


def test_harness_profile_never_populates_another_role(monkeypatch):
    for suffix in ("MODEL", "BASE_URL", "API_KEY"):
        monkeypatch.setenv(f"HARNESS_LLM_{suffix}", f"harness-{suffix.lower()}")
        monkeypatch.delenv(f"USER_LLM_{suffix}", raising=False)
        monkeypatch.delenv(f"LLM_{suffix}", raising=False)
    role_environment("HARNESS")
    assert "LLM_API_KEY" not in os.environ
    with pytest.raises(SystemExit, match="USER_LLM_MODEL"):
        role_environment("USER")
    with harness_environment():
        assert os.environ["LLM_API_KEY"] == "harness-api_key"
    assert "LLM_API_KEY" not in os.environ


def test_harness_child_scope_restores_common_profile_on_failure(monkeypatch):
    for suffix in ("MODEL", "BASE_URL", "API_KEY"):
        monkeypatch.setenv(f"HARNESS_LLM_{suffix}", f"harness-{suffix.lower()}")
        monkeypatch.setenv(f"LLM_{suffix}", f"common-{suffix.lower()}")
    with pytest.raises(RuntimeError, match="spawn failed"), harness_environment():
        assert os.environ["LLM_API_KEY"] == "harness-api_key"
        raise RuntimeError("spawn failed")
    assert os.environ["LLM_API_KEY"] == "common-api_key"
    role_environment("USER")
    assert os.environ["USER_LLM_API_KEY"] == "common-api_key"


def probe_input_args(tmp_path: Path, name: str) -> list[str]:
    if name != "probe_swebench_persona":
        return []
    import pyarrow as pa
    import pyarrow.parquet as pq

    dataset = tmp_path / "fixture.parquet"
    pq.write_table(
        pa.table(
            {
                "instance_id": ["test__task-1"],
                "repo": ["test/task"],
                "base_commit": ["a" * 40],
                "problem_statement": ["Inspect local task inputs"],
                "difficulty": ["easy"],
            }
        ),
        dataset,
    )
    harness = tmp_path / "harness"
    harness.mkdir()
    (harness / "entry.py").write_text("pass\n")
    return ["--dataset", str(dataset), "--harness-repo", str(harness), "--instance", "test__task-1"]


@pytest.mark.parametrize(
    "name", ["probe_persona_wait_matrix", "probe_peek_decision_trace", "probe_swebench_persona"]
)
def test_probe_preflight_reads_current_library_and_never_loads_credentials(
    tmp_path, monkeypatch, capsys, name
):
    import importlib
    import sys

    from tools.dev.probes import DEFAULT_PERSONA_LIBRARY

    probe = importlib.import_module(f"tools.dev.probes.{name}")
    monkeypatch.setattr(
        probe, "load_secrets", lambda *_: pytest.fail("offline preflight read credentials")
    )
    monkeypatch.setattr(
        probe, "role_environment", lambda *_: pytest.fail("offline preflight selected a model")
    )
    monkeypatch.setattr(sys, "argv", [name, "--check-inputs", *probe_input_args(tmp_path, name)])
    assert probe.main() in (0, None)
    report = json.loads(capsys.readouterr().out)
    assert Path(report["persona_library"]) == DEFAULT_PERSONA_LIBRARY
    assert report["status"] == "inputs-valid"
    assert report["personas"]
    assert all(persona.startswith("sr-") for persona in report["personas"])


@pytest.mark.parametrize(
    "name", ["probe_persona_wait_matrix", "probe_peek_decision_trace", "probe_swebench_persona"]
)
def test_probe_missing_library_fails_before_credentials_or_models(tmp_path, monkeypatch, name):
    import importlib
    import sys

    probe = importlib.import_module(f"tools.dev.probes.{name}")
    monkeypatch.setattr(
        probe, "load_secrets", lambda *_: pytest.fail("missing file reached credentials")
    )
    monkeypatch.setattr(
        probe, "role_environment", lambda *_: pytest.fail("missing file reached model")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            name,
            "--check-inputs",
            "--persona-library",
            str(tmp_path / "missing.json"),
            *probe_input_args(tmp_path, name),
        ],
    )
    with pytest.raises(SystemExit, match="Persona library does not exist"):
        probe.main()


@pytest.mark.parametrize(
    "name", ["probe_persona_wait_matrix", "probe_peek_decision_trace", "probe_swebench_persona"]
)
def test_probe_preflight_honors_explicit_persona_library(tmp_path, monkeypatch, capsys, name):
    import importlib
    import sys

    from tools.dev.probes import DEFAULT_PERSONA_LIBRARY

    card = json.loads(DEFAULT_PERSONA_LIBRARY.read_text())[0]
    card["id"] = "custom-selected-persona"
    library = tmp_path / "chosen-library.json"
    library.write_text(json.dumps([card]))
    probe = importlib.import_module(f"tools.dev.probes.{name}")
    monkeypatch.setattr(
        probe, "load_secrets", lambda *_: pytest.fail("offline preflight read credentials")
    )
    monkeypatch.setattr(
        probe, "role_environment", lambda *_: pytest.fail("offline preflight selected a model")
    )
    selection = "--personas" if name == "probe_persona_wait_matrix" else "--persona"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            name,
            "--check-inputs",
            "--persona-library",
            str(library),
            selection,
            "custom-selected-persona",
            *probe_input_args(tmp_path, name),
        ],
    )
    assert probe.main() in (0, None)
    report = json.loads(capsys.readouterr().out)
    assert report["personas"] == ["custom-selected-persona"]
    assert report["persona_library"] == str(library)


def test_probe_preflight_rejects_nonexistent_persona_before_credentials(tmp_path, monkeypatch):
    import sys

    from tools.dev.probes import probe_peek_decision_trace as probe

    monkeypatch.setattr(
        probe, "load_secrets", lambda *_: pytest.fail("invalid persona reached credentials")
    )
    monkeypatch.setattr(sys, "argv", ["probe", "--check-inputs", "--persona", "missing-persona"])
    with pytest.raises(SystemExit, match="Persona ids not found"):
        probe.main()
