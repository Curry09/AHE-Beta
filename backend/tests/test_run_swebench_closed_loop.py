"""The shared unified runtime also loads recovery for SWE and mixed tasks."""

import json
from pathlib import Path

import pytest

from auto_designer.experiment.controllers import runtime


def test_shared_recovery_loader_reuses_identity_and_rejects_missing_state(
    tmp_path: Path, monkeypatch
) -> None:
    values = {
        "AUTO_DESIGNER_EXPERIMENT_ID": "exp",
        "AUTO_DESIGNER_RUN_ID": "run",
        "AUTO_DESIGNER_CONFIG_HASH": "config",
        "AUTO_DESIGNER_CONTROLLER_SHA": "controller",
        "AUTO_DESIGNER_PLAN_HASH": "plan",
        "AUTO_DESIGNER_RECOVERY_ROOT": str(tmp_path / "checkpoints"),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    fresh = runtime.load_recovery_store(mode="fresh")
    assert fresh is not None
    resumed = runtime.load_recovery_store(mode="resume")
    assert resumed is not None and resumed.snapshot()["identity"]["run_id"] == "run"

    snapshot = tmp_path / "checkpoints" / "recovery.json"
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    document["identity"]["plan_hash"] = "drift"
    snapshot.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(Exception, match="identity changed"):
        runtime.load_recovery_store(mode="resume")
