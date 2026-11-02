"""Spec-0074/T2: foreground batches reuse single-run lifecycle and durable leases."""

from __future__ import annotations

import fcntl
import math
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ahe_beta.experiment import runtime
from ahe_beta.experiment.batch_config import load_batch_config, verify_entry_inputs
from ahe_beta.experiment.batch_store import BatchRevisionConflict, BatchStore
from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.manifest import read_runtime

Progress = Callable[[dict[str, Any]], None]
_TERMINAL = {"COMPLETED", "FAILED", "STOPPED"}
_UNKNOWN = {"UNKNOWN", "OPERATION_IN_PROGRESS"}


def check_batch(
    config_path: Path, offline: bool = False, secrets_file: Path | None = None
) -> dict[str, Any]:
    config = load_batch_config(config_path)
    reports = []
    for entry in config["entries"]:
        report = runtime.check_v2(
            config_path=Path(entry["config_path"]), offline=offline, secrets_file=secrets_file
        )
        reports.append({"id": entry["id"], **report})
    # The providers do not guarantee an account-wide remaining-capacity API.
    return {
        "action": "check",
        "ok": True,
        "offline": offline,
        "batch": config,
        "entries": reports,
        "capacity": {"observation": "UNKNOWN", "new_repositories": len(reports)},
    }


def _notify(progress: Progress | None, value: dict[str, Any]) -> None:
    if progress:
        progress(value)


def _prepare(
    store: BatchStore, secrets_file: Path | None, progress: Progress | None
) -> dict[str, Any]:
    with store.lock("prepare", blocking=False):
        if (store.directory / "manifest.json").exists():
            store.manifest()
            return _result(store, "prepare")
        for entry in store.intent["config"]["entries"]:
            if store.state().get("paused"):
                store.update("prepare-paused", {"batch_state": "PAUSED"})
                return _result(store, "prepare")
            entry_id = entry["id"]
            _notify(
                progress, {"batch_id": store.batch_id, "entry_id": entry_id, "phase": "PREPARING"}
            )
            try:
                child = store.find_child(entry)
                if child is None:
                    verify_entry_inputs(entry)
                    store.update(
                        "prepare-intent",
                        {},
                        {entry_id: {"prepare_intent": True, "phase": "PREPARING"}},
                    )
                    runtime.prepare_v2(
                        config_path=Path(entry["config_path"]),
                        root=store.child_root(entry_id),
                        secrets_file=secrets_file,
                    )
                    child = store.find_child(entry)
                if child is None:
                    raise ConfigError("Preparation did not publish a child run")
                store.update("child-assigned", {}, {entry_id: {"run_id": child["run_id"]}})
                if (
                    read_runtime(run_dir=Path(child["run_dir"])).get("preparation_complete")
                    is not True
                ):
                    raise ConfigError(
                        "Existing child environment is not prepared; inspect its prepare log"
                    )
                store.update(
                    "child-prepared", {}, {entry_id: {"phase": "PREPARED", "last_error": None}}
                )
            except Exception:
                # Do not put provider/model exception text (or credentials) in batch receipts.
                store.update(
                    "prepare-blocked",
                    {"batch_state": "BLOCKED_PREPARATION"},
                    {
                        entry_id: {
                            "phase": "BLOCKED_PREPARATION",
                            "last_error": "Preparation blocked; inspect the original child inputs and prepare logs",
                        }
                    },
                )
                return _result(store, "prepare")
        store.publish()
        _refresh_state(store)
        return _result(store, "prepare")


