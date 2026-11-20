"""Frozen cohort conversion keeps task budgets, interaction assignments and services."""

import json
import tomllib
from pathlib import Path

import pytest
import yaml

from ahe_beta.integrations.hermit import export

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "name,users,simulated",
    [("u8-mixed", 8, 6), ("u8-direct", 8, 0), ("u16-mixed", 16, 12), ("u32-mixed", 32, 25)],
)
def test_cohort_keeps_complete_rounds_and_final_observation(
    tmp_path, monkeypatch, name, users, simulated
):
    def materialize(*, material, destination):
        destination.mkdir(parents=True)
        (destination / "input").write_text("fixture")

    monkeypatch.setattr(export, "fetch_material", lambda **kw: tmp_path / "verified-fixture")
    monkeypatch.setattr(export, "materialize_input", materialize)
    target = tmp_path / "out"
    manifest = export.export_cohort(
        ROOT / f"examples/experiments/{name}-e2b.json",
        output=target,
        cache=tmp_path,
        agent_seconds=None,
    )
    rows = [json.loads(line) for line in (target / "tasks.jsonl").read_text().splitlines()]
    assert len(rows) == 6 * users
    assert manifest["training_rounds"] == 5
    assert len((target / "train.txt").read_text().splitlines()) == users * 5
    assert len((target / "final-round.txt").read_text().splitlines()) == users
    for number in range(1, 7):
        round_rows = [r for r in rows if r["ahe_session"]["round"] == number]
        assert len(round_rows) == users
        assert (
            sum(r["ahe_session"]["interaction"] == "simulated_user" for r in round_rows)
            == simulated
        )
    kv = next(r for r in rows if r["harbor_task"] == "kv-live-surgery")
    assert kv["agent_timeout_sec"] == 28800
    config = tomllib.loads((target / "tasks/kv-live-surgery/task.toml").read_text())
    assert config["agent"]["timeout_sec"] == 28800
    compose = yaml.safe_load(
        (target / "tasks/kv-live-surgery/environment/docker-compose.yaml").read_text()
    )
    assert set(compose["services"]) == {"main", "capture", "loadgen"}
    assert compose["services"]["main"]["cap_add"] == ["SYS_PTRACE"]
    assert all(service["entrypoint"] == [] for service in compose["services"].values())
    assert "task" in compose["services"]["main"]["networks"]["default"]["aliases"]


def test_failed_export_does_not_leave_a_partial_cohort(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("material server unavailable")

    monkeypatch.setattr(export, "export_task", fail)
    target = tmp_path / "out"
    with pytest.raises(OSError):
        export.export_cohort(
            ROOT / "examples/experiments/u8-mixed-e2b.json",
            output=target,
            cache=tmp_path,
            agent_seconds=None,
        )
    assert not target.exists()
