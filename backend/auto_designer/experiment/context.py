"""Spec-0069/T2: one credential-free context and model mapping for both runners."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from auto_designer.experiment.config import (
    ConfigError,
    compose_project,
    delivery_auth_type,
    delivery_required,
    local_ci_enabled,
    runtime_policies,
)


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
    # Spec-0073/T1: new runs bind a complete catalog, legacy contexts retain their shape.
    contract = manifest.get("workload_contract_version")
    workspace = resources.get("workspace") or {}
    expected_workspace = "docker-seed" if backend == "local" else "prebuilt"
    if "workload_contract_version" in manifest:
        from auto_designer.experiment.workload import read_task_catalog, verify_task_workspaces

        catalog = read_task_catalog(root, manifest)
        workspaces = resources.get("task_workspaces") or {}
        verify_task_workspaces(catalog, workspaces)
        if any(item["kind"] != expected_workspace for item in workspaces.values()):
            raise ConfigError(f"{backend} requires prepared {expected_workspace} task workspaces")
    elif workspace.get("kind") != expected_workspace:
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
    if "workload_contract_version" in manifest:
        values.update(
            workload_contract_version=contract,
            catalog_hash=manifest["catalog_hash"],
            plan_hash=manifest["plan_hash"],
        )
        _write_private(path, json.dumps(values, ensure_ascii=False, indent=2) + "\n")
        _write_private(
            root / "runtime/task-workspaces.json", json.dumps(workspaces, indent=2) + "\n"
        )
    else:
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


def require_controller_context(*, swebench: bool = False) -> SimpleNamespace:
    """Internal controllers require explicit inputs prepared by the public CLI."""
    required = [
        "AUTO_DESIGNER_EXPERIMENT_CONTEXT",
        "AUTO_DESIGNER_EXPERIMENT_ID",
        "AUTO_DESIGNER_RUN_ID",
        "AUTO_DESIGNER_CONFIG_HASH",
        "AUTO_DESIGNER_CONTROLLER_SHA",
        "AUTO_DESIGNER_PLAN_HASH",
        "AUTO_DESIGNER_RUN_MODE",
        "AUTO_DESIGNER_EXECUTION_BACKEND",
        "AUTO_DESIGNER_RECOVERY_ROOT",
        "AUTO_DESIGNER_HARNESS_ARCHIVE",
        "AUTO_DESIGNER_TASK_PACKAGE",
        "AUTO_DESIGNER_WORKSPACE_FILE",
        "AUTO_DESIGNER_GITEA_ENV_FILE",
        "PERSONA_LIBRARY",
        "AUTO_DESIGNER_INTERACTION_PLAN",
        "TOTAL_ROUNDS",
    ]
    if os.environ.get("AUTO_DESIGNER_WORKLOAD_CONTRACT_VERSION"):
        if os.environ["AUTO_DESIGNER_WORKLOAD_CONTRACT_VERSION"] != "1":
            raise ConfigError("Unknown workload_contract_version")
        for legacy in (
            "AUTO_DESIGNER_TASK_PACKAGE",
            "AUTO_DESIGNER_WORKSPACE_FILE",
            "AUTO_DESIGNER_INTERACTION_PLAN",
        ):
            required.remove(legacy)
        required.extend(
            [
                "AUTO_DESIGNER_TASK_CATALOG",
                "AUTO_DESIGNER_SESSION_PLAN",
                "AUTO_DESIGNER_TASK_WORKSPACES_FILE",
                "AUTO_DESIGNER_FROZEN_MANIFEST",
            ]
        )
        swebench = False
    if swebench:
        required.extend(
            [
                "SWEBENCH_PARQUET",
                "SWEBENCH_INSTANCE_FILE",
                "PERSONA_ROSTER",
                "SWEBENCH_INTERACTION_PLAN",
                "SESSIONS_PER_ROUND",
            ]
        )
    missing = [key for key in required if not os.environ.get(key, "").strip()]
    if missing:
        raise ConfigError(
            "Controller requires frozen inputs from experiment.py prepare/run: "
            + ", ".join(missing)
        )
    return load_controller_context(os.environ["AUTO_DESIGNER_EXPERIMENT_CONTEXT"])


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
    ci_stage = _controller_ci_stage(manifest=manifest, resources=resources)
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
            "AUTO_DESIGNER_GITEA_ENV_FILE": str(root / "secrets/demand-gitea.env"),
            "PERSONA_LIBRARY": str(material_path(root, manifest, "persona_library")),
            "PERSONA_ROSTER": str(material_path(root, manifest, "persona_roster")),
            "TOTAL_ROUNDS": str(config["rounds"]["count"]),
            "SESSIONS_PER_ROUND": str(config["rounds"]["sessions_per_round"]),
            "N_USERS": str(config["rounds"]["sessions_per_round"]),
            "MAX_PARALLEL_USERS": str(config["rounds"]["max_parallel_users"]),
            "N_OWNERS": "1" if config["roles"].get("owner_mode") == "llm" else "0",
            "VIGIL_KEEP_ALIVE": "0",
            "VIGIL_CI_STAGE": ci_stage,
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
    # Spec-0079/T4: no host inheritance; bind frozen parent material explicitly.
    harness_limits = config["runtime"].get("harness") or {}
    if "request_budget_seconds" in harness_limits:
        env["AUTO_DESIGNER_HARNESS_REQUEST_BUDGET_SECONDS"] = str(
            harness_limits["request_budget_seconds"]
        )
    if "termination_grace_seconds" in harness_limits:
        env["AUTO_DESIGNER_HARNESS_TERMINATION_GRACE_SECONDS"] = str(
            harness_limits["termination_grace_seconds"]
        )
    if "message_activity_seconds" in harness_limits:
        env["AUTO_DESIGNER_HARNESS_MESSAGE_ACTIVITY_SECONDS"] = str(
            harness_limits["message_activity_seconds"]
        )
    env["AUTO_DESIGNER_DELIVERY_REQUIRED"] = "1" if delivery_required(config) else "0"
    if "continuation" in config:
        env["AUTO_DESIGNER_CONTINUATION_INPUT"] = str(
            material_path(root, manifest, "continuation_input")
        )
    if "workload_contract_version" in manifest:
        env.update(
            {
                "AUTO_DESIGNER_WORKLOAD_CONTRACT_VERSION": str(
                    manifest["workload_contract_version"]
                ),
                "AUTO_DESIGNER_TASK_CATALOG": str(material_path(root, manifest, "task_catalog")),
                "AUTO_DESIGNER_SESSION_PLAN": str(material_path(root, manifest, "session_plan")),
                "AUTO_DESIGNER_TASK_WORKSPACES_FILE": str(root / "runtime/task-workspaces.json"),
                "AUTO_DESIGNER_FROZEN_MANIFEST": str(root / "manifest.json"),
                "AUTO_DESIGNER_CATALOG_HASH": manifest["catalog_hash"],
            }
        )
    else:
        env.update(
            {
                "AUTO_DESIGNER_TASK_PACKAGE": str(material_path(root, manifest, "task_package")),
                "AUTO_DESIGNER_WORKSPACE_FILE": str(root / "runtime/workspace.json"),
                "AUTO_DESIGNER_INTERACTION_PLAN": str(
                    material_path(root, manifest, "interaction_plan")
                ),
            }
        )
    # Spec-0072/T1: public policies, not host variables or credential profile settings.
    policies = runtime_policies(config)
    timing, delivery, alarms = (policies[key] for key in ("timing", "delivery", "alarms"))
    if "policies" in config:
        env.update(
            {
                "SYNTHESIZER_GROUPING": "1" if policies["synthesizer_grouping"] else "0",
                "AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT": "1"
                if timing["latency_isolated"]
                else "0",
                "AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS": str(timing["wall_guard_seconds"]),
                "ROUND_DELIVERY_TIMEOUT_SEC": str(delivery["timeout_seconds"]),
                "ROUND_DELIVERY_POLL_SEC": str(delivery["poll_seconds"]),
                "VIGIL_COORDINATION": delivery["coordination"],
                "OPENAGENTS_PERMISSION_MODE": delivery["permission_mode"],
                "OPENAGENTS_CLAUDE_IDLE_TIMEOUT": str(delivery["idle_timeout_seconds"]),
                "PROPOSAL_DEPTH_ALARM": str(alarms["proposal_depth"]),
                "READY_DEPTH_ALARM": str(alarms["ready_depth"]),
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
            # Spec-0072/T1: variable names locate secrets; auth_type defines their protocol.
            auth_name = {
                "api-key": "ANTHROPIC_API_KEY",
                "bearer": "ANTHROPIC_AUTH_TOKEN",
                "oauth": "CLAUDE_CODE_OAUTH_TOKEN",
            }[delivery_auth_type(model)]
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
            if "max_context_tokens" in (model.get("limits") or {}):
                env[prefix + "MAX_CONTEXT_TOKENS"] = str(model["limits"]["max_context_tokens"])
            if model.get("reasoning_effort"):
                env[prefix + "REASONING_EFFORT"] = model["reasoning_effort"]
    if "workload_contract_version" not in manifest and config["workload"]["kind"] == "swebench":
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


def _controller_ci_stage(*, manifest: dict[str, Any], resources: Mapping[str, Any]) -> str:
    """Spec-0077/T1: require an owned successful receipt; provider rechecks live facts."""
    if not local_ci_enabled(manifest["config"]):
        return "skip"
    ci = resources.get("ci")
    if not isinstance(ci, Mapping):
        raise ConfigError("Enabled local CI requires a verified READY resource receipt")
    project = compose_project(
        experiment_id=manifest["run_id"].lower(), cfg_hash=manifest["config_hash"]
    )
    if (
        ci.get("enabled") is not True
        or ci.get("state") != "READY"
        or ci.get("run_id") != manifest["run_id"]
        or ci.get("config_hash") != manifest["config_hash"]
        or ci.get("network") != project + "_ci"
        or ci.get("topology") != "private-docker-daemon-v1"
        or ci.get("job_network") != "host"
        or ("compose_project" in resources and resources["compose_project"] != project)
    ):
        raise ConfigError("Local CI resource receipt identity/state differs from this frozen run")
    daemon = ci.get("daemon")
    if (
        not isinstance(daemon, Mapping)
        or not _receipt_string(daemon.get("container_id"))
        or not _receipt_string(daemon.get("image_id"))
        or daemon.get("network") != project + "_ci"
        or daemon.get("storage_volume") != project + "_ci_docker_data"
    ):
        raise ConfigError("Local CI resource receipt is missing private daemon identity/bindings")
    runner = ci.get("runner")
    if (
        not isinstance(runner, Mapping)
        or type(runner.get("id")) is not int
        or runner["id"] <= 0
        or any(not _receipt_string(runner.get(key)) for key in ("name", "container_id", "image_id"))
        or not _receipt_string(ci.get("job_image_id"))
    ):
        raise ConfigError("Local CI resource receipt is missing runner/image identity")
    readiness = ci.get("readiness")
    if (
        not isinstance(readiness, Mapping)
        or not isinstance(readiness.get("head_sha"), str)
        or not re.fullmatch(r"[a-f0-9]{40}", readiness["head_sha"])
        or type(readiness.get("status_count")) is not int
        or readiness["status_count"] <= 0
        or readiness.get("state") != "success"
        or not _receipt_string(readiness.get("checked_at"))
    ):
        raise ConfigError(
            "Local CI readiness requires a current head and nonempty success statuses"
        )
    try:
        checked_at = datetime.fromisoformat(readiness["checked_at"])
        if "T" not in readiness["checked_at"] or checked_at.utcoffset() is None:
            raise ValueError("Timestamp must have a time and timezone")
    except ValueError as exc:
        raise ConfigError(
            "Local CI readiness checked_at must be an ISO timestamp with timezone"
        ) from exc
    return "agent"


def _receipt_string(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not any(ord(character) < 32 for character in value)
    )


def frozen_scenario(task_id: str | None = None):
    """Load the task instruction and backend-supplied prepared workspace directly."""
    from auto_designer.models import SeedScenario, WorkspaceSpec

    if os.environ.get("AUTO_DESIGNER_WORKLOAD_CONTRACT_VERSION"):
        catalog, _, workspaces = frozen_workload()
        tasks = {task["id"]: task for task in catalog["tasks"]}
        if task_id not in tasks:
            raise ConfigError(f"Frozen scenario requires a known explicit task_id: {task_id}")
        package = tasks[task_id]["package"]
        root = Path(os.environ["AUTO_DESIGNER_TASK_CATALOG"]).parent.parent
        workspace = workspaces[task_id]
    else:
        package_path = Path(os.environ["AUTO_DESIGNER_TASK_PACKAGE"])
        package = json.loads(package_path.read_text(encoding="utf-8"))
        root = package_path.parent.parent
        workspace = json.loads(Path(os.environ["AUTO_DESIGNER_WORKSPACE_FILE"]).read_text())
    instruction = root / package["instruction_file"]
    if instruction.is_symlink() or not instruction.resolve().is_relative_to(root.resolve()):
        raise ConfigError("Task instruction escapes frozen run")
    specification = WorkspaceSpec.from_dict(workspace)
    if os.environ.get("AUTO_DESIGNER_WORKLOAD_CONTRACT_VERSION"):
        specification.params.update(
            instance_id=package["id"],
            task_id=package["id"],
            task_key=package["id"],
            task_digest=tasks[task_id]["digest"],
            task_kind=tasks[task_id]["kind"],
            benchmark="swebench" if package["kind"] == "swebench" else "ordinary",
            not_in_benchmark=package.get("not_in_benchmark", False),
        )
    else:
        specification.params.setdefault("instance_id", package["id"])
        specification.params.setdefault("task_id", package["id"])
        specification.params.setdefault("task_key", package["id"])
    specification.params["interaction"] = package.get("interaction", "simulated_user")
    # Spec-0083/T3: public declarations only; private grading plans never enter this context.
    from auto_designer.experiment.workload import (
        execution_declaration,
        task_artifact_declarations,
        task_provenance,
    )

    fallback = os.environ.get("AUTO_DESIGNER_HARNESS_REQUEST_BUDGET_SECONDS")
    specification.params["execution"] = execution_declaration(
        package, fallback_seconds=float(fallback) if fallback else None
    )
    if "task_digest" not in specification.params:
        from auto_designer.execution_contract import canonical_sha256

        specification.params["task_digest"] = canonical_sha256(package)
    origin = task_provenance(package)
    specification.params["benchmark"] = origin["suite"]
    specification.params["instance_id"] = origin["instance_id"]
    declarations = task_artifact_declarations(package)
    if declarations:
        specification.params["evaluation_artifacts"] = declarations
    return SeedScenario(
        description=instruction.read_text(encoding="utf-8"), workspace=specification
    )


def frozen_workload() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Spec-0073/T1: read validated logical bindings and prepared provider workspaces."""
    from auto_designer.experiment.workload import (
        read_session_plan,
        read_task_catalog,
        verify_task_workspaces,
    )

    root = Path(os.environ["AUTO_DESIGNER_TASK_CATALOG"]).parent.parent
    manifest = json.loads(Path(os.environ["AUTO_DESIGNER_FROZEN_MANIFEST"]).read_text())
    catalog = read_task_catalog(root, manifest)
    plan = read_session_plan(root, manifest)
    workspaces = json.loads(Path(os.environ["AUTO_DESIGNER_TASK_WORKSPACES_FILE"]).read_text())
    verify_task_workspaces(catalog, workspaces)
    return catalog, plan, workspaces
