# Spec-0047/T2：ExperimentConfig fail-closed 单测。
from __future__ import annotations

from pathlib import Path

import pytest

from auto_designer.experiment.config import (
    ConfigError,
    ExperimentConfig,
    compose_project,
    config_hash,
    ensure_under_root,
    experiment_paths,
    experiments_root,
    validate_experiment_id,
)


def _cfg(**overrides: object) -> dict:
    data: dict = {
        "schema_version": 1,
        "experiment_id": "glm-evolution-e0",
        "mode": "full-evolution",
        "source": {"auto_designer_sha": "abc123"},
        "images": {"vigil": "sha256:deadbeef"},
        "models": {"profile": "glm-local"},
        "capacity": {"endpoint": "glm-local", "user_parallel": 2},
        "infrastructure": {"isolation": "dedicated"},
        "retention": {"keep_on_stop": True},
    }
    data.update(overrides)
    return data


def test_valid_id_and_hash_suffix() -> None:
    cfg = ExperimentConfig.from_mapping(_cfg())
    digest = config_hash(data=_cfg())
    project = compose_project(experiment_id=cfg.experiment_id, cfg_hash=digest)
    assert project.startswith("adx-glm-evolution-e0-")
    assert project.split("-")[-1] == digest[:8]


def test_invalid_ids_fail_closed() -> None:
    with pytest.raises(ConfigError):
        validate_experiment_id(raw="UPPER")
    with pytest.raises(ConfigError):
        validate_experiment_id(raw="has_underscore")
    with pytest.raises(ConfigError):
        validate_experiment_id(raw="a--b")
    with pytest.raises(ConfigError):
        validate_experiment_id(raw="")


def test_secret_fields_rejected() -> None:
    with pytest.raises(ConfigError, match="密钥"):
        ExperimentConfig.from_mapping(_cfg(models={"api_key": "sk-secret"}))


def test_latest_image_rejected() -> None:
    with pytest.raises(ConfigError, match="latest"):
        ExperimentConfig.from_mapping(_cfg(images={"vigil": "auto-designer-vigil:latest"}))


def test_path_escape_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    root.mkdir()
    with pytest.raises(ConfigError, match="越出"):
        ensure_under_root(root=root, path=Path("/etc/passwd"))
    nested = experiment_paths(experiment_id="glm-evolution-e0", root=root)
    assert nested["root"].is_relative_to(root)


def test_experiments_root_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EXPERIMENTS_ROOT", str(tmp_path / "root"))
    assert experiments_root() == (tmp_path / "root").resolve()
