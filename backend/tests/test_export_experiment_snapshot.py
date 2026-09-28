"""Public snapshots must not carry free text from private monitor data."""

import json
import sys

import pytest

from export_experiment_snapshot import export, main


def test_public_export_excludes_private_strings_in_all_outputs(tmp_path, monkeypatch):
    marker = "PRIVATE_SENTINEL_token_https://internal.example_/home/operator/prompt"
    source = tmp_path / "private-experiment-name"
    telemetry = source / "telemetry"
    telemetry.mkdir(parents=True)
    row = {
        "state": marker,
        "time": marker,
        "round": marker,
        "total_rounds": marker,
        "worker_alive": marker,
        "sessions_saved": marker,
        "active_roles": {marker: 2, "user": marker},
        "alerts": [marker, {"text": marker}],
        "issues": {"open": marker},
        "agents": [
            {
                "agent_id": marker,
                "role": marker,
                "status": marker,
                "running": marker,
                "round": marker,
                "updated_at": marker,
            }
        ],
        "prompt": marker,
    }
    (telemetry / "monitor-latest.json").write_text(json.dumps(row))
    (telemetry / "monitor.jsonl").write_text(json.dumps(row) + "\ninvalid\n[]\nnull\n")
    output = tmp_path / "public"
    monkeypatch.setattr(sys, "argv", ["export", str(source), str(output)])
    main()
    for path in output.rglob("*.json"):
        assert marker not in path.read_text()
        assert source.name not in path.read_text()
    index = json.loads((output / "index.json").read_text())
    public = output / index["experiments"][0]["id"]
    summary = json.loads((public / "latest.json").read_text())
    assert summary["alerts"] == ["2 alert(s); details withheld"]
    assert summary["status"] == "UNKNOWN"
    assert summary["round"] == 0


def test_export_preserves_coarse_progress_and_explicit_public_metadata(tmp_path):
    source = tmp_path / "input"
    telemetry = source / "telemetry"
    telemetry.mkdir(parents=True)
    row = {
        "state": "RUNNING",
        "time": "2026-09-28T12:00:00+00:00",
        "round": 2,
        "total_rounds": 5,
        "worker_alive": True,
        "sessions_saved": 4,
        "active_roles": {"user": 1},
        "agents": [{"role": "designer", "running": True}],
    }
    (telemetry / "monitor-latest.json").write_text(json.dumps(row))
    output = tmp_path / "public"
    entry = export(source, output, "Synthetic demo", public_id="demo")
    assert entry["id"] == "demo"
    assert entry["title"] == "Synthetic demo"
    assert entry["status"] == "RUNNING"
    summary = json.loads((output / "demo/latest.json").read_text())
    assert summary["round"] == 2
    assert summary["sessions_saved"] == 4
    assert summary["worker_alive"] is True
    roster = json.loads((output / "demo/api/config.json").read_text())["roster"]
    assert roster["designer"] == 1
    assert roster["user"] == 0
    with pytest.raises(ValueError, match="slug"):
        export(source, output, None, public_id="../escape")
