# Spec-0047/T4：生命周期与 CLI。
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from auto_designer.experiment import runtime
from auto_designer.experiment.manifest import (
    ManifestError,
    last_state,
    read_manifest,
    recovery_identity,
)
from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore


def _yaml(tmp_path: Path, *, experiment_id: str) -> Path:
    path = tmp_path / f"{experiment_id}.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                f"experiment_id: {experiment_id}",
                "mode: full-evolution",
                "source:",
                "  auto_designer_sha: abcdef",
                "images:",
                "  vigil: sha256:vigilpin",
                "models:",
                "  profile: glm-local",
                "capacity:",
                "  endpoint: glm-local",
                "  user_parallel: 1",
                "infrastructure:",
                "  isolation: dedicated",
                "retention:",
                "  keep_on_stop: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


class _Docker:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "ok", "")


def test_create_plan_start_stop_archive_destroy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EXPERIMENTS_ROOT", str(tmp_path))
    cfg = _yaml(tmp_path, experiment_id="exp-a")
    created = runtime.create(config_path=cfg, root=tmp_path)
    assert created["experiment_id"] == "exp-a"
    assert len(created["manifest"]["run_id"]) == 32
    assert created["manifest"]["controller_sha"] == "abcdef"
    assert created["manifest"]["plan_hash"] == created["manifest"]["config_hash"]
    planned = runtime.plan(experiment_id="exp-a", root=tmp_path)
    assert "TOKEN" not in json.dumps(planned)
    docker = _Docker()
    ctx = runtime.start(experiment_id="exp-a", root=tmp_path, run=docker)
    assert ctx.compose_project.startswith("adx-exp-a-")
    assert last_state(path=tmp_path / "exp-a" / "journal.jsonl") == "RUNNING"
    runtime.stop(experiment_id="exp-a", root=tmp_path, run=docker)
    assert last_state(path=tmp_path / "exp-a" / "journal.jsonl") == "STOPPED"
    assert (tmp_path / "exp-a" / "sessions").is_dir()
    bundle = runtime.archive(experiment_id="exp-a", root=tmp_path)
    assert (bundle / "manifest.json").is_file()
    assert not (bundle / "secrets").exists()
    runtime.destroy(experiment_id="exp-a", confirm="exp-a", root=tmp_path, run=docker)
    assert not (tmp_path / "exp-a").exists()


def test_duplicate_create_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EXPERIMENTS_ROOT", str(tmp_path))
    cfg = _yaml(tmp_path, experiment_id="exp-a")
    runtime.create(config_path=cfg, root=tmp_path)
    try:
        runtime.create(config_path=cfg, root=tmp_path)
        raise AssertionError("应拒绝重复 create")
    except ManifestError as exc:
        assert "已存在" in str(exc)


def test_preflight_and_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EXPERIMENTS_ROOT", str(tmp_path))
    cfg = _yaml(tmp_path, experiment_id="exp-c")
    runtime.create(config_path=cfg, root=tmp_path)
    check = runtime.preflight(experiment_id="exp-c", root=tmp_path)
    assert check["ok"] is True
    docker = _Docker()
    runtime.start(experiment_id="exp-c", root=tmp_path, run=docker)
    runtime.stop(experiment_id="exp-c", root=tmp_path, run=docker)
    ctx = runtime.resume(experiment_id="exp-c", root=tmp_path, run=docker)
    assert ctx.experiment_id == "exp-c"


def test_auditable_resume_launches_demand_controller_instead_of_only_infrastructure(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EXPERIMENTS_ROOT", str(tmp_path))
    cfg = _yaml(tmp_path, experiment_id="exp-demand")
    raw = cfg.read_text(encoding="utf-8")
    cfg.write_text(
        raw
        + "execution:\n"
        + "  runner: swebench-closed-loop\n"
        + "  plan:\n"
        + "    sha256: frozen-plan\n",
        encoding="utf-8",
    )
    runtime.create(config_path=cfg, root=tmp_path)
    identity = recovery_identity(read_manifest(path=tmp_path / "exp-demand" / "manifest.json"))
    RecoveryStore.initialize(
        root=tmp_path / "exp-demand" / "checkpoints", identity=RecoveryIdentity(**identity)
    )
    calls: list[tuple[list[str], Path]] = []

    def demand(command, *, cwd, env, check):
        assert check is False
        assert env["EXPERIMENTS_ROOT"] == str(tmp_path)
        calls.append((list(command), cwd))
        return subprocess.CompletedProcess(command, 0)

    ctx = runtime.resume(experiment_id="exp-demand", root=tmp_path, demand_run=demand)

    assert ctx.experiment_id == "exp-demand"
    assert len(calls) == 1
    command, cwd = calls[0]
    assert command[-1] == "--resume"
    assert command[-3:-1] == ["--config", str(tmp_path / "exp-demand" / "config.yaml")]
    assert cwd == Path(__file__).resolve().parents[3]


def test_auditable_resume_rejects_missing_recovery_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EXPERIMENTS_ROOT", str(tmp_path))
    cfg = _yaml(tmp_path, experiment_id="exp-old")
    cfg.write_text(
        cfg.read_text(encoding="utf-8")
        + "execution:\n  runner: swebench-closed-loop\n  plan:\n    sha256: plan\n",
        encoding="utf-8",
    )
    runtime.create(config_path=cfg, root=tmp_path)

    with pytest.raises(runtime.ConfigError, match="no recovery state"):
        runtime.resume(experiment_id="exp-old", root=tmp_path, demand_run=lambda *a, **k: None)


def test_experiment_context_private_json_round_trip(tmp_path: Path) -> None:
    ctx = runtime.ExperimentContext(
        experiment_id="exp-context",
        data_root=tmp_path / "data",
        harness_repo=tmp_path / "data/harness",
        harness_runs_root=tmp_path / "data/runs",
        sessions_root=tmp_path / "sessions",
        vigil_config_root=tmp_path / "runtime/vigil",
        vigil_container="exp-vigil",
        vigil_network="exp-network",
        compose_project="exp-project",
        gitea_host="http://127.0.0.1:3000",
        gitea_internal="http://gitea:3000",
        model_profile="glm-local",
        telemetry_root=tmp_path / "telemetry",
        mode="full-evolution",
        manifest_sha="abc",
    )
    path = tmp_path / "context.json"
    path.write_text(json.dumps(ctx.to_dict()), encoding="utf-8")
    loaded = runtime.ExperimentContext.load(path=path)
    assert loaded == ctx
