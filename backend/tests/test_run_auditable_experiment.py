from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import run_auditable_experiment


def _module():
    return run_auditable_experiment


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_experiment_validates_round_roster_and_pins(tmp_path: Path) -> None:
    module = _module()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    harness = inputs / "harness.tar.gz"
    harness.write_bytes(b"frozen harness")
    library = inputs / "personas.json"
    library.write_text(
        json.dumps(
            [
                {
                    "id": "correct",
                    "dimensions": {"D3_interaction_style": {"on_offtrack": {"value": "correct"}}},
                },
                {
                    "id": "handover",
                    "dimensions": {"D3_interaction_style": {"on_offtrack": {"value": "fix-self"}}},
                },
            ]
        ),
        encoding="utf-8",
    )
    roster = inputs / "roster.json"
    roster.write_text(
        json.dumps(
            {
                "distribution": {"correct": 1, "fix-self": 1},
                "personas": [
                    {"id": "correct", "strategy": "correct"},
                    {"id": "handover", "strategy": "fix-self"},
                ],
            }
        ),
        encoding="utf-8",
    )
    pool = inputs / "pool.json"
    pool.write_text(
        json.dumps({"instances": [{"instance_id": "one"}, {"instance_id": "two"}]}),
        encoding="utf-8",
    )
    dataset = inputs / "dataset.parquet"
    dataset.write_bytes(b"unit parquet pin")
    plan = inputs / "plan.json"
    plan.write_text(
        json.dumps(
            [
                [["correct", "one"], ["handover", "two"]],
                [["handover", "one"], ["correct", "two"]],
            ]
        ),
        encoding="utf-8",
    )
    image = "sha256:" + "a" * 64
    document = {
        "schema_version": 1,
        "experiment_id": "unit-audit",
        "mode": "full-evolution",
        "source": {
            "auto_designer_sha": "a" * 40,
            "openagents_sha": "b" * 40,
            "nexau_sha": "c" * 40,
            "harness": {"kind": "archive", "path": str(harness), "sha256": _sha(harness)},
        },
        "images": {key: image for key in ("gitea", "runner", "egress", "vigil", "seed")},
        "models": {
            "profile": "unit",
            **{
                key: "glm-unit"
                for key in (
                    "user",
                    "harness",
                    "triage",
                    "designer",
                    "divergent",
                    "owner",
                    "delivery",
                )
            },
        },
        "capacity": {"endpoint": "unit", "user_parallel": 2, "delivery_parallel": 1},
        "roster": {
            "user": 2,
            "triager": 1,
            "designer": 1,
            "divergent": 1,
            "owner": 1,
            "developer": 1,
        },
        "personas": {
            "library": {"path": str(library), "sha256": _sha(library)},
            "roster": {"path": str(roster), "sha256": _sha(roster)},
            "distribution": {"correct": 1, "fix-self": 1},
        },
        "workload": {
            "dataset": {"path": str(dataset), "sha256": _sha(dataset)},
            "pool": {"path": str(pool), "sha256": _sha(pool)},
        },
        "execution": {
            "runner": "swebench-closed-loop",
            "total_rounds": 2,
            "final_round_users_only": True,
            "wait_for_delivery_between_rounds": True,
            "plan": {"path": str(plan), "sha256": _sha(plan)},
        },
        "infrastructure": {"isolation": "dedicated"},
        "retention": {"keep_on_stop": True},
    }
    config = inputs / "config.json"
    config.write_text(json.dumps(document), encoding="utf-8")

    frozen = module.FrozenExperiment.load(config_path=config, root=tmp_path / "experiments")
    assert frozen.experiment_id == "unit-audit"
    assert frozen.roster["user"] == 2

    for enabled in (False, True):
        frozen.raw["execution"]["designer_grouping"] = enabled
        environment = module._execution_environment(frozen, profile={}, context_path=tmp_path / "context.json")
        assert environment["DESIGNER_GROUPING"] == ("1" if enabled else "0")
        assert environment["NO_PROXY"] == environment["no_proxy"] == "*"
        frozen.validate_contract()
    frozen.raw["execution"]["designer_grouping"] = "false"
    with pytest.raises(module.AuditLaunchError, match="designer_grouping"):
        frozen.validate_contract()
    frozen.raw["execution"]["designer_grouping"] = True

    document["experiment_id"] = "unit-user-only"
    document["mode"] = "user-only"
    document["execution"]["total_rounds"] = 1
    plan.write_text(json.dumps([[["correct", "one"], ["handover", "two"]]]), encoding="utf-8")
    document["execution"]["plan"]["sha256"] = _sha(plan)
    document["capacity"]["delivery_parallel"] = 0
    document["roster"].update(
        {"triager": 0, "designer": 0, "divergent": 0, "owner": 0, "developer": 0}
    )
    config.write_text(json.dumps(document), encoding="utf-8")

    canary = module.FrozenExperiment.load(config_path=config, root=tmp_path / "experiments")
    assert canary.config.mode == "user-only"
    assert canary.execution["total_rounds"] == 1
