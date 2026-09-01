# Spec-0047/T4：生命周期与 CLI。
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from auto_designer.experiment import runtime
from auto_designer.experiment.manifest import ManifestError, last_state


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
