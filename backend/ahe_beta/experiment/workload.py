"""Spec-0073/T1: logical task catalog and session plan, independent of providers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ahe_beta.experiment.config import (
    ConfigError,
    config_hash,
    read_json_document,
    validate_task_package_document,
)

CONTRACT_VERSION = 1
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def validate_task_ids(tasks: list[dict[str, Any]]) -> None:
    ids = [task.get("id") for task in tasks]
    if not ids or any(not isinstance(value, str) or not _TASK_ID.fullmatch(value) for value in ids):
        raise ConfigError("Task IDs must be safe, nonempty single path segments")
    if len(set(ids)) != len(ids):
        raise ConfigError("Task catalog contains duplicate task IDs")


def interaction_plan(config: dict[str, Any], tasks: list[dict[str, Any]]) -> list[list[list[str]]]:
    """Compile preview pairs; this intentionally makes no source-content claims."""
    validate_task_ids(tasks)
    personas = config["workload"]["persona_ids"]
    task_ids = [task["id"] for task in tasks]
    count = config["rounds"]["count"]
    sessions = config["rounds"]["sessions_per_round"]
    plan = config["workload"].get("interaction_plan")
    if plan is None:
        plan = [
            [
                [
                    personas[(r * sessions + slot) % len(personas)],
                    task_ids[(r * sessions + slot) % len(task_ids)],
                ]
                for slot in range(sessions)
            ]
            for r in range(count)
        ]
    if not isinstance(plan, list) or len(plan) != count:
        raise ConfigError(f"workload.interaction_plan must contain {count} rounds")
    for round_no, picks in enumerate(plan, 1):
        label = f"workload.interaction_plan round {round_no}"
        if not isinstance(picks, list) or len(picks) != sessions:
            raise ConfigError(f"{label} does not match rounds.sessions_per_round")
        for pair in picks:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(v, str) for v in pair)
            ):
                raise ConfigError(f"{label} must contain [persona_id, task_id] pairs")
            persona, task = pair
            if persona not in personas:
                raise ConfigError(f"{label} references unselected persona {persona}")
            if task not in task_ids:
                raise ConfigError(f"{label} references unknown task {task}")
    return json.loads(json.dumps(plan))


def task_digest(task: dict[str, Any]) -> str:
    """Content identity excludes provider coordinates and the record's own digest."""
    return config_hash(
        data={
            key: task[key]
            for key in ("id", "kind", "interaction", "package", "source_snapshot", "content_hashes")
        }
    )


def task_artifact_declarations(package: dict[str, Any]) -> list[dict[str, Any]]:
    """Read public capture declarations without adding defaults to schema 1 packages."""
    if package.get("schema_version") not in {2, 3}:
        return []
    validate_task_package_document(package)
    return json.loads(json.dumps(package.get("artifacts", {}).get("exports", [])))


def task_provenance(package: dict[str, Any]) -> dict[str, str]:
    """Benchmark source is independent of its local task ID and scoring adapter."""
    if package["kind"] == "benchmark":
        validate_task_package_document(package)
        return dict(package["benchmark"])
    return {"suite": package["kind"], "instance_id": package["id"]}


def validate_artifact_backend(package: dict[str, Any], backend: str) -> None:
    """Service exports require the explicit container contract, never old workspaces."""
    if package.get("schema_version") == 3:
        validate_task_package_document(package)
        if backend not in {"local", "e2b"}:
            raise ConfigError(f"Task {package['id']}: unsupported container backend {backend}")
        return
    for declaration in task_artifact_declarations(package):
        if declaration["source"] == "managed_service":
            raise ConfigError(
                f"Task {package['id']} artifact {declaration['id']}: {backend} does not support "
                "controller-owned managed_service capture; requires Spec-0081 capability"
            )


