# Spec-0047/T5: Capacity leases and expiration cleanup.
from __future__ import annotations

from pathlib import Path

import pytest

from auto_designer.experiment.capacity import CapacityError, acquire, release


def test_parallel_acquire_respects_capacity(tmp_path: Path) -> None:
    acquire(
        experiment_id="e1",
        endpoint="glm",
        units=2,
        capacity=3,
        ttl_sec=60,
        root=tmp_path,
        pid=1,
        now=100.0,
    )
    acquire(
        experiment_id="e2",
        endpoint="glm",
        units=1,
        capacity=3,
        ttl_sec=60,
        root=tmp_path,
        pid=2,
        now=100.0,
    )
    with pytest.raises(CapacityError, match="Insufficient capacity"):
        acquire(
            experiment_id="e3",
            endpoint="glm",
            units=1,
            capacity=3,
            ttl_sec=60,
            root=tmp_path,
            pid=3,
            now=100.0,
        )


def test_expired_dead_pid_is_reclaimed(tmp_path: Path, monkeypatch) -> None:
    acquire(
        experiment_id="e1",
        endpoint="glm",
        units=3,
        capacity=3,
        ttl_sec=1,
        root=tmp_path,
        pid=999999,
        now=10.0,
    )
    monkeypatch.setattr("auto_designer.experiment.capacity._pid_alive", lambda *, pid: False)
    acquire(
        experiment_id="e2",
        endpoint="glm",
        units=3,
        capacity=3,
        ttl_sec=10,
        root=tmp_path,
        pid=8,
        now=20.0,
    )


def test_expired_live_pid_is_kept(tmp_path: Path, monkeypatch) -> None:
    acquire(
        experiment_id="e1",
        endpoint="glm",
        units=3,
        capacity=3,
        ttl_sec=1,
        root=tmp_path,
        pid=42,
        now=10.0,
    )
    monkeypatch.setattr("auto_designer.experiment.capacity._pid_alive", lambda *, pid: True)
    with pytest.raises(CapacityError):
        acquire(
            experiment_id="e2",
            endpoint="glm",
            units=3,
            capacity=3,
            ttl_sec=10,
            root=tmp_path,
            pid=8,
            now=20.0,
        )
    release(experiment_id="e1", endpoint="glm", root=tmp_path)
    acquire(
        experiment_id="e2",
        endpoint="glm",
        units=3,
        capacity=3,
        ttl_sec=10,
        root=tmp_path,
        pid=8,
        now=20.0,
    )
