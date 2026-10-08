"""Spec-0083/T5: freeze private grading plans before dispatch or allocation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from auto_designer.evaluation.contracts import MAX_INPUT_BYTES
from auto_designer.experiment.config import ConfigError


@dataclass(frozen=True)
class GradingPlan:
    document: dict
    digest: str
    payload: bytes
    materials: dict[str, dict]

    def selections(self, known_tasks: set[str]) -> dict[str, dict]:
        result = {}
        for grader in self.document["graders"]:
            for task_id in grader["task_ids"]:
                if task_id not in known_tasks:
                    raise ConfigError(f"Grading plan references unknown task: {task_id}")
                if task_id in result:
                    raise ConfigError(f"Grading plan selects task more than once: {task_id}")
                result[task_id] = grader
        return result


def _unique(pairs: list[tuple[str, Any]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ConfigError(f"Duplicate grading plan JSON key: {key}")
        value[key] = item
    return value


def read_material(path: Path, expected: str) -> bytes:
    path = path.expanduser().absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ConfigError("Grading material path contains a symlink")
    if not path.is_file():
        raise ConfigError(f"Grading material missing or not a regular file: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ConfigError("Grading material must be a regular file")
        if before.st_size > MAX_INPUT_BYTES:
            raise ConfigError("Grading material exceeds the 256 MiB execution limit")
        data = stream.read(MAX_INPUT_BYTES + 1)
        after = os.fstat(stream.fileno())
        if len(data) > MAX_INPUT_BYTES:
            raise ConfigError("Grading material exceeds the 256 MiB execution limit")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(data) != after.st_size:
            raise ConfigError("Grading material changed while reading")
    if hashlib.sha256(data).hexdigest() != expected:
        raise ConfigError(f"Grading material SHA-256 mismatch: {path.name}")
    return data


def load_grading_plan(path: Path) -> GradingPlan:
    path = path.expanduser().absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ConfigError("Grading plan path contains a symlink")
    try:
        payload = path.read_bytes()
        document = json.loads(payload, object_pairs_hook=_unique)
        schema = json.loads((Path(__file__).parent / "schemas/grading-plan-v1.json").read_text())
        jsonschema.Draft202012Validator(schema).validate(document)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        raise ConfigError(f"Invalid grading plan: {getattr(exc, 'message', str(exc))}") from exc
    records = {}
    for name, material in document["materials"].items():
        material_path = Path(material["path"]).expanduser()
        if not material_path.is_absolute():
            material_path = path.parent / material_path
        material_path = material_path.absolute()
        records[name] = {
            "path": material_path,
            "sha256": material["sha256"],
            "payload": read_material(material_path, material["sha256"]),
        }
    for grader in document["graders"]:
        for name in grader["inputs"].values():
            if name not in records:
                raise ConfigError(f"Unknown grading material reference: {name}")
    return GradingPlan(document, hashlib.sha256(payload).hexdigest(), payload, records)


def archived_artifacts(
    *, receipt: dict | None, provenance: dict, declarations: list[dict], files: dict[str, bytes]
) -> dict[str, dict]:
    """Verify original receipt ownership, declarations and exact retained bytes."""
    if receipt is None:
        return {}
    if not isinstance(receipt, dict) or receipt.get("contract_version") != 1:
        raise ConfigError("Invalid session artifact receipt")
    expected = {
        key: provenance[key]
        for key in ("run_id", "round_no", "slot", "task_id", "task_digest", "harness_sha")
    }
    expected["session_id"] = provenance["session_id"]
    if json.dumps(receipt.get("identity"), sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ConfigError("Session artifact receipt ownership mismatch")
    entries = receipt.get("entries")
    if not isinstance(entries, list):
        raise ConfigError("Malformed session artifact entries")
    declared = {item["id"]: item for item in declarations}
    if len(entries) != len(declared):
        raise ConfigError("Session artifact receipt differs from public declarations")
    result, seen = {}, set()
    for item in entries:
        if not isinstance(item, dict) or item.get("id") not in declared or item["id"] in seen:
            raise ConfigError("Unknown or duplicate session artifact receipt")
        name = item["id"]
        seen.add(name)
        declaration = declared[name]
        if any(
            item.get(key) != declaration[key]
            for key in ("source", "content_type", "required", "max_bytes")
        ):
            raise ConfigError("Artifact receipt differs from frozen declaration")
        if item.get("status") != "collected":
            continue
        # Current backends have no independent managed-service ownership boundary.
        if declaration["source"] != "workspace":
            raise ConfigError("Managed measurement cannot be verified on this runtime version")
        relative = f"evaluation-artifacts/{provenance['session_id']}/{receipt['attempt_id']}/{name}"
        if (
            not re.fullmatch(r"[0-9a-f]{32}", str(receipt.get("attempt_id", "")))
            or item.get("path") != relative
        ):
            raise ConfigError("Unsafe session artifact receipt path")
        archive_path = f"data/role_runs/{provenance['run_id']}/{relative}"
        if archive_path not in files:
            raise ConfigError("Collected artifact is missing from archive")
        payload = files[archive_path]
        if (
            type(item.get("bytes")) is not int
            or item["bytes"] != len(payload)
            or len(payload) > declaration["max_bytes"]
            or hashlib.sha256(payload).hexdigest() != item.get("sha256")
        ):
            raise ConfigError("Collected artifact bytes/digest mismatch")
        result[name] = {**item, "payload": payload}
    if receipt.get("complete") is not all(
        not row.get("required") or row.get("status") == "collected" for row in entries
    ):
        raise ConfigError("Artifact completeness receipt is inconsistent")
    return result
