"""Spec-0073/T1: logical task catalog and session plan, independent of providers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from auto_designer.experiment.config import ConfigError, config_hash, read_json_document

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
    from auto_designer.experiment.context import material_path

    return material_path(run_dir, manifest, key)


def read_task_catalog(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if (
        type(manifest.get("workload_contract_version")) is not int
        or manifest["workload_contract_version"] != CONTRACT_VERSION
    ):
        raise ConfigError("Unknown or missing workload_contract_version")
    from auto_designer.experiment.materials import sha256_file

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
    from auto_designer.experiment.materials import sha256_file

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
