# Spec-0047/T5: Experiment-level rolling error-rate protection—pause only this experiment.
"""Rolling success/error window. Trip pauses this experiment, not the shared endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from auto_designer.experiment.config import experiments_root

WINDOW = 20
ERROR_RATE = 0.5


def _path(*, experiment_id: str, root: Path | None) -> Path:
    base = (root or experiments_root()) / experiment_id / "telemetry"
    base.mkdir(parents=True, exist_ok=True)
    return base / "health.json"


def record(
    *,
    experiment_id: str,
    success: bool,
    kind: str,
    root: Path | None = None,
) -> dict[str, Any]:
    path = _path(experiment_id=experiment_id, root=root)
    data = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.is_file()
        else {"events": [], "paused": False}
    )
    events = list(data.get("events") or [])
    events.append({"success": success, "kind": kind})
    events = events[-WINDOW:]
    failures = sum(1 for item in events if not item.get("success"))
    paused = bool(data.get("paused"))
    if len(events) >= WINDOW and failures / len(events) >= ERROR_RATE:
        paused = True
    data = {"events": events, "paused": paused, "last_kind": kind}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def should_pause(*, experiment_id: str, root: Path | None = None) -> bool:
    path = _path(experiment_id=experiment_id, root=root)
    if not path.is_file():
        return False
    return bool(json.loads(path.read_text(encoding="utf-8")).get("paused"))


def resume(*, experiment_id: str, root: Path | None = None) -> None:
    path = _path(experiment_id=experiment_id, root=root)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"events": []}
    data["paused"] = False
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
