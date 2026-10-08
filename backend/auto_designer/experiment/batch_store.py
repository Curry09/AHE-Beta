"""Spec-0074/T1: immutable batch intent, atomic receipts and owned child roots."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auto_designer.experiment import materials, runtime
from auto_designer.experiment.config import ConfigError, config_hash, read_json_document
from auto_designer.experiment.manifest import read_runtime
from auto_designer.experiment.workload import read_task_catalog

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_ENTRY_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class BatchRevisionConflict(ConfigError):
    """The caller must derive its state again from the newest control revision."""


def _secret_free(value: Any, location: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            inventory = location.rsplit(".", 1)[-1] in {"files", "controller_files", "source_files"}
            if (
                not inventory
                and re.search(r"token|password|secret|api[_-]?key|credential", key, re.I)
                and not key.endswith("_env")
            ):
                raise ConfigError("Credential-bearing field forbidden in batch receipts")
            _secret_free(item, f"{location}.{key}")
    elif isinstance(value, list):
        for item in value:
            _secret_free(item, location)
    elif isinstance(value, str) and value.startswith(("sk-", "gitea_")) and len(value) > 20:
        raise ConfigError("Possible credential forbidden in batch receipts")


def _safe_descendant(base: Path, path: Path) -> Path:
    relative = path.relative_to(base)
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ConfigError("Symbolic batch path rejected")
    if not path.resolve().is_relative_to(base.resolve()):
        raise ConfigError("Batch path escapes its root")
    return path


def _atomic(path: Path, payload: dict[str, Any], exclusive: bool) -> None:
    _secret_free(payload, "batch")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".batch-write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise ConfigError("Immutable batch document already exists") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "payload_hash": config_hash(data=payload)}


def _read_sealed(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ConfigError("Symbolic batch document rejected")
    payload = read_json_document(path=path)
    if not isinstance(payload, dict):
        raise ConfigError("Batch document must be an object")
    _secret_free(payload, "batch")
    expected = payload.pop("payload_hash", None)
    if expected != config_hash(data=payload):
        raise ConfigError("Batch document hash mismatch")
    return {**payload, "payload_hash": expected}


class BatchStore:
    def __init__(self, directory: Path, intent: dict[str, Any]) -> None:
        self.directory = directory
        self.intent = intent
        self.batch_id = intent["batch_id"]

    @classmethod
    def create(cls, config: dict[str, Any], root: Path | None = None) -> BatchStore:
        base = runtime.runs_root_v2(root)
        batch_id = (
            "batch-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        )
        directory = _safe_descendant(base, base / ".batches" / batch_id)
        directory.parent.mkdir(parents=True, mode=0o700)
        stage = Path(tempfile.mkdtemp(prefix=".creating-", dir=directory.parent))
        intent = _seal(
            {
                "schema_version": 1,
                "batch_id": batch_id,
                "batch_dir": str(directory),
                "created_at": datetime.now(UTC).isoformat(),
                "config": config,
            }
        )
        try:
            _atomic(stage / "intent.json", intent, True)
            _atomic(
                stage / "runtime.json",
                _seal(
                    {
                        "schema_version": 1,
                        "batch_id": batch_id,
                        "revision": 0,
                        "batch_state": "PREPARING",
                        "paused": False,
                        "entries": {
                            item["id"]: {
                                "run_id": None,
                                "prepare_intent": False,
                                "launch_intent": False,
                                "active_lease": False,
                                "phase": "PENDING",
                            }
                            for item in config["entries"]
                        },
                    }
                ),
                True,
            )
            stage.rename(directory)
            directory_fd = os.open(directory.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        return cls(directory, intent)

    @classmethod
    def load(cls, batch_id: str, root: Path | None = None) -> BatchStore:
        if not _ID.fullmatch(batch_id):
            raise ConfigError("Invalid batch ID")
        base = runtime.runs_root_v2(root)
        directory = _safe_descendant(base, base / ".batches" / batch_id)
        intent = _read_sealed(directory / "intent.json")
        if type(intent.get("schema_version")) is not int or intent["schema_version"] != 1:
            raise ConfigError("Unknown batch contract")
        if intent.get("batch_id") != batch_id or intent.get("batch_dir") != str(directory):
            raise ConfigError("Batch identity or location changed")
        store = cls(directory, intent)
        store.state()
        return store

    @contextmanager
    def lock(self, name: str = "state", blocking: bool = True):
        if name not in {"state", "scheduler", "prepare"}:
            raise ConfigError("Unknown batch lock")
        path = _safe_descendant(self.directory, self.directory / f"{name}.lock")
        with path.open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as exc:
                raise ConfigError(f"Batch {name} is already active") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def state(self) -> dict[str, Any]:
        value = _read_sealed(self.directory / "runtime.json")
        if (
            type(value.get("schema_version")) is not int
            or value["schema_version"] != 1
            or value.get("batch_id") != self.batch_id
            or type(value.get("revision")) is not int
        ):
            raise ConfigError("Batch runtime identity changed")
        if set(value["entries"]) != {item["id"] for item in self.intent["config"]["entries"]}:
            raise ConfigError("Batch member set changed")
        return value

    def update(
        self,
        action: str,
        changes: dict[str, Any],
        entries: dict[str, dict[str, Any]] | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self.lock():
            previous = self.state()
            if expected_revision is not None and previous["revision"] != expected_revision:
                raise BatchRevisionConflict("Batch state revision changed")
            values = copy.deepcopy(previous["entries"])
            for entry_id, fields in (entries or {}).items():
                if entry_id not in values:
                    raise ConfigError("Unknown batch entry")
                if (
                    values[entry_id].get("run_id")
                    and "run_id" in fields
                    and fields["run_id"] != values[entry_id]["run_id"]
                ):
                    raise ConfigError("Batch child run ID cannot change")
                values[entry_id].update(fields)
            if {"batch_id", "revision", "entries", "payload_hash"} & set(changes):
                raise ConfigError("Cannot update batch identity fields")
            next_value = {
                **previous,
                **changes,
                "entries": values,
                "revision": previous["revision"] + 1,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            next_value.pop("payload_hash")
            _atomic(self.directory / "runtime.json", _seal(next_value), False)
            journal = _safe_descendant(self.directory, self.directory / "journal.jsonl")
            with journal.open("a") as handle:
                handle.write(
                    json.dumps(
                        {
                            "revision": next_value["revision"],
                            "action": action,
                            "time": next_value["updated_at"],
                        }
                    )
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            return self.state()

    def child_root(self, entry_id: str) -> Path:
        if not _ENTRY_ID.fullmatch(entry_id) or entry_id not in self.state()["entries"]:
            raise ConfigError("Invalid batch entry")
        return _safe_descendant(self.directory, self.directory / "children" / entry_id)

    def find_child(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        root = self.child_root(entry["id"])
        if not root.exists():
            return None
        candidates = []
        for path in root.iterdir():
            if path.is_symlink():
                raise ConfigError("Symbolic child run rejected")
            if path.name == ".cache" or path.name.startswith(".preparing-"):
                continue
            if not path.is_dir() or not (path / "manifest.json").is_file():
                raise ConfigError("Incomplete or unexpected child directory")
            candidates.append(path)
        if len(candidates) > 1:
            raise ConfigError("Multiple child manifests; refusing to choose a replacement")
        if not candidates:
            return None
        path = candidates[0]
        _, manifest = runtime.load_run_v2(run_id=path.name, root=root)
        recorded = self.state()["entries"][entry["id"]].get("run_id")
        if recorded and recorded != manifest["run_id"]:
            raise ConfigError("Recorded child run cannot be replaced")
        self.verify_child(entry, manifest)
        return manifest

    def verify_child(self, entry: dict[str, Any], manifest: dict[str, Any]) -> None:
        materials.verify_materials(manifest)
        expected = entry["input_identity"]
        if (
            manifest["config_hash"] != expected["config_hash"]
            or config_hash(data=manifest["config"]) != expected["config_hash"]
        ):
            raise ConfigError("Child config identity differs from batch intent")
        if manifest["source_snapshot"]["files"] != expected["controller_files"]:
            raise ConfigError("Child controller source differs from batch intent")
        directory = Path(manifest["run_dir"])
        cards = read_json_document(
            path=directory / manifest["materials"]["persona_library"]["path"]
        )
        if config_hash(data={"cards": cards}) != expected["persona_hash"]:
            raise ConfigError("Child personas differ from batch intent")
        actual_tasks = read_task_catalog(directory, manifest)["tasks"]
        if len(actual_tasks) != len(expected["tasks"]):
            raise ConfigError("Child task set differs from batch intent")
        for task, item in zip(actual_tasks, expected["tasks"], strict=True):
            package = copy.deepcopy(task["package"])
            package.pop("instruction_file")
            package.pop("setup")
            if package["source"]["kind"] == "local":
                package["source"].pop("path")
                if task["source_snapshot"]["files"] != item["source_files"]:
                    raise ConfigError("Child task source differs from batch intent")
            if (
                config_hash(data=package) != config_hash(data=item["package"])
                or task["content_hashes"] != item["content_hashes"]
            ):
                raise ConfigError("Child task materials differ from batch intent")
        harness = expected["harness"]
        if "archive_sha256" in harness:
            if manifest["materials"]["harness_archive"]["sha256"] != harness["archive_sha256"]:
                raise ConfigError("Child Harness archive differs from batch intent")
        else:
            prefix = "backend/harness_template/"
            actual = {
                key.removeprefix(prefix): value
                for key, value in manifest["source_snapshot"]["files"].items()
                if key.startswith(prefix)
            }
            if actual != harness["files"]:
                raise ConfigError("Child Harness source differs from batch intent")

    def publish(self) -> dict[str, Any]:
        members = []
        for entry in self.intent["config"]["entries"]:
            manifest = self.find_child(entry)
            if (
                not manifest
                or read_runtime(run_dir=Path(manifest["run_dir"])).get("preparation_complete")
                is not True
            ):
                raise ConfigError("Cannot publish a partially prepared batch")
            members.append(
                {
                    "id": entry["id"],
                    "run_id": manifest["run_id"],
                    "manifest_hash": config_hash(data=manifest),
                    "config_hash": manifest["config_hash"],
                    "materials_hash": config_hash(data=manifest["materials"]),
                }
            )
        value = _seal(
            {
                "schema_version": 1,
                "batch_id": self.batch_id,
                "intent_hash": self.intent["payload_hash"],
                "members": members,
            }
        )
        _atomic(self.directory / "manifest.json", value, True)
        return value

    def manifest(self) -> dict[str, Any]:
        value = _read_sealed(self.directory / "manifest.json")
        if (
            type(value.get("schema_version")) is not int
            or value["schema_version"] != 1
            or value.get("batch_id") != self.batch_id
            or value.get("intent_hash") != self.intent["payload_hash"]
        ):
            raise ConfigError("Final batch manifest identity changed")
        expected_ids = [entry["id"] for entry in self.intent["config"]["entries"]]
        if [item["id"] for item in value["members"]] != expected_ids:
            raise ConfigError("Final batch member order changed")
        for entry, member in zip(self.intent["config"]["entries"], value["members"], strict=True):
            child = self.find_child(entry)
            if (
                not child
                or child["run_id"] != member["run_id"]
                or config_hash(data=child) != member["manifest_hash"]
            ):
                raise ConfigError("Frozen batch child manifest changed")
        return value
