"""Typed evaluation-plan schema and fail-closed validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    """The requested experiment cannot be made comparable or auditable."""


class InteractionMode(StrEnum):
    DIRECT = "direct"
    SIMULATED_USER = "simulated_user"
    BENCHMARK_NATIVE = "benchmark_native"


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PlanError(f"{field_name} must be a mapping")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{field_name} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlanError(f"{field_name} must be a positive integer")
    return value


@dataclass(frozen=True)
class CaseRef:
    benchmark: str
    task_id: str
    revision: str
    digest: str
    root: str | None = None

    @classmethod
    def from_mapping(cls, value: object, index: int) -> CaseRef:
        item = _mapping(value, f"cases[{index}]")
        return cls(
            benchmark=_text(item.get("benchmark"), f"cases[{index}].benchmark"),
            task_id=_text(item.get("task_id"), f"cases[{index}].task_id"),
            revision=_text(item.get("revision"), f"cases[{index}].revision"),
            digest=_text(item.get("digest"), f"cases[{index}].digest"),
            root=str(item["root"]) if item.get("root") else None,
        )


@dataclass(frozen=True)
class HarnessSpec:
    id: str
    archive: str
    sha256: str
    adapter: str = "stdio-jsonl-v1"
    self_timeout: str = "as_shipped"

    @classmethod
    def from_mapping(cls, value: object, index: int) -> HarnessSpec:
        item = _mapping(value, f"harnesses[{index}]")
        self_timeout = str(item.get("self_timeout", "as_shipped"))
        if self_timeout not in {"as_shipped", "task_aligned"}:
            raise PlanError(f"harnesses[{index}].self_timeout must be as_shipped or task_aligned")
        return cls(
            id=_text(item.get("id"), f"harnesses[{index}].id"),
            archive=_text(item.get("archive"), f"harnesses[{index}].archive"),
            sha256=_text(item.get("sha256"), f"harnesses[{index}].sha256"),
            adapter=str(item.get("adapter", "stdio-jsonl-v1")),
            self_timeout=self_timeout,
        )


@dataclass(frozen=True)
class InteractionSpec:
    mode: InteractionMode
    policy: str
    model: str | None = None
    seeds: tuple[int, ...] = ()
    heartbeat_seconds: int = 90
    max_turns: int = 40
    max_heartbeats: int | None = None

    @classmethod
    def from_mapping(cls, value: object, index: int) -> InteractionSpec:
        item = _mapping(value, f"interactions[{index}]")
        try:
            mode = InteractionMode(_text(item.get("mode"), f"interactions[{index}].mode"))
        except ValueError as exc:
            raise PlanError(f"unsupported interactions[{index}].mode") from exc
        policy = str(item.get("policy") or mode.value)
        raw_seeds = item.get("seed_set", item.get("seeds", []))
        if not isinstance(raw_seeds, list) or any(
            isinstance(seed, bool) or not isinstance(seed, int) for seed in raw_seeds
        ):
            raise PlanError(f"interactions[{index}].seed_set must contain integers")
        model = str(item["model"]) if item.get("model") else None
        if mode is InteractionMode.SIMULATED_USER and not model:
            raise PlanError(f"interactions[{index}].model is required for simulated_user")
        if mode is InteractionMode.DIRECT and (model or raw_seeds):
            raise PlanError("direct interaction cannot declare a user model or seeds")
        return cls(
            mode=mode,
            policy=policy,
            model=model,
            seeds=tuple(raw_seeds),
            heartbeat_seconds=_positive_int(
                item.get("heartbeat_seconds", 90),
                f"interactions[{index}].heartbeat_seconds",
            ),
            max_turns=_positive_int(item.get("max_turns", 40), f"interactions[{index}].max_turns"),
            max_heartbeats=(
                _positive_int(item["max_heartbeats"], f"interactions[{index}].max_heartbeats")
                if item.get("max_heartbeats") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ProviderSpec:
    type: str
    image: str
    image_digest: str
    cpu: int
    memory_mb: int
    storage_mb: int
    network_policy: str
    concurrency: int = 1
    ephemeral: bool = True

    @classmethod
    def from_mapping(cls, value: object) -> ProviderSpec:
        item = _mapping(value, "provider")
        ephemeral = item.get("ephemeral", True)
        if not isinstance(ephemeral, bool):
            raise PlanError("provider.ephemeral must be a boolean")
        if not ephemeral:
            raise PlanError("standard evaluation requires ephemeral sandboxes")
        return cls(
            type=_text(item.get("type"), "provider.type"),
            image=_text(item.get("image"), "provider.image"),
            image_digest=_text(item.get("image_digest"), "provider.image_digest"),
            cpu=_positive_int(item.get("cpu"), "provider.cpu"),
            memory_mb=_positive_int(item.get("memory_mb"), "provider.memory_mb"),
            storage_mb=_positive_int(item.get("storage_mb"), "provider.storage_mb"),
            network_policy=_text(
                item.get("network_policy", "benchmark_minimum"),
                "provider.network_policy",
            ),
            concurrency=_positive_int(item.get("concurrency", 1), "provider.concurrency"),
            ephemeral=ephemeral,
        )


@dataclass(frozen=True)
class MeasurementSpec:
    repetitions: int = 3
    scheduling_seed: int = 17

    @classmethod
    def from_mapping(cls, value: object) -> MeasurementSpec:
        item = _mapping(value, "measurement")
        seed = item.get("scheduling_seed", 17)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise PlanError("measurement.scheduling_seed must be an integer")
        return cls(
            repetitions=_positive_int(item.get("repetitions", 3), "measurement.repetitions"),
            scheduling_seed=seed,
        )


@dataclass(frozen=True)
class EvaluationPlan:
    schema_version: int
    suite: str
    cases: tuple[CaseRef, ...]
    harnesses: tuple[HarnessSpec, ...]
    harness_model: str
    interactions: tuple[InteractionSpec, ...]
    provider: ProviderSpec
    measurement: MeasurementSpec
    fallback_agent_timeout_seconds: int = 1800
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: object) -> EvaluationPlan:
        data = _mapping(value, "plan")
        if data.get("schema_version") != 1:
            raise PlanError("schema_version must be 1")
        suite_value = data.get("suite")
        if isinstance(suite_value, Mapping):
            suite = _text(suite_value.get("name"), "suite.name")
            raw_cases = suite_value.get("cases", data.get("cases"))
        else:
            suite = _text(suite_value, "suite")
            raw_cases = data.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise PlanError("cases must be a non-empty list")
        raw_harnesses = data.get("harnesses")
        if not isinstance(raw_harnesses, list) or not raw_harnesses:
            raise PlanError("harnesses must be a non-empty list")
        raw_interactions = data.get("interactions")
        if not isinstance(raw_interactions, list) or not raw_interactions:
            raise PlanError("interactions must be a non-empty list")
        models = _mapping(data.get("models"), "models")
        harness_model_value = models.get("harness")
        if isinstance(harness_model_value, Mapping):
            harness_model_value = harness_model_value.get("id")
        budgets = data.get("budgets", {})
        budgets = _mapping(budgets, "budgets")
        fallback = _positive_int(
            budgets.get("fallback_agent_seconds", 1800),
            "budgets.fallback_agent_seconds",
        )
        if fallback != 1800:
            raise PlanError(
                "the standard fallback for tasks without an official timeout is 1800 seconds"
            )
        plan = cls(
            schema_version=1,
            suite=suite,
            cases=tuple(CaseRef.from_mapping(item, index) for index, item in enumerate(raw_cases)),
            harnesses=tuple(
                HarnessSpec.from_mapping(item, index) for index, item in enumerate(raw_harnesses)
            ),
            harness_model=_text(harness_model_value, "models.harness"),
            interactions=tuple(
                InteractionSpec.from_mapping(item, index)
                for index, item in enumerate(raw_interactions)
            ),
            provider=ProviderSpec.from_mapping(data.get("provider")),
            measurement=MeasurementSpec.from_mapping(data.get("measurement", {})),
            fallback_agent_timeout_seconds=fallback,
            metadata=_mapping(data.get("metadata", {}), "metadata"),
        )
        plan._validate_unique_ids()
        return plan

    def _validate_unique_ids(self) -> None:
        harness_ids = [item.id for item in self.harnesses]
        if len(set(harness_ids)) != len(harness_ids):
            raise PlanError("harness ids must be unique")
        case_ids = [(item.benchmark, item.task_id) for item in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise PlanError("benchmark/task_id pairs must be unique")
        interaction_ids = [(item.mode, item.policy) for item in self.interactions]
        if len(set(interaction_ids)) != len(interaction_ids):
            raise PlanError("interaction mode/policy pairs must be unique")

    def validate_local_artifacts(self) -> None:
        for harness in self.harnesses:
            if not Path(harness.archive).is_file():
                raise PlanError(f"harness archive does not exist: {harness.archive}")
