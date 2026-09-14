# Spec-0047/T4：实验生命周期与 ExperimentContext。
"""create/plan/preflight/start/stop/resume/archive/destroy. Manifest stays frozen."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from auto_designer.experiment.config import (
    ConfigError,
    ExperimentConfig,
    compose_project,
    config_hash,
    experiment_paths,
    experiments_root,
)
from auto_designer.experiment.infrastructure import (
    destroy_stack,
    provision,
    stop_stack,
    write_runtime,
)
from auto_designer.experiment.manifest import (
    ManifestError,
    append_journal,
    create_manifest,
    last_state,
    read_manifest,
    recovery_identity,
)
from auto_designer.loop.recovery import RecoveryError, RecoveryIdentity, RecoveryStore


@dataclass(frozen=True)
class ExperimentContext:
    experiment_id: str
    data_root: Path
    harness_repo: Path
    harness_runs_root: Path
    sessions_root: Path
    vigil_config_root: Path
    vigil_container: str
    vigil_network: str
    compose_project: str
    gitea_host: str
    gitea_internal: str
    model_profile: str
    telemetry_root: Path
    mode: str
    manifest_sha: str

    def to_dict(self) -> dict[str, Any]:
        return {
            key: str(value) if isinstance(value, Path) else value
            for key, value in self.__dict__.items()
        }

    @classmethod
    def load(cls, *, path: Path) -> ExperimentContext:
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"实验 context 不可读：{path}: {exc}") from exc
        if not isinstance(values, dict):
            raise ConfigError("实验 context 必须为 JSON object")
        for key in (
            "data_root",
            "harness_repo",
            "harness_runs_root",
            "sessions_root",
            "vigil_config_root",
            "telemetry_root",
        ):
            if key in values:
                values[key] = Path(str(values[key])).resolve()
        try:
            return cls(**values)
        except TypeError as exc:
            raise ConfigError(f"实验 context 字段非法：{exc}") from exc


def load_config(*, path: Path) -> ExperimentConfig:
    yaml = YAML(typ="safe")
    data = yaml.load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("配置必须是 mapping")
    return ExperimentConfig.from_mapping(data)


def create(*, config_path: Path, root: Path | None = None) -> dict[str, Any]:
    cfg = load_config(path=config_path)
    paths = experiment_paths(experiment_id=cfg.experiment_id, root=root or experiments_root())
    try:
        paths["root"].mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ManifestError(f"实验已存在：{paths['root']}") from exc
    for key in (
        "checkpoints",
        "telemetry",
        "logs",
        "sessions",
        "workspaces",
        "source",
        "infrastructure",
        "runtime",
        "secrets",
        "archive",
        "data",
    ):
        paths[key].mkdir(parents=True, exist_ok=True)
        if key == "secrets":
            paths[key].chmod(0o700)
    snapshot = cfg.raw
    yaml = YAML()
    yaml.default_flow_style = False
    with paths["config"].open("w", encoding="utf-8") as handle:
        yaml.dump(snapshot, handle)
    digest = config_hash(data=cfg.raw)
    project = compose_project(experiment_id=cfg.experiment_id, cfg_hash=digest)
    execution = cfg.raw.get("execution") if isinstance(cfg.raw.get("execution"), dict) else {}
    plan_node = execution.get("plan") if isinstance(execution.get("plan"), dict) else {}
    manifest = {
        "experiment_id": cfg.experiment_id,
        "run_id": uuid.uuid4().hex,
        "config_hash": digest,
        "controller_sha": str(cfg.source.get("auto_designer_sha") or digest),
        "plan_hash": str(plan_node.get("sha256") or digest),
        "runner": str(execution.get("runner") or ""),
        "compose_project": project,
        "mode": cfg.mode,
        "isolation": cfg.infrastructure.get("isolation", "dedicated"),
        "images": cfg.images,
        "models": cfg.models,
        "capacity": cfg.capacity,
        "source": cfg.source,
        "schema_version": cfg.schema_version,
    }
    create_manifest(path=paths["manifest"], data=manifest)
    append_journal(
        path=paths["journal"],
        action="create",
        from_state="ABSENT",
        to_state="CREATED",
        resources={"compose_project": project},
    )
    return {"experiment_id": cfg.experiment_id, "root": str(paths["root"]), "manifest": manifest}


def plan(*, experiment_id: str, root: Path | None = None) -> dict[str, Any]:
    paths = experiment_paths(experiment_id=experiment_id, root=root or experiments_root())
    manifest = read_manifest(path=paths["manifest"])
    return {
        "experiment_id": experiment_id,
        "root": str(paths["root"]),
        "compose_project": manifest["compose_project"],
        "isolation": manifest.get("isolation"),
        "mode": manifest.get("mode"),
        "images": manifest.get("images"),
        "sessions": str(paths["sessions"]),
        "secrets_excluded": True,
    }


def preflight(*, experiment_id: str, root: Path | None = None) -> dict[str, Any]:
    paths = experiment_paths(experiment_id=experiment_id, root=root or experiments_root())
    manifest = read_manifest(path=paths["manifest"])
    isolation = manifest.get("isolation", "dedicated")
    if isolation == "dedicated" and not manifest.get("compose_project"):
        raise ConfigError("dedicated 实验缺少 compose_project")
    if not paths["root"].is_dir():
        raise ConfigError("实验根不存在")
    return {"ok": True, "isolation": isolation, "compose_project": manifest["compose_project"]}


def start(*, experiment_id: str, root: Path | None = None, run=None) -> ExperimentContext:
    paths = experiment_paths(experiment_id=experiment_id, root=root or experiments_root())
    manifest = read_manifest(path=paths["manifest"])
    vigil_image = str((manifest.get("images") or {}).get("vigil") or "")
    if not vigil_image:
        raise ConfigError("manifest.images.vigil 缺失")
    info = provision(
        dest=paths["infrastructure"],
        experiment_id=experiment_id,
        manifest_sha=manifest["config_hash"],
        vigil_image=vigil_image,
        run=run,
    )
    write_runtime(dest=paths["infrastructure"], data=info)
    append_journal(
        path=paths["journal"],
        action="start",
        from_state=last_state(path=paths["journal"]),
        to_state="RUNNING",
        resources=info,
    )
    (paths["checkpoints"] / "start.json").write_text(
        json.dumps({"state": "RUNNING", **info}, indent=2), encoding="utf-8"
    )
    return context_from_manifest(experiment_id=experiment_id, paths=paths, manifest=manifest)


def stop(*, experiment_id: str, root: Path | None = None, run=None) -> None:
    paths = experiment_paths(experiment_id=experiment_id, root=root or experiments_root())
    manifest = read_manifest(path=paths["manifest"])
    stop_stack(
        dest=paths["infrastructure"],
        experiment_id=experiment_id,
        manifest_sha=manifest["config_hash"],
        run=run,
    )
    append_journal(
        path=paths["journal"],
        action="stop",
        from_state=last_state(path=paths["journal"]),
        to_state="STOPPED",
        resources={"kept": True},
    )


def resume(
    *, experiment_id: str, root: Path | None = None, run=None, demand_run=None
) -> ExperimentContext:
    """Resume infrastructure and, for auditable runs, the demand controller."""
    paths = experiment_paths(experiment_id=experiment_id, root=root or experiments_root())
    state = last_state(path=paths["journal"])
    if state not in ("STOPPED", "FAILED", "CREATED", "PROVISIONED", "READY"):
        raise ConfigError(f"不可从 {state} resume")
    manifest = read_manifest(path=paths["manifest"])
    if manifest.get("runner") == "swebench-closed-loop":
        identity = recovery_identity(manifest)
        try:
            RecoveryStore.open(root=paths["checkpoints"], identity=RecoveryIdentity(**identity))
        except RecoveryError as exc:
            raise ConfigError(f"recovery state 不可续跑：{exc}") from exc
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "scripts" / "run_auditable_experiment.py"),
            "--config",
            str(paths["config"]),
            "--resume",
        ]
        runner = demand_run or subprocess.run
        environment = os.environ.copy()
        environment["EXPERIMENTS_ROOT"] = str(paths["root"].parent)
        result = runner(
            command,
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            check=False,
        )
        if getattr(result, "returncode", 1) != 0:
            raise ConfigError(
                f"需求进程 resume 失败：returncode={getattr(result, 'returncode', '?')}"
            )
        return context_from_manifest(experiment_id=experiment_id, paths=paths, manifest=manifest)
    return start(experiment_id=experiment_id, root=root, run=run)


def archive(*, experiment_id: str, root: Path | None = None) -> Path:
    paths = experiment_paths(experiment_id=experiment_id, root=root or experiments_root())
    dest = paths["archive"] / "bundle"
    dest.mkdir(parents=True, exist_ok=True)
    append_journal(
        path=paths["journal"],
        action="archive",
        from_state=last_state(path=paths["journal"]),
        to_state="ARCHIVED",
        resources={"archive": str(dest)},
    )
    for name in ("manifest.json", "journal.jsonl", "config.yaml"):
        src = paths["root"] / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    for name in ("sessions", "telemetry", "logs", "checkpoints", "data", "runtime"):
        if paths[name].is_dir():
            shutil.copytree(paths[name], dest / name, dirs_exist_ok=True)
    if (dest / "secrets").exists():
        shutil.rmtree(dest / "secrets")
    harness_bundle = paths["archive"] / "harness.bundle"
    if harness_bundle.is_file():
        shutil.copy2(harness_bundle, dest / harness_bundle.name)
    return dest


def destroy(*, experiment_id: str, confirm: str, root: Path | None = None, run=None) -> None:
    paths = experiment_paths(experiment_id=experiment_id, root=root or experiments_root())
    manifest = read_manifest(path=paths["manifest"])
    labels = {
        "io.openagents.experiment_id": experiment_id,
        "io.openagents.manifest_sha": manifest["config_hash"],
    }
    destroy_stack(
        dest=paths["infrastructure"],
        experiment_id=experiment_id,
        manifest_sha=manifest["config_hash"],
        confirm=confirm,
        labels=labels,
        run=run,
    )
    shutil.rmtree(paths["root"])


def context_from_manifest(
    *, experiment_id: str, paths: dict[str, Path], manifest: dict[str, Any]
) -> ExperimentContext:
    project = str(manifest["compose_project"])
    return ExperimentContext(
        experiment_id=experiment_id,
        data_root=paths["data"],
        harness_repo=paths["data"] / "harness_sandbox" / "harness_repo",
        harness_runs_root=paths["data"] / "harness_runs",
        sessions_root=paths["sessions"],
        vigil_config_root=paths["infrastructure"] / "vigil-config",
        vigil_container=f"{project}-vigil-1",
        vigil_network=f"{project}_vigil_net",
        compose_project=project,
        gitea_host="http://127.0.0.1",
        gitea_internal="http://gitea:3000",
        model_profile=str((manifest.get("models") or {}).get("profile") or ""),
        telemetry_root=paths["telemetry"],
        mode=str(manifest.get("mode") or "full-evolution"),
        manifest_sha=str(manifest["config_hash"]),
    )
