"""Shared request construction and verified result normalization (Spec-0084/T5).

Callers establish their own immutable source: a complete collected run or a sealed
session bundle. Neither caller can disable the other's provenance checks.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path

from ahe_beta.evaluation.contracts import (
    ArtifactInput,
    GradingRequest,
    InputValidationError,
    MaterialInput,
)
from ahe_beta.evaluation.registry import get_adapter
from ahe_beta.evaluation.results import EXECUTION_CONTRACTS
from ahe_beta.execution_contract import canonical_sha256
from ahe_beta.experiment.config import ConfigError

_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def implementation_digest() -> str:
    root = Path(__file__).parent
    return canonical_sha256(
        {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.py"))
        }
    )


def _json(payload: bytes, label: str):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    try:
        return json.loads(payload, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise ConfigError(f"Invalid JSON grading input: {label}") from exc


def _dataset(path: Path, expected_sha: str) -> tuple[list[dict], bytes]:
    if not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha):
        raise ConfigError("dataset_sha256 must be a lowercase SHA-256")
    path = path.expanduser().absolute()
    if path.is_symlink() or any(part.is_symlink() for part in path.parents):
        raise ConfigError("Dataset path contains a symlink")
    try:
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected_sha:
            raise ConfigError("Dataset SHA-256 mismatch")
        if path.suffix == ".json":
            decoded = _json(payload, "dataset")
            rows = decoded if isinstance(decoded, list) else [decoded]
        elif path.suffix == ".jsonl":
            rows = [
                _json(line, "dataset JSONL row") for line in payload.splitlines() if line.strip()
            ]
        elif path.suffix == ".parquet":
            try:
                import pyarrow.parquet as parquet
            except ImportError as exc:
                raise ConfigError("Parquet dataset requires the evaluation extra") from exc
            rows = parquet.read_table(io.BytesIO(payload)).to_pylist()
        else:
            raise ConfigError("Dataset must be JSON, JSONL or parquet")
        if path.read_bytes() != payload:
            raise ConfigError("Dataset changed while reading")
    except OSError as exc:
        raise ConfigError("Dataset file cannot be read") from exc
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise ConfigError("Dataset must contain nonempty official row objects")
    if any(not isinstance(row.get("instance_id"), str) or not row["instance_id"] for row in rows):
        raise ConfigError("Dataset rows require instance_id")
    return rows, payload


def _official_row(rows: list[dict], task: dict, *, frozen_source: bool = True) -> dict:
    matches = [row for row in rows if row["instance_id"] == task["id"]]
    if len(matches) != 1:
        raise ConfigError(f"Dataset must uniquely match selected instance: {task['id']}")
    row = matches[0]
    source = task["package"].get("source", {})
    if (
        source.get("kind") != "git"
        or not isinstance(source.get("repo"), str)
        or row.get("repo") != source["repo"]
        or not isinstance(row.get("base_commit"), str)
        or not _COMMIT.fullmatch(row["base_commit"])
        or row["base_commit"] != source.get("revision")
        or (frozen_source and row["base_commit"] != task["source_snapshot"].get("revision"))
    ):
        raise ConfigError(f"Dataset repo/base_commit differs from frozen task: {task['id']}")
    # These fields are consumed by the official runner, never the experiment.
    for field in ("patch", "test_patch", "version", "FAIL_TO_PASS", "PASS_TO_PASS"):
        if field not in row:
            raise ConfigError(f"Official dataset row is missing required field: {field}")
    if any(not isinstance(row[field], str) for field in ("patch", "test_patch", "version")):
        raise ConfigError("Official dataset patch/test_patch/version fields must be strings")
    for field in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        values = _json(row[field].encode(), field) if isinstance(row[field], str) else row[field]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ConfigError("Official dataset test lists are malformed")
    return row


def task_source(task: dict) -> dict:
    package = task["package"]
    if task["kind"] == "benchmark":
        return {**package.get("source", {}), **package["benchmark"]}
    return {**package.get("source", {}), "suite": task["kind"], "instance_id": task["id"]}


def _plan_metadata(*, task: dict, plan, selection: dict, frozen_source: bool = True):
    origin = task_source(task)
    if selection["adapter"] != "custom" and origin["suite"] != selection["adapter"]:
        raise ConfigError("Grading adapter differs from frozen benchmark source")
    materials = {name: plan.materials[ref] for name, ref in selection["inputs"].items()}
    config = dict(selection.get("config", {}))
    if selection["adapter"] == "swebench":
        if "dataset" not in materials:
            raise ConfigError("SWE adapter requires inputs.dataset")
        material = materials["dataset"]
        rows, _ = _dataset(material["path"], material["sha256"])
        config["official_dataset_row"] = _official_row(rows, task, frozen_source=frozen_source)
    return origin, materials, config


def preflight_plan(*, task: dict, plan, selection: dict) -> None:
    """Validate private rules and public exports before any Actor is launched.

    This metadata-only request has no session or output artifacts. Adapters only
    run their static plan validation here; runtime artifact validation remains
    mandatory when actual sealed outputs are available.
    """
    if "package" not in task:
        task = {"id": task["id"], "kind": task["kind"], "package": task}
    try:
        adapter = get_adapter(selection["adapter"], selection["contract_version"])
        origin, materials, config = _plan_metadata(
            task=task, plan=plan, selection=selection, frozen_source="source_snapshot" in task
        )
        request = GradingRequest(
            adapter=selection["adapter"],
            contract_version=selection["contract_version"],
            task_id=task["id"],
            task_digest=task.get("digest", ""),
            session_id="",
            source=origin,
            materials={
                name: MaterialInput(path=item["path"], sha256=item["sha256"])
                for name, item in materials.items()
            },
            config=config,
            timeout_seconds=selection["timeout_seconds"],
            plan_digest=plan.digest,
            instance_id=origin["instance_id"],
        )
        required = adapter.validate_plan(request)
        declarations = {
            item["id"]: item for item in task["package"].get("artifacts", {}).get("exports", [])
        }
        if any(item["source"] != "workspace" for item in declarations.values()) or any(
            source != "workspace" for source in required.values()
        ):
            raise ConfigError("Online grading cannot reproduce managed service evidence")
        for name, source in required.items():
            if name not in declarations or declarations[name]["source"] != source:
                raise ConfigError(f"Grader input has no matching public artifact export: {name}")
    except (ValueError, TypeError, KeyError) as exc:
        raise ConfigError(f"Invalid {selection['adapter']} online grading plan: {exc}") from exc


def build_request(
    *, task: dict, session: dict, outputs: dict, plan, selection: dict, patch: str = ""
) -> GradingRequest:
    adapter = get_adapter(selection["adapter"], selection["contract_version"])
    origin, materials, config = _plan_metadata(task=task, plan=plan, selection=selection)
    declarations = task["package"].get("artifacts", {}).get("exports", [])
    missing = [
        item["id"] for item in declarations if item["required"] and item["id"] not in outputs
    ]
    if missing:
        raise InputValidationError(
            "missing_required_outputs: " + ",".join(missing), status="missing_artifact"
        )
    request = GradingRequest(
        adapter=selection["adapter"],
        contract_version=selection["contract_version"],
        task_id=task["id"],
        task_digest=task["digest"],
        session_id=session["session_id"],
        source=origin,
        artifacts={
            name: ArtifactInput(
                path=Path(item["path"]),
                sha256=item["sha256"],
                bytes=item["bytes"],
                source=item["source"],
                metadata={k: v for k, v in item.items() if k != "payload"},
                payload=item["payload"],
            )
            for name, item in outputs.items()
        },
        materials={
            name: MaterialInput(path=item["path"], sha256=item["sha256"])
            for name, item in materials.items()
        },
        config=config,
        timeout_seconds=selection["timeout_seconds"],
        plan_digest=plan.digest,
        instance_id=origin["instance_id"],
        patch=patch,
        session=session,
    )
    try:
        adapter.validate_inputs(request)
    except InputValidationError:
        raise
    except ValueError as exc:
        raise ConfigError(f"Invalid {selection['adapter']} grading inputs: {exc}") from exc
    return request


def evaluate_request(request: GradingRequest, attempt_dir: Path) -> dict:
    try:
        adapter = get_adapter(request.adapter, request.contract_version)
        adapter.validate_inputs(request)
        result = adapter.evaluate(request, attempt_dir).to_dict()
        execution = result.get("execution") or {}
        if result.get("status") == "completed" and (
            execution.get("contract") not in EXECUTION_CONTRACTS
            or execution.get("verified") is not True
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(execution.get("image_digest")))
        ):
            result = {
                **result,
                "status": "ungradable",
                "passed": None,
                "score": None,
                "reason": "execution_contract_not_verified",
            }
        if result.get("status") != "completed":
            result.update(passed=None, score=None)
        return result
    except InputValidationError as exc:
        return {
            "adapter": request.adapter,
            "contract_version": request.contract_version,
            "status": exc.status,
            "passed": None,
            "score": None,
            "reason": str(exc),
        }
    except Exception as exc:
        return {
            "adapter": request.adapter,
            "contract_version": request.contract_version,
            "status": "crashed",
            "passed": None,
            "score": None,
            "reason": type(exc).__name__,
        }
