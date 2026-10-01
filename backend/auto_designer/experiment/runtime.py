# Spec-0047/T4：实验生命周期与 ExperimentContext。
"""create/plan/preflight/start/stop/resume/archive/destroy. Manifest stays frozen."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
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


# Spec-0069/T5: version-two controller lifecycle. Legacy v1 APIs remain readable.
def runs_root_v2(root: Path | None = None) -> Path:
    return (
        Path(
            root
            or os.environ.get("AUTO_DESIGNER_RUNS_DIR")
            or Path(__file__).resolve().parents[3] / ".experiments"
        )
        .expanduser()
        .resolve()
    )


def load_run_v2(*, run_id: str, root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", run_id):
        raise ConfigError("Invalid run ID; a single path component is required")
    base = runs_root_v2(root)
    directory = base / run_id
    if directory.is_symlink() or not directory.resolve().is_relative_to(base):
        raise ConfigError("Unsafe run directory")
    manifest = read_manifest(path=directory / "manifest.json")
    if manifest.get("schema_version") != 2 or manifest.get("run_id") != run_id:
        raise ConfigError("This command requires a matching version-two run manifest")
    if Path(manifest["run_dir"]).resolve() != directory.resolve():
        raise ConfigError("Run directory moved; explicit recovery import is required")
    return directory, manifest


def credentials_v2(
    *,
    manifest: dict[str, Any],
    run_dir: Path | None = None,
    secrets_file: Path | None = None,
    models: bool = False,
) -> dict[str, str]:
    import stat

    from dotenv import dotenv_values

    allowed = {"E2B_API_KEY", "GITEA_TOKEN", "GITEA_USER", "GITEA_URL", "GITEA_PASSWORD"}
    if models:
        for role in manifest["config"]["models"].values():
            allowed.update((role["base_url_env"], role["api_key_env"]))
    result: dict[str, str] = {k: os.environ[k] for k in allowed if os.environ.get(k)}
    references = (
        [Path(secrets_file or manifest["secrets_file"])]
        if secrets_file or manifest.get("secrets_file")
        else []
    )
    if run_dir and (run_dir / "secrets/provider.env").is_file():
        if manifest["config"]["runtime"]["backend"] == "local":
            references.append(run_dir / "secrets/provider.env")
        else:
            references.insert(0, run_dir / "secrets/provider.env")
    for path in references:
        path = path.expanduser()
        if not path.exists() and not models and secrets_file is None:
            continue
        if not path.is_file() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ConfigError(f"Credential file must be a regular private file (chmod 600): {path}")
        values = dotenv_values(path, interpolate=False)
        result.update({k: str(v) for k, v in values.items() if k in allowed and v})
    if manifest["config"]["runtime"]["backend"] == "local" and not (
        run_dir and (run_dir / "secrets/provider.env").is_file()
    ):
        for key in ("GITEA_TOKEN", "GITEA_USER", "GITEA_URL", "GITEA_PASSWORD"):
            result.pop(key, None)
    if any("\n" in v or "\r" in v for v in result.values()):
        raise ConfigError("Credential values must fit on a single line")
    return result


def backend_v2(*, run_dir: Path, manifest: dict[str, Any], credentials: dict[str, str]):
    if manifest["config"]["runtime"]["backend"] == "local":
        from auto_designer.experiment.backends.local import LocalBackend

        return LocalBackend(run_dir, manifest, credentials)
    from auto_designer.experiment.backends.e2b import E2BBackend

    return E2BBackend(run_dir, manifest, credentials)


def check_v2(
    *,
    config_path: Path,
    offline: bool = False,
    secrets_file: Path | None = None,
    probe_models: bool = False,
) -> dict[str, Any]:
    from auto_designer.experiment.materials import check_materials

    report = check_materials(config_path)
    if offline:
        if probe_models:
            raise ConfigError("--probe-models cannot be combined with --offline")
        return {"action": "check", "offline": True, **report}
    manifest = {
        "config": report["config"],
        "secrets_file": str(secrets_file) if secrets_file else None,
    }
    credentials = credentials_v2(manifest=manifest, models=True)
    _require_model_credentials(manifest, credentials)
    selected = report["config"]["runtime"]["backend"]
    if selected == "local":
        for command in (["docker", "info"], ["docker", "compose", "version"]):
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ConfigError(
                    "Docker Engine and Compose must be available for local runs"
                ) from exc
            if result.returncode:
                raise ConfigError(
                    "Docker Engine or Compose is unavailable; restart Docker and check docker info"
                )
    else:
        from e2b import Sandbox

        if not credentials.get("E2B_API_KEY") or not credentials.get("GITEA_TOKEN"):
            raise ConfigError("E2B_API_KEY and GITEA_TOKEN are required for E2B")
        try:
            Sandbox.list(api_key=credentials["E2B_API_KEY"]).next_items()
            import requests

            response = requests.get(
                "https://gitea.com/api/v1/user",
                headers={"Authorization": "token " + credentials["GITEA_TOKEN"]},
                timeout=30,
            )
            if response.status_code != 200:
                raise ConfigError(
                    f"Gitea.com credential probe failed (HTTP {response.status_code})"
                )
            login = response.json()["login"]
            if credentials.get("GITEA_USER") and credentials["GITEA_USER"] != login:
                raise ConfigError("GITEA_USER does not match token owner")
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(
                "Provider credential probe failed; inspect connectivity and credentials"
            ) from exc
    if probe_models:
        from openai import OpenAI

        for name in ("user", "harness", "demand"):
            role = manifest["config"]["models"][name]
            try:
                client = OpenAI(
                    base_url=credentials[role["base_url_env"]],
                    api_key=credentials[role["api_key_env"]],
                    timeout=45,
                    max_retries=0,
                )
                client.chat.completions.create(
                    model=role["model"],
                    messages=[{"role": "user", "content": "Reply OK."}],
                    max_tokens=8,
                )
            except Exception as exc:
                raise ConfigError(
                    f"Model probe failed for {name}; check model and endpoint"
                ) from exc
        from anthropic import Anthropic

        role = manifest["config"]["models"]["delivery"]
        try:
            key = credentials[role["api_key_env"]]
            kwargs = (
                {"api_key": key}
                if role["api_key_env"] == "ANTHROPIC_API_KEY"
                else {"api_key": None, "auth_token": key}
            )
            client = Anthropic(
                base_url=credentials[role["base_url_env"]], timeout=45, max_retries=0, **kwargs
            )
            client.messages.create(
                model=role["model"],
                max_tokens=8,
                messages=[{"role": "user", "content": "Reply OK."}],
            )
        except Exception as exc:
            raise ConfigError(
                "Model probe failed for delivery; check Anthropic endpoint configuration"
            ) from exc
    return {"action": "check", "offline": False, "model_probes": probe_models, **report}


def _require_model_credentials(manifest: dict[str, Any], credentials: dict[str, str]) -> None:
    missing = sorted(
        {
            role[field]
            for role in manifest["config"]["models"].values()
            for field in ("base_url_env", "api_key_env")
            if not credentials.get(role[field])
        }
    )
    if missing:
        raise ConfigError("Missing model credential variables: " + ", ".join(missing))


def prepare_v2(
    *,
    config_path: Path,
    root: Path | None = None,
    secrets_file: Path | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    from auto_designer.experiment.manifest import run_lock, update_runtime
    from auto_designer.experiment.materials import prepare_materials

    manifest = prepare_materials(config_path, runs_root_v2(root), secrets_file)
    directory = Path(manifest["run_dir"])
    with run_lock(run_dir=directory):
        update_runtime(
            run_dir=directory,
            action="prepare-intent",
            changes={
                "experiment_state": "PREPARING",
                "preparation_complete": False,
            },
        )
        if progress:
            progress(
                {
                    "run_id": manifest["run_id"],
                    "run_dir": str(directory),
                    "preparation_log": str(directory / "logs/prepare.log")
                    if manifest["config"]["runtime"]["backend"] == "local"
                    else None,
                }
            )
        try:
            if manifest["config"]["runtime"]["backend"] == "local":
                from auto_designer.experiment.backends.local import prepare_images

                prepare_images(
                    run_dir=directory,
                    manifest=manifest,
                    credentials=credentials_v2(manifest=manifest, run_dir=directory),
                )
            update_runtime(
                run_dir=directory,
                action="prepare",
                changes={"experiment_state": "PREPARED", "preparation_complete": True},
            )
        except Exception:
            update_runtime(
                run_dir=directory,
                action="prepare-failed",
                changes={
                    "experiment_state": "FAILED",
                    "preparation_complete": False,
                    "failing_stage": "prepare",
                    "last_error": "Environment preparation failed; frozen inputs retained",
                },
            )
            raise ConfigError(
                f"Preparation failed for {manifest['run_id']}; frozen inputs retained at {directory}"
            ) from None
    return {
        "action": "prepare",
        "run_id": manifest["run_id"],
        "run_dir": str(directory),
        "experiment_state": "PREPARED",
        "resource_state": "ABSENT",
        "collection_state": "NONE",
        "next_command": f"python backend/scripts/experiment.py --runs-dir {runs_root_v2(root)} run {manifest['run_id']}",
    }


def _status_v2_unlocked(
    *, run_id: str, root: Path | None = None, secrets_file: Path | None = None
) -> dict[str, Any]:
    from auto_designer.experiment.manifest import read_runtime, update_runtime

    directory, manifest = load_run_v2(run_id=run_id, root=root)
    previous = read_runtime(run_dir=directory)
    try:
        adapter = backend_v2(
            run_dir=directory,
            manifest=manifest,
            credentials=credentials_v2(
                manifest=manifest, run_dir=directory, secrets_file=secrets_file
            ),
        )
        receipt = adapter.inspect()
    except Exception:
        receipt = {
            "observation": "UNKNOWN",
            "error": "Provider observation unavailable; last known state retained",
        }
    controller = receipt.get("controller") or receipt
    observation = receipt.get("observation", "OBSERVED")
    state = controller.get("state")
    changes: dict[str, Any] = {
        "observation": observation,
        "provider": receipt,
        "progress": receipt.get("progress") or progress_v2(directory),
    }
    changes.update(_gitea_facts(directory))
    resource = receipt.get("resource_state")
    if resource:
        changes["resource_state"] = resource
    if resource == "LOST" or state == "LOST":
        changes.update(experiment_state="LOST", observation="OBSERVED")
    elif state == "RUNNING" and controller.get("running"):
        changes["experiment_state"] = "RUNNING"
        if previous.get("failed_stage") in {"provision", "preflight", "controller launch"}:
            changes.update(failed_stage=None, error_class=None)
            if previous.get("last_error") not in {
                "Collection failed; previous archive retained",
                "Automatic collection failed; compute retained for manual recovery",
            }:
                changes["last_error"] = None
    elif state == "STOPPING":
        changes["experiment_state"] = "STOPPING"
    elif state == "STOPPED":
        changes["experiment_state"] = "STOPPED"
    elif state == "EXITED":
        changes["experiment_state"] = (
            "COMPLETED" if controller.get("experiment_complete") else "FAILED"
        )
    elif state == "UNKNOWN" or observation == "UNKNOWN":
        changes["observation"] = "UNKNOWN"
    elif state == "ABSENT" and previous["experiment_state"] in {"RUNNING", "STOPPING"}:
        changes["observation"] = "UNKNOWN"
    current = update_runtime(run_dir=directory, action="observe", changes=changes)
    return {"run_id": run_id, **current}


def _gitea_facts(directory: Path) -> dict[str, Any]:
    path = directory / "resources.json"
    if not path.is_file():
        return {}
    record = json.loads(path.read_text()).get("gitea") or {}
    repository_id = record.get("repository_id", record.get("repo_id"))
    public = {field: record[field] for field in ("url", "owner", "repo") if field in record}
    if repository_id is not None:
        public["repository_id"] = repository_id
    return {"gitea": public}


def status_v2(
    *, run_id: str, root: Path | None = None, secrets_file: Path | None = None
) -> dict[str, Any]:
    from auto_designer.experiment.manifest import read_runtime, run_lock

    directory, _ = load_run_v2(run_id=run_id, root=root)
    try:
        with run_lock(run_dir=directory, blocking=False):
            return _status_v2_unlocked(run_id=run_id, root=root, secrets_file=secrets_file)
    except BlockingIOError:
        return {
            "run_id": run_id,
            **read_runtime(run_dir=directory),
            "observation": "OPERATION_IN_PROGRESS",
        }


def progress_v2(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "checkpoints/recovery.json"
    if not path.is_file():
        return {"current_round": None, "rounds": {}}
    value = json.loads(path.read_text())
    rounds = {
        key: {
            "status": item.get("status"),
            "sealed_sha": item.get("sealed_sha"),
            "stages": {name: stage.get("status") for name, stage in item.get("stages", {}).items()},
        }
        for key, item in value.get("rounds", {}).items()
    }
    return {"current_round": value.get("round"), "rounds": rounds}


def run_v2(
    *,
    run_id: str,
    root: Path | None = None,
    secrets_file: Path | None = None,
    resume_run: bool = False,
    monitor: bool = True,
) -> dict[str, Any]:
    from auto_designer.experiment.manifest import read_runtime, run_lock, update_runtime
    from auto_designer.experiment.materials import verify_materials

    directory, manifest = load_run_v2(run_id=run_id, root=root)
    with run_lock(run_dir=directory):
        if read_runtime(run_dir=directory).get("preparation_complete") is not True:
            raise ConfigError("Environment preparation is incomplete; inspect prepare logs")
        current = _status_v2_unlocked(run_id=run_id, root=root, secrets_file=secrets_file)
        if (
            current["experiment_state"] in {"LOST", "STOPPING"}
            or current["observation"] == "UNKNOWN"
        ):
            raise ConfigError(
                "Cannot launch while resource or controller identity is lost/unknown/stopping"
            )
        if current["experiment_state"] in {"RUNNING", "COMPLETED"}:
            if monitor and current["experiment_state"] == "RUNNING":
                _start_monitor_v2(directory, manifest)
            return {"action": "attach", **current}
        if current["resource_state"] == "DESTROYED":
            raise ConfigError("Compute has been destroyed; start a new experiment")
        if not resume_run and current["experiment_state"] == "STOPPED":
            raise ConfigError("This run was stopped; use resume to preserve checkpoints")
        if resume_run and not (directory / "checkpoints").is_dir():
            # Cloud checkpoints can remain in the sandbox rather than host.
            if manifest["config"]["runtime"]["backend"] == "local":
                raise ConfigError("No recovery checkpoint exists for this run")
        verify_materials(manifest)
        credentials = credentials_v2(
            manifest=manifest, run_dir=directory, secrets_file=secrets_file, models=True
        )
        _require_model_credentials(manifest, credentials)
        adapter = backend_v2(run_dir=directory, manifest=manifest, credentials=credentials)
        update_runtime(
            run_dir=directory,
            action="provision-intent",
            changes={
                "launch_mode": "resume" if resume_run else "fresh",
                "collection_state": "PARTIAL",
                "resource_state": "PROVISIONING",
            },
        )
        stage = "provision"
        try:
            adapter.provision()
            _persist_provider_credentials(directory, credentials)
            update_runtime(
                run_dir=directory, action="provisioned", changes={"resource_state": "PROVISIONED"}
            )
            stage = "preflight"
            adapter.preflight()
            stage = "controller launch"
            receipt = adapter.launch(mode="resume" if resume_run else "fresh")
            controller = receipt.get("controller") or receipt
            if controller.get("state") != "RUNNING" or not controller.get("running"):
                raise ConfigError("Controller launch did not return a running acknowledgement")
            update_runtime(
                run_dir=directory,
                action="launch",
                changes={
                    "experiment_state": "RUNNING",
                    "resource_state": "RUNNING",
                    "observation": "OBSERVED",
                    "last_error": None,
                    "failed_stage": None,
                    "error_class": None,
                    "launch_receipt": receipt,
                    "provider": {**receipt, "controller": controller, "resource_state": "RUNNING"},
                    **_gitea_facts(directory),
                },
            )
        except Exception as exc:
            reason = str(exc)
            for value in credentials.values():
                if len(value) >= 8:
                    reason = reason.replace(value, "[REDACTED]")
            reason = reason[:2000]
            update_runtime(
                run_dir=directory,
                action="launch-failed",
                changes={
                    "experiment_state": "FAILED",
                    "failed_stage": stage,
                    "error_class": type(exc).__name__,
                    "last_error": reason,
                },
            )
            raise ConfigError(
                f"Experiment launch failed during {stage}: {reason}; inputs/resources retained"
            ) from None
        if monitor:
            _start_monitor_v2(directory, manifest)
        return {
            "action": "resume" if resume_run else "run",
            "run_id": run_id,
            **read_runtime(run_dir=directory),
        }


def logs_v2(
    *, run_id: str, root: Path | None = None, secrets_file: Path | None = None, tail: int = 100
) -> str:
    directory, manifest = load_run_v2(run_id=run_id, root=root)
    adapter = backend_v2(
        run_dir=directory,
        manifest=manifest,
        credentials=credentials_v2(manifest=manifest, run_dir=directory, secrets_file=secrets_file),
    )
    return adapter.logs(tail=tail)


def collect_v2(
    *, run_id: str, root: Path | None = None, secrets_file: Path | None = None
) -> dict[str, Any]:
    from auto_designer.experiment.collection import collect_archive, export_gitea_snapshot
    from auto_designer.experiment.manifest import read_runtime, run_lock, update_runtime

    directory, manifest = load_run_v2(run_id=run_id, root=root)
    with run_lock(run_dir=directory):
        credentials = credentials_v2(
            manifest=manifest, run_dir=directory, secrets_file=secrets_file
        )
        adapter = backend_v2(run_dir=directory, manifest=manifest, credentials=credentials)
        try:
            observed = adapter.inspect()
            controller = observed.get("controller") or observed
            provider_file = directory / "resources.json"
            provider = read_manifest(path=provider_file) if provider_file.is_file() else {}
            evidence = export_gitea_snapshot(
                run_dir=directory,
                resources=provider,
                credentials=credentials,
                terminal=controller.get("state") in {"STOPPED", "EXITED"}
                and not controller.get("running"),
                controller_nonce=controller.get("nonce"),
            )
            snapshot = adapter.collect()
            snapshot["gitea_evidence"] = evidence
            receipt = collect_archive(
                run_dir=directory,
                manifest=manifest,
                snapshot=snapshot,
                credentials={**credentials, **_redaction_credentials_v2(directory)},
            )
            changes = {"collection_state": receipt["collection_state"], "collection": receipt}
            if read_runtime(run_dir=directory).get("last_error") in {
                "Collection failed; previous archive retained",
                "Automatic collection failed; compute retained for manual recovery",
            }:
                changes["last_error"] = None
            update_runtime(
                run_dir=directory,
                action="collect",
                changes=changes,
            )
            return receipt
        except Exception:
            update_runtime(
                run_dir=directory,
                action="collect-failed",
                changes={
                    "collection_state": "PARTIAL",
                    "last_error": "Collection failed; previous archive retained",
                },
            )
            raise ConfigError(
                "Collection failed; provider data and previous host archive retained"
            ) from None


def stop_v2(
    *,
    run_id: str,
    root: Path | None = None,
    secrets_file: Path | None = None,
    grace_seconds: float = 30,
) -> dict[str, Any]:
    from auto_designer.experiment.manifest import run_lock, update_runtime

    directory, manifest = load_run_v2(run_id=run_id, root=root)
    with run_lock(run_dir=directory):
        adapter = backend_v2(
            run_dir=directory,
            manifest=manifest,
            credentials=credentials_v2(
                manifest=manifest, run_dir=directory, secrets_file=secrets_file
            ),
        )
        receipt = adapter.stop(grace_seconds=grace_seconds)
        controller = receipt.get("controller") or receipt
        if controller.get("state") not in {"STOPPED", "EXITED", "ABSENT"}:
            update_runtime(
                run_dir=directory, action="stop-unconfirmed", changes={"observation": "UNKNOWN"}
            )
            raise ConfigError("Stop not confirmed; resources retained")
        complete = controller.get("experiment_complete")
        state = (
            "COMPLETED"
            if complete
            else ("FAILED" if controller.get("state") == "EXITED" else "STOPPED")
        )
        update_runtime(
            run_dir=directory,
            action="stop",
            changes={
                "experiment_state": state,
                "resource_state": receipt.get("resource_state", "STOPPED"),
                "observation": "OBSERVED",
            },
        )
    # E2B stop retains the sandbox, local stop retains its volume; both collect
    # without model credentials before any destructive operation.
    try:
        collect_v2(run_id=run_id, root=root, secrets_file=secrets_file)
    except ConfigError:
        pass  # status explicitly records PARTIAL; stop itself was confirmed.
    return status_v2(run_id=run_id, root=root, secrets_file=secrets_file)


def destroy_v2(
    *,
    run_id: str,
    confirm: str,
    root: Path | None = None,
    secrets_file: Path | None = None,
    discard_uncollected: bool = False,
) -> dict[str, Any]:
    from auto_designer.experiment.manifest import read_runtime, run_lock, update_runtime

    if confirm != run_id:
        raise ConfigError("--confirm must exactly match the run ID")
    directory, manifest = load_run_v2(run_id=run_id, root=root)
    with run_lock(run_dir=directory):
        current = read_runtime(run_dir=directory)
        if current["resource_state"] == "DESTROYED":
            return {"run_id": run_id, **current}
        if current["collection_state"] != "COMPLETE" and not discard_uncollected:
            raise ConfigError(
                "Collect a consistent terminal archive first, or explicitly use --discard-uncollected"
            )
        adapter = backend_v2(
            run_dir=directory,
            manifest=manifest,
            credentials=credentials_v2(
                manifest=manifest, run_dir=directory, secrets_file=secrets_file
            ),
        )
        observed = adapter.inspect()
        controller = observed.get("controller") or observed
        if controller.get("state") == "UNKNOWN" or observed.get("observation") == "UNKNOWN":
            raise ConfigError("Controller identity is unknown; refusing compute destruction")
        collected = current.get("collection", {}).get("controller") or {}
        if (
            controller.get("nonce")
            and collected.get("nonce") != controller["nonce"]
            and not discard_uncollected
        ):
            raise ConfigError(
                "Terminal collection belongs to another controller attempt; collect again"
            )
        if controller.get("running"):
            raise ConfigError("Stop the controller before destroying compute")
        receipt = adapter.destroy()
        return {
            "run_id": run_id,
            **update_runtime(
                run_dir=directory,
                action="destroy",
                changes={
                    "resource_state": receipt.get("resource_state", "UNKNOWN"),
                    "destruction": receipt,
                },
            ),
        }


def _persist_provider_credentials(run_dir: Path, credentials: dict[str, str]) -> None:
    from dotenv import dotenv_values

    directory = run_dir / "secrets"
    directory.mkdir(exist_ok=True, mode=0o700)
    path = directory / "provider.env"
    current = dict(dotenv_values(path, interpolate=False)) if path.is_file() else {}
    current.update(
        {
            k: v
            for k, v in credentials.items()
            if k in {"E2B_API_KEY", "GITEA_TOKEN", "GITEA_URL", "GITEA_USER", "GITEA_PASSWORD"}
        }
    )
    temporary = directory / ".provider.env.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as handle:
        for key, value in current.items():
            if value is not None:
                handle.write(
                    key + "='" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'\n"
                )
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    registry = directory / "redaction-values.json"
    values = _redaction_credentials_v2(run_dir)
    values.update(
        {
            k: v
            for k, v in credentials.items()
            if any(part in k for part in ("KEY", "TOKEN", "PASSWORD"))
        }
    )
    fd = os.open(registry, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(values, handle)


def _redaction_credentials_v2(run_dir: Path) -> dict[str, str]:
    path = run_dir / "secrets/redaction-values.json"
    if not path.is_file():
        return {}
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ConfigError("Redaction registry must be private")
    value = json.loads(path.read_text())
    return {str(k): str(v) for k, v in value.items()}


def _start_monitor_v2(run_dir: Path, manifest: dict[str, Any]) -> None:
    from auto_designer.experiment.engine import materialize_controller_source

    source = materialize_controller_source(run_dir, manifest)
    python = sys.executable
    images = run_dir / "runtime/local-images.json"
    if images.is_file():
        python = json.loads(images.read_text()).get("controller_python", python)
    log = run_dir / "logs/collector.log"
    log.parent.mkdir(exist_ok=True)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(run_dir)),
        "PYTHONPATH": str(source / "backend"),
    }
    with log.open("ab") as handle:
        subprocess.Popen(
            [
                python,
                "-m",
                "auto_designer.experiment.runtime",
                "--monitor-run",
                manifest["run_id"],
                "--runs-dir",
                str(run_dir.parent),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=handle,
            start_new_session=True,
        )


def monitor_v2(*, run_id: str, root: Path) -> None:
    """Best-effort host collector; cloud expiry is never confused with success."""
    import fcntl
    import time

    from auto_designer.experiment.manifest import run_lock, update_runtime

    directory, _ = load_run_v2(run_id=run_id, root=root)
    with (directory / "runtime/monitor.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        last_collection = 0.0
        while True:
            current = status_v2(run_id=run_id, root=root)
            state = current["experiment_state"]
            terminal = state in {"COMPLETED", "STOPPED", "FAILED", "LOST"}
            if current["observation"] != "UNKNOWN" and (
                terminal or time.monotonic() - last_collection >= 60
            ):
                try:
                    receipt = collect_v2(run_id=run_id, root=root)
                    last_collection = time.monotonic()
                    if state == "COMPLETED" and receipt["collection_state"] == "COMPLETE":
                        destroy_v2(run_id=run_id, confirm=run_id, root=root)
                        return
                    if terminal:
                        with run_lock(run_dir=directory):
                            latest = _status_v2_unlocked(run_id=run_id, root=root)
                            if latest["experiment_state"] in {
                                "COMPLETED",
                                "STOPPED",
                                "FAILED",
                                "LOST",
                            }:
                                fcntl.flock(lock, fcntl.LOCK_UN)
                                return
                except ConfigError:
                    update_runtime(
                        run_dir=directory,
                        action="monitor-collection-failed",
                        changes={
                            "last_error": "Automatic collection failed; compute retained for manual recovery"
                        },
                    )
                    if terminal:
                        with run_lock(run_dir=directory):
                            latest = _status_v2_unlocked(run_id=run_id, root=root)
                            if latest["experiment_state"] in {
                                "COMPLETED",
                                "STOPPED",
                                "FAILED",
                                "LOST",
                            }:
                                fcntl.flock(lock, fcntl.LOCK_UN)
                                return
            time.sleep(15)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Internal host collector")
    parser.add_argument("--monitor-run", required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    options = parser.parse_args()
    monitor_v2(run_id=options.monitor_run, root=options.runs_dir)
