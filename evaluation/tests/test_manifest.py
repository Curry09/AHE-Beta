from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evaluation.config import HarborEvaluationPlan, PlanError
from evaluation.manifest import freeze_manifest
from evaluation.tests.test_config import plan_payload


def test_manifest_is_stable_and_expands_trials(tmp_path: Path) -> None:
    harness = tmp_path / "harness.tar.gz"
    harness.write_bytes(b"frozen")
    digest = hashlib.sha256(b"frozen").hexdigest()
    plan = HarborEvaluationPlan.from_mapping(plan_payload(harness, digest), tmp_path / "plan.json")

    first = freeze_manifest(plan, framework_commit="abc", created_at="one")
    second = freeze_manifest(plan, framework_commit="abc", created_at="two")

    assert first["manifest_digest"] == second["manifest_digest"]
    assert first["run_id"] == second["run_id"]
    assert first["created_at"] != second["created_at"]
    assert len(first["trials"]) == 3
    assert len({item["trial_id"] for item in first["trials"]}) == 3


def test_manifest_rejects_checksum_drift(tmp_path: Path) -> None:
    harness = tmp_path / "harness.tar.gz"
    harness.write_bytes(b"wrong")
    plan = HarborEvaluationPlan.from_mapping(
        plan_payload(harness, "0" * 64), tmp_path / "plan.json"
    )

    with pytest.raises(PlanError, match="checksum mismatch"):
        freeze_manifest(plan, framework_commit="abc")


def test_manifest_rejects_secret_like_metadata(tmp_path: Path) -> None:
    harness = tmp_path / "harness.tar.gz"
    harness.write_bytes(b"x")
    digest = hashlib.sha256(b"x").hexdigest()
    payload = plan_payload(harness, digest)
    payload["metadata"] = {"api_key": "must-not-land"}
    plan = HarborEvaluationPlan.from_mapping(payload, tmp_path / "plan.json")

    with pytest.raises(PlanError, match="secret-like"):
        freeze_manifest(plan, framework_commit="abc")