def compile_session_plan(
    config: dict[str, Any],
    catalog: dict[str, Any],
    catalog_hash: str,
    inherited_pairs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tasks = catalog_tasks(catalog)
    by_id = {task["id"]: task for task in tasks}
    if config["workload"].get("source") == "parent":
        if not inherited_pairs:
            raise ConfigError("Inherited workload requires frozen parent pairs")
        if len(inherited_pairs) != config["rounds"]["sessions_per_round"]:
            raise ConfigError("Inherited pair count differs from sessions_per_round")
        picks = []
        for pair in inherited_pairs:
            task_id, persona = pair["task_id"], pair["persona_id"]
            # Spec-0080/T1: parent pairs are an ordered execution list, not a set.
            if task_id not in by_id:
                raise ConfigError("Inherited workload contains unknown task")
            if (pair["task_digest"], pair["interaction"]) != (
                by_id[task_id]["digest"],
                by_id[task_id]["interaction"],
            ):
                raise ConfigError("Inherited task binding identity differs from catalog")
            picks.append([persona, task_id])
        pairs = [picks for _ in range(config["rounds"]["count"])]
    else:
        pairs = interaction_plan(config, tasks)
    return {
        "contract_version": CONTRACT_VERSION,
        "catalog_hash": catalog_hash,
        "rounds": [
            [
                {
                    "round_no": round_no,
                    "slot": slot,
                    "persona_id": persona,
                    "task_id": task_id,
                    "task_digest": by_id[task_id]["digest"],
                    "interaction": by_id[task_id]["interaction"],
                }
                for slot, (persona, task_id) in enumerate(picks)
            ]
            for round_no, picks in enumerate(pairs, 1)
        ],
    }


def catalog_tasks(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    if (
        not isinstance(catalog, dict)
        or type(catalog.get("contract_version")) is not int
        or catalog["contract_version"] != CONTRACT_VERSION
    ):
        raise ConfigError("Unknown task catalog contract_version")
    tasks = catalog.get("tasks")
    if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
        raise ConfigError("Task catalog must contain ordered task records")
    validate_task_ids(tasks)
    for task in tasks:
        try:
            package = task["package"]
            version = package.get("schema_version")
            if "schema_version" in package and (
                type(version) is not int or version not in {1, 2, 3}
            ):
                raise ConfigError("Unknown frozen task package schema_version")
            if version in {2, 3} or task["kind"] == "benchmark":
                validate_task_package_document(package)
            elif "artifacts" in package or "benchmark" in package:
                raise ConfigError("Frozen schema 1 package cannot contain schema 2 fields")
            if (
                task_digest(task) != task["digest"]
                or task["package"]["id"] != task["id"]
                or task["kind"] != task["package"]["kind"]
                or task["interaction"] != task["package"].get("interaction", "simulated_user")
            ):
                raise ConfigError(f"Task catalog digest or identity mismatch: {task['id']}")
        except (KeyError, TypeError) as exc:
            raise ConfigError(f"Incomplete frozen task record: {task['id']}") from exc
    return tasks


def tasks_by_id(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build the validated ID index without duplicating task records in frozen JSON."""
    return {task["id"]: task for task in catalog_tasks(catalog)}


def _material_path(run_dir: Path, manifest: dict[str, Any], key: str) -> Path:
    from ahe_beta.experiment.context import material_path

    return material_path(run_dir, manifest, key)


def read_task_catalog(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if (
        type(manifest.get("workload_contract_version")) is not int
        or manifest["workload_contract_version"] != CONTRACT_VERSION
    ):
        raise ConfigError("Unknown or missing workload_contract_version")
    from ahe_beta.experiment.materials import sha256_file

    path = _material_path(run_dir, manifest, "task_catalog")
    if sha256_file(path) != manifest.get("catalog_hash"):
        raise ConfigError("Frozen task catalog hash mismatch")
    catalog = read_json_document(path=path)
    for task in catalog_tasks(catalog):
        try:
            package_path = task_material_path(run_dir, manifest, task, "package")
            if config_hash(data=read_json_document(path=package_path)) != config_hash(
                data=task["package"]
            ):
                raise ConfigError(f"Frozen package differs from catalog: {task['id']}")
            for name, expected in task["content_hashes"].items():
                path = task_material_path(run_dir, manifest, task, name)
                if sha256_file(path) != expected:
                    raise ConfigError(f"Frozen task content hash mismatch: {task['id']}/{name}")
            if task["package"].get("schema_version") != 3 or "source_archive" in task["materials"]:
                task_material_path(run_dir, manifest, task, "source_archive")
        except (KeyError, TypeError) as exc:
            raise ConfigError(f"Incomplete task materials: {task['id']}") from exc
    return catalog


def task_material_path(
    run_dir: Path, manifest: dict[str, Any], task: dict[str, Any], name: str
) -> Path:
    try:
        key = task["materials"][name]
    except KeyError as exc:
        raise ConfigError(f"Task {task.get('id')} material missing: {name}") from exc
    return _material_path(run_dir, manifest, key)


def read_session_plan(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    from ahe_beta.experiment.materials import sha256_file

    catalog = read_task_catalog(run_dir, manifest)
    path = _material_path(run_dir, manifest, "session_plan")
    if sha256_file(path) != manifest.get("plan_hash"):
        raise ConfigError("Frozen session plan hash mismatch")
    plan = read_json_document(path=path)
    if (
        not isinstance(plan, dict)
        or type(plan.get("contract_version")) is not int
        or plan["contract_version"] != CONTRACT_VERSION
    ):
        raise ConfigError("Unknown session plan contract_version")
    inherited_pairs = None
    if manifest["config"]["workload"].get("source") == "parent":
        inherited = read_json_document(path=_material_path(run_dir, manifest, "continuation_input"))
        inherited_pairs = inherited["pairs"]
    expected = compile_session_plan(
        manifest["config"], catalog, manifest["catalog_hash"], inherited_pairs
    )
    # JSON hashing preserves scalar types: True/1 and 1.0/1 must not compare equal.
    if config_hash(data=plan) != config_hash(data=expected):
        raise ConfigError("Frozen session plan does not match logical task/persona bindings")
    return plan


def verify_task_workspaces(catalog: dict[str, Any], workspaces: dict[str, Any]) -> None:
    tasks = catalog_tasks(catalog)
    if not isinstance(workspaces, dict) or set(workspaces) != {task["id"] for task in tasks}:
        raise ConfigError("Prepared task workspaces do not match the frozen catalog")
    for task in tasks:
        workspace = workspaces[task["id"]]
        if task["package"].get("schema_version") == 3:
            from ahe_beta.experiment.task_environments.contract import (
                EnvironmentContractError,
                environment_identity,
            )

            try:
                actual_recipe = environment_identity(
                    {**task["package"], "environment": workspace["params"]["environment"]}
                )
            except (EnvironmentContractError, KeyError, TypeError) as exc:
                raise ConfigError(
                    f"Prepared container workspace identity/content mismatch: {task['id']}"
                ) from exc

            if (
                not isinstance(workspace, dict)
                or workspace.get("kind") != "container"
                or workspace.get("status") != "prepared"
                or workspace.get("task_digest") != task["digest"]
                or workspace.get("recipe_hash") != environment_identity(task["package"])
                or actual_recipe != workspace.get("recipe_hash")
                or not isinstance(workspace.get("params"), dict)
                or workspace["params"].get("task_id") != task["id"]
                or workspace["params"].get("task_digest") != task["digest"]
                or workspace["params"].get("environment", {}).get("image")
                != task["package"]["environment"]["image"]
            ):
                raise ConfigError(
                    f"Prepared container workspace identity/content mismatch: {task['id']}"
                )
            source = task["package"].get("source")
            expected_revision = source["revision"] if source else None
            params = workspace["params"]
            if (
                params.get("source") != source
                or params.get("expected_git_revision") != expected_revision
                or workspace.get("source_revision") != expected_revision
            ):
                raise ConfigError(
                    f"Prepared container Git source differs from frozen task: {task['id']}"
                )
            continue
        if (
            not isinstance(workspace, dict)
            or workspace.get("task_digest") != task["digest"]
            or workspace.get("status") != "prepared"
            or not workspace.get("recipe_hash")
            or workspace.get("source_revision") != task["source_snapshot"]["revision"]
            or workspace.get("source_hash") != config_hash(data=task["source_snapshot"]["files"])
            or workspace.get("kind") not in {"docker-seed", "prebuilt"}
            or not isinstance(workspace.get("params"), dict)
        ):
            raise ConfigError(f"Prepared task workspace identity/content mismatch: {task['id']}")


def validate_task_execution(
    package: dict[str, Any], *, source_root: Path | None, fallback_seconds: float | None = None
) -> dict[str, Any]:
    """Spec-0084/T3: validate known metadata; prose never supplies the deadline."""
    import math
    import tomllib

    execution = dict(package.get("execution") or {})
    seconds = execution.get("budget_seconds")
    source = execution.get("budget_source")
    if execution and (
        type(seconds) not in (int, float)
        or not math.isfinite(seconds)
        or seconds <= 0
        or source not in {"task_metadata", "operator_quota"}
    ):
        raise ConfigError(
            "Task execution requires a positive budget_seconds and declared budget_source"
        )
    metadata_seconds = None
    if source_root is not None:
        metadata = source_root / "task.toml"
        if metadata.is_file():
            if metadata.is_symlink() or not metadata.resolve().is_relative_to(
                source_root.resolve()
            ):
                raise ConfigError("Task metadata escapes source root")
            try:
                document = tomllib.loads(metadata.read_text())
                metadata_seconds = document.get("agent", {}).get("timeout_sec")
            except (ValueError, OSError) as exc:
                raise ConfigError("Invalid task.toml execution metadata") from exc
            if metadata_seconds is not None and (
                type(metadata_seconds) not in (int, float)
                or not math.isfinite(metadata_seconds)
                or metadata_seconds <= 0
            ):
                raise ConfigError("task.toml agent.timeout_sec must be positive finite seconds")
    selected_seconds = seconds if seconds is not None else fallback_seconds
    if (
        selected_seconds is not None
        and metadata_seconds is not None
        and selected_seconds != metadata_seconds
    ):
        if source != "operator_quota" or not execution.get("quota_override_reason", "").strip():
            raise ConfigError(
                "Task budget conflicts with task.toml; declare operator_quota and quota_override_reason"
            )
    instruction = Path(package["instruction_file"])
    if selected_seconds is not None and instruction.is_file():
        text = instruction.read_text(encoding="utf-8")
        # A deliberately narrow lint, never a parser that selects a deadline.
        for match in re.finditer(
            r"\btime\s+limit\s*:\s*(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?)\b", text, re.I
        ):
            explicit = float(match[1]) * {"s": 1, "m": 60, "h": 3600}[match[2][0].lower()]
            if explicit != selected_seconds and not (
                source == "operator_quota" and execution.get("quota_override_reason", "").strip()
            ):
                raise ConfigError(
                    "Explicit instruction time limit conflicts with execution budget; fix materials or declare a quota override"
                )
    return {
        **execution,
        "instruction_budget_verification": (
            "task_metadata_verified"
            if metadata_seconds is not None and selected_seconds == metadata_seconds
            else "operator_quota_override"
            if metadata_seconds is not None and selected_seconds is not None
            else "instruction_budget_unverified"
        ),
        "metadata_budget_seconds": metadata_seconds,
    }


def execution_declaration(
    package: dict[str, Any], *, fallback_seconds: float | None
) -> dict[str, Any]:
    """The frozen task budget takes precedence over an operator runtime fallback."""
    declaration = dict(package.get("execution") or {})
    return {
        **declaration,
        "task_budget_seconds": declaration.get("budget_seconds", fallback_seconds),
        "budget_source": declaration.get(
            "budget_source", "operator_quota" if fallback_seconds is not None else "undeclared"
        ),
        "followup_input": "unavailable" if package.get("interaction") == "direct" else "possible",
        "instruction_budget_verification": "instruction_budget_unverified",
    }
