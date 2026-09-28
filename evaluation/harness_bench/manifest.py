"""Freeze a validated plan into a secret-free, content-addressed manifest."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schema import EvaluationPlan, InteractionMode, PlanError

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "password",
    "secret",
    "access_token",
    "auth_token",
    "bearer_token",
}


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_secret_free(value: object, trail: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SECRET_KEYS or normalized.endswith("_api_key"):
                raise PlanError(f"secret-like field is forbidden in {trail}: {key}")
            _assert_secret_free(item, f"{trail}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_secret_free(item, f"{trail}[{index}]")


def _trial_rows(plan: EvaluationPlan) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in plan.cases:
        for harness in plan.harnesses:
            for interaction in plan.interactions:
                seeds: tuple[int | None, ...]
                if interaction.mode is InteractionMode.DIRECT:
                    seeds = (None,)
                else:
                    seeds = interaction.seeds or (0,)
                for seed in seeds:
                    for repetition in range(plan.measurement.repetitions):
                        identity = {
                            "benchmark": case.benchmark,
                            "task_id": case.task_id,
                            "case_digest": case.digest,
                            "harness": harness.id,
                            "interaction": interaction.mode.value,
                            "policy": interaction.policy,
                            "seed": seed,
                            "repetition": repetition,
                        }
                        rows.append({"trial_id": digest_json(identity)[:24], **identity})
    random.Random(plan.measurement.scheduling_seed).shuffle(rows)
    return rows


def freeze_manifest(
    plan: EvaluationPlan,
    *,
    framework_commit: str,
    resolved_cases: Mapping[str, Mapping[str, Any]] | None = None,
    image_digests: Mapping[str, str] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    plan.validate_local_artifacts()
    harnesses = []
    for harness in plan.harnesses:
        actual = sha256_file(harness.archive)
        if actual != harness.sha256:
            raise PlanError(
                f"harness checksum mismatch for {harness.id}: expected {harness.sha256}, got {actual}"
            )
        harnesses.append({**asdict(harness), "resolved_sha256": actual})
    body: dict[str, Any] = {
        "schema_version": 1,
        "suite": plan.suite,
        "framework_commit": framework_commit,
        "cases": [asdict(item) for item in plan.cases],
        "harnesses": harnesses,
        "harness_model": plan.harness_model,
        "interactions": [{**asdict(item), "mode": item.mode.value} for item in plan.interactions],
        "provider": asdict(plan.provider),
        "measurement": asdict(plan.measurement),
        "fallback_agent_timeout_seconds": plan.fallback_agent_timeout_seconds,
        "resolved_cases": dict(resolved_cases or {}),
        "image_digests": dict(image_digests or {}),
        "trials": _trial_rows(plan),
        "metadata": dict(plan.metadata),
    }
    _assert_secret_free(body)
    body["manifest_digest"] = digest_json(body)
    body["run_id"] = f"hbench-{body['manifest_digest'][:16]}"
    body["created_at"] = created_at or datetime.now(UTC).isoformat()
    return body
