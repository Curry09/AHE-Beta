"""Spec-0083/T5: grade immutable collected sessions without resuming an experiment."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import re
import tarfile
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from auto_designer.evaluation.acceptance import derive_acceptance_assessment
from auto_designer.evaluation.contracts import (
    ArtifactInput,
    GradingRequest,
    InputValidationError,
    MaterialInput,
)
from auto_designer.evaluation.registry import get_adapter
from auto_designer.evaluation.results import EXECUTION_CONTRACTS
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.grading_inputs import archived_artifacts, load_grading_plan
from auto_designer.experiment.manifest import recovery_identity
from auto_designer.experiment.materials import sha256_file, verify_materials
from auto_designer.experiment.runtime import load_run_v2
from auto_designer.experiment.workload import read_session_plan, tasks_by_id
from auto_designer.loop.recovery import RecoveryError, digest_value, operation_key
from auto_designer.models import Session, validate_session_provenance

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _safe_file(path: Path, root: Path) -> None:
    if not path.is_relative_to(root):
        raise ConfigError("Grading input escapes its root")
    if any(part.is_symlink() for part in [path, *path.parents] if part.is_relative_to(root)):
        raise ConfigError("Grading input contains a symlink")
    if not path.is_file():
        raise ConfigError(f"Grading input missing: {path.name}")


@contextmanager
def _operation_read(run_dir: Path):
    """Participate briefly in the existing lifecycle lock without creating files."""
    path = run_dir / "runtime/operation.lock"
    _safe_file(path, run_dir)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConfigError(
                "Lifecycle operation in progress; grading inputs are uncertain"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _host_snapshot(run_dir: Path) -> dict:
    """Project current known generation, ignoring harmless heartbeat/status timestamps."""
    path = run_dir / "runtime.json"
    _safe_file(path, run_dir)
    runtime = _object(path.read_bytes(), "current runtime")
    if (
        runtime.get("experiment_state") not in {"COMPLETED", "STOPPED", "FAILED"}
        or runtime.get("collection_state") != "COMPLETE"
        or runtime.get("observation") not in {"KNOWN", "OBSERVED"}
        or runtime.get("resource_state") in {"PROVISIONING", "LOST", "UNKNOWN"}
    ):
        raise ConfigError("Grading requires current terminal runtime and COMPLETE collection")
    controllers = {}
    for key in ("provider", "launch_receipt"):
        value = runtime.get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ConfigError("Invalid current controller receipt")
        controller = value.get("controller", value)
        if not isinstance(controller, dict):
            raise ConfigError("Invalid current nested controller receipt")
        if key == "provider" and value.get("observation") == "UNKNOWN":
            raise ConfigError("Current provider observation is uncertain")
        if "nonce" not in controller and "state" not in controller:
            continue
        if not isinstance(controller.get("nonce"), str) or not controller["nonce"]:
            raise ConfigError("Current controller receipt has no known nonce")
        if key == "provider" and (
            controller.get("state") not in {"STOPPED", "EXITED"}
            or controller.get("running") is not False
        ):
            raise ConfigError("Current provider controller is active or uncertain")
        controllers[key] = {
            "nonce": controller["nonce"],
            "command_identity": controller.get("command_identity"),
        }
    for name in ("controller.json", "controller-exit.json"):
        path = run_dir / "runtime" / name
        if path.exists() or path.is_symlink():
            _safe_file(path, run_dir)
            value = _object(path.read_bytes(), "current engine receipt")
            if not isinstance(value.get("nonce"), str) or not value["nonce"]:
                raise ConfigError("Current engine receipt has no known nonce")
            controllers[name] = {
                "nonce": value["nonce"],
                "command_identity": value.get("command_identity"),
            }
    receipt_path = run_dir / "archive/collection.json"
    _safe_file(receipt_path, run_dir)
    receipt = _object(receipt_path.read_bytes(), "current collection receipt")
    collected = runtime.get("collection")
    if collected is not None and (
        not isinstance(collected, dict)
        or collected.get("archive_sha256") != receipt.get("archive_sha256")
        or collected.get("collection_state") != "COMPLETE"
    ):
        raise ConfigError("Current collection receipt differs from retained archive")
    manifest_path = run_dir / "manifest.json"
    _safe_file(manifest_path, run_dir)
    return {
        "experiment_state": runtime["experiment_state"],
        "collection_state": runtime["collection_state"],
        "resource_state": runtime.get("resource_state"),
        "controllers": controllers,
        "archive_sha256": receipt.get("archive_sha256"),
        "manifest_sha256": sha256_file(manifest_path),
    }


def _assert_host_current(run_dir: Path, expected: dict, receipt: dict) -> None:
    current = _host_snapshot(run_dir)
    if current != expected:
        raise ConfigError("Current run generation changed during grading")
    observed = receipt["controller"]
    controller = observed.get("controller", observed)
    if current["archive_sha256"] != receipt["archive_sha256"]:
        raise ConfigError("Current archive generation differs from grading input")
    for value in current["controllers"].values():
        if value["nonce"] != controller["nonce"] or (
            value["command_identity"] is not None
            and value["command_identity"] != controller.get("command_identity")
        ):
            raise ConfigError("Current controller nonce differs from collected archive")
    archive = run_dir / "archive/artifacts.tar.gz"
    _safe_file(archive, run_dir)
    if sha256_file(archive) != receipt["archive_sha256"]:
        raise ConfigError("Collected archive changed during grading")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(payload, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise ConfigError(f"Invalid JSON grading input: {label}") from exc


def _object(payload: bytes, label: str) -> dict:
    value = _json(payload, label)
    if not isinstance(value, dict):
        raise ConfigError(f"Expected JSON object: {label}")
    return value


def _archive(run_dir: Path, manifest: dict) -> tuple[dict, dict[str, bytes]]:
    receipt_path = run_dir / "archive/collection.json"
    archive_path = run_dir / "archive/artifacts.tar.gz"
    for path in (receipt_path, archive_path):
        _safe_file(path, run_dir)
    receipt = _object(receipt_path.read_bytes(), "collection receipt")
    if (
        receipt.get("collection_state") != "COMPLETE"
        or receipt.get("consistent") is not True
        or receipt.get("terminal") is not True
        or receipt.get("run_id") != manifest["run_id"]
        or receipt.get("config_hash") != manifest["config_hash"]
    ):
        raise ConfigError("Grading requires a matching terminal COMPLETE collection")
    archive_hash = receipt.get("archive_sha256")
    if not isinstance(archive_hash, str) or not _SHA.fullmatch(archive_hash):
        raise ConfigError("Collection has no valid archive SHA-256")
    inventory = receipt.get("files")
    if not isinstance(inventory, dict) or "collection.json" in inventory:
        raise ConfigError("Invalid collection file inventory")
    retained: dict[str, bytes] = {}
    actual = {}
    try:
        with archive_path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != archive_hash:
                raise ConfigError("Collected archive SHA-256 mismatch")
            handle.seek(0)
            with tarfile.open(fileobj=handle, mode="r:gz") as archive:
                for member in archive:
                    name = member.name
                    path = PurePosixPath(name)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or "\\" in name
                        or path.as_posix() != name
                        or not name
                        or not member.isfile()
                        or name in actual
                    ):
                        raise ConfigError("Unsafe or duplicate collected archive member")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ConfigError("Unreadable archive member")
                    with stream:
                        payload = stream.read()
                    actual[name] = hashlib.sha256(payload).hexdigest()
                    if (
                        name in {"collection.json", "manifest.json", "checkpoints/recovery.json"}
                        or name.startswith("runtime/controller")
                        or name.startswith("checkpoints/recovery-receipts/")
                        or name.startswith(f"data/role_runs/{manifest['run_id']}/sessions/")
                        or name.startswith(f"data/role_runs/{manifest['run_id']}/predictions/")
                        or name.startswith(
                            f"data/role_runs/{manifest['run_id']}/evaluation-artifacts/"
                        )
                    ):
                        retained[name] = payload
            handle.seek(0)
            if hashlib.file_digest(handle, "sha256").hexdigest() != archive_hash:
                raise ConfigError("Collected archive changed while reading")
    except (OSError, tarfile.TarError) as exc:
        raise ConfigError("Invalid collected archive") from exc
    if set(actual) != set(inventory) | {"collection.json"} or any(
        not isinstance(digest, str) or actual[name] != digest for name, digest in inventory.items()
    ):
        raise ConfigError("Collected archive file inventory mismatch")
    internal = _object(retained["collection.json"], "internal collection")
    if internal != {
        key: value for key, value in receipt.items() if key not in {"archive", "archive_sha256"}
    }:
        raise ConfigError("Internal and external collection receipts differ")
    host_manifest = run_dir / "manifest.json"
    if actual.get("manifest.json") != sha256_file(host_manifest):
        raise ConfigError("Archived manifest differs from the immutable run")
    for record in manifest["materials"].values():
        if actual.get(record["path"]) != record["sha256"]:
            raise ConfigError("Archived frozen material hash mismatch")
    return receipt, retained


def _terminal(receipt: dict, files: dict[str, bytes]) -> None:
    observation = receipt.get("controller")
    if not isinstance(observation, dict):
        raise ConfigError("Collection lacks terminal controller observation")
    controller = observation.get("controller", observation)
    if (
        not isinstance(controller, dict)
        or not isinstance(controller.get("nonce"), str)
        or not controller["nonce"]
        or controller.get("running") is not False
        or controller.get("state") not in {"STOPPED", "EXITED"}
    ):
        raise ConfigError("Collection controller is not explicitly terminal")
    try:
        launch = _object(files["runtime/controller.json"], "controller launch")
        exit_receipt = _object(files["runtime/controller-exit.json"], "controller exit")
    except KeyError as exc:
        raise ConfigError("Archive lacks authoritative controller launch/exit receipts") from exc
    if (
        launch.get("nonce") != controller["nonce"]
        or exit_receipt.get("nonce") != controller["nonce"]
        or exit_receipt.get("state") != controller["state"]
        or not isinstance(launch.get("command_identity"), str)
        or not launch["command_identity"]
        or launch["command_identity"] != exit_receipt.get("command_identity")
        or controller.get("command_identity") != launch["command_identity"]
        or exit_receipt.get("cleanup_complete") is not True
        or type(exit_receipt.get("residual_processes")) is not int
        or exit_receipt.get("residual_processes") != 0
    ):
        raise ConfigError("Controller terminal nonce/identity/cleanup mismatch")


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


def _official_row(rows: list[dict], task: dict) -> dict:
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
        or row["base_commit"] != task["source_snapshot"].get("revision")
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


def _session_entry(
    *, binding: dict, task: dict, round_state: dict, files: dict[str, bytes], manifest: dict
) -> tuple[dict, str | None]:
    run_id = manifest["run_id"]
    session_id = operation_key(run_id, "users", binding)
    users = round_state["stages"].get("users", {})
    unit = users.get("units", {}).get(session_id)
    if (
        users.get("status") != "completed"
        or not isinstance(unit, dict)
        or unit.get("status") != "completed"
        or unit.get("input") != {"binding": binding, "user_sha": round_state["user_sha"]}
        or unit.get("input_digest")
        != digest_value({"binding": binding, "user_sha": round_state["user_sha"]})
        or unit.get("observed_postconditions", {}).get("completed") is not True
        or unit.get("observed_postconditions", {}).get("session_id") != session_id
    ):
        raise ConfigError("Archived user unit differs from frozen session binding")
    relative = f"data/role_runs/{run_id}/sessions/{session_id}.json"
    try:
        document = _object(files[relative], "session")
        session = Session.from_dict(document)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("Missing or malformed authoritative session") from exc
    expected = {
        "contract_version": 1,
        "run_id": run_id,
        **{
            key: binding[key]
            for key in ("round_no", "slot", "persona_id", "task_id", "task_digest", "interaction")
        },
        "task_kind": task["kind"],
        "harness_sha": round_state["user_sha"],
    }
    try:
        validate_session_provenance(session, expected)
    except ValueError as exc:
        raise ConfigError("Archived session provenance mismatch") from exc
    if session.session_id != session_id:
        raise ConfigError("Archived session ID mismatch")
    output_relative = unit.get("output_artifact")
    if output_relative != f"recovery-receipts/{binding['round_no']}/users/{session_id}.json":
        raise ConfigError("Recovery user receipt path mismatch")
    try:
        output = _object(files[f"checkpoints/{output_relative}"], "user recovery receipt")
    except KeyError as exc:
        raise ConfigError("Missing user recovery receipt") from exc
    saved = output.get("output")
    if (
        type(output.get("schema_version")) is not int
        or output["schema_version"] != 1
        or output.get("round") != binding["round_no"]
        or output.get("stage") != "users"
        or output.get("operation_key") != session_id
        or output.get("input_digest") != unit.get("input_digest")
        or output.get("output_digest") != unit.get("output_digest")
        or not isinstance(saved, dict)
        or digest_value(saved) != unit.get("output_digest")
        or saved.get("session_id") != session_id
        or digest_value(saved.get("session_provenance")) != digest_value(expected)
    ):
        raise ConfigError("User recovery receipt digest/identity/provenance mismatch")
    # The recovery serializer represents datetimes differently from SessionStore.
    # Compare the stable task/prediction fields, never fabricate a serialized session.
    defaults = {
        "persona": {},
        "scenario": {},
        "workspace_evidence": {},
        "user_outcome": {},
        "request_outcomes": [],
        "accept_validity": "not_applicable",
    }
    for field, default in defaults.items():
        if saved.get(field, default) != document.get(field, default):
            raise ConfigError("Session differs from immutable recovery output")
    saved_trace = saved.get("sim_trace")
    document_trace = document.get("sim_trace")
    if (saved_trace is None) != (document_trace is None):
        raise ConfigError("Session trace presence differs from immutable recovery output")
    if saved_trace is not None:
        if not isinstance(saved_trace, dict) or not isinstance(document_trace, dict):
            raise ConfigError("Malformed session eligibility trace")
        trace_defaults = {"evaluation_status": "valid", "interaction_status": "completed"}
        for field, default in trace_defaults.items():
            if saved_trace.get(field, default) != document_trace.get(field, default):
                raise ConfigError(
                    "Session trace eligibility differs from immutable recovery output"
                )
    entry = {
        **expected,
        "session_id": session_id,
        "status": "ready",
        "_session": document,
        "passed": None,
        "user_outcome": session.user_outcome,
        "accept_validity": session.accept_validity,
        "evaluation_status": session.sim_trace.evaluation_status if session.sim_trace else "valid",
        "interaction_status": session.sim_trace.interaction_status
        if session.sim_trace
        else session.user_outcome.get("status", "completed"),
    }
    if (
        entry["evaluation_status"] != "valid"
        or entry["interaction_status"] not in {"completed", "protocol_repaired"}
        or session.user_outcome.get("review_status", "completed") != "completed"
    ):
        return {
            **entry,
            "status": "ungradable",
            "reason": "invalid_or_infrastructure_session",
        }, None
    evidence = session.workspace_evidence
    prediction = evidence.get("prediction")
    if prediction is None:
        if task["kind"] != "swebench":
            return entry, None
        return {**entry, "status": "ungradable", "reason": "missing_prediction"}, None
    if not evidence.get("diff_base_commit"):
        if task["kind"] != "swebench":
            return entry, None
        return {**entry, "status": "ungradable", "reason": "missing_prediction_base"}, None
    if task["kind"] == "swebench" and (
        evidence["diff_base_commit"] != task["source_snapshot"].get("revision")
        or evidence["diff_base_commit"] != task["package"].get("source", {}).get("revision")
    ):
        raise ConfigError("Prediction base differs from frozen task baseline")
    if (
        not isinstance(prediction, dict)
        or set(prediction) != {"contract_version", "session_id", "path", "sha256", "bytes"}
        or type(prediction.get("contract_version")) is not int
        or prediction["contract_version"] != 1
        or prediction.get("session_id") != session_id
        or prediction.get("path") != f"predictions/{session_id}.patch"
        or not isinstance(prediction.get("sha256"), str)
        or not _SHA.fullmatch(prediction["sha256"])
        or type(prediction.get("bytes")) is not int
        or prediction["bytes"] < 0
    ):
        raise ConfigError("Invalid immutable prediction receipt")
    try:
        payload = files[f"data/role_runs/{run_id}/{prediction['path']}"]
    except KeyError as exc:
        raise ConfigError("Prediction receipt references a missing archive patch") from exc
    if (
        hashlib.sha256(payload).hexdigest() != prediction["sha256"]
        or len(payload) != prediction["bytes"]
        or evidence.get("diff_sha256") != prediction["sha256"]
        or evidence.get("patch_export_error")
        or evidence.get("prediction_export_error")
        or evidence.get("prediction_error")
        or evidence.get("diff_bytes") != len(payload)
    ):
        raise ConfigError("Prediction bytes/export evidence mismatch")
    try:
        patch = payload.decode("utf-8")
    except UnicodeError as exc:
        raise ConfigError("Prediction is not UTF-8") from exc
    return {**entry, "prediction": prediction}, patch


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _result(identity: dict, entries: list[dict], report_dir: Path | None, offline: bool) -> dict:
    counts = Counter(entry["status"] for entry in entries)
    return {
        **identity,
        "offline": offline,
        "ok": all(
            entry["status"] in {"not_configured", "ready" if offline else "completed"}
            for entry in entries
        ),
        "report_dir": str(report_dir) if report_dir else None,
        "entries": [
            {key: value for key, value in entry.items() if not key.startswith("_")}
            for entry in entries
        ],
        "summary": {
            "total": len(entries),
            "statuses": dict(counts),
            "passed": sum(entry.get("passed") is True for entry in entries),
            "failed": sum(
                entry.get("status") == "completed" and entry.get("passed") is False
                for entry in entries
            ),
        },
    }


def grade_run(
    *,
    run_id: str,
    plan: Path,
    root: Path | None = None,
    round_no: int | None = None,
    offline: bool = False,
) -> dict:
    """Spec-0083/T5: verify original archive once, dispatch a private frozen plan."""
    try:
        return _grade_run(
            run_id=run_id, plan_path=plan, root=root, round_no=round_no, offline=offline
        )
    except ConfigError:
        raise
    except (OSError, KeyError, TypeError, ValueError, RecoveryError) as exc:
        raise ConfigError("Malformed or unsupported collected grading inputs") from exc


def _source(task: dict) -> dict:
    package = task["package"]
    if task["kind"] == "benchmark":
        return {**package.get("source", {}), **package["benchmark"]}
    return {**package.get("source", {}), "suite": task["kind"], "instance_id": task["id"]}


def _grade_run(
    *, run_id: str, plan_path: Path, root: Path | None, round_no: int | None, offline: bool
) -> dict:
    grading_plan = load_grading_plan(Path(plan_path))
    run_dir, manifest = load_run_v2(run_id=run_id, root=root)
    if (
        type(manifest.get("schema_version")) is not int
        or manifest.get("workload_contract_version") != 1
    ):
        raise ConfigError("Grading requires schema 2/workload contract 1")
    with _operation_read(run_dir):
        host_snapshot = _host_snapshot(run_dir)
    _safe_file(run_dir / "manifest.json", run_dir)
    for record in manifest.get("materials", {}).values():
        _safe_file(run_dir / record["path"], run_dir)
    verify_materials(manifest)
    plan = read_session_plan(run_dir, manifest)
    catalog_path = run_dir / manifest["materials"]["task_catalog"]["path"]
    tasks = tasks_by_id(_object(catalog_path.read_bytes(), "task catalog"))
    selected = manifest["config"]["rounds"]["count"] if round_no is None else round_no
    if type(selected) is not int or not 1 <= selected <= len(plan["rounds"]):
        raise ConfigError("Selected grading round is outside the frozen plan")
    receipt, files = _archive(run_dir, manifest)
    _terminal(receipt, files)
    try:
        recovery = _object(files["checkpoints/recovery.json"], "recovery ledger")
    except KeyError as exc:
        raise ConfigError("Archive lacks recovery ledger") from exc
    if (
        type(recovery.get("schema_version")) is not int
        or recovery["schema_version"] != 1
        or recovery.get("identity") != recovery_identity(manifest)
    ):
        raise ConfigError("Archived recovery identity mismatch")
    round_state = recovery.get("rounds", {}).get(str(selected), {})
    bindings = plan["rounds"][selected - 1]
    if (
        round_state.get("status") != "completed"
        or round_state.get("plan") != bindings
        or round_state.get("plan_hash") != digest_value(bindings)
        or digest_value(round_state.get("plan")) != digest_value(bindings)
        or not isinstance(round_state.get("user_sha"), str)
        or not _COMMIT.fullmatch(round_state["user_sha"])
        or not isinstance(round_state.get("sealed_sha"), str)
        or not _COMMIT.fullmatch(round_state["sealed_sha"])
        or round_state.get("stages", {}).get("round_sealed", {}).get("status") != "completed"
    ):
        raise ConfigError("Selected grading round is not completely sealed/bound")
    seal_key = operation_key(selected, "round_sealed", "stage-marker")
    seal_input = {"user_sha": round_state["user_sha"], "sealed_sha": round_state["sealed_sha"]}
    seal_unit = round_state["stages"]["round_sealed"].get("units", {}).get(seal_key, {})
    if (
        seal_unit.get("status") != "completed"
        or seal_unit.get("input") != seal_input
        or seal_unit.get("input_digest") != digest_value(seal_input)
        or digest_value(seal_unit.get("input")) != digest_value(seal_input)
        or seal_unit.get("observed_postconditions", {}).get("completed") is not True
    ):
        raise ConfigError("Archived round seal unit does not bind its user/delivery SHA")
    selections = grading_plan.selections(set(tasks))
    entries, requests, adapters = [], {}, {}
    for binding in bindings:
        task = tasks[binding["task_id"]]
        entry, patch = _session_entry(
            binding=binding, task=task, round_state=round_state, files=files, manifest=manifest
        )
        entries.append(entry)
        selection = selections.get(task["id"])
        if selection is None:
            entry.update(status="not_configured", passed=None)
            continue
        entry.update(
            adapter=selection["adapter"], adapter_contract_version=selection["contract_version"]
        )
        if entry["status"] != "ready":
            continue
        try:
            adapter = get_adapter(selection["adapter"], selection["contract_version"])
        except ValueError as exc:
            entry.update(status="unsupported", reason=str(exc), passed=None)
            continue
        origin = _source(task)
        if selection["adapter"] != "custom" and origin["suite"] != selection["adapter"]:
            raise ConfigError("Grading adapter differs from frozen benchmark source")
        session = entry["_session"]
        declarations = task["package"].get("artifacts", {}).get("exports", [])
        outputs = archived_artifacts(
            receipt=session.get("workspace_evidence", {}).get("evaluation_artifacts"),
            provenance=entry,
            declarations=declarations,
            files=files,
        )
        frozen_materials = {
            name: grading_plan.materials[reference]
            for name, reference in selection["inputs"].items()
        }
        config = dict(selection.get("config", {}))
        if selection["adapter"] == "swebench":
            if "dataset" not in frozen_materials:
                raise ConfigError("SWE adapter requires inputs.dataset")
            material = frozen_materials["dataset"]
            rows, _ = _dataset(material["path"], material["sha256"])
            config["official_dataset_row"] = _official_row(rows, task)
        missing = [
            item["id"] for item in declarations if item["required"] and item["id"] not in outputs
        ]
        if missing:
            entry.update(
                status="missing_artifact", reason="missing_required_outputs: " + ",".join(missing)
            )
            continue
        request = GradingRequest(
            adapter=selection["adapter"],
            contract_version=selection["contract_version"],
            task_id=task["id"],
            task_digest=task["digest"],
            session_id=entry["session_id"],
            source=origin,
            artifacts={
                name: ArtifactInput(
                    path=Path(item["path"]),
                    sha256=item["sha256"],
                    bytes=item["bytes"],
                    source=item["source"],
                    metadata=item,
                    payload=item["payload"],
                )
                for name, item in outputs.items()
            },
            materials={
                name: MaterialInput(path=value["path"], sha256=value["sha256"])
                for name, value in frozen_materials.items()
            },
            config=config,
            timeout_seconds=selection["timeout_seconds"],
            plan_digest=grading_plan.digest,
            instance_id=origin["instance_id"],
            patch=patch or "",
            session=session,
        )
        try:
            adapter.validate_inputs(request)
        except InputValidationError as exc:
            entry.update(status=exc.status, reason=str(exc), passed=None)
            continue
        except ValueError as exc:
            raise ConfigError(f"Invalid {selection['adapter']} grading inputs: {exc}") from exc
        requests[entry["session_id"]] = (request, frozen_materials, outputs)
        adapters[entry["session_id"]] = adapter
    identity = {
        **recovery_identity(manifest),
        "catalog_hash": manifest["catalog_hash"],
        "archive_sha256": receipt["archive_sha256"],
        "manifest_sha256": sha256_file(run_dir / "manifest.json"),
        "plan_digest": grading_plan.digest,
        "round_no": selected,
        "user_sha": round_state["user_sha"],
        "sealed_sha": round_state["sealed_sha"],
        "grading_implementation": {
            path.relative_to(Path(__file__).parents[1]).as_posix(): sha256_file(path)
            for path in sorted(
                [Path(__file__), Path(__file__).with_name("grading_inputs.py")]
                + list((Path(__file__).parents[1] / "evaluation").rglob("*.py"))
            )
        },
    }
    for entry in entries:
        entry["acceptance_assessment"] = derive_acceptance_assessment(
            session=entry["_session"], result={"status": "not_evaluated", "passed": None}
        )
    with _operation_read(run_dir):
        _assert_host_current(run_dir, host_snapshot, receipt)
    if offline:
        result = _result(identity, entries, None, True)
        result["environment_status"] = "not_checked_offline"
        return result
    evaluation_root = run_dir / "evaluation"
    if evaluation_root.is_symlink() or any(parent.is_symlink() for parent in run_dir.parents):
        raise ConfigError("Unsafe evaluation output directory")
    evaluation_root.mkdir(mode=0o700, exist_ok=True)
    lock_path = evaluation_root / ".grading.lock"
    if lock_path.is_symlink():
        raise ConfigError("Unsafe grading lock")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with _operation_read(run_dir):
            _assert_host_current(run_dir, host_snapshot, receipt)
            attempt = (
                evaluation_root
                / f"grade-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
            )
            attempt.mkdir(mode=0o700)
            (attempt / "plan.json").write_bytes(grading_plan.payload)
            material_root = attempt / "materials"
            material_root.mkdir(mode=0o700)
            snapshots = {}
            for name, record in grading_plan.materials.items():
                # Original suffix matters for SWE JSON/JSONL/parquet and typed adapter inputs.
                destination = material_root / (name + record["path"].suffix)
                destination.write_bytes(record["payload"])
                destination.chmod(0o400)
                snapshots[name] = destination
            _write(
                attempt / "materials.json",
                {
                    name: {
                        "path": str(snapshots[name].relative_to(attempt)),
                        "sha256": record["sha256"],
                    }
                    for name, record in grading_plan.materials.items()
                },
            )
            _write(
                attempt / "intent.json",
                {
                    **identity,
                    "sessions": [
                        {
                            key: entry[key]
                            for key in ("session_id", "task_id", "harness_sha", "status")
                        }
                        for entry in entries
                    ],
                },
            )
        for entry in entries:
            if entry["status"] != "ready":
                entry["acceptance_assessment"] = derive_acceptance_assessment(
                    session=entry["_session"], result={"status": entry["status"], "passed": None}
                )
                continue
            from dataclasses import replace

            original, frozen_materials, outputs = requests[entry["session_id"]]
            session_root = attempt / entry["session_id"]
            session_root.mkdir(mode=0o700)
            artifact_root = session_root / "inputs"
            artifact_root.mkdir(mode=0o700)
            artifacts = {}
            for name, artifact in original.artifacts.items():
                path = artifact_root / name
                path.write_bytes(outputs[name]["payload"])
                path.chmod(0o400)
                artifacts[name] = replace(artifact, path=path)
            selection = selections[entry["task_id"]]
            request = replace(
                original,
                artifacts=artifacts,
                materials={
                    name: MaterialInput(
                        path=snapshots[reference], sha256=frozen_materials[name]["sha256"]
                    )
                    for name, reference in selection["inputs"].items()
                },
            )
            with _operation_read(run_dir):
                _assert_host_current(run_dir, host_snapshot, receipt)
            try:
                scored = adapters[entry["session_id"]].evaluate(request, session_root)
                result = scored.to_dict()
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
                        "reason": "execution_contract_not_verified",
                    }
            except Exception as exc:  # noqa: BLE001 - preserve failed scorer independently
                result = {
                    "adapter": request.adapter,
                    "contract_version": request.contract_version,
                    "status": "crashed",
                    "passed": None,
                    "reason": type(exc).__name__,
                }
            _write(session_root / "result.json", result)
            with _operation_read(run_dir):
                _assert_host_current(run_dir, host_snapshot, receipt)
            entry.update(
                status=result["status"],
                passed=result.get("passed"),
                evaluation=result,
                acceptance_assessment=derive_acceptance_assessment(
                    session=entry["_session"], result=result
                ),
            )
        result = _result(identity, entries, attempt, False)
        with _operation_read(run_dir):
            _assert_host_current(run_dir, host_snapshot, receipt)
            _write(attempt / "summary.json", result)
        return result