def prepare_batch(
    config_path: Path,
    root: Path | None = None,
    secrets_file: Path | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    # All-selected credential/provider checks occur before any child is launched.
    report = check_batch(config_path, offline=False, secrets_file=secrets_file)
    store = BatchStore.create(report["batch"], root)
    _notify(progress, {"batch_id": store.batch_id, "phase": "PREPARING"})
    return _prepare(store, secrets_file, progress)


@contextmanager
def _dispatch_gate(store: BatchStore):
    """A stop intent stays writable while it waits for an in-flight launch to finish."""
    path = store.directory / "dispatch.lock"
    if path.is_symlink():
        raise ConfigError("Symbolic batch dispatch lock rejected")
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _child(store: BatchStore, entry_id: str) -> tuple[Path, dict[str, Any]]:
    entry = store.state()["entries"][entry_id]
    if not entry.get("run_id"):
        raise ConfigError("Batch entry has no frozen run ID")
    return runtime.load_run_v2(run_id=entry["run_id"], root=store.child_root(entry_id))


def _safe_unstarted(store: BatchStore, entry_id: str) -> bool:
    directory, _ = _child(store, entry_id)
    receipt = read_runtime(run_dir=directory)
    return (
        receipt.get("preparation_complete") is True
        and receipt.get("experiment_state") in {"PREPARED", "PREPARING"}
        and receipt.get("resource_state") == "ABSENT"
        and not receipt.get("launch_mode")
        and not (directory / "resources.json").exists()
    )


def _progress_counts(progress: dict[str, Any]) -> dict[str, Any]:
    rounds = {}
    for round_id, row in progress.get("rounds", {}).items():
        users = row.get("users") or {}
        rounds[str(round_id)] = {
            "status": row.get("status"),
            "stages": row.get("stages", {}),
            "users": {
                key: users.get(key)
                for key in (
                    "observation",
                    "expected",
                    "started",
                    "completed",
                    "running",
                    "pending",
                    "failed",
                )
            },
        }
    return {
        "current_round": progress.get("current_round"),
        "observation": progress.get("observation", "UNKNOWN"),
        "source": progress.get("source"),
        "rounds": rounds,
    }


def _observed_status(value: dict[str, Any]) -> dict[str, Any]:
    provider = value.get("provider") or {}
    controller = provider.get("controller") or provider
    return {
        "experiment_state": value.get("experiment_state", "UNKNOWN"),
        "resource_state": value.get("resource_state", "UNKNOWN"),
        "collection_state": value.get("collection_state", "NONE"),
        "observation": value.get("observation", "UNKNOWN"),
        "controller_state": controller.get("state", "UNKNOWN"),
        "controller_running": controller.get("running"),
        "controller_nonce": controller.get("nonce"),
        "failed_stage": value.get("failed_stage"),
        "error_class": value.get("error_class"),
        "observed_at": provider.get("observed_at", value.get("updated_at")),
        "progress": _progress_counts(value.get("progress") or {}),
    }


def _collect_terminal(
    store: BatchStore, entry_id: str, observed: dict[str, Any], secrets_file: Path | None
) -> dict[str, Any]:
    item = store.state()["entries"][entry_id]
    identity = {"state": observed["experiment_state"], "nonce": observed["controller_nonce"]}
    if item.get("terminal_collection") == identity and observed["collection_state"] == "COMPLETE":
        return {
            "phase": observed["experiment_state"],
            "active_lease": False,
            "collection_error": False,
        }
    try:
        result = runtime.collect_v2(
            run_id=item["run_id"], root=store.child_root(entry_id), secrets_file=secrets_file
        )
        if result.get("collection_state") != "COMPLETE":
            raise ConfigError("Terminal collection is incomplete")
        controller = result.get("controller") or {}
        controller = controller.get("controller") or controller
        if (
            not observed.get("controller_nonce")
            or controller.get("nonce") != observed["controller_nonce"]
            or controller.get("running") is not False
            or controller.get("state") not in {"STOPPED", "EXITED"}
            or controller.get("state") != observed["controller_state"]
        ):
            raise ConfigError("Terminal collection belongs to an unconfirmed controller attempt")
    except Exception:
        return {
            "phase": "BLOCKED_COLLECTION",
            "active_lease": True,
            "last_error": "Terminal collection failed or partial; retry batch collect",
            "collection_error": True,
            "terminal_collection": None,
        }
    return {
        "phase": observed["experiment_state"],
        "active_lease": False,
        "terminal_collection": identity,
        "collection_state": "COMPLETE",
        "last_status": {**observed, "collection_state": "COMPLETE"},
        "collection_error": False,
        "collection_receipt": {
            "path": "runtime/collection.json",
            "archive_sha256": result.get("archive_sha256"),
            "collected_at": result.get("collected_at"),
        },
        "last_error": None,
    }


def _reconcile(store: BatchStore, secrets_file: Path | None, collect_terminal: bool) -> None:
    for entry in store.intent["config"]["entries"]:
        entry_id = entry["id"]
        item = store.state()["entries"][entry_id]
        if not item.get("run_id"):
            continue
        try:
            observed = _observed_status(
                runtime.status_v2(
                    run_id=item["run_id"],
                    root=store.child_root(entry_id),
                    secrets_file=secrets_file,
                )
            )
        except Exception:
            observed = {**item.get("last_status", {}), "observation": "UNKNOWN"}
        changes: dict[str, Any] = {"last_status": observed}
        state = observed.get("experiment_state")
        if observed.get("observation") in _UNKNOWN or observed.get("controller_state") == "UNKNOWN":
            changes.update(
                phase="BLOCKED_OBSERVATION",
                active_lease=item["active_lease"] or item["launch_intent"],
            )
        elif state == "LOST" and (
            observed.get("resource_state") == "LOST" or observed.get("controller_state") == "LOST"
        ):
            changes.update(
                phase="LOST",
                active_lease=False,
                last_error="Original resources lost; no automatic replacement",
            )
        elif observed.get("controller_running") is True or state in {"RUNNING", "STOPPING"}:
            changes.update(
                phase=state if state in {"RUNNING", "STOPPING"} else "BLOCKED_OBSERVATION",
                active_lease=True,
                launch_intent=True,
                terminal_collection=None,
            )
        elif (
            state in _TERMINAL
            and observed.get("controller_running") is False
            and observed.get("controller_state") in {"STOPPED", "EXITED"}
        ):
            if collect_terminal:
                changes.update(_collect_terminal(store, entry_id, observed, secrets_file))
            else:
                collected = (
                    item.get("terminal_collection")
                    == {"state": state, "nonce": observed["controller_nonce"]}
                    and observed["collection_state"] == "COMPLETE"
                )
                changes.update(
                    phase=state if collected else "AWAITING_COLLECTION", active_lease=not collected
                )
                if not collected:
                    changes["terminal_collection"] = None
        elif _safe_unstarted(store, entry_id):
            changes.update(
                phase="FAILED" if item.get("launch_failed") else "PREPARED", active_lease=False
            )
        else:
            # Provision intent/resources with an absent controller is an ambiguous crash.
            changes.update(
                phase="BLOCKED_PROVISION",
                active_lease=item["launch_intent"]
                or (store.child_root(entry_id) / item["run_id"] / "resources.json").exists(),
                last_error="Provision/launch outcome unresolved; inspect original run, do not recreate",
            )
        store.update("observe-child", {}, {entry_id: changes})
    _refresh_state(store)


def _refresh_state(store: BatchStore) -> None:
    while True:
        state = store.state()
        items = list(state["entries"].values())
        phases = {item["phase"] for item in items}
        if state.get("paused"):
            phase = "PAUSING" if any(item["active_lease"] for item in items) else "PAUSED"
        elif "LOST" in phases:
            phase = "BLOCKED_LOST"
        elif "FAILED" in phases:
            phase = "BLOCKED_MEMBER_FAILURE"
        elif any(value.startswith("BLOCKED_") for value in phases):
            phase = next(item["phase"] for item in items if item["phase"].startswith("BLOCKED_"))
        elif phases == {"COMPLETED"}:
            phase = "COMPLETED"
        elif "STOPPED" in phases:
            phase = "PAUSED"
        elif phases & {"RUNNING", "STARTING", "STOPPING", "AWAITING_COLLECTION"}:
            phase = "RUNNING"
        else:
            phase = "READY"
        try:
            store.update(
                "batch-observed", {"batch_state": phase}, expected_revision=state["revision"]
            )
            return
        except BatchRevisionConflict:
            continue


def _terminal_complete(item: dict[str, Any]) -> bool:
    observed = item.get("last_status") or {}
    return (
        item["phase"] in _TERMINAL
        and observed.get("collection_state") == "COMPLETE"
        and item.get("terminal_collection")
        == {"state": observed.get("experiment_state"), "nonce": observed.get("controller_nonce")}
    )


def _result(store: BatchStore, action: str) -> dict[str, Any]:
    state = store.state()
    items = state["entries"]
    config = store.intent["config"]
    return {
        "action": action,
        **state,
        "ok": not state["batch_state"].startswith("BLOCKED_")
        and not (
            action == "collect" and any(item.get("collection_error") for item in items.values())
        ),
        "experiment_success": state["batch_state"] == "COMPLETED",
        "collection_state": "COMPLETE"
        if all(_terminal_complete(item) for item in items.values())
        else ("PARTIAL" if any(item["launch_intent"] for item in items.values()) else "NONE"),
        "batch_dir": str(store.directory),
        "configured": {
            "max_parallel_runs": config["max_parallel_runs"],
            "backend": config["backend"],
            "members": len(items),
        },
        "counts": {
            "active": sum(item["active_lease"] for item in items.values()),
            "pending": sum(item["phase"] in {"PENDING", "PREPARED"} for item in items.values()),
            "completed": sum(item["phase"] == "COMPLETED" for item in items.values()),
            "retained_resources": sum(
                item.get("last_status", {}).get("resource_state", "ABSENT")
                not in {"ABSENT", "DESTROYED", "LOST", "UNKNOWN"}
                for item in items.values()
            ),
        },
        "capacity": {
            "observation": "UNKNOWN",
            "new_repositories": sum(not item["launch_intent"] for item in items.values()),
        },
        "member_configuration": {
            entry["id"]: entry["config"]["rounds"] for entry in config["entries"]
        },
        "child_roots": {entry_id: str(store.child_root(entry_id)) for entry_id in items},
    }


def status_batch(
    batch_id: str, root: Path | None = None, secrets_file: Path | None = None
) -> dict[str, Any]:
    store = BatchStore.load(batch_id, root)
    if (store.directory / "manifest.json").exists():
        store.manifest()
        _reconcile(store, secrets_file, False)
    return _result(store, "status")


def collect_batch(
    batch_id: str, root: Path | None = None, secrets_file: Path | None = None
) -> dict[str, Any]:
    store = BatchStore.load(batch_id, root)
    store.manifest()
    with _dispatch_gate(store):
        _reconcile(store, secrets_file, True)
        for entry_id, item in store.state()["entries"].items():
            if item["phase"] not in {"RUNNING", "STOPPING"}:
                continue
            try:
                receipt = runtime.collect_v2(
                    run_id=item["run_id"],
                    root=store.child_root(entry_id),
                    secrets_file=secrets_file,
                )
                store.update(
                    "collect-live",
                    {},
                    {
                        entry_id: {
                            "collection_state": receipt["collection_state"],
                            "collection_error": False,
                        }
                    },
                )
            except Exception:
                store.update(
                    "collect-live-failed",
                    {},
                    {
                        entry_id: {
                            "last_error": "Active collection failed; original resources retained",
                            "collection_error": True,
                        }
                    },
                )
    return _result(store, "collect")


def stop_batch(
    batch_id: str, root: Path | None = None, secrets_file: Path | None = None
) -> dict[str, Any]:
    store = BatchStore.load(batch_id, root)
    store.update("pause-intent", {"paused": True, "batch_state": "PAUSING"})
    if not (store.directory / "manifest.json").exists():
        store.update("prepare-paused", {"batch_state": "PAUSED"})
        return _result(store, "stop")
    store.manifest()
    with _dispatch_gate(store):
        for entry_id, item in store.state()["entries"].items():
            if (
                not item["launch_intent"]
                or item["phase"] in {"COMPLETED", "FAILED", "LOST"}
                or _safe_unstarted(store, entry_id)
            ):
                continue
            try:
                runtime.stop_v2(
                    run_id=item["run_id"],
                    root=store.child_root(entry_id),
                    secrets_file=secrets_file,
                )
            except Exception:
                store.update(
                    "stop-unresolved",
                    {},
                    {
                        entry_id: {
                            "phase": "BLOCKED_OBSERVATION",
                            "active_lease": True,
                            "last_error": "Stop outcome unresolved; inspect original run",
                        }
                    },
                )
        _reconcile(store, secrets_file, True)
    return _result(store, "stop")


def _dispatch(
    store: BatchStore,
    entry_id: str,
    secrets_file: Path | None,
    resume_child: bool,
    progress: Progress | None,
) -> None:
    with _dispatch_gate(store):
        if store.state().get("paused"):
            return
        store.update(
            "launch-intent",
            {},
            {
                entry_id: {
                    "launch_intent": True,
                    "active_lease": True,
                    "phase": "STARTING",
                    "terminal_collection": None,
                }
            },
        )
        _notify(progress, {"batch_id": store.batch_id, "entry_id": entry_id, "phase": "STARTING"})
        item = store.state()["entries"][entry_id]
        try:
            runtime.run_v2(
                run_id=item["run_id"],
                root=store.child_root(entry_id),
                secrets_file=secrets_file,
                resume_run=resume_child,
                monitor=False,
            )
        except Exception:
            store.update(
                "launch-error",
                {},
                {
                    entry_id: {
                        "phase": "BLOCKED_PROVISION",
                        "active_lease": True,
                        "last_error": "Child launch failed; original run/resources retained",
                        "launch_failed": True,
                    }
                },
            )
            return
        # A successful launch acknowledgement still occupies its lease.
        store.update("started", {}, {entry_id: {"phase": "RUNNING", "active_lease": True}})


def run_batch(
    batch_id: str,
    root: Path | None = None,
    secrets_file: Path | None = None,
    resume_batch: bool = False,
    poll_seconds: float = 5,
    progress: Progress | None = None,
) -> dict[str, Any]:
    if (
        isinstance(poll_seconds, bool)
        or not isinstance(poll_seconds, (int, float))
        or not math.isfinite(poll_seconds)
        or not 0 < poll_seconds <= 60
    ):
        raise ConfigError("poll_seconds must be greater than zero and at most 60")
    store = BatchStore.load(batch_id, root)
    with store.lock("scheduler", blocking=False):
        if resume_batch:
            store.update("resume-intent", {"paused": False, "supervisor_stopped": False})
        if not (store.directory / "manifest.json").exists():
            if not resume_batch:
                raise ConfigError("Batch is not fully prepared; use batch resume for preparation")
            result = _prepare(store, secrets_file, progress)
            if not result["ok"] or not (store.directory / "manifest.json").exists():
                return result
        store.manifest()
        state = store.state()
        if not resume_batch and (
            state.get("paused")
            or state.get("supervisor_stopped")
            or state["batch_state"] == "INTERRUPTED"
        ):
            raise ConfigError("Batch supervision was stopped; use batch resume")
        # Validate every frozen member's model mapping before any dispatch, without a model call.
        for entry_id in state["entries"]:
            directory, manifest = _child(store, entry_id)
            credentials = runtime.credentials_v2(
                manifest=manifest, run_dir=directory, secrets_file=secrets_file, models=True
            )
            runtime._require_model_credentials(manifest, credentials)
        previous = None
        try:
            while True:
                _reconcile(store, secrets_file, True)
                result = _result(store, "resume" if resume_batch else "run")
                signature = (
                    result["batch_state"],
                    [
                        (
                            key,
                            item["phase"],
                            item["active_lease"],
                            item.get("last_status", {}).get("progress"),
                        )
                        for key, item in result["entries"].items()
                    ],
                )
                if signature != previous:
                    _notify(progress, result)
                    previous = signature
                phase = result["batch_state"]
                if phase in {"COMPLETED", "PAUSING"} or (
                    phase == "PAUSED" and (result["paused"] or not resume_batch)
                ):
                    return result
                if phase.startswith("BLOCKED_"):
                    # Failure blocks pending but lets other known running members finish/collect.
                    if phase not in {"BLOCKED_MEMBER_FAILURE", "BLOCKED_LOST"} or not any(
                        item["phase"] in {"RUNNING", "STOPPING"}
                        for item in result["entries"].values()
                    ):
                        return result
                else:
                    available = (
                        store.intent["config"]["max_parallel_runs"] - result["counts"]["active"]
                    )
                    if available < 0:
                        store.update("concurrency-blocked", {"batch_state": "BLOCKED_CONCURRENCY"})
                        return _result(store, "run")
                    for entry_id, item in result["entries"].items():
                        if not available:
                            break
                        if item["phase"] == "PREPARED" or (
                            resume_batch and item["phase"] == "STOPPED"
                        ):
                            _dispatch(
                                store, entry_id, secrets_file, item["phase"] == "STOPPED", progress
                            )
                            available -= 1
                            if store.state()["entries"][entry_id]["phase"].startswith("BLOCKED_"):
                                break
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            store.update(
                "supervision-interrupted",
                {"batch_state": "INTERRUPTED", "supervisor_stopped": True},
            )
            return _result(store, "run")
