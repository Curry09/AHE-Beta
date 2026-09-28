from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.harness_bench.config import load_plan
from evaluation.harness_bench.schema import InteractionMode, PlanError


def plan_payload(harness: Path, digest: str) -> dict:
    return {
        "schema_version": 1,
        "suite": "unit-suite",
        "cases": [
            {
                "benchmark": "SWE-bench Verified",
                "task_id": "demo",
                "revision": "abc123",
                "digest": "case-digest",
                "root": "/tmp/case.json",
            }
        ],
        "harnesses": [{"id": "v0", "archive": str(harness), "sha256": digest}],
        "models": {"harness": "z-ai/glm-5.2"},
        "interactions": [
            {"mode": "direct"},
            {
                "mode": "simulated_user",
                "policy": "heartbeat-persona-v1",
                "model": "z-ai/glm-5.2",
                "seed_set": [17, 29],
            },
        ],
        "budgets": {"fallback_agent_seconds": 1800},
        "provider": {
            "type": "daytona",
            "image": "ubuntu:24.04",
            "image_digest": "sha256:image-digest",
            "cpu": 2,
            "memory_mb": 4096,
            "storage_mb": 10240,
            "network_policy": "benchmark_minimum",
            "concurrency": 2,
        },
        "measurement": {"repetitions": 3, "scheduling_seed": 7},
    }


def test_load_json_plan(tmp_path: Path) -> None:
    harness = tmp_path / "harness.tar.gz"
    harness.write_bytes(b"harness")
    payload = plan_payload(harness, "unused")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    plan = load_plan(path)

    assert plan.fallback_agent_timeout_seconds == 1800
    assert [item.mode for item in plan.interactions] == [
        InteractionMode.DIRECT,
        InteractionMode.SIMULATED_USER,
    ]
    assert plan.provider.concurrency == 2


def test_direct_mode_rejects_user_model(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    harness.write_bytes(b"x")
    payload = plan_payload(harness, "unused")
    payload["interactions"] = [{"mode": "direct", "model": "should-not-exist"}]

    with pytest.raises(PlanError, match="direct"):
        from evaluation.harness_bench.schema import EvaluationPlan

        EvaluationPlan.from_mapping(payload)


def test_nonstandard_missing_timeout_fallback_is_rejected(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    harness.write_bytes(b"x")
    payload = plan_payload(harness, "unused")
    payload["budgets"]["fallback_agent_seconds"] = 360

    with pytest.raises(PlanError, match="1800"):
        from evaluation.harness_bench.schema import EvaluationPlan

        EvaluationPlan.from_mapping(payload)


def test_provider_image_and_resources_are_required(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    harness.write_bytes(b"x")
    payload = plan_payload(harness, "unused")
    del payload["provider"]["image_digest"]

    with pytest.raises(PlanError, match="provider.image_digest"):
        from evaluation.harness_bench.schema import EvaluationPlan

        EvaluationPlan.from_mapping(payload)
