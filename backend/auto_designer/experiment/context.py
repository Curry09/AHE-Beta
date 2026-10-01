"""Spec-0069/T2: one credential-free context and model mapping for both runners."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from auto_designer.experiment.config import ConfigError


def material_path(run_dir: Path, manifest: dict[str, Any], key: str) -> Path:
    """Resolve a frozen input after relocation to a cloud sandbox."""
    try:
        relative = Path(manifest["materials"][key]["path"])
    except (KeyError, TypeError) as exc:
        raise ConfigError(f"Frozen material missing: {key}") from exc
    root = Path(run_dir).resolve()
    path = root / relative
    if relative.is_absolute() or not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ConfigError(f"Frozen material path escapes run: {key}")
    if not path.is_file():
        raise ConfigError(f"Frozen material file missing: {key}")
    return path


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_controller_context(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    credentials: Mapping[str, str],
    resources: Mapping[str, Any],
    execution_root: Path | None = None,
    mode: str = "fresh",
) -> Path:
    """Bind dynamic addresses and workspace facts, without writing model credentials."""
    if mode not in {"fresh", "resume"}:
        raise ConfigError("Controller mode must be fresh or resume")
    root = Path(execution_root or run_dir).resolve()
    backend = manifest["config"]["runtime"]["backend"]
    gitea = resources.get("gitea") or {}
    vigil = resources.get("vigil") or {}
    workspace = resources.get("workspace") or {}
    expected_workspace = "docker-seed" if backend == "local" else "prebuilt"
    if workspace.get("kind") != expected_workspace:
        raise ConfigError(f"{backend} requires a prepared {expected_workspace} workspace")
    token = credentials.get("GITEA_TOKEN", "")
    required = {
        "GITEA_URL": gitea.get("url"),
        "OWNER": gitea.get("owner"),
        "REPO": gitea.get("repo"),
        "TOKEN": token,
    }
    if any(not value for value in required.values()):
        raise ConfigError("Gitea identity/address/token is incomplete")
    if any("\n" in str(value) or "\r" in str(value) for value in required.values()):
        raise ConfigError("Gitea environment contains a newline")
    _write_private(
        root / "secrets/demand-gitea.env",
        "".join(f"{key}={value}\n" for key, value in required.items()),
    )
    project = str(resources.get("compose_project") or f"adx-{manifest['run_id'].lower()}")
    values = {
        "experiment_id": manifest["experiment_id"],
        "data_root": str(root / "data"),
        "harness_repo": str(root / "data/harness_sandbox/harness_repo"),
        "harness_runs_root": str(root / "data/harness_runs"),
        "sessions_root": str(root / "data/role_runs" / manifest["run_id"] / "sessions"),
        "vigil_config_root": str(root / "runtime/vigil-config"),
        "vigil_container": str(vigil.get("container") or f"{project}-vigil-1"),
        "vigil_network": str(vigil.get("network") or f"{project}_vigil_net"),
        "compose_project": project,
        "gitea_host": str(gitea["url"]),
        "gitea_internal": str(gitea.get("internal_url") or gitea["url"]),
        "model_profile": "explicit-v2",
        "telemetry_root": str(root / "telemetry"),
        "mode": "full-evolution",
        "manifest_sha": manifest["config_hash"],
    }
    path = root / "runtime/controller-context.json"
    _write_private(path, json.dumps(values, ensure_ascii=False, indent=2) + "\n")
    _write_private(root / "runtime/workspace.json", json.dumps(workspace, indent=2) + "\n")
    return path


def load_controller_context(path: str | Path) -> SimpleNamespace:
    """Also read historical contexts without coupling runners to CLI state code."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ConfigError("Controller context must be an object")
    for key in (
        "experiment_id",
        "data_root",
        "harness_repo",
        "vigil_config_root",
        "vigil_container",
        "vigil_network",
    ):
        if not document.get(key):
            raise ConfigError(f"Controller context is missing {key}")
    return SimpleNamespace(**document)


