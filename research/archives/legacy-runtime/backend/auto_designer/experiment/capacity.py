# Spec-0047/T5: Capacity leases for endpoints shared across experiments.
"""File-locked lease registry under EXPERIMENTS_ROOT. Expired leases reclaim only if pid is dead."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from auto_designer.experiment.config import ConfigError, experiments_root

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class CapacityError(ConfigError):
    """Endpoint oversubscribed or lease reclaim refused."""


def _registry_path(*, root: Path | None) -> Path:
    base = root or experiments_root()
    base.mkdir(parents=True, exist_ok=True)
    return base / ".capacity-leases.json"


def _load(*, path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"endpoints": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(*, path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _pid_alive(*, pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(
    *,
    experiment_id: str,
    endpoint: str,
    units: int,
    capacity: int,
    ttl_sec: int,
    root: Path | None = None,
    pid: int | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    if units <= 0:
        raise CapacityError("Lease units must be positive")
    path = _registry_path(root=root)
    owner_pid = pid if pid is not None else os.getpid()
    clock = time.time() if now is None else now
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read()
        data = json.loads(raw) if raw.strip() else {"endpoints": {}}
        _reclaim(data=data, clock=clock)
        bucket = data.setdefault("endpoints", {}).setdefault(
            endpoint, {"capacity": capacity, "leases": []}
        )
        bucket["capacity"] = capacity
        used = sum(int(item["units"]) for item in bucket["leases"])
        if used + units > capacity:
            raise CapacityError(
                f"endpoint {endpoint} Insufficient capacity：used={used} request={units} cap={capacity}"
            )
        lease = {
            "experiment_id": experiment_id,
            "pid": owner_pid,
            "units": units,
            "expires_at": clock + ttl_sec,
        }
        bucket["leases"].append(lease)
        _dump(path=path, data=data)
        return lease


def heartbeat(
    *,
    experiment_id: str,
    endpoint: str,
    ttl_sec: int,
    root: Path | None = None,
    now: float | None = None,
) -> None:
    path = _registry_path(root=root)
    clock = time.time() if now is None else now
    data = _load(path=path)
    bucket = data.get("endpoints", {}).get(endpoint, {})
    for item in bucket.get("leases", []):
        if item.get("experiment_id") == experiment_id:
            item["expires_at"] = clock + ttl_sec
    _dump(path=path, data=data)


def release(*, experiment_id: str, endpoint: str, root: Path | None = None) -> None:
    path = _registry_path(root=root)
    data = _load(path=path)
    bucket = data.get("endpoints", {}).get(endpoint)
    if not bucket:
        return
    bucket["leases"] = [
        item for item in bucket["leases"] if item.get("experiment_id") != experiment_id
    ]
    _dump(path=path, data=data)


def _reclaim(*, data: dict[str, Any], clock: float) -> None:
    for bucket in data.get("endpoints", {}).values():
        kept = []
        for item in bucket.get("leases", []):
            expired = float(item.get("expires_at") or 0) <= clock
            alive = _pid_alive(pid=int(item.get("pid") or 0))
            if expired and not alive:
                continue
            kept.append(item)
        bucket["leases"] = kept
