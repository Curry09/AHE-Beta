"""Spec-0074/T1: strict batch inputs and identities using the existing material compiler."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from auto_designer.experiment import materials
from auto_designer.experiment.config import (
    ConfigError,
    config_hash,
    read_json_document,
    resolve_input_path,
    validate_schema,
)


def load_batch_config(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    value = read_json_document(path=source)
    validate_schema(document=value, schema_name="batch-v1.json")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ConfigError("Batch schema_version must be integer 1")
    limit = value.get("max_parallel_runs", 1)
    if type(limit) is not int or limit < 1:
        raise ConfigError("max_parallel_runs must be a positive integer")
    if not value["name"].strip():
        raise ConfigError("Batch name must not be blank")
    seen = set()
    backends = set()
    entries = []
    for entry in value["entries"]:
        if entry["id"] in seen:
            raise ConfigError("Batch entry IDs must be unique")
        seen.add(entry["id"])
        config_path = resolve_input_path(value=entry["config"], base=source.parent)
        description = describe_entry(config_path)
        backends.add(description["config"]["runtime"]["backend"])
        entries.append({"id": entry["id"], "config_path": config_path, **description})
    if len(backends) != 1:
        raise ConfigError("A batch must use one backend")
    return {
        "schema_version": 1,
        "name": value["name"],
        "max_parallel_runs": limit,
        "backend": backends.pop(),
        "entries": entries,
    }


def describe_entry(config_path: str | Path) -> dict[str, Any]:
    """Hash actual local input contents without fetching fixed Git task sources."""
    report = materials.check_materials(config_path)
    tasks = []
    for original in report["task_packages"]:
        task = copy.deepcopy(original)
        hashes = {
            "instruction": materials.sha256_file(task.pop("instruction_file")),
            **{name: materials.sha256_file(path) for name, path in task.pop("setup").items()},
        }
        source_files = None
        if task["source"]["kind"] == "local":
            # Match the compiler's exclusion/symlink rules rather than invent another snapshot.
            source_files = materials._snapshot_files(
                root=Path(task["source"].pop("path")), paths=None
            )
        tasks.append({"package": task, "content_hashes": hashes, "source_files": source_files})
    controller = materials._controller_root()
    harness = report["config"]["harness"]
    identity = {
        "config_hash": report["config_hash"],
        "persona_hash": config_hash(data={"cards": report["persona_cards"]}),
        "tasks": tasks,
        "controller_files": materials._snapshot_files(
            root=controller, paths=list(materials._SOURCE_ROOTS)
        ),
        "harness": (
            {"archive_sha256": materials.sha256_file(harness["archive"])}
            if harness["source"] == "archive"
            else {
                "files": materials._snapshot_files(
                    root=controller / "backend/harness_template", paths=None
                )
            }
        ),
    }
    return {
        "config": report["config"],
        "input_identity": identity,
        "input_hash": config_hash(data=identity),
    }


def verify_entry_inputs(entry: dict[str, Any]) -> None:
    actual = describe_entry(entry["config_path"])
    if actual["input_hash"] != entry["input_hash"]:
        raise ConfigError(f"Batch inputs changed for {entry['id']}; create a new batch")