def build_controller_environment(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    credentials: Mapping[str, str],
    resources: Mapping[str, Any],
    execution_root: Path | None = None,
    mode: str = "fresh",
) -> dict[str, str]:
    """Return a complete child environment; never inherit unrelated host model keys."""
    root = Path(execution_root or run_dir).resolve()
    config = manifest["config"]
    context_path = write_controller_context(
        run_dir=run_dir,
        manifest=manifest,
        credentials=credentials,
        resources=resources,
        execution_root=root,
        mode=mode,
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}
    }
    source_root = Path(resources.get("source_root") or root / "source/controller")
    env.update(
        {
            "PYTHONPATH": str(source_root / "backend"),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "AUTO_DESIGNER_EXPERIMENT_CONTEXT": str(context_path),
            "AUTO_DESIGNER_EXECUTION_BACKEND": config["runtime"]["backend"],
            "AUTO_DESIGNER_RUN_MODE": mode,
            "AUTO_DESIGNER_RECOVERY_ROOT": str(root / "checkpoints"),
            "AUTO_DESIGNER_HARNESS_ARCHIVE": str(material_path(root, manifest, "harness_archive")),
            "AUTO_DESIGNER_TASK_PACKAGE": str(material_path(root, manifest, "task_package")),
            "AUTO_DESIGNER_WORKSPACE_FILE": str(root / "runtime/workspace.json"),
            "AUTO_DESIGNER_INTERACTION_PLAN": str(
                material_path(root, manifest, "interaction_plan")
            ),
            "AUTO_DESIGNER_GITEA_ENV_FILE": str(root / "secrets/demand-gitea.env"),
            "PERSONA_LIBRARY": str(material_path(root, manifest, "persona_library")),
            "PERSONA_ROSTER": str(material_path(root, manifest, "persona_roster")),
            "TOTAL_ROUNDS": str(config["rounds"]["count"]),
            "SESSIONS_PER_ROUND": str(config["rounds"]["sessions_per_round"]),
            "N_USERS": str(config["rounds"]["sessions_per_round"]),
            "MAX_PARALLEL_USERS": str(config["rounds"]["max_parallel_users"]),
            "N_OWNERS": "0",
            "VIGIL_KEEP_ALIVE": "0",
            "VIGIL_CI_STAGE": "skip",
            "AUTO_DESIGNER_OBJECTIVE_EVALUATION": "0",
            "DISABLE_UPDATES": "1",
            "OPENAGENTS_NO_SELF_UPDATE": "1",
            "VIGIL_MODE": "container" if config["runtime"]["backend"] == "local" else "subprocess",
            "VIGIL_GITEA_INTERNAL_URL": str(
                resources["gitea"].get("internal_url") or resources["gitea"]["url"]
            ),
            "GITEA_TOKEN": credentials["GITEA_TOKEN"],
            "CLAUDE_CONFIG_DIR": str(root / "secrets/claude"),
        }
    )
    (root / "secrets/claude").mkdir(mode=0o700, exist_ok=True)
    for field in ("experiment_id", "run_id", "config_hash", "controller_sha", "plan_hash"):
        env[f"AUTO_DESIGNER_{field.upper()}"] = str(manifest[field])
    for role, name in (
        ("triager", "N_TRIAGERS"),
        ("synthesizer", "N_SYNTHESIZERS"),
        ("divergent", "N_DIVERGENTS"),
        ("developer", "N_DEVELOPERS"),
    ):
        env[name] = str(config["roles"][role])
    for role in ("user", "harness", "demand", "delivery"):
        model = config["models"][role]
        url = credentials.get(model["base_url_env"], "")
        key = credentials.get(model["api_key_env"], "")
        if not url or not key:
            raise ConfigError(
                f"Missing model environment for {role}: {model['base_url_env']} / {model['api_key_env']}"
            )
        if role == "delivery":
            env.update(
                ANTHROPIC_BASE_URL=url,
                ANTHROPIC_MODEL=model["model"],
                ANTHROPIC_SMALL_FAST_MODEL=model["model"],
            )
            # Standard Anthropic keys and gateway bearer tokens use different headers.
            auth_name = (
                "ANTHROPIC_API_KEY"
                if model["api_key_env"] == "ANTHROPIC_API_KEY"
                else "ANTHROPIC_AUTH_TOKEN"
            )
            env[auth_name] = key
        else:
            prefix = role.upper() + "_LLM_"
            env.update(
                {
                    prefix + "MODEL": model["model"],
                    prefix + "BASE_URL": url,
                    prefix + "API_KEY": key,
                }
            )
    if config["workload"]["kind"] == "swebench":
        env["SWEBENCH_PARQUET"] = str(material_path(root, manifest, "dataset"))
        env["SWEBENCH_INSTANCE_FILE"] = str(material_path(root, manifest, "pool"))
        env["SWEBENCH_INTERACTION_PLAN"] = env["AUTO_DESIGNER_INTERACTION_PLAN"]
    vigil = resources.get("vigil") or {}
    if vigil.get("image"):
        env["AUTO_DESIGNER_VIGIL_IMAGE"] = str(vigil["image"])
    if vigil.get("container"):
        env["AUTO_DESIGNER_VIGIL_CONTAINER"] = str(vigil["container"])
    if config["runtime"]["backend"] == "e2b":
        if not resources.get("sandbox_id"):
            raise ConfigError("E2B context requires the actual sandbox identity")
        env["AUTO_DESIGNER_SANDBOX_ID"] = str(resources["sandbox_id"])
    return env


def frozen_scenario():
    """Load the task instruction and backend-supplied prepared workspace directly."""
    from auto_designer.models import SeedScenario, WorkspaceSpec

    package_path = Path(os.environ["AUTO_DESIGNER_TASK_PACKAGE"])
    package = json.loads(package_path.read_text(encoding="utf-8"))
    root = package_path.parent.parent
    instruction = root / package["instruction_file"]
    if not instruction.resolve().is_relative_to(root.resolve()):
        raise ConfigError("Task instruction escapes frozen run")
    workspace = json.loads(Path(os.environ["AUTO_DESIGNER_WORKSPACE_FILE"]).read_text())
    specification = WorkspaceSpec.from_dict(workspace)
    specification.params.setdefault("instance_id", package["id"])
    return SeedScenario(
        description=instruction.read_text(encoding="utf-8"), workspace=specification
    )
